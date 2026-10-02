"""Experiment items (Annex II), the reliance classification and the case/break sequence.

The item wording is copied verbatim so results stay comparable with the reference study.
classify() and the sequence functions are mirrored in static/app.js (used by the offline demo).
"""
from __future__ import annotations

DECISIONS = ("INCLUDE", "EXCLUDE")
REASONING_TABS = ("agree", "disagree")  # agree = reasons to include, disagree = reasons to exclude
EC3_OPTIONS = (
    "Inaccurate or incorrect information",
    "Irrelevant or incomplete information",
    "Not appropriate or unexpected result",
    "Unfair or unjust decision",
    "Disrespects staff autonomy to change the decision",
    "Lack of transparency or explainability",
    "Unclear roles between staff and tool",
)
LIKERT_ITEMS = ("EC1", "EC5", "EC6", "EC7")
PRINCIPLE_IDS = ("harm", "fairness", "autonomy", "transparency", "accountability")


def opposite(decision: str) -> str:
    return "EXCLUDE" if decision == "INCLUDE" else "INCLUDE"


def classify(own: str, cashy: str, ref: str, ec2: str, ec4: str | None) -> dict:
    """Appropriate-reliance outcome for one assessment.

    "Correct" means agreement with the operation's recorded determination (ref).
    Over-reliance is defined by EC4: on a discordant case, not overriding is over-reliance.
    """
    final = cashy if (ec2 == "Agree" or ec4 == "No") else opposite(cashy)
    relation = "concordant" if cashy == ref else "discordant"
    if relation == "discordant":
        outcome = "correct_override" if final != cashy else "over_reliance"
    else:
        outcome = "correct_acceptance" if final == cashy else "under_reliance"
    return {
        "relation": relation,
        "final_decision": final,
        "outcome": outcome,
        "switched_to_cashy": own != cashy and final == cashy,
        "end_to_end_correct": final == ref,
    }


def is_mistake(own: str, ref: str) -> bool:
    """On a wrong case, a mistake is a decision that differs from the operation's recorded determination."""
    return own != ref


# ---------- Case sequence and breaks (mirrored in static/app.js for the offline demo) ----------
# start: N genuine -> repeat: M genuine -> wrong1
#   wrong1, no mistake -> repeat;  mistake -> after_mistake: K genuine -> break offered
#     break skipped -> start;  break taken -> wrong2
#       wrong2, no mistake -> repeat;  mistake -> forced break -> start
PHASE_KIND = {"start": "genuine", "repeat": "genuine", "wrong1": "wrong", "after_mistake": "genuine", "wrong2": "wrong"}


def enter(state: dict, phase: str, sizes: dict) -> None:
    state["phase"] = phase
    state["left"] = sizes.get(phase, 1)


def after_case(state: dict, mistake: bool, sizes: dict) -> str | None:
    """Advance after a case is submitted. Returns "offer" or "force" when a break is due, else None."""
    phase = state["phase"]
    if phase == "wrong1":
        enter(state, "after_mistake" if mistake else "repeat", sizes)
        return None
    if phase == "wrong2":
        if mistake:
            return "force"
        enter(state, "repeat", sizes)
        return None
    state["left"] -= 1
    if state["left"] > 0:
        return None
    if phase == "after_mistake":
        return "offer"
    enter(state, "repeat" if phase == "start" else "wrong1", sizes)
    return None


def after_break(state: dict, kind: str, result: str, sizes: dict) -> None:
    """A taken offered break leads to the second wrong case; a skipped one or a forced one restarts the cycle."""
    enter(state, "wrong2" if kind == "offer" and result == "completed" else "start", sizes)


def validate_answers(a: dict) -> dict:
    clean: dict = {}
    for k in LIKERT_ITEMS:
        v = a.get(k)
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise ValueError(f"{k} must be an integer from 1 to 5")
        clean[k] = v
    if a.get("EC2") not in ("Agree", "Disagree"):
        raise ValueError("EC2 must be Agree or Disagree")
    clean["EC2"] = a["EC2"]
    if clean["EC2"] == "Disagree":
        ec3 = a.get("EC3") or []
        if not ec3 or any(x not in EC3_OPTIONS for x in ec3):
            raise ValueError("EC3 needs at least one listed reason")
        if a.get("EC4") not in ("Yes", "No"):
            raise ValueError("EC4 must be Yes or No")
        clean["EC3"] = list(dict.fromkeys(ec3))
        clean["EC4"] = a["EC4"]
    else:
        clean["EC3"] = []
        clean["EC4"] = None
    return clean
