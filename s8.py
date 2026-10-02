"""Render one S8 row as the registration record a caseworker sees.

Column meanings and value sets follow Annex I (data dictionary) of the challenge brief.
Outcome columns (Elegibilidad, EligibilityTarget) are never part of the public record:
they are the reference determination, used to score the caseworker's decision.
"""
from __future__ import annotations

import csv
from pathlib import Path

# (column, label, group, levels). Levels are the discrete values listed in Annex I.
FACTORS = [
    ("Demographics.HH.Head", "Head of household", "demographics", [1.0, 1.60, 2.07, 2.70]),
    ("Demographics.Language", "Language barrier", "demographics", [1.0, 1.53, 2.05]),
    ("Demographics.Profiles", "Specific needs", "demographics", [1.0, 1.25, 2.58, 3.25]),
    ("Demographics.Documentation", "Documentation", "demographics", [1.0, 1.56, 2.13]),
    ("Needs_and_Coping.BasicNeeds", "Basic needs unmet", "needs", [1.0, 1.78]),
    ("Needs_and_Coping.Housing", "Housing instability", "needs", [1.0, 1.50, 2.12, 2.82]),
    ("Needs_and_Coping.Neg.mechanism", "Negative coping", "needs", [1.0, 1.79, 2.58]),
    ("Needs_and_Coping.Dependency", "Dependency burden", "needs", [1.0, 1.04, 1.74, 2.54]),
]
FACTOR_BY_COL = {f[0]: f for f in FACTORS}

BANDS = {
    "Vulnerabilidad Baja": "Baja (low)",
    "Vulnerabilidad Moderada": "Moderada (moderate)",
    "Vulnerabilidad Elevada": "Elevada (high)",
    "Vulnerabilidad Severa": "Severa (severe)",
}
NA = "Not applicable"

