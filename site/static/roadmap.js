/* Roadmap page: reads the profile from the address bar (or ?example=<id> for a fictional example), runs
   picker.js and renders the result. Nothing leaves the browser. */
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("fm-data").textContent);
  const P = window.FundingPicker;
  const q = new URLSearchParams(location.search);
  const form = document.getElementById("pick");
  const out = document.getElementById("rm-out");
  const byId = Object.fromEntries(data.programs.map(p => [p.id, p]));
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = v => v == null ? "–" : v >= 999500 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1e3)}K`;
  const pct = v => `${Math.round(v * 100)}%`;
  const parts = iso => iso.split("-").map(Number);
  const dayText = iso => { const [y, m, d] = parts(iso); return `${P.MONTHS[m - 1]} ${d}, ${y}`; };
  const monText = iso => { const [y, m] = parts(iso); return `${P.MONTHS[m - 1]} ${y}`; };
  const monKey = iso => { const [y, m] = parts(iso); return y * 12 + m - 1; };
  const label = (name, value) => {
    const el = form.querySelector(`input[name="${name}"][value="${value}"]`);
    return el ? el.parentElement.textContent.trim() : value;
  };
  const int = v => (v === null || v === "" || isNaN(parseInt(v, 10)) ? null : parseInt(v, 10));
  const prog = id => `<a href="program/${esc(id)}.html">${esc(byId[id].name)}</a>`;
  const states = new Map([...form.s.options].filter(o => o.value).map(o => [o.value, o.textContent]));
  const effort = id => {
    const e = byId[id].effort;
    return e ? `<small>To apply: ${esc(e.steps)}${e.pages ? ` (${e.pages} pages)` : ""}</small>` : "";
  };
  const oddsCell = o => o.odds === null
    ? `<span class="chip np">Not published</span>${byId[o.program].odds_note ? `<small>${esc(byId[o.program].odds_note)}</small>` : ""}`
    : esc(o.odds_basis);

  function profileFromUrl() {
    const ex = q.get("example");
    if (ex) return data.examples.find(e => e.id === ex) || null;
    if (!q.has("d") && !q.has("e")) return null;
    return {
      id: "custom", label: "Your profile", fictional: false, entity: q.get("e") === "academic" ? "academic" : "small-business",
      state: states.has(q.get("s")) ? q.get("s") : "", domains: q.getAll("d"), trl: int(q.get("t")), held: q.getAll("h"),
      cash_need: int(q.get("n")), runway_months: int(q.get("r")), prep_days: int(q.get("p")) ?? 30,
    };
  }

  function fill(p) {
    const set = (name, value) => form.querySelectorAll(`input[name="${name}"]`).forEach(i => { i.checked = i.value === value; });
    set("e", p.entity); form.s.value = states.has(p.state) ? p.state : "";
    form.querySelectorAll('input[name="d"]').forEach(i => { i.checked = p.domains.includes(i.value); });
    form.querySelectorAll('input[name="h"]').forEach(i => { i.checked = (p.held || []).includes(i.value); });
    form.t.value = p.trl || ""; form.p.value = p.prep_days ?? 30;
    form.n.value = p.cash_need || ""; form.r.value = p.runway_months || "";
  }

  const walk = s => [s].concat(...s.next.map(walk));

  function why(rm) {
    const withEv = rm.options.filter(o => o.ev !== null && o.apply);
    if (!withEv.length)
      return `<p class="callout"><b>No expected value.</b> None of the dated options has a published success rate, so the map shows sizes and dates but does not multiply them by guessed odds. <a href="methods.html#ev">Why</a>.</p>`;
    const rates = withEv.map(o => o.odds), top = withEv[0];
    const lo = Math.min(...rates), hi = Math.max(...rates);
    return `<div class="callout"><b>Why the expected figure is low.</b> Expected value is the typical award times the funder's published success rate.
      Published rates for these options run ${pct(lo)}${hi > lo ? ` to ${pct(hi)}` : ""}, so most of each award is discounted away:
      ${esc(top.name)} pays about ${money(top.size)}, and at ${pct(top.odds)} odds it counts as ${money(top.ev)}
      (about one application in ${Math.round(1 / top.odds)} is funded). You win a whole award or nothing, so use the figure to compare
      programs and to size how many applications to file, not as a cash forecast. Programs with no published rate add nothing to it.
      <a href="methods.html#ev">How it is computed</a>.</div>`;
  }

  function table(opts) {
    const rows = opts.map((o, i) => {
      const flags = o.flags.map(f => /^cash/.test(f) ? `<span class="chip flag">${esc(f)}</span>` : `<small>${esc(f)}</small>`).join(" ");
      const apply = o.apply
        ? `${dayText(o.apply)}<small>${esc(o.apply_basis)}${o.later_dates.length ? `; also ${o.later_dates.slice(0, 2).map(dayText).join(", ")}` : ""}</small>`
        : `<span class="muted">${esc(o.apply_basis)}</span>`;
      const cash = o.cash ? `${monText(o.cash[0])} to ${monText(o.cash[1])}<small>${esc(o.cash_basis)}</small>`
        : `<span class="muted">${/^award|^notice/.test(o.cash_basis) ? "needs an application date" : esc(o.cash_basis)}</span>`;
      return `<tr><td class="n">${i + 1}</td><td class="prog">${prog(o.program)}${effort(o.program)}${flags ? `<div class="chips">${flags}</div>` : ""}</td>
        <td>${apply}</td><td>${cash}</td><td class="n">${money(o.size)}<small>${esc(o.size_basis)}</small></td>
        <td class="n">${oddsCell(o)}</td><td class="n">${money(o.ev)}</td></tr>`;
    }).join("");
    return `<div class="tw"><table class="wide"><thead><tr><th class="n">#</th><th>Program</th><th>Apply</th><th>Cash</th>
      <th class="n">Typical award</th><th class="n">Published odds</th><th class="n">Expected</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function watch(opts, rm) {
    const rows = opts.map(o => {
      const p = byId[o.program];
      const past = p.dates.filter(d => d < rm.start);
      const last = past.length ? `<small>Last date on record: ${dayText(past[past.length - 1])}</small>` : "";
      const link = p.watch_url ? `<a href="${esc(p.watch_url)}">Funder's page</a>` : "";
      return `<tr><td class="prog">${prog(o.program)}${effort(o.program)}</td>
        <td>${esc(o.apply_basis)}${last}</td>
        <td class="n">${money(o.size)}<small>${esc(o.size_basis)}</small></td><td class="n">${oddsCell(o)}</td><td>${link}</td></tr>`;
    }).join("");
    return `<div class="tw"><table class="wide"><thead><tr><th>Program</th><th>Why there is no date yet</th>
      <th class="n">Typical award</th><th class="n">Published odds</th><th>Watch</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function timeline(rm) {
    const m0 = monKey(rm.start), m1 = monKey(rm.end);
    const cols = [];
    for (let m = m0; m <= m1; m++) cols.push(m);
    const head = cols.map(m => `<th class="m" scope="col">${P.MONTHS[m % 12]}<br>${String(Math.floor(m / 12)).slice(2)}</th>`).join("");
    const rows = [];
    const add = (s, depth) => {
      if (s.apply) {
        const a = monKey(s.apply), c0 = s.cash ? monKey(s.cash[0]) : null, c1 = s.cash ? monKey(s.cash[1]) : null;
        const cells = cols.map(m => {
          const cls = [m === a ? "a" : "", c0 !== null && m >= c0 && m <= c1 ? "c" : ""].filter(Boolean).join(" ");
          const tip = m === a ? `Apply ${dayText(s.apply)}` : cls ? "Cash may start" : "";
          return `<td${cls ? ` class="${cls}"` : ""}${tip ? ` title="${tip}"` : ""}></td>`;
        }).join("");
        rows.push(`<tr${depth ? ' class="ch"' : ""}><td class="lbl">${depth ? "then " : ""}${prog(s.program)}</td>${cells}</tr>`);
      }
      s.next.forEach(n => add(n, depth + 1));
    };
    rm.options.forEach(o => add(o, 0));
    if (!rows.length) return `<p class="sub">No option has a date inside the window.</p>`;
    return `<div class="key"><span><i class="k-apply"></i>Application month</span><span><i class="k-cash"></i>Cash may start (award timing range)</span></div>
      <div class="tw"><table class="tl"><thead><tr><th class="lbl">Step</th>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }

  function stepLine(s) {
    const when = s.apply ? `apply ${dayText(s.apply)} (${esc(s.apply_basis)})` : esc(s.apply_basis);
    const odds = s.chain_odds !== null ? `odds along this path ${(s.chain_odds * 100).toFixed(1)}%` : "odds along this path not published";
    const cash = s.cash ? `cash ${monText(s.cash[0])} to ${monText(s.cash[1])}` : esc(s.cash_basis);
    return `<span class="step">${prog(s.program)}<span class="meta">${when}; ${cash}; ${money(s.size)}; ${odds}; expected ${money(s.ev)}</span></span>`;
  }
  const later = s => [...new Set(s.next.flatMap(walk).map(n => n.program))];
  const tree = (s, depth = 0) => {
    if (depth === 0) return `<li>${stepLine(s)}<ul class="tree">${s.next.map(n => tree(n, 1)).join("")}</ul></li>`;
    const more = later(s);
    return `<li>${stepLine(s)}${more.length ? `<span class="meta">Later: ${more.map(prog).join(", ")}</span>` : ""}</li>`;
  };

  function render(p) {
    const start = q.get("start") || undefined;
    if (!p.domains.length) {
      out.innerHTML = `<p class="callout warn">Pick at least one technology area.</p>`;
      return;
    }
    const rm = P.pick(data, p, start), sm = rm.summary;
    const doms = p.domains.map(d => label("d", d)).join(", ");
    const held = (p.held || []).map(h => byId[h] ? byId[h].name : h).join(", ") || "none";
    const chains = rm.options.filter(o => o.next.length);
    const before = rm.options.filter(o => o.apply && o.prerequisites);
    const dated = rm.options.filter(o => o.apply), undated = rm.options.filter(o => !o.apply);
    document.getElementById("rm-lede").textContent = p.fictional
      ? "A fictional example company. Edit the profile to make it yours; the address bar keeps the result shareable."
      : "Your roadmap. The address bar holds the profile, so the link reproduces this page.";
    out.innerHTML = `
      <h2>${esc(p.label)} ${p.fictional ? '<span class="chip fict">Fictional profile</span>' : ""}</h2>
      <p class="sub">${esc(label("e", p.entity))}, ${p.state ? esc(states.get(p.state) || p.state) : "no state set"}, TRL ${p.trl || "not set"};
        ${esc(doms)}; awards held: ${esc(held)}; runway ${p.runway_months ? p.runway_months + " months" : "not set"};
        ${p.prep_days ?? 30} days until the first submission. Window ${dayText(rm.start)} to ${dayText(rm.end)}.</p>
      <div class="figs">
        <div class="fig"><b>${money(sm.expected_first_awards)}</b><span>Expected from first applications whose cash lands in the window</span></div>
        <div class="fig"><b>${sm.coverage === null ? "–" : pct(sm.coverage)}</b><span>${sm.cash_need ? `of the ${money(sm.cash_need)} need` : "Set a cash need to compare"}</span></div>
        <div class="fig"><b>${sm.any_award === null ? "–" : pct(sm.any_award)}</b><span>${sm.any_award === null
          ? "Chance of at least one award: no dated option publishes odds"
          : `Chance of at least one award from the ${sm.any_award_counted.length} dated first application${sm.any_award_counted.length > 1 ? "s" : ""} with published odds, if outcomes are independent`}
          <a href="methods.html#any">How</a></span></div>
        <div class="fig"><b>${sm.applications_dated}</b><span>Programs with a date in the window</span></div>
        <div class="fig"><b>${sm.applications_undated}</b><span>Programs that fit but have no announced date</span></div>
      </div>
      ${why(rm)}
      ${sm.without_odds.length ? `<p class="sub">Dated, but no published odds (not in the expected figure): ${sm.without_odds.map(prog).join(", ")}.</p>` : ""}
      <h2>Apply</h2>
      <p class="sub">Programs that fit and have a date inside the window, ranked by expected value, then by award size. Dates are funder deadlines and DoD topic close dates; nothing is guessed. Verify every date on the funder's page.</p>
      ${dated.length ? table(dated) : `<p class="sub">${rm.options.length ? "No program that fits has a date inside the window." : "No program fits this profile."}</p>`}
      ${undated.length ? `<h2>Watch</h2>
      <p class="sub">Programs that fit but have no usable date yet: the next round is not announced, the funder states no timing, or the step depends on an earlier award. Each links the page to watch for the next call.</p>
      ${watch(undated, rm)}` : ""}
      <h2>Calendar</h2>
      <p class="sub">Each dated step, including follow-ons that can start inside the window. Cash timing comes from the funder or from SBIR.gov days to award (25th to 75th percentile).</p>
      ${timeline(rm)}
      ${chains.length ? `<h2>Stacking</h2><p class="sub">What each first award unlocks next, with the steps after that listed. Odds along a path multiply the published rate of every step. See <a href="paths.html">all stacking paths</a>.</p>
        <ul class="tree">${chains.map(o => tree(o)).join("")}</ul>` : ""}
      ${before.length ? `<h2>Before you apply</h2><p class="sub">The funder's own conditions. The picker does not check these.</p>
        <ul class="src">${before.map(o => `<li><b>${prog(o.program)}</b>: ${esc(o.prerequisites)}</li>`).join("")}</ul>` : ""}
      <h2>Not a fit</h2>
      <details><summary>${rm.excluded.length} programs and why</summary>
        <div class="tw"><table><thead><tr><th>Program</th><th>Why not</th></tr></thead><tbody>
        ${rm.excluded.map(([id, r]) => `<tr><td class="prog">${prog(id)}</td><td>${esc(r)}</td></tr>`).join("")}
        </tbody></table></div></details>`;
  }

  const p = profileFromUrl();
  if (p) {
    fill(p);
    document.getElementById("rm-edit").open = false;
    document.getElementById("rm-ex").hidden = !p.fictional;
    render(p);
  }
})();
