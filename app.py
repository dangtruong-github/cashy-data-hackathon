"""Cashy: caseworker review screen with server-enforced protocol, break prompts and CSV logging.

Run:  python app.py   then open http://127.0.0.1:5000
      add ?research=1 to the URL to show the researcher log drawer.

The server never sends Cashy's answer before the caseworker's decision is logged,
picks which case comes next (genuine or wrong) so the browser cannot tell them apart,
and will not open the next case until a due break is resolved.
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

import protocol as P
import s8

BASE = Path(__file__).resolve().parent
S8_PATH = Path(os.environ.get("CASHY_S8_PATH", BASE / "S8.synthetic_cashy_sample.csv"))
CASES_PATH = Path(os.environ.get("CASHY_CASES_PATH", BASE / "cases" / "cases.json"))
LOG_DIR = Path(os.environ.get("CASHY_LOG_DIR", BASE / "logs"))
VARIANT = os.environ.get("CASHY_VARIANT", "cashy_reasoning_first")


def env_int(name: str, default: int) -> int:
    return max(1, int(os.environ.get(name, default)))


# Demo defaults. The full design uses 10 / 5 / 1 cases and breaks set by the operation.
SIZES = {
    "start": env_int("CASHY_BLOCK_START", 1),
    "repeat": env_int("CASHY_BLOCK_REPEAT", 1),
    "after_mistake": env_int("CASHY_BLOCK_AFTER_MISTAKE", 1),
}
BREAK_SECONDS = {"offer": env_int("CASHY_BREAK_SECONDS", 10), "force": env_int("CASHY_FORCED_BREAK_SECONDS", 10)}

ROWS = s8.load_rows(S8_PATH)
AUTHORED = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
s8.validate_cases(AUTHORED, ROWS)
AUTHORED_BY_ROW = {c["s8_row"]: c for c in AUTHORED}
WRONG_ROWS = [i for i, r in enumerate(ROWS) if s8.wrong_band(r) and i not in AUTHORED_BY_ROW]
CASHY_CACHE: dict[int, dict] = {}


def cashy(row_index: int) -> dict:
    if row_index not in CASHY_CACHE:
        CASHY_CACHE[row_index] = s8.cashy_answer(ROWS, row_index)
    return CASHY_CACHE[row_index]


def make_case(row_index: int, kind: str) -> dict:
    authored = AUTHORED_BY_ROW.get(row_index)
    row = ROWS[row_index]
    return {
        "case_id": authored["case_id"] if authored else f"H-{row_index:04d}",
        "s8_row": row_index,
        "kind": kind,
        "shown_band": s8.wrong_band(row) if kind == "wrong" else None,
        "reasoning": authored["reasoning"] if authored else s8.auto_reasoning(row),
    }


def pick_case(sess: dict) -> dict:
    """Authored cases come first as genuine cases, then random S8 rows. A row is never shown twice."""
    kind = P.PHASE_KIND[sess["seq"]["phase"]]
    used = {c["s8_row"] for c in sess["served"]}
    if kind == "genuine":
        fresh = [c["s8_row"] for c in AUTHORED if c["s8_row"] not in used]
        row_index = fresh[0] if fresh else sess["rng"].choice([i for i in range(len(ROWS)) if i not in used])
    else:
        row_index = sess["rng"].choice([i for i in WRONG_ROWS if i not in used])
    return make_case(row_index, kind)


app = Flask(__name__, static_folder="static", static_url_path="/static")
SESSIONS: dict[str, dict] = {}
LOCK = threading.Lock()
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
EVENT_RE = re.compile(r"^[a-z0-9_]{1,64}$")

ASSESSMENT_FIELDS = [
    "timestamp_utc", "session_id", "participant", "variant", "case_id", "case_index", "phase",
    "case_kind", "true_band", "shown_band", "cashy_include_pct", "cashy_lean",
    "relation", "own_decision", "reference_target", "own_correct", "mistake",
    "EC1", "EC2", "EC3", "EC4", "EC5", "EC6", "EC7", "gap_ec6_minus_ec5",
    "final_decision", "outcome", "switched_to_cashy", "end_to_end_correct",
    "reasoning_first_tab", "reasoning_tabs_viewed", "ms_open_to_decision", "ms_decision_to_submit",
]
BREAK_FIELDS = ["timestamp_utc", "session_id", "participant", "break_kind", "trigger_case_id",
                "seconds_planned", "ms_open", "result", "worked_ms"]
SESSION_FIELDS = ["timestamp_utc", "session_id", "participant", "variant", "worked_ms", "cases_reviewed",
                  "wrong_cases", "mistakes", "breaks_offered", "breaks_taken", "forced_breaks"]
PRINCIPLE_FIELDS = ["timestamp_utc", "session_id", "participant", *P.PRINCIPLE_IDS, "comment"]
EVENT_FIELDS = ["timestamp_utc", "session_id", "participant", "case_id", "client_ms", "event", "data"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_ms() -> int:
    return int(time.time() * 1000)


def append_csv(name: str, fields: list[str], row: dict) -> None:
    """Append one row. A file written with older columns is set aside, not mixed with the new ones."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / name
    with LOCK:
        if path.exists():
            with path.open(encoding="utf-8", newline="") as f:
                header = next(csv.reader(f), [])
            if header != fields:
                path.rename(path.with_name(f"{path.stem}.old-{now_ms()}{path.suffix}"))
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            if new:
                w.writeheader()
            w.writerow(row)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@app.errorhandler(ApiError)