# Plain-language reasons per factor: (when above its lowest level, when at its lowest level).
FACTOR_REASONS = {
    "Demographics.HH.Head": ("The household head's profile adds vulnerability, for example a lone or female head of household.",
                             "The household head's profile adds no vulnerability."),
    "Demographics.Language": ("A language barrier is recorded, which limits access to services and work.",
                              "No language barrier is recorded."),
    "Demographics.Profiles": ("Members have specific needs, such as a disability, a chronic illness or a medical condition.",
                              "No specific needs are recorded for any member."),
    "Demographics.Documentation": ("Documentation is incomplete, which restricts access to formal work and services.",
                                   "Identity documents are in order."),
    "Needs_and_Coping.BasicNeeds": ("Basic needs are reported as unmet.", "Basic needs are reported as met."),
    "Needs_and_Coping.Housing": ("Housing is unstable.", "Housing is stable."),
    "Needs_and_Coping.Neg.mechanism": ("The household relies on negative coping strategies.",
                                       "No negative coping strategies are reported."),
    "Needs_and_Coping.Dependency": ("Dependants weigh on the household's resources.", "There are few or no dependants."),
}
ADMIN_COLS = ("ScoreCOMAR_PIL", "ScoreIntenciones", "ScoreDuplicidad")


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _num(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def _level(value: float, levels: list[float]) -> int:
    return min(range(len(levels)), key=lambda i: abs(levels[i] - value))


def factor(row: dict, col: str) -> dict:
    _, label, group, levels = FACTOR_BY_COL[col]
    value = _num(row[col]) or 1.0
    lvl = _level(value, levels)
    return {"col": col, "name": label, "group": group, "value": round(value, 2),
            "levels": len(levels), "level": lvl, "max": lvl == len(levels) - 1}


def household(row: dict) -> list[dict]:
    n = int(float(row["NumIntegrantes"] or 0))
    single = n == 1
    head = {"jefatura_femenina": "Female", "jefatura_masculina": "Male"}.get(row["FemaleHeadedHousehold"])
    carer = {"si": "Yes", "no": "No"}.get(row["CuidadorSolo"])
    na_note = "(1-person household)" if single else "(not recorded)"
    spanish = row["HablaEspanol"] == "espanol_uno_mas_adultos"
    illiterate = row["Analfabeta_si"] == "adultos_uno_mas_analfabeta"
    return [
        {"label": "Household size", "value": f"{n} member{'s' if n != 1 else ''}"},
        {"label": "Dependency ratio", "value": (row["dependencyCategory"] or NA).capitalize()},
        {"label": "Head of household", "value": head or NA, "note": None if head else na_note, "na": head is None},
        {"label": "Sole carer of dependants", "value": carer or NA, "note": None if carer else na_note, "na": carer is None},
        {"label": "An adult speaks Spanish", "value": "Yes" if spanish else "No",
         "note": "(1 or more adults)" if spanish else "(no adult)"},
        {"label": "Adult illiteracy", "value": "Yes" if illiterate else "None",
         "note": "(1 or more adults)" if illiterate else None},
    ]


def _flag(label: str, raw: str) -> dict:
    v = _num(raw)
    if v is None:
        return {"label": label, "chip": NA, "tone": "neutral"}
    if v <= -500:
        return {"label": label, "chip": "−500 · excludes", "tone": "danger"}
    if v >= 500:
        return {"label": label, "chip": "+500", "tone": "primary"}
    return {"label": label, "chip": "Clear · 0", "tone": "clear"}


def admin(row: dict) -> list[dict]:
    flags = [
        _flag("Asylum procedure (COMAR)", row["ScoreCOMAR_PIL"]),
        _flag("Stated intentions", row["ScoreIntenciones"]),
        _flag("Duplicate registration", row["ScoreDuplicidad"]),
    ]
    return sorted(flags, key=lambda f: f["tone"] != "danger")  # a -500 flag is listed first


def totals(row: dict, band: str | None = None) -> dict:
    """Card C. `band` overrides the recorded Vulnerability_Category (used by wrong cases)."""
    category = band or row["Vulnerability_Category"]
    return {
        "demographics": round(_num(row["Demographics_Score"]) or 0, 1),
        "needs": round(_num(row["NeedsandCoping_Score"]) or 0, 1),
        "final": round(_num(row["FinalScore"]) or 0, 1),
        "final_max": 81.1,
        "vulnerability_score": round(_num(row["Vulnerability_Score"]) or 0, 2),
        "band": BANDS.get(category, category),
    }


def has_exclusion_flag(row: dict) -> bool:
    return any((_num(row[c]) or 0) <= -500 for c in ADMIN_COLS)


def wrong_band(row: dict) -> str | None:
    """A misleading Vulnerability_Category for a wrong case, pointing away from the recorded determination:
    an included household is shown as Baja, an excluded one as Severa. None if the row cannot be misled."""
    if has_exclusion_flag(row):
        return None
    band = "Vulnerabilidad Baja" if row["EligibilityTarget"] == "INCLUSION" else "Vulnerabilidad Severa"
    return None if band == row["Vulnerability_Category"] else band


def auto_reasoning(row: dict) -> dict:
    """Reasons to include (agree) and to exclude (disagree), built from the factor levels.
    Never mentions the band or the score, so a wrong case's band is not contradicted in words."""
    agree, disagree = [], []
    for col, *_ in FACTORS:
        high, low = FACTOR_REASONS[col]
        if factor(row, col)["level"] > 0:
            agree.append(high)
        else:
            disagree.append(low)
    for f in admin(row):
        if f["tone"] == "danger":
            disagree.insert(0, f"An administrative check excludes this household: {f['label']}.")
    return {"agree": agree or ["No factor is above its lowest level."],
            "disagree": disagree or ["Every factor is above its lowest level."]}


def cashy_answer(rows: list[dict], i: int, k: int = 30) -> dict:
    """Cashy's answer without an INCLUDE/EXCLUDE verdict: the score, the band, and how often comparable
    past households were included. Comparable = same month (funding varies by month) and closest FinalScore."""
    row = rows[i]
    score = _num(row["FinalScore"]) or 0
    same = [j for j in range(len(rows)) if j != i and rows[j]["month"] == row["month"]]
    near = sorted(same, key=lambda j: abs((_num(rows[j]["FinalScore"]) or 0) - score))[:k]
    included = sum(rows[j]["EligibilityTarget"] == "INCLUSION" for j in near)
    pct = round(100 * included / len(near)) if near else 50
    return {
        "score": round(score, 1),
        "category": BANDS.get(row["Vulnerability_Category"], row["Vulnerability_Category"]),
        "include_pct": pct,
        "exclude_pct": 100 - pct,
        "basis": f"Of the {len(near)} past households from the same month with the closest scores, {included} were included.",
    }


def public_case(cfg: dict, rows: list[dict], index: int) -> dict:
    """Everything shown on the review screen. No Cashy answer, no reference determination."""
    row = rows[cfg["s8_row"]]
    return {
        "case_id": cfg["case_id"], "index": index, "number": index + 1,
        "kind": cfg.get("kind"),
        "meta": {"office": row["OficinaACNUR"] or NA, "month": row["month"]},
        "household": household(row),
        "admin": admin(row),
        "factors": [factor(row, f[0]) for f in FACTORS],
        "totals": totals(row, cfg.get("shown_band")),
        "reasoning": {"agree": cfg["reasoning"]["agree"], "disagree": cfg["reasoning"]["disagree"]},
    }


def reference(row: dict) -> dict:
    """The operation's own recorded determination: the reference standard, not ground truth."""
    target = row["EligibilityTarget"]
    return {
        "target": "INCLUDE" if target == "INCLUSION" else "EXCLUDE",
        "label": target,
        "elegibilidad": row["Elegibilidad"],
        "final_score": round(_num(row["FinalScore"]) or 0, 1),
        "band": BANDS.get(row["Vulnerability_Category"], row["Vulnerability_Category"]),
    }


def validate_cases(cases: list[dict], rows: list[dict]) -> None:
    for c in cases:
        if not 0 <= c["s8_row"] < len(rows):
            raise ValueError(f"{c['case_id']}: s8_row {c['s8_row']} is out of range")
        for side in ("agree", "disagree"):
            if not c["reasoning"].get(side):
                raise ValueError(f"{c['case_id']}: reasoning.{side} is empty")
