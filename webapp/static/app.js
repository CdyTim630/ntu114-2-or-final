// Convenience-store meal recommender — front-end logic
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const form = $("#profile-form");
const placeholder = $("#result-placeholder");
const resultBody = $("#result-body");

function bar(label, val, lo, hi, unit) {
  // Zero-origin fill bar: the fill grows from the left (0) and its length is the
  // current value. The acceptable range [lo, hi] is marked with two ticks, and
  // the fill colour reports status. The axis keeps a little headroom past the
  // upper limit so the hi tick never sits flush against the right edge.
  const axisMax = Math.max(hi * 1.2, val * 1.08, 1);
  const clamp = (x) => Math.max(0, Math.min(100, x));
  const valPct = clamp((val / axisMax) * 100);
  const loPct  = clamp((lo  / axisMax) * 100);
  const hiPct  = clamp((hi  / axisMax) * 100);

  // status: within [lo, hi] = ok, below lo = under-target (warn), above hi = over (bad)
  let cls = "ok", tag = "達標";
  if (val > hi) { cls = "bad"; tag = "偏高"; }
  else if (val < lo) { cls = "warn"; tag = "偏低"; }

  // shade the acceptable window faintly so the ticks read as a range
  const bandW = Math.max(0, hiPct - loPct);

  return `
    <div class="bar-row">
      <div class="bar-head">
        <span class="bar-name">${label}</span>
        <span class="bar-flag ${cls}">${tag}</span>
      </div>
      <div class="bar-stat">
        <span class="bar-val num ${cls}">${val.toFixed(1)}</span>
        <span class="bar-target num">/ ${lo.toFixed(0)}–${hi.toFixed(0)}${unit}</span>
      </div>
      <div class="bar-track">
        <div class="bar-band" style="left:${loPct}%; width:${bandW}%"></div>
        <div class="bar-fill ${cls}" style="width:${valPct}%"></div>
        <div class="bar-tick" style="left:${loPct}%"></div>
        <div class="bar-tick" style="left:${hiPct}%"></div>
      </div>
    </div>`;
}

function nutritionGrid(t, totals) {
  // each metric: value, soft lo, soft hi (from targets)
  const rows = [
    ["熱量 (kcal)", totals.cal, t.cal_min, t.cal_max, ""],
    ["蛋白質 (g)", totals.pro, t.protein_min, t.protein_min * 2, ""],
    ["脂肪 (g)", totals.fat, t.fat_min, t.fat_max, ""],
    ["碳水 (g)", totals.carb, t.carb_min, t.carb_max, ""],
    ["糖 (g)", totals.sug, 0, t.sugar_max, ""],
    ["鈉 (mg)", totals.sod, 0, t.sodium_max, ""],
  ];
  let html = '<div class="nutri-grid">';
  for (const [lbl, v, lo, hi, u] of rows) {
    html += `<div class="nutri-cell">${bar(lbl, v, lo, hi, u)}</div>`;
  }
  html += "</div>";
  return html;
}

function itemCard(p) {
  const tags = [];
  if (p.is_main) tags.push('<span class="tag main">主食</span>');
  if (p.is_protein) tags.push('<span class="tag pro">蛋白</span>');
  const accent = p.is_main ? "main" : (p.is_protein ? "pro" : "");
  return `
    <div class="item ${accent}">
      <div class="item-top">
        <span class="item-name">${p.name}</span>
        <span class="item-price num">$${p.price}</span>
      </div>
      <div class="item-tags">${tags.join("")}</div>
      <div class="item-stats">
        <div class="st"><span class="sv num">${Math.round(p.cal)}</span><span class="sl">熱量 kcal</span></div>
        <div class="st"><span class="sv num">${p.pro}</span><span class="sl">蛋白 g</span></div>
        <div class="st"><span class="sv num">${Math.round(p.sod)}</span><span class="sl">鈉 mg</span></div>
      </div>
    </div>`;
}

function renderFull(d) {
  const t = d.targets, totals = d.totals;

  $("#meal-summary").innerHTML = `<div class="summary-line">
    <div class="stat"><span class="k">求解器</span><span class="v">${d.solver.toUpperCase()}</span></div>
    <div class="stat"><span class="k">花費</span><span class="v accent num">NT$${totals.cost}</span></div>
    <div class="stat"><span class="k">目標值</span><span class="v num">${d.obj}</span></div>
    <div class="stat"><span class="k">耗時</span><span class="v num">${d.runtime_ms} ms</span></div>
  </div>`;

  $("#targets").innerHTML = nutritionGrid(t, totals);

  let itemsHtml = "";
  for (const p of d.items) itemsHtml += itemCard(p);
  for (const c of (d.combos || [])) {
    const save = Math.max(0, Math.round(c.original_price - c.promo_price));
    itemsHtml += `<div class="item combo">
      <div class="item-top">
        <span class="item-name">${c.name}</span>
        <span class="item-price num">$${c.promo_price}</span>
      </div>
      <div class="item-tags"><span class="tag combo-tag">優惠組合</span></div>
      <div class="item-stats combo-stats">
        <div class="st"><span class="sv num strike">$${c.original_price}</span><span class="sl">原價</span></div>
        <div class="st"><span class="sv num save">−$${save}</span><span class="sl">省下</span></div>
      </div></div>`;
  }
  $("#item-list").innerHTML = itemsHtml;

  renderHistory(d.history);
  $("#meta").innerHTML = "";

  // swap the empty-state placeholder for the real result
  placeholder.style.display = "none";
  resultBody.style.display = "";
}

// Tiered "口味記憶" panel (MLFQ-style): items are grouped by recency tier and
// faded by tier — the darker/more-solid a chip, the more recently it was eaten
// and the less likely it is to be recommended again. The lowest tier is
// collapsed to a count so the panel never gets too long.
const TIER_OPACITY = [1.0, 0.62, 0.38];   // tiers 0,1,2 shown as chips
function renderHistory(history) {
  const elHist = $("#history");
  if (!elHist) return;
  if (!history || history.length === 0) {
    elHist.innerHTML = '<span class="hist-empty">尚無紀錄</span>';
    return;
  }
  const groups = {};
  for (const h of history) (groups[h.tier] ??= []).push(h);

  let html = "";
  for (let t = 0; t <= 2; t++) {
    const g = groups[t];
    if (!g || !g.length) continue;
    const label = g[0].tier_label;
    const chips = g.map(h =>
      `<span class="hist-chip" style="opacity:${TIER_OPACITY[t]}">${h.name}</span>`).join("");
    html += `<div class="hist-tier">
        <span class="hist-tier-label">${label}</span>
        <span class="hist-chips">${chips}</span>
      </div>`;
  }
  // tier 3+ : collapse to a count
  const far = (groups[3] || []).concat(groups[4] || []);
  if (far.length) {
    html += `<div class="hist-tier">
        <span class="hist-tier-label">更久以前</span>
        <span class="hist-chips"><span class="hist-chip faint">+${far.length} 項</span></span>
      </div>`;
  }
  elHist.innerHTML = html;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(form);
  const payload = Object.fromEntries(fd.entries());
  const btn = form.querySelector("button.primary");
  const oldLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "計算中…";
  try {
    const res = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (!d.ok) { alert(d.err || "error"); return; }
    renderFull(d);
  } catch (err) {
    alert("發生錯誤：" + err);
  } finally {
    btn.disabled = false;
    btn.textContent = oldLabel;
  }
});

$("#reset-history").addEventListener("click", async () => {
  await fetch("/api/reset_history", { method: "POST" });
  renderHistory([]);
});
