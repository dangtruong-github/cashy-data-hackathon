# Cashy Second Look: caseworker review screen

A review screen for the UNHCR Cashy Oversight Challenge. The caseworker reads the household record, the interviewer's view, the interview transcript and Cashy's reasoning **for both sides** (an *Agree* tab with reasons to include, a *Disagree* tab with reasons to exclude), and makes their own decision. Cashy's recommendation is shown only after that decision is logged. The screen then collects the Annex II items (EC1–EC7), reveals the operation's recorded determination, and ends each session with the five UN AI principle items.

All data is synthetic. Records come from `S8.synthetic_cashy_sample.csv`. The interviewer's views, transcripts, Cashy's reasoning and Cashy's answers in `cases/cases.json` are written by hand as placeholders for a Cashy-like model. No real household or caseworker appears anywhere.

## Run

```bash
cd cashy_review
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and enter a participant code such as `P-07`. Add `?research=1` to the URL to show the researcher log drawer.

| Variable | Default | Meaning |
|---|---|---|
| `CASHY_S8_PATH` | `../S8.synthetic_cashy_sample.csv` | Synthetic Scorecard records |
| `CASHY_CASES_PATH` | `cases/cases.json` | Cases shown in a session, in order |
| `CASHY_LOG_DIR` | `logs/` | Where the CSV logs are written |
| `CASHY_VARIANT` | `second_look_reasoning_first` | Design variant label written to every row |
| `PORT` | `5000` | Server port |

## Flow

| Page | What happens | What the server releases |
|---|---|---|
| S0 Start | Participant enters a pseudonymous code (names are rejected by format) | Session id |
| S1 Review | Record cards A–D, then three columns: interviewer's view, transcript, and Cashy's reasoning as plain text in two tabs (Agree = include, Disagree = exclude). The tab shown first is random per case. Include / Exclude buttons | Public record only |
| S2a Reveal & rate | Cashy's recommendation, score, category and certainty, then EC1–EC7 (EC3 and EC4 only after Disagree) | Cashy's answer, after the decision is logged |
| S2b Compare | Own decision, Cashy and the operation's recorded determination side by side, then accept or override that determination | Reference determination, after EC items are submitted |
| S3 Post-session | Five UN AI principle items and a required comment, once per session | – |

The server enforces this order, so nothing can be fetched early from the browser.

## Logs (Power BI ready)

| File | One row per | Key columns |
|---|---|---|
| `assessments.csv` | Case | `relation`, `own_decision`, `cashy_recommendation`, `reference_target`, `EC1`–`EC7`, `gap_ec6_minus_ec5`, `final_decision`, `outcome`, `switched_to_cashy`, `end_to_end_correct`, `reasoning_first_tab`, `reasoning_tabs_viewed`, timings |
| `second_decisions.csv` | Case | Accept / Override of the recorded determination |
| `principles.csv` | Session | Five ratings (1–5) and the comment |
| `events.csv` | Interaction | Event name, client time, small JSON payload |

`outcome` follows the challenge's decomposition. On discordant cases (Cashy differs from the recorded determination) it is `correct_override` or `over_reliance`; on concordant cases it is `correct_acceptance` or `under_reliance`. "Correct" means agreement with the operation's own recorded determination, which is the standard caseworkers are accountable to and not the truth about a household's need. Over-reliance is defined by EC4, as in the study.

Analyse at the participant level (or with participant-clustered models) and report Wilson intervals; assessments from one caseworker are not independent. Free-text comments can identify people: keep `principles.csv` and `second_decisions.csv` access-restricted.

## Adding cases

Add an entry to `cases/cases.json` with the S8 row (0-based), `interviewer_view` (paragraphs), `transcript` (lines with time in seconds), `reasoning.agree` and `reasoning.disagree` (paragraphs), Cashy's answer, and `demo_autofill` (used only by the offline demo). The app checks references when it starts. Mix concordant and discordant cases, and both error directions, so error direction is not confounded with case.

## Offline demo

```bash
python build_demo.py            # writes ../cashy-review-demo.html
```

This bundles the same markup, styles and script into one HTML file with an in-page mock API, so the prototype and the app never drift apart. The demo file contains every answer, so use it for demos only, never for data collection.

## Files

```
app.py          Flask server, protocol order, CSV logging
s8.py           S8 row → registration record (Annex I labels and factor levels)
protocol.py     Annex II items, reliance classification, answer validation
cases/          Synthetic review cases
templates/      Page markup (shared by app and demo)
static/         style.css, app.js (shared by app and demo)
build_demo.py   Builds the single-file offline prototype
```
