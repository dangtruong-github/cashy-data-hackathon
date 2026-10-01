"""Render one S8 row as the registration record a caseworker sees.

Column meanings and value sets follow Annex I (data dictionary) of the challenge brief.
Outcome columns (Elegibilidad, EligibilityTarget) are never part of the public record:
they are the reference determination, revealed only after the caseworker submits.
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


def totals(row: dict) -> dict:
    return {
        "demographics": round(_num(row["Demographics_Score"]) or 0, 1),
        "needs": round(_num(row["NeedsandCoping_Score"]) or 0, 1),
        "final": round(_num(row["FinalScore"]) or 0, 1),
        "final_max": 81.1,
        "vulnerability_score": round(_num(row["Vulnerability_Score"]) or 0, 2),
        "band": BANDS.get(row["Vulnerability_Category"], row["Vulnerability_Category"]),
    }


def public_case(cfg: dict, rows: list[dict], index: int, total: int) -> dict:
    """Everything shown on the review screen. No Cashy answer, no reference determination."""
    row = rows[cfg["s8_row"]]
    return {
        "case_id": cfg["case_id"], "index": index, "total": total,
        "meta": {"office": row["OficinaACNUR"] or NA, "month": row["month"]},
        "household": household(row),
        "admin": admin(row),
        "factors": [factor(row, f[0]) for f in FACTORS],
        "totals": totals(row),
        "interviewer_view": cfg["interviewer_view"],
        "transcript": cfg["transcript"],
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
        if not c.get("interviewer_view"):
            raise ValueError(f"{c['case_id']}: interviewer_view is empty")
        times = [line["t"] for line in c["transcript"]]
        if not times or times != sorted(times):
            raise ValueError(f"{c['case_id']}: transcript must be non-empty and in time order")
        for side in ("agree", "disagree"):
            if not c["reasoning"].get(side):
                raise ValueError(f"{c['case_id']}: reasoning.{side} is empty")
        if c["cashy"]["recommendation"] not in ("INCLUDE", "EXCLUDE"):
            raise ValueError(f"{c['case_id']}: recommendation must be INCLUDE or EXCLUDE")
