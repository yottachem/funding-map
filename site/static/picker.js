/* Funding roadmap picker: the browser copy of tracker/picker.py. Same rules, same text; tests/test_site.py runs both
   on the same profiles and compares every field. Figures (size, cash timing, odds text) come precomputed from
   tracker.picker.site_data, so nothing here estimates. Dates are day numbers (days since 1970-01-01, UTC). */
(function (root) {
  "use strict";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const ROLLING = /\brolling\b|\banytime\b/i;
  const GO_NO_GO = /go\/no-go/i;
  const ENTITY_REASON = { "small-business": "needs a small business", "academic": "university-led" };
  const DAY = 86400000;

  const day = iso => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / DAY; };
  const ymd = n => { const t = new Date(n * DAY); return [t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()]; };
  const pad = v => String(v).padStart(2, "0");
  const iso = n => { const [y, m, d] = ymd(n); return `${y}-${pad(m)}-${pad(d)}`; };
  const bd = n => { const [, m, d] = ymd(n); return `${MONTHS[m - 1]} ${pad(d)}`; };            // %b %d
  const bdy = n => { const [y, m, d] = ymd(n); return `${MONTHS[m - 1]} ${pad(d)}, ${y}`; };    // %b %d, %Y
  function addMonths(n, k) {
    const [y0, m0, d] = ymd(n);
    const t = m0 - 1 + k, y = y0 + Math.floor(t / 12), m = ((t % 12) + 12) % 12 + 1;
    const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    return Date.UTC(y, m - 1, Math.min(d, last)) / DAY;
  }
  function pyRound(x) {                       // Python round(): halves go to the even integer
    const r = Math.round(x);
    return Math.abs(x - Math.trunc(x)) === 0.5 && r % 2 !== 0 ? r - 1 : r;
  }
  const today = () => { const t = new Date(); return Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()) / DAY; };

  function ineligible(p, prof, verified) {
    const out = [];
    if (p.state && prof.state !== p.state) out.push(`${p.state} companies only`);
    if (p.entity !== "either" && p.entity !== prof.entity) out.push(ENTITY_REASON[p.entity]);
    if (!p.domains.some(d => prof.domains.includes(d))) out.push("outside your domains");
    if (prof.trl && p.trl && !(p.trl[0] <= prof.trl && prof.trl <= p.trl[1])) out.push(`TRL ${p.trl[0]}-${p.trl[1]} only`);
    if (p.status === "closed" || p.status === "paused") out.push(`${p.status} (as of ${verified})`);
    return out;
  }

  function pick(data, prof, startIso) {
    const start = startIso ? day(startIso) : today();
    const end = addMonths(start, data.window_months);
    const progs = new Map(data.programs.map(p => [p.id, p]));
    const held = new Set(prof.held || []);
    const prep = prof.prep_days == null ? 30 : prof.prep_days;
    const reasons = new Map(data.programs.map(p => [p.id, ineligible(p, prof, data.verified)]));
    const eligible = id => reasons.get(id).length === 0;
    const successors = id => data.programs.filter(p => (p.requires.any || []).includes(id) && eligible(p.id)).map(p => p.id);
    const dl = (p, lo, hi) => p.dates.map(day).filter(d => lo <= d && d <= hi);

    function step(id, prev, chainOdds) {
      const p = progs.get(id), cad = p.cadence, req = p.requires || {}, lead = p.lead || {};
      const flags = [];
      const leadDays = lead.days ? lead.days[1] : 0;
      let earliest = start + prep + leadDays, apply = null, basis = "";
      const prepText = `${prep}-day prep time` + (leadDays ? ` plus ${leadDays}-day ${lead.basis}` : "");
      if (Object.keys(lead).length && !leadDays) flags.push(`first: ${lead.basis}`);
      if (prev) {
        if (prev.apply === null) { earliest = null; basis = `after ${prev.name}, which has no date in the window`; }
        else if (prev.cash === null) { earliest = null; basis = `after the ${prev.name} award; its time to award is not published`; }
        else {
          earliest = prev._cash[1] + leadDays;
          if (req.after_months) earliest = addMonths(earliest, req.after_months);
        }
      }
      if (earliest !== null && earliest > end) { earliest = null; basis = "after the 18-month window"; }
      const dates = earliest !== null ? dl(p, earliest, end) : [];
      const tooSoon = earliest !== null && !dates.length && !prev ? dl(p, start, earliest - 1) : [];
      const tail = cad ? ` (${cad})` : "";
      if (dates.length) { apply = dates[0]; basis = "deadline"; }
      else if (earliest !== null && prev && GO_NO_GO.test(cad)) {
        const months = progs.get(prev.program).term_max;
        if (months == null) basis = `go/no-go at the end of ${prev.name}; term not published`;
        else { apply = addMonths(prev._cash[1], months); basis = "go/no-go (no new application)"; }
      } else if (earliest !== null && p.status === "open" && ROLLING.test(cad)) { apply = earliest; basis = "rolling"; }
      else if (tooSoon.length) basis = `${bd(tooSoon[tooSoon.length - 1])} is inside the ${prepText}; next date not announced` + tail;
      else if (earliest !== null) basis = (prev ? `no date announced after ${bdy(earliest)}` : "date not announced") + tail;
      if (apply !== null && apply > end) { apply = null; basis = "after the 18-month window"; }
      if (apply !== null && leadDays && (basis === "deadline" || basis === "rolling")) basis += `, allowing ${leadDays} days for the ${lead.basis}`;
      const cash = apply !== null && p.cash_days ? [apply + p.cash_days[0], apply + p.cash_days[1]] : null;
      if (cash && prof.runway_months) {
        const runwayEnd = addMonths(start, prof.runway_months);
        if (cash[0] > runwayEnd) flags.push("cash lands after runway");
        else if (cash[1] > runwayEnd) flags.push("cash may land after runway");
      }
      if (cash && cash[1] > end) flags.push("cash may land after the window");
      if (p.cost_share) flags.push(`cost share: ${p.cost_share}`);
      const rate = p.rate;
      const chained = chainOdds !== null && rate !== null ? chainOdds * rate : null;
      const ev = p.size !== null && chained !== null ? pyRound(p.size * chained) : null;
      return {
        program: id, name: p.name, apply: apply === null ? null : iso(apply), apply_basis: basis,
        later_dates: dates.slice(1).map(iso), cash: cash && cash.map(iso), cash_basis: p.cash_basis,
        size: p.size, size_basis: p.size_basis, odds: rate, odds_basis: p.odds_basis, chain_odds: chained, ev,
        flags, prerequisites: p.prerequisites, next: [], _apply: apply, _cash: cash,
      };
    }

    function grow(s, path) {
      if (path.length < data.max_depth)
        for (const q of successors(s.program))
          if (!path.includes(q) && !held.has(q)) s.next.push(grow(step(q, s, s.chain_odds), path.concat([q])));
      return s;
    }

    const options = [], gated = [];
    for (const p of data.programs) {
      if (held.has(p.id) || !eligible(p.id)) continue;
      const req = p.requires.any || [];
      if (req.length && !req.some(r => held.has(r))) { gated.push(p.id); continue; }
      options.push(grow(step(p.id, null, 1.0), [p.id]));
    }
    const key = s => [s.apply === null ? 1 : 0, s.ev === null ? 1 : 0, -(s.ev || 0), -(s.size || 0)];
    options.sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < 4; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0; });
    const walk = s => [s].concat(...s.next.map(walk));
    const reached = new Set(options.flatMap(walk).map(s => s.program));
    const excluded = [];
    for (const [id, r] of reasons) if (r.length) excluded.push([id, r.join("; ")]);
    for (const id of gated)
      if (!reached.has(id)) excluded.push([id, "needs one of: " + progs.get(id).requires.any.map(r => progs.get(r).name).join(", ")]);
    for (const id of held) if (progs.has(id)) excluded.push([id, "already held"]);
    excluded.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));

    const firsts = options.filter(o => o.apply !== null && o.cash !== null && o._cash[1] <= end);
    const ev = firsts.reduce((t, o) => t + (o.ev === null ? 0 : o.ev), 0);
    const summary = {
      applications_dated: options.filter(o => o.apply !== null).length,
      applications_undated: options.filter(o => o.apply === null).length,
      expected_first_awards: ev, without_odds: firsts.filter(o => o.ev === null).map(o => o.program),
      cash_need: prof.cash_need == null ? null : prof.cash_need,
      coverage: prof.cash_need ? ev / prof.cash_need : null,
    };
    const clean = s => { delete s._apply; delete s._cash; s.next.forEach(clean); return s; };
    return { start: iso(start), end: iso(end), options: options.map(clean), excluded, summary };
  }

  const api = { pick, addMonths, day, iso, today, MONTHS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FundingPicker = api;
})(this);
