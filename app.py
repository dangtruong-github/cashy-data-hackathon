"""Cashy Second Look: caseworker review screen with server-enforced protocol and CSV logging.

Run:  python app.py   then open http://127.0.0.1:5000
      add ?research=1 to the URL to show the researcher log drawer.

The server never sends Cashy's answer before the caseworker's decision is logged,
and never sends the reference determination before the rating items are submitted.
"""
from __future__ import annotations

import csv
import json
import os
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
VARIANT = os.environ.get("CASHY_VARIANT", "second_look_reasoning_first")

ROWS = s8.load_rows(S8_PATH)


def expand_cases(cases: list[dict], rows: list[dict], target: int = 5) -> list[dict]:
    """Pad the prototype to the study's five cases per participant using unique S8 rows from the synthetic dataset."""
    if not cases:
        return []
    expanded = list(cases[:target])
    used_rows = {int(c["s8_row"]) for c in expanded if "s8_row" in c and isinstance(c.get("s8_row"), int)}
    if len(expanded) >= target:
        return expanded

    seed = expanded[0]
    for offset in range(len(rows)):
        row_index = (offset * 37 + 13) % len(rows)
        if row_index in used_rows:
            continue
        clone = json.loads(json.dumps(seed))
        clone["case_id"] = f"H-{row_index:04d}"
        clone["s8_row"] = row_index
        clone["demo_autofill"] = {
            "decision": "INCLUDE" if row_index % 2 == 0 else "EXCLUDE",
            "answers": {"EC1": 3, "EC2": "Agree" if row_index % 2 == 0 else "Disagree", "EC3": [], "EC4": None, "EC5": 3, "EC6": 3, "EC7": 3},
            "second": "Accept"
        }
        expanded.append(clone)
        used_rows.add(row_index)
        if len(expanded) >= target:
            break
    return expanded[:target]


CASES = expand_cases(json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"], ROWS, target=5)
s8.validate_cases(CASES, ROWS)

app = Flask(__name__, static_folder="static", static_url_path="/static")
SESSIONS: dict[str, dict] = {}
LOCK = threading.Lock()
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
EVENT_RE = re.compile(r"^[a-z0-9_]{1,64}$")

ASSESSMENT_FIELDS = [
    "timestamp_utc", "session_id", "participant", "variant", "case_id", "case_index",
    "relation", "own_decision", "cashy_recommendation", "reference_target",
    "EC1", "EC2", "EC3", "EC4", "EC5", "EC6", "EC7", "gap_ec6_minus_ec5",
    "final_decision", "outcome", "switched_to_cashy", "end_to_end_correct",
    "reasoning_first_tab", "reasoning_tabs_viewed", "ms_open_to_decision", "ms_decision_to_submit",
]
SECOND_FIELDS = ["timestamp_utc", "session_id", "participant", "case_id", "second_decision", "second_reason"]
PRINCIPLE_FIELDS = ["timestamp_utc", "session_id", "participant", *P.PRINCIPLE_IDS, "comment"]
EVENT_FIELDS = ["timestamp_utc", "session_id", "participant", "case_id", "client_ms", "event", "data"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_ms() -> int:
    return int(time.time() * 1000)


def append_csv(name: str, fields: list[str], row: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / name
    with LOCK:
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
    if not 0 <= index < len(CASES):
        raise ApiError("Case not found.", 404)
    st = sess["cases"].get(index)
    if st is None:
        raise ApiError("Open the case before acting on it.", 409)
    return st


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON object.")
    return data


# ---------- Page ----------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cashy Second Look</title>
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
    SESSIONS[sid] = {"id": sid, "participant": code, "cases": {}, "principles": None}
    return jsonify(session=sid, participant=code, total=len(CASES))


@app.get("/api/session/<sid>/case/<int:index>")
def open_case(sid: str, index: int):
    sess = get_session(sid)
    if not 0 <= index < len(CASES):
        raise ApiError("Case not found.", 404)
    sess["cases"].setdefault(index, {"opened_ms": now_ms()})
    return jsonify(s8.public_case(CASES[index], ROWS, index, len(CASES)))


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
    cfg = CASES[index]
    first_tab = data.get("first_tab") if data.get("first_tab") in P.REASONING_TABS else ""
    viewed = [t for t in P.REASONING_TABS if t in (data.get("tabs_viewed") or [])]
    st.update(decision=decision, first_tab=first_tab, tabs_viewed=viewed, decision_ms=now_ms())
    return jsonify(cashy=cfg["cashy"])


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
    cfg = CASES[index]
    ref = s8.reference(ROWS[cfg["s8_row"]])
    cashy = cfg["cashy"]["recommendation"]
    cls = P.classify(st["decision"], cashy, ref["target"], a["EC2"], a["EC4"])
    gap = a["EC6"] - a["EC5"]
    t = now_ms()
    st.update(rated=a, rated_ms=t)
    append_csv("assessments.csv", ASSESSMENT_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"], "variant": VARIANT,
        "case_id": cfg["case_id"], "case_index": index, "relation": cls["relation"],
        "own_decision": st["decision"], "cashy_recommendation": cashy, "reference_target": ref["target"],
        "EC1": a["EC1"], "EC2": a["EC2"], "EC3": "|".join(a["EC3"]), "EC4": a["EC4"] or "",
        "EC5": a["EC5"], "EC6": a["EC6"], "EC7": a["EC7"], "gap_ec6_minus_ec5": gap,
        "final_decision": cls["final_decision"], "outcome": cls["outcome"],
        "switched_to_cashy": cls["switched_to_cashy"], "end_to_end_correct": cls["end_to_end_correct"],
        "reasoning_first_tab": st["first_tab"], "reasoning_tabs_viewed": "|".join(st["tabs_viewed"]),
        "ms_open_to_decision": st["decision_ms"] - st["opened_ms"], "ms_decision_to_submit": t - st["decision_ms"],
    })
    return jsonify(reference=ref, record={**cls, "gap_ec6_minus_ec5": gap})


@app.post("/api/session/<sid>/case/<int:index>/second")
def second(sid: str, index: int):
    sess = get_session(sid)
    st = get_case_state(sess, index)
    if "rated" not in st:
        raise ApiError("Submit the rating items first.", 409)
    if "second" in st:
        raise ApiError("The second decision is already logged.", 409)
    data = body()
    value = data.get("value")
    if value not in ("Accept", "Override"):
        raise ApiError("Choose Accept or Override.")
    reason = str(data.get("reason") or "")[:500]
    st["second"] = value
    append_csv("second_decisions.csv", SECOND_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"],
        "case_id": CASES[index]["case_id"], "second_decision": value, "second_reason": reason,
    })
    return jsonify(ok=True)


@app.post("/api/session/<sid>/principles")
def principles(sid: str):
    sess = get_session(sid)
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
    case_id = CASES[idx]["case_id"] if isinstance(idx, int) and 0 <= idx < len(CASES) else ""
    payload = json.dumps(data.get("data"), ensure_ascii=False)[:2000]
    append_csv("events.csv", EVENT_FIELDS, {
        "timestamp_utc": now_iso(), "session_id": sid, "participant": sess["participant"],
        "case_id": case_id, "client_ms": data.get("client_ms", ""), "event": event, "data": payload,
    })
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))
