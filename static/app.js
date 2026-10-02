/* Cashy Second Look: review flow.
   Server mode talks to the Flask API (app.py). Demo mode (window.CASHY_DEMO set by build_demo.py)
   uses an in-page mock with the same contract, so the single-file prototype behaves the same. */
(function () {
  "use strict";

  const DEMO = window.CASHY_DEMO || null;
  const params = new URLSearchParams(location.search);
  const RESEARCH = !!DEMO || params.has("research");
  // Participant code comes from the link, e.g. /?p=P-07. Without ?p= the session uses P-07.
  const PARTICIPANT = (params.get("p") || "").trim() || "P-07";
  const $ = (id) => document.getElementById(id);

  function h(tag, props, ...kids) {
    const n = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }
  const fmtMs = (ms) => { const s = Math.floor(ms / 1000); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };

  /* ---------- Instruments (Annex II, verbatim) ---------- */
  const ITEMS = [
    { id: "EC1", q: "Rate the effectiveness of Cashy-AI for identifying and selecting the “right” individuals for the assistance", kind: "likert", l: "Not effective", r: "Very effective" },
    { id: "EC2", q: "Do you agree or disagree with Cashy-AI's final recommendation for this case?", kind: "seg", opts: ["Agree", "Disagree"] },
    { id: "EC3", q: "Why do you disagree? Select all that apply", kind: "check", cond: true, opts: ["Inaccurate or incorrect information", "Irrelevant or incomplete information", "Not appropriate or unexpected result", "Unfair or unjust decision", "Disrespects staff autonomy to change the decision", "Lack of transparency or explainability", "Unclear roles between staff and tool"] },
    { id: "EC4", q: "Do you want to override Cashy-AI's final recommendation?", kind: "seg", cond: true, opts: ["Yes", "No"], labels: ["Yes, override", "No, keep Cashy's recommendation"] },
    { id: "EC5", q: "Does Cashy-AI provide a correct and accurate recommendation?", kind: "likert", l: "Completely inaccurate", r: "Completely accurate" },
    { id: "EC6", q: "Does Cashy-AI provide content that is relevant to help you make an informed decision?", kind: "likert", l: "Strongly disagree", r: "Strongly agree" },
    { id: "EC7", q: "Does Cashy-AI provide a recommendation that is appropriate to the vulnerability profile of the case?", kind: "likert", l: "Very inappropriate", r: "Very appropriate" }
  ];
  const PRINCIPLES = [
    { id: "harm", name: "Do no harm", def: "Prevent causing or exacerbating harm, respect human rights and adhere to UN principles.", q: "Where does Cashy-AI fall on the following harm scale?", labels: ["Actively harmful", "Lacks safeguards", "Basic safety", "Minimizes harm", "Proactively protective"] },
    { id: "fairness", name: "Fairness and non-discrimination", def: "Ensure an equal and just distribution of benefits, risks and costs, and prevent bias, discrimination and stigmatization; consider whether results are equitable across demographic groups.", q: "Based on your analysis, where does Cashy-AI fall on the following fairness scale?", labels: ["Discriminatory", "Potentially biased", "Mixed fairness", "Largely fair", "Highly fair"] },
    { id: "autonomy", name: "Human autonomy and oversight", def: "Uphold human autonomy through human-centric design and oversight, maintaining human control and override capabilities; consider the control staff retain and whether they can intervene, override or customize the system.", q: "Evaluate Cashy-AI's impact on human autonomy using the scale below.", labels: ["Undermines staff autonomy", "Limits staff autonomy", "Basic staff autonomy", "Respects staff autonomy", "Enhances staff autonomy"] },
    { id: "transparency", name: "Transparency and explainability", def: "Be transparent and explainable, ensuring users can understand and trace recommendations.", q: "How transparent and explainable is Cashy-AI?", labels: ["Opaque", "Limited transparency", "Partial transparency", "Largely transparent", "Fully transparent"] },
    { id: "accountability", name: "Responsibility and accountability", def: "Guarantee full accountability via oversight, audit or due-diligence mechanisms, and clearly define human responsibility.", q: "Based on the oversight and the clarity of defined human responsibilities, where does Cashy-AI fall on the following accountability scale?", labels: ["Unaccountable", "Weak accountability", "Basic accountability", "Good accountability", "Strong accountability"] }
  ];

  /* Mirrors protocol.classify() in Python. */
  const opposite = (d) => (d === "INCLUDE" ? "EXCLUDE" : "INCLUDE");
  function classify(own, cashy, ref, ec2, ec4) {
    const final = (ec2 === "Agree" || ec4 === "No") ? cashy : opposite(cashy);
    const relation = cashy === ref ? "concordant" : "discordant";
    const outcome = relation === "discordant"
      ? (final !== cashy ? "correct_override" : "over_reliance")
      : (final === cashy ? "correct_acceptance" : "under_reliance");
    return { relation, final_decision: final, outcome, switched_to_cashy: own !== cashy && final === cashy, end_to_end_correct: final === ref };
  }

  /* ---------- API ---------- */
  async function req(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "The server did not accept the request (" + r.status + ").");
    return data;
  }
  const serverApi = {
    start: (participant) => req("POST", "/api/session", { participant }),
    getCase: (i) => req("GET", `/api/session/${S.session}/case/${i}`),
    decide: (i, decision, extra) => req("POST", `/api/session/${S.session}/case/${i}/decision`, Object.assign({ decision }, extra)),
    rate: (i, answers) => req("POST", `/api/session/${S.session}/case/${i}/rate`, answers),
    second: (i, value, reason) => req("POST", `/api/session/${S.session}/case/${i}/second`, { value, reason }),
    principles: (ratings, comment) => req("POST", `/api/session/${S.session}/principles`, { ratings, comment }),
    log: (i, event, data, ms) => {
      fetch(`/api/session/${S.session}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_index: i, event, data, client_ms: ms }), keepalive: true }).catch(() => {});
    }
  };
  function mockApi(D) {
    const own = {};
    return {
      start: async (p) => ({ session: "demo", participant: p, total: D.cases.length }),
      getCase: async (i) => D.cases[i].public,
      decide: async (i, decision) => { own[i] = decision; return { cashy: D.cases[i].hidden.cashy }; },
      rate: async (i, a) => {
        const c = D.cases[i].hidden;
        const cls = classify(own[i], c.cashy.recommendation, c.reference.target, a.EC2, a.EC4);
        return { reference: c.reference, record: Object.assign(cls, { gap_ec6_minus_ec5: a.EC6 - a.EC5 }) };
      },
      second: async () => ({ ok: true }),
      principles: async () => ({ ok: true }),
      log: () => {}
    };
  }
  const api = DEMO ? mockApi(DEMO) : serverApi;

  /* ---------- State ---------- */
  let S;
  function fresh() {
    return { page: "review", session: null, participant: null, total: 0, idx: 0, kase: null, events: [], t0: Date.now(),
      tab: "agree", firstTab: "agree", viewed: [], decision: null, cashy: null, ec: {}, ec3: [], submitted: false, solved: false, reference: null, record: null,
      second: null, reason: "", pr: {}, comment: "", prDone: false, busy: false, transitionTimer: null, toastTimer: null };
  }
  function resetCase() {
    const first = Math.random() < 0.5 ? "agree" : "disagree"; // counterbalance which side is read first
    Object.assign(S, { kase: null, tab: first, firstTab: first, viewed: [first], decision: null, cashy: null, ec: {}, ec3: [], submitted: false,
      solved: false, reference: null, record: null, second: null, reason: "", t0: Date.now() });
    if ($("secReason")) $("secReason").value = "";
  }
  function log(event, data) {
    const ms = Date.now() - S.t0;
    S.events.push({ case: S.kase ? S.kase.case_id : "-", ms, event, data });
    if (S.session) api.log(S.idx, event, data, ms);
    renderLog();
  }
  async function run(fn) {
    if (S.busy) return;
    S.busy = true; $("errBox").hidden = true;
    try { await fn(); }
    catch (e) { $("errBox").textContent = e.message; $("errBox").hidden = false; }
    finally { S.busy = false; render(); }
  }

  /* ---------- Derived ---------- */
  const isDisagree = () => S.ec.EC2 === "Disagree";
  function canSubmit() {
    if (!["EC1", "EC2", "EC5", "EC6", "EC7"].every((k) => S.ec[k] != null)) return false;
    return isDisagree() ? S.ec3.length > 0 && S.ec.EC4 != null : true;
  }
  const gap = () => (S.ec.EC6 != null && S.ec.EC5 != null ? S.ec.EC6 - S.ec.EC5 : null);

  /* ---------- Flow ---------- */
  async function startSession(code) {
    const r = await api.start(code);
    Object.assign(S, { session: r.session, participant: r.participant, total: r.total, events: [] });
    await loadCase(0);
  }
  async function loadCase(i) {
    if (S.transitionTimer) clearTimeout(S.transitionTimer);
    if (S.toastTimer) clearTimeout(S.toastTimer);
    S.toastTimer = null;
    resetCase();
    S.idx = i;
    S.kase = await api.getCase(i);
    buildCase();
    S.page = "review";
    log("case_opened", { case_id: S.kase.case_id, first_tab: S.firstTab });
    window.scrollTo(0, 0);
  }
  async function decide(decision) {
    const r = await api.decide(S.idx, decision, { first_tab: S.firstTab, tabs_viewed: S.viewed });
    S.decision = decision; S.cashy = r.cashy;
    log("decision", { decision });
    log("cashy_revealed", { recommendation: r.cashy.recommendation });
    S.page = "rate";
    window.scrollTo(0, 0);
  }
  async function submit() {
    const a = { EC1: S.ec.EC1, EC2: S.ec.EC2, EC3: isDisagree() ? S.ec3 : [], EC4: isDisagree() ? S.ec.EC4 : null, EC5: S.ec.EC5, EC6: S.ec.EC6, EC7: S.ec.EC7 };
    const r = await api.rate(S.idx, a);
    S.reference = r.reference; S.record = r.record; S.submitted = true; S.solved = true;
    log("submitted", { gap: r.record.gap_ec6_minus_ec5, outcome: r.record.outcome });
    render();
    window.scrollTo(0, 0);

    if (S.toastTimer) clearTimeout(S.toastTimer);
    if (S.transitionTimer) clearTimeout(S.transitionTimer);
    S.toastTimer = null;
    S.transitionTimer = null;

    if (S.idx + 1 < S.total) {
      await loadCase(S.idx + 1);
    } else {
      S.page = "post";
      log("post_session_opened");
      window.scrollTo(0, 0);
    }
  }
  async function next() {
    if (S.idx + 1 < S.total) await loadCase(S.idx + 1);
    else { S.page = "post"; log("post_session_opened"); window.scrollTo(0, 0); }
  }
  async function finish() {
    await api.principles(S.pr, S.comment.trim());
    S.prDone = true;
    log("principles_submitted", { ratings: S.pr, comment_chars: S.comment.trim().length });
  }

  /* ---------- Build: case ---------- */
  function buildCase() {
    const k = S.kase;
    const cardA = $("cardA");
    if (cardA && Array.isArray(k.household)) {
      cardA.replaceChildren(...k.household.map((f) =>
        h("div", { class: "field" }, h("span", { class: "k", text: f.label }),
          h("span", { class: "v" + (f.na ? " na" : "") }, f.value, f.note ? h("small", null, " " + f.note) : null))));
    }

    const cardC = $("cardC");
    if (cardC && Array.isArray(k.admin)) {
      cardC.replaceChildren(...k.admin.map((f) =>
        h("div", { class: "flag" }, h("span", { text: f.label }), h("span", { class: "chip " + f.tone, text: f.chip }))));
    }

    const factorRow = (f) => h("div", { class: "factor" },
      h("span", { text: f.name }), h("span", { class: "mono", text: f.value.toFixed(2) }),
      h("span", { class: "bar" }, Array.from({ length: f.levels }, (_, i) => h("i", { class: i <= f.level ? "on" : null })),
        f.max ? h("span", { class: "max", text: "MAX" }) : null));

    const factorsDemo = $("factorsDemo");
    if (factorsDemo && Array.isArray(k.factors)) {
      factorsDemo.replaceChildren(...k.factors.filter((f) => f.group === "demographics").map(factorRow));
    }
    const factorsNeeds = $("factorsNeeds");
    if (factorsNeeds && Array.isArray(k.factors)) {
      factorsNeeds.replaceChildren(...k.factors.filter((f) => f.group === "needs").map(factorRow));
    }

    const cardD = $("cardD");
    if (cardD && k.totals) {
      const t = k.totals;
      cardD.replaceChildren(
        h("div", { class: "fields" },
          h("div", { class: "field" }, h("span", { class: "k", text: "Demographics" }), h("span", { class: "v mono", text: t.demographics.toFixed(1) })),
          h("div", { class: "field" }, h("span", { class: "k", text: "Needs & coping" }), h("span", { class: "v mono", text: "+ " + t.needs.toFixed(1) }))),
        h("hr", { class: "div" }),
        h("div", { class: "total" }, h("span", { class: "muted", text: "FinalScore" }),
          h("span", { class: "big" }, t.final.toFixed(1) + " ", h("small", { text: "/ " + t.final_max }))),
        h("div", { class: "fields" },
          h("div", { class: "field" }, h("span", { class: "k" }, "Vulnerability_Score ", h("small", { class: "muted", text: "(index)" })), h("span", { class: "v mono", text: t.vulnerability_score.toFixed(2) })),
          h("div", { class: "field" }, h("span", { class: "k", text: "Band" }), h("span", { class: "v" }, h("span", { class: "chip primary", text: t.band })))));
    }

    const viewText = $("viewText");
    if (viewText) viewText.replaceChildren(...k.interviewer_view.map((t) => h("p", { text: t })));
    showTab(S.tab);
  }
  function showTab(tab) {
    document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    const reasoningText = $("reasoningText");
    if (!reasoningText || !S.kase || !S.kase.reasoning || !S.kase.reasoning[tab]) return;
    const list = h("ul", { class: "reasoning-list" }, ...S.kase.reasoning[tab].map((t) => h("li", { text: t })));
    reasoningText.replaceChildren(list);
    reasoningText.scrollTop = 0;
  }

  /* ---------- Build: items and principles (once) ---------- */
  function buildItems() {
    const box = $("qs");
    let cond = null;
    for (const it of ITEMS) {
      const wrap = h("div", { class: "item" }, h("div", { class: "qt" }, h("span", { class: "chip primary mono", text: it.id }), h("span", { text: it.q })));
      if (it.kind === "likert") {
        wrap.append(h("div", { class: "likert" },
          h("span", { class: "end l", text: it.l }),
          h("div", { class: "dots", role: "group", "aria-label": it.id },
            [1, 2, 3, 4, 5].map((v) => h("button", { type: "button", "data-item": it.id, "data-v": v, "aria-pressed": "false",
              onclick: () => { S.ec[it.id] = v; log("item_answered", { item: it.id, value: v }); render(); } }, v))),
          h("span", { class: "end", text: it.r })));
      } else if (it.kind === "seg") {
        wrap.append(h("div", { class: "seg" }, it.opts.map((o, i) => h("button", { type: "button", "data-item": it.id, "data-v": o, "aria-pressed": "false",
          onclick: () => { S.ec[it.id] = o; log("item_answered", { item: it.id, value: o }); render(); } }, (it.labels || it.opts)[i]))));
        if (it.id === "EC4") wrap.append(h("span", { class: "prefill", id: "ec4hint" }));
      } else {
        wrap.append(h("div", { class: "checklist" }, it.opts.map((o, i) => h("label", null,
          h("input", { type: "checkbox", id: "ec3-" + i, value: o, onchange: () => {
            S.ec3 = Array.from(document.querySelectorAll(".checklist input:checked")).map((x) => x.value);
            log("item_answered", { item: "EC3", value: S.ec3.slice() }); render();
          } }), h("span", { text: o })))));
      }
      if (it.cond) { if (!cond) { cond = h("div", { class: "cond", id: "condBox" }); box.append(cond); } cond.append(wrap); }
      else box.append(wrap);
    }
  }
  function buildPrinciples() {
    $("principles").append(...PRINCIPLES.map((p) => h("div", { class: "principle" },
      h("h4", { text: p.name }), h("p", { class: "def", text: p.def }), h("div", { class: "q", text: p.q }),
      h("div", { class: "scale5", role: "group", "aria-label": p.name }, p.labels.map((lab, i) =>
        h("button", { type: "button", "data-p": p.id, "data-v": i + 1, "aria-pressed": "false",
          onclick: () => { S.pr[p.id] = i + 1; log("principle_rated", { principle: p.id, value: i + 1 }); render(); } },
          h("b", { text: i + 1 }), lab))))));
  }

  /* ---------- Render ---------- */
  const PAGES = { review: "pReview", rate: "pRate", post: "pPost" };
  function render() {
    const p = S.page;
    for (const [k, id] of Object.entries(PAGES)) $(id).hidden = p !== k;
    document.querySelectorAll("[data-jump]").forEach((b) => b.setAttribute("aria-current", String(b.dataset.jump === p)));

    // Top bar
    const step = { review: 1, rate: 2, post: 2 }[p] || 0;
    $("stepper").hidden = step === 0;
    document.querySelectorAll("#stepper span").forEach((s) => {
      const n = +s.dataset.step;
      s.className = n === step ? "on" : n < step ? "done" : "";
      s.textContent = (n < step ? "✓ " : n + " ") + ["Review", "Rate"][n - 1];
    });
    const meta = $("meta");
    if (S.kase && step >= 1 && step <= 3) {
      meta.replaceChildren(
        h("span", null, "Case ", h("b", { text: S.kase.case_id })),
        h("span", null, "Office ", h("b", { text: S.kase.meta.office })),
        h("span", null, "Interview ", h("b", { text: S.kase.meta.month }))
      );
    } else meta.replaceChildren(h("span", { text: p === "post" ? "Post-session questionnaire" : "Review session" }));
    $("caseChip").textContent = S.participant
      ? (p === "post" ? "Session complete" : `Case ${S.idx + 1} / ${S.total}`)
      : "Not started";

    // S1
    if (S.kase) {
      const can = !S.decision && !S.busy;
      $("decInclude").disabled = !can; $("decExclude").disabled = !can;
      $("decInclude").setAttribute("aria-pressed", String(S.decision === "INCLUDE"));
      $("decExclude").setAttribute("aria-pressed", String(S.decision === "EXCLUDE"));
      $("backBtn").hidden = !S.decision;
      $("decideHint").textContent = S.decision
        ? `Your decision (${S.decision}) is logged and locked. You are viewing the case again.`
        : "Cashy's recommendation appears after you decide. Your decision is logged first.";
    }

    // S2a
    if (S.cashy) {
      const c = S.cashy;
      $("rvBadge").textContent = c.recommendation;
      $("rvScore").textContent = Number(c.score).toFixed(1);
      $("rvCat").textContent = c.category;
      $("rvCert").textContent = c.certainty_text;
      document.querySelectorAll("#rvCertBars i").forEach((i, k) => i.classList.toggle("on", k < c.certainty_level));
      const same = S.decision === c.recommendation;
      $("rvWarn").classList.toggle("same", same);
      $("rvWarnTxt").textContent = same
        ? `You decided ${S.decision}. Cashy also recommends ${c.recommendation}.`
        : `You decided ${S.decision}. Cashy recommends ${c.recommendation}.`;
      $("rcOwn").textContent = S.decision;
      const hint = $("ec4hint");
      if (hint) hint.textContent = `Yes means the final decision is ${opposite(c.recommendation)}. No means it is ${c.recommendation}.`;
    }
    document.querySelectorAll("[data-item]").forEach((b) => {
      const v = b.dataset.v, cur = S.ec[b.dataset.item];
      b.setAttribute("aria-pressed", String(cur != null && String(cur) === v)); b.disabled = S.submitted;
    });
    document.querySelectorAll(".checklist input").forEach((i) => { i.checked = S.ec3.includes(i.value); i.disabled = S.submitted; });
    if ($("condBox")) $("condBox").hidden = !isDisagree();
    const solved = !!S.solved;
    $("submitBtn").disabled = !canSubmit() || S.submitted || S.busy;
    $("submitBtn").textContent = S.submitted ? "Submitted" : "Submit & next case →";
    $("submitHint").textContent = solved ? "Case recorded. Moving to the next case…" : S.submitted ? "Submitted and locked." : canSubmit() ? "You can't change these answers after submitting." : "Answer every item to continue.";
    $("lockChip").textContent = S.submitted ? "Locked" : "7 items · Annex II";
    if ($("rateSolved")) $("rateSolved").hidden = !solved;

    // S3
    $("postTitle").textContent = `Session complete · ${S.total} of ${S.total} households reviewed`;
    $("postCode").textContent = S.participant || "–";
    document.querySelectorAll("[data-p]").forEach((b) => { b.setAttribute("aria-pressed", String(S.pr[b.dataset.p] === +b.dataset.v)); b.disabled = S.prDone; });
    $("prComment").disabled = S.prDone;
    const ready = PRINCIPLES.every((x) => S.pr[x.id]) && S.comment.trim().length > 0;
    $("prSubmit").disabled = !ready || S.prDone || S.busy;
    $("prHint").textContent = S.prDone ? "Submitted." : ready ? "Ready to finish." : "Answer all five items and add a comment to finish.";
    $("prChip").textContent = S.prDone ? "Locked" : "5 items · Annex II 2c";
    $("prDone").hidden = !S.prDone;

    renderLog();
  }

  function renderLog() {
    if ($("drawer").hidden) return;
    const r = S.record;
    const g = gap();
    const metrics = [
      ["Case relation", r ? r.relation : "hidden until submit"],
      ["Reliance outcome", r ? r.outcome.replace(/_/g, " ") : "pending"],
      ["Reasoning–answer gap", g == null ? "–" : (g > 0 ? "+" : "") + g + " (EC6 − EC5)"],
      ["Reasoning tabs read", S.kase ? `${S.viewed.join(" + ")} (first: ${S.firstTab})` : "–"],
      ["You → Cashy → final", S.decision ? `${S.decision} → ${S.cashy ? S.cashy.recommendation : "?"} → ${r ? r.final_decision : "?"}` : "–"],
      ["Switched to Cashy", r ? (r.switched_to_cashy ? "yes" : "no") : "–"]
    ];
    $("metrics").replaceChildren(...metrics.map(([k, v]) => h("div", { class: "metric" }, h("div", { class: "mk", text: k }), h("div", { class: "mv", text: v }))));
    const items = S.events.slice().reverse().map((e) => h("li", null, h("span", { class: "mono muted", text: fmtMs(e.ms) }),
      h("span", null, h("code", { text: e.event }), " ", h("span", { class: "muted", text: e.case + (e.data ? " " + JSON.stringify(e.data) : "") }))));
    $("events").replaceChildren(...(items.length ? items : [h("li", { class: "muted", text: "No events yet." })]));
    $("rec").textContent = JSON.stringify({
      participant: S.participant, case_id: S.kase ? S.kase.case_id : null,
      own_decision: S.decision, reasoning_first_tab: S.firstTab, reasoning_tabs_viewed: S.viewed,
      cashy: S.cashy, reference: S.reference || "withheld until submit",
      EC1: S.ec.EC1 ?? null, EC2: S.ec.EC2 ?? null, EC3: isDisagree() ? S.ec3 : null, EC4: isDisagree() ? (S.ec.EC4 ?? null) : null,
      EC5: S.ec.EC5 ?? null, EC6: S.ec.EC6 ?? null, EC7: S.ec.EC7 ?? null,
      gap_ec6_minus_ec5: g, result: r, second_decision: S.second,
      post_session: S.prDone ? { ratings: S.pr } : null
    }, null, 2);
  }

  /* ---------- Demo jumps (prototype only) ---------- */
  async function jump(target) {
    const auto = () => DEMO.cases[S.idx].autofill;
    if (target === "review" || !S.session) { S = fresh(); await startSession(PARTICIPANT); if (target === "review") return; }
    if (target === "post") { S.page = "post"; log("demo_jump", { to: "post" }); return; }
    if (S.page === "review" && !S.decision) await decide(auto().decision);
    if (target === "rate") { S.page = "rate"; return; }
    if (!S.submitted) {
      const a = auto().answers;
      Object.assign(S.ec, { EC1: a.EC1, EC2: a.EC2, EC4: a.EC4, EC5: a.EC5, EC6: a.EC6, EC7: a.EC7 }); S.ec3 = a.EC3.slice();
      await submit();
    }
    S.page = "rate";
  }

  /* ---------- Wire ---------- */
  $("decInclude").addEventListener("click", () => run(() => decide("INCLUDE")));
  $("decExclude").addEventListener("click", () => run(() => decide("EXCLUDE")));
  $("viewCase").addEventListener("click", () => { log("viewed_case_again"); S.page = "review"; render(); window.scrollTo(0, 0); });
  $("submitBtn").addEventListener("click", () => run(submit));
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    const tab = b.dataset.tab;
    if (tab === S.tab) return;
    S.tab = tab;
    if (!S.viewed.includes(tab)) S.viewed.push(tab);
    showTab(tab);
    log("reasoning_tab", { tab });
  }));
  $("prComment").addEventListener("input", (e) => { S.comment = e.target.value; render(); });
  $("prSubmit").addEventListener("click", () => run(finish));
  $("restart").addEventListener("click", () => { S = fresh(); $("prComment").value = ""; run(() => startSession(PARTICIPANT)); });
  $("openLog").addEventListener("click", () => { $("drawer").hidden = false; renderLog(); });
  $("closeLog").addEventListener("click", () => { $("drawer").hidden = true; });
  document.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => run(() => jump(b.dataset.jump))));

  $("backBtn").addEventListener("click", () => { S.page = "rate"; render(); window.scrollTo(0, 0); });

  S = fresh();
  buildItems();
  buildPrinciples();
  $("demoStrip").hidden = !DEMO && !RESEARCH;
  document.querySelector(".demo-tabs").hidden = !DEMO;
  $("openLog").hidden = !RESEARCH;
  run(() => startSession(PARTICIPANT));
})();
