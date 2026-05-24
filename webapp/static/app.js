const form = document.getElementById("profile-form");
const resultCard = document.getElementById("result-card");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  const btn = form.querySelector("button.primary");
  btn.disabled = true; btn.textContent = "求解中…";

  try {
    const r = await fetch("/api/recommend", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data),
    });
    const out = await r.json();
    render(out);
  } catch (err) {
    alert("Error: " + err);
  } finally {
    btn.disabled = false; btn.textContent = "🎯 推薦這一餐";
  }
});

document.getElementById("reset-history").addEventListener("click", async () => {
  await fetch("/api/reset_history", {method: "POST"});
  const h = document.getElementById("history");
  if (h) h.textContent = "(已清空)";
});

function bar(value, vmin, vmax, hardMin, hardMax) {
  // returns a bar element representing value relative to [vmin, vmax]
  const range = Math.max(vmax * 1.2, 1);
  const pct = Math.min(100, (value / range) * 100);
  let cls = "";
  if (hardMax !== undefined && value > hardMax) cls = "over";
  else if (hardMin !== undefined && value < hardMin) cls = "below";
  const refMin = (vmin / range) * 100;
  const refMax = (vmax / range) * 100;
  return `<div class="bar">
    <div class="${cls}" style="width:${pct}%"></div>
    <div class="ref" style="left:${refMin}%"></div>
    <div class="ref" style="left:${refMax}%"></div>
  </div>`;
}

function render(out) {
  resultCard.style.display = "block";
  resultCard.scrollIntoView({behavior: "smooth"});

  if (!out.ok) {
    document.getElementById("meal-summary").innerHTML =
      `<div class="warn">⚠️ ${out.err}</div>`;
    document.getElementById("item-list").innerHTML = "";
    document.getElementById("targets").innerHTML = "";
    document.getElementById("meta").textContent = "";
    return;
  }

  const t = out.targets, tot = out.totals;
  const overBudget = tot.cost > t.budget;
  document.getElementById("meal-summary").innerHTML =
    `<div class="summary-line">
       共 <strong>${out.items.length}</strong> 件商品，總價
       <strong>NT$${tot.cost.toFixed(0)}</strong>（預算 NT$${t.budget}）；
       熱量 <strong>${tot.cal.toFixed(0)} kcal</strong>（區間 ${t.cal_min.toFixed(0)}–${t.cal_max.toFixed(0)}），
       蛋白質 <strong>${tot.pro.toFixed(1)} g</strong>（下限 ${t.protein_min.toFixed(1)} g）。
     </div>`;

  document.getElementById("item-list").innerHTML = out.items.map(i => `
    <div class="item">
      <div class="name">${i.name}</div>
      <div class="meta">
        NT$${i.price} ｜ ${i.cal} kcal ｜ pro ${i.pro} g ｜ sod ${i.sod} mg
      </div>
      <div>
        ${i.is_main ? '<span class="tag main">主食</span>' : ''}
        ${i.is_protein ? '<span class="tag pro">蛋白質來源</span>' : ''}
        <span class="tag">${i.category || ''}</span>
      </div>
    </div>
  `).join("");

  const targetItems = [
    {l: "熱量 (kcal)",   v: tot.cal,  min: t.cal_min,  max: t.cal_max},
    {l: "蛋白質 (g)",     v: tot.pro,  min: t.protein_min, max: t.protein_min*2},
    {l: "脂肪 (g)",       v: tot.fat,  min: t.fat_min,  max: t.fat_max},
    {l: "碳水 (g)",       v: tot.carb, min: t.carb_min, max: t.carb_max},
    {l: "糖 (g)",         v: tot.sug,  min: 0, max: t.sugar_max},
    {l: "鈉 (mg)",        v: tot.sod,  min: 0, max: t.sodium_max},
  ];
  document.getElementById("targets").innerHTML = targetItems.map(o => `
    <div class="target">
      <strong>${o.l}</strong>　${o.v.toFixed(1)} <small style="color:#999">/ ${o.min.toFixed(0)}–${o.max.toFixed(0)}</small>
      ${bar(o.v, o.min, o.max, o.min, o.max)}
    </div>
  `).join("");

  document.getElementById("history").textContent =
    out.history && out.history.length
      ? out.history.map(p => `pid=${p}`).join(", ")
      : "(空)";

  document.getElementById("meta").innerHTML =
    `Solver: <strong>${out.solver.toUpperCase()}</strong> ·
     Objective = ${out.obj} · Runtime = ${out.runtime_ms} ms · ` +
    (overBudget ? "<span style='color:red'>超出預算！</span>" : "");
}