def _api_error(e: ApiError):
    return jsonify(error=str(e)), e.status


@app.after_request
def _no_cache(response):
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def get_session(sid: str) -> dict:
    sess = SESSIONS.get(sid)
    if not sess:
        raise ApiError("Session not found. Start a new session.", 404)
    return sess


def get_case_state(sess: dict, index: int) -> dict:
    if not 0 <= index < len(sess["served"]):
        raise ApiError("Open the case before acting on it.", 409)
    return sess["cases"][index]


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON object.")
    return data


def worked_ms(data: dict) -> int | str:
    v = data.get("worked_ms")
    return v if isinstance(v, int) and v >= 0 else ""


# ---------- Page ----------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cashy</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
{body}
<script src="/static/app.js"></script>
</body>
</html>"""


@app.get("/")
def index():
    markup = (BASE / "templates" / "body.html").read_text(encoding="utf-8")
    return PAGE.replace("{body}", markup)


# ---------- API ----------

@app.post("/api/session")
def start_session():
    code = str(body().get("participant", "")).strip()
    if not CODE_RE.match(code):
        raise ApiError("Use the participant code from your briefing (2–16 letters, digits, - or _). Do not enter your name.")
    sid = secrets.token_urlsafe(12)
    seq: dict = {}
    P.enter(seq, "start", SIZES)
    SESSIONS[sid] = {"id": sid, "participant": code, "served": [], "cases": [], "seq": seq, "rng": random.Random(sid),
                     "pending_break": None, "breaks": [], "ended": False, "principles": None}
    return jsonify(session=sid, participant=code)


@app.get("/api/session/<sid>/case/<int:index>")
def open_case(sid: str, index: int):
    sess = get_session(sid)
    if index < len(sess["served"]):
        return jsonify(s8.public_case(sess["served"][index], ROWS, index))
    if index != len(sess["served"]):
        raise ApiError("Case not found.", 404)
    if sess["ended"]:
        raise ApiError("This session has ended.", 409)
    if sess["pending_break"]:
        raise ApiError("Your break is not over yet.", 409)
    if sess["cases"] and "rated" not in sess["cases"][-1]:
        raise ApiError("Finish the current case first.", 409)
    case = pick_case(sess)
    sess["served"].append(case)
    sess["cases"].append({"opened_ms": now_ms(), "phase": sess["seq"]["phase"]})
    return jsonify(s8.public_case(case, ROWS, index))


@app.post("/api/session/<sid>/case/<int:index>/decision")
def decide(sid: str, index: int):
    sess = get_session(sid)
    st = get_case_state(sess, index)
    if "decision" in st:
        raise ApiError("A decision is already logged for this case.", 409)
    data = body()
    decision = data.get("decision")
    if decision not in P.DECISIONS:
        raise ApiError("Decision must be INCLUDE or EXCLUDE.")
    first_tab = data.get("first_tab") if data.get("first_tab") in P.REASONING_TABS else ""
    viewed = [t for t in P.REASONING_TABS if t in (data.get("tabs_viewed") or [])]
    st.update(decision=decision, first_tab=first_tab, tabs_viewed=viewed, decision_ms=now_ms())
    return jsonify(cashy=cashy(sess["served"][index]["s8_row"]))


@app.post("/api/session/<sid>/case/<int:index>/rate")
def rate(sid: str, index: int):
    sess = get_session(sid)
    st = get_case_state(sess, index)
    if "decision" not in st:
        raise ApiError("Log your decision first.", 409)
    if "rated" in st:
        raise ApiError("These answers are already submitted and locked.", 409)
    try:
        a = P.validate_answers(body())
    except ValueError as e:
        raise ApiError(str(e)) from e
    case = sess["served"][index]
    row = ROWS[case["s8_row"]]
    ref = s8.reference(row)
    answer = cashy(case["s8_row"])
    lean = "INCLUDE" if answer["include_pct"] >= 50 else "EXCLUDE"  # the side Cashy's percentages favour
    cls = P.classify(st["decision"], lean, ref["target"], a["EC2"], a["EC4"])
    mistake = case["kind"] == "wrong" and P.is_mistake(st["decision"], ref["target"])
    gap = a["EC6"] - a["EC5"]
    t = now_ms()
    st.update(rated=a, rated_ms=t, mistake=mistake)

    due = P.after_case(sess["seq"], mistake, SIZES)
    if due:
        sess["pending_break"] = {"kind": due, "seconds": BREAK_SECONDS[due], "issued_ms": t, "trigger": case["case_id"]}

    append_csv("assessments.csv", ASSESSMENT_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"], "variant": VARIANT,
        "case_id": case["case_id"], "case_index": index, "phase": st["phase"],
        "case_kind": case["kind"], "true_band": row["Vulnerability_Category"], "shown_band": case["shown_band"] or row["Vulnerability_Category"],
        "cashy_include_pct": answer["include_pct"], "cashy_lean": lean,
        "relation": cls["relation"], "own_decision": st["decision"], "reference_target": ref["target"],
        "own_correct": st["decision"] == ref["target"], "mistake": mistake if case["kind"] == "wrong" else "",
        "EC1": a["EC1"], "EC2": a["EC2"], "EC3": "|".join(a["EC3"]), "EC4": a["EC4"] or "",
        "EC5": a["EC5"], "EC6": a["EC6"], "EC7": a["EC7"], "gap_ec6_minus_ec5": gap,
        "final_decision": cls["final_decision"], "outcome": cls["outcome"],
        "switched_to_cashy": cls["switched_to_cashy"], "end_to_end_correct": cls["end_to_end_correct"],
        "reasoning_first_tab": st["first_tab"], "reasoning_tabs_viewed": "|".join(st["tabs_viewed"]),
        "ms_open_to_decision": st["decision_ms"] - st["opened_ms"], "ms_decision_to_submit": t - st["decision_ms"],
    })
    pb = sess["pending_break"]
    return jsonify(reference=ref, record={**cls, "gap_ec6_minus_ec5": gap, "case_kind": case["kind"], "mistake": mistake},
                   **{"break": {"kind": pb["kind"], "seconds": pb["seconds"]} if pb else None})


@app.post("/api/session/<sid>/break")
def resolve_break(sid: str):
    sess = get_session(sid)
    pb = sess["pending_break"]
    if not pb:
        raise ApiError("No break is due.", 409)
    data = body()
    result = data.get("result")
    if result not in ("completed", "skipped"):
        raise ApiError("Result must be completed or skipped.")
    open_ms = now_ms() - pb["issued_ms"]
    if result == "skipped" and pb["kind"] == "force":
        raise ApiError("This break cannot be skipped.", 409)
    if result == "completed" and open_ms < pb["seconds"] * 1000 - 500:
        raise ApiError("Your break is not over yet.", 409)
    sess["pending_break"] = None
    sess["breaks"].append({"kind": pb["kind"], "result": result})
    P.after_break(sess["seq"], pb["kind"], result, SIZES)
    append_csv("breaks.csv", BREAK_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"], "break_kind": pb["kind"],
        "trigger_case_id": pb["trigger"], "seconds_planned": pb["seconds"], "ms_open": open_ms,
        "result": result, "worked_ms": worked_ms(data),
    })
    return jsonify(ok=True)


@app.post("/api/session/<sid>/end")
def end_session(sid: str):
    sess = get_session(sid)
    if sess["ended"]:
        raise ApiError("This session has already ended.", 409)
    sess["ended"] = True
    rated = [c for c in sess["cases"] if "rated" in c]
    wrong = [c for s, c in zip(sess["served"], sess["cases"]) if s["kind"] == "wrong" and "rated" in c]
    append_csv("sessions.csv", SESSION_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"], "variant": VARIANT,
        "worked_ms": worked_ms(body()), "cases_reviewed": len(rated), "wrong_cases": len(wrong),
        "mistakes": sum(c["mistake"] for c in wrong),
        "breaks_offered": sum(b["kind"] == "offer" for b in sess["breaks"]),
        "breaks_taken": sum(b["kind"] == "offer" and b["result"] == "completed" for b in sess["breaks"]),
        "forced_breaks": sum(b["kind"] == "force" for b in sess["breaks"]),
    })
    return jsonify(ok=True, cases_reviewed=len(rated))


@app.post("/api/session/<sid>/principles")
def principles(sid: str):
    sess = get_session(sid)
    if not sess["ended"]:
        raise ApiError("End the session before the post-session questionnaire.", 409)
    if sess["principles"] is not None:
        raise ApiError("The post-session questionnaire is already submitted.", 409)
    data = body()
    ratings = data.get("ratings") or {}
    if any(not isinstance(ratings.get(k), int) or not 1 <= ratings[k] <= 5 for k in P.PRINCIPLE_IDS):
        raise ApiError("Rate all five principles from 1 to 5.")
    comment = str(data.get("comment") or "").strip()
    if not comment:
        raise ApiError("The general comment is required.")
    sess["principles"] = ratings
    append_csv("principles.csv", PRINCIPLE_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"],
        **{k: ratings[k] for k in P.PRINCIPLE_IDS}, "comment": comment[:2000],
    })
    return jsonify(ok=True)


@app.post("/api/session/<sid>/events")
def events(sid: str):
    sess = get_session(sid)
    data = body()
    event = str(data.get("event", ""))
    if not EVENT_RE.match(event):
        raise ApiError("Unknown event name.")
    idx = data.get("case_index")
    case_id = sess["served"][idx]["case_id"] if isinstance(idx, int) and 0 <= idx < len(sess["served"]) else ""
    payload = json.dumps(data.get("data"), ensure_ascii=False)[:2000]
    append_csv("events.csv", EVENT_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"],
        "case_id": case_id, "client_ms": data.get("client_ms", ""), "event": event, "data": payload,
    })
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))
