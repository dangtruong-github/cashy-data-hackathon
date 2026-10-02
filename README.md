# Cashy: caseworker review screen

A review screen for the UNHCR Cashy Oversight Challenge. The caseworker reads the household record and Cashy's reasoning **for both sides** (an *Agree* tab with reasons to include, a *Disagree* tab with reasons to exclude), and makes their own Include / Exclude decision. Cashy's assessment is shown only after that decision is logged, then the caseworker answers the Annex II items (EC1–EC7) and moves to the next household.

Most households are **genuine cases**. Now and then the screen shows a **wrong case**, where the vulnerability band on the record has been changed. How the caseworker handles wrong cases decides when the screen offers or enforces a break. A work clock at the top right counts only the time spent reviewing. When the caseworker ends the session, they answer the five UN AI principle items once.

All data is synthetic. Records come from `S8.synthetic_cashy_sample.csv`. The reasoning in `cases/cases.json` is written by hand; for every other S8 row it is generated from the factor levels. No real household or caseworker appears anywhere.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and press **Start**. The participant code is `P-07` unless the link carries one, such as http://127.0.0.1:5000/?p=P-12 (2–16 letters, digits, `-` or `_`; never a name). Add `?research=1` (or `&research=1` after `p`) to show the researcher log drawer.

| Variable | Default | Meaning |
|---|---|---|
| `CASHY_S8_PATH` | `S8.synthetic_cashy_sample.csv` | Synthetic Scorecard records |
| `CASHY_CASES_PATH` | `cases/cases.json` | Hand-written cases, shown first as genuine cases |
| `CASHY_LOG_DIR` | `logs/` | Where the CSV logs are written |
| `CASHY_VARIANT` | `cashy_reasoning_first` | Design variant label written to every row |
| `CASHY_BLOCK_START` | `1` (design: `10`) | Genuine cases at the start of each cycle |
| `CASHY_BLOCK_REPEAT` | `1` (design: `5`) | Genuine cases before each first wrong case |
| `CASHY_BLOCK_AFTER_MISTAKE` | `1` | Genuine cases between a missed wrong case and the break offer |
| `CASHY_BREAK_SECONDS` | `10` | Length of an offered break |
| `CASHY_FORCED_BREAK_SECONDS` | `10` | Length of a forced break |
| `PORT` | `5000` | Server port |

The defaults are set for a short demo. For the full design, set `CASHY_BLOCK_START=10` and `CASHY_BLOCK_REPEAT=5`, and set the break lengths the operation chooses.

## Flow

Each household goes through two pages:

| Page | What happens | What the server releases |
|---|---|---|
| Review | Card A (household), card B (Scorecard factors), card C (Scorecard totals and band), Cashy's reasoning in two tabs (Agree = include, Disagree = exclude; the tab shown first is random per case). Include / Exclude buttons | Public record only. On a wrong case the band in card C is changed |
| Reveal & rate | Cashy's assessment: Include % / Exclude %, score, category and what the percentages are based on. Then EC1–EC7 (EC3 and EC4 only after Disagree). Submitting opens the next household | Cashy's answer, after the decision is logged |

### Cases and breaks

```
Start → N genuine → M genuine → 1st wrong case
          ▲            ▲            ├─ caught  → back to the M genuine cases
          │            │            └─ mistake → 1 genuine → break offered
          │            │                           ├─ closed → back to Start
          │            │                           └─ taken  → 2nd wrong case
          │            └──────────────────────────────────────── ├─ caught
          └───────────────────── forced break (cannot be closed) ┘─ mistake
```

- **Genuine case:** the record as it is in S8.
- **Wrong case:** the band in card C points away from the recorded determination. An included household is shown as *Baja*, an excluded one as *Severa*. The factors, scores and Vulnerability_Score stay true, so the mismatch can be noticed. Rows with a −500 administrative flag are never used as wrong cases.
- **Mistake:** on a wrong case, the caseworker's Include / Exclude decision differs from the operation's recorded determination (`EligibilityTarget`).
- **Offered break:** a pop-up with an encouraging message that uses the time worked, and a countdown. Closing it skips the break.
- **Forced break:** the same pop-up without a close button. The server will not open the next case until the time is up.

The browser never learns whether a case is genuine or wrong; the server picks the next case.

### Work clock

**Start** begins the clock and opens the first household. **Pause** stops it and covers the screen, with **Continue** or **End**. The clock does not run during a pause or a break. **End** closes the session and opens the post-session questionnaire: the five UN AI principle items (1–5) and a required comment about Cashy as a whole, once per session.

### Cashy's assessment

Cashy shows no Include / Exclude verdict. It shows how often comparable past households were included: the 30 S8 households from the same month with the closest FinalScore. The same month is used because inclusion in S8 depends mostly on the month (3% to 44% included), and hardly on the score (20–27% at every score level).

## Logs (Power BI ready)

| File | One row per | Key columns |
|---|---|---|
| `assessments.csv` | Case | `phase`, `case_kind`, `true_band`, `shown_band`, `cashy_include_pct`, `own_decision`, `reference_target`, `own_correct`, `mistake`, `EC1`–`EC7`, `gap_ec6_minus_ec5`, `outcome`, `reasoning_first_tab`, `reasoning_tabs_viewed`, timings |
| `breaks.csv` | Break | `break_kind` (offer / force), `trigger_case_id`, `seconds_planned`, `ms_open`, `result` (completed / skipped), `worked_ms` |
| `sessions.csv` | Session | `worked_ms`, `cases_reviewed`, `wrong_cases`, `mistakes`, `breaks_offered`, `breaks_taken`, `forced_breaks` |
| `principles.csv` | Session | Five ratings (1–5) and the comment |
| `events.csv` | Interaction | Event name, client time, small JSON payload |

If a log file was written with older columns, it is renamed to `<name>.old-<time>.csv` and a new file is started.

`outcome` follows the challenge's decomposition, using the side Cashy's percentages favour (`cashy_lean`) as Cashy's recommendation. On discordant cases it is `correct_override` or `over_reliance`; on concordant cases it is `correct_acceptance` or `under_reliance`. "Correct" means agreement with the operation's own recorded determination, which is the standard caseworkers are accountable to and not the truth about a household's need.

Analyse at the participant level (or with participant-clustered models) and report Wilson intervals; assessments from one caseworker are not independent. Free-text comments can identify people: keep `principles.csv` access-restricted.

## Adding cases

Add an entry to `cases/cases.json` with the S8 row (0-based), `reasoning.agree` and `reasoning.disagree` (paragraphs), and `demo_autofill` (used only by the offline demo). These cases are shown first, as genuine cases. The app checks them when it starts.

## Offline demo

```bash
python build_demo.py            # writes ../cashy-review-demo.html
```

This bundles the same markup, styles and script into one HTML file with an in-page mock API that runs the same case and break sequence on 20 genuine and 20 wrong cases. The demo file contains every answer, so use it for demos only, never for data collection.

## Files

```
app.py          Flask server, case picking, break enforcement, CSV logging
s8.py           S8 row → registration record, Cashy's answer, generated reasoning, wrong bands
protocol.py     Annex II items, reliance classification, case/break sequence
cases/          Hand-written review cases
templates/      Page markup (shared by app and demo)
static/         style.css, app.js (shared by app and demo)
build_demo.py   Builds the single-file offline prototype
```
