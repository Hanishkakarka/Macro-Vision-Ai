/**
 * MacroVision AI frontend: presentation + interaction only.
 * Recognition, nutrient scaling, targets, reports and suggestions all come from the API.
 */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: d });
const MACRO_COLORS = { protein_g: "#6366F1", carbs_g: "#F59E0B", fat_g: "#EC4899", fiber_g: "#10B981" };
const LABELS = { calories: "Calories", protein_g: "Protein", carbs_g: "Carbs", fat_g: "Fat",
                 fiber_g: "Fibre", sugar_g: "Sugar", sodium_mg: "Sodium" };
const UNITS = { calories: "kcal", sodium_mg: "mg" };
const unit = (k) => UNITS[k] || "g";
const MEAL_ICONS = { breakfast: "🌅", lunch: "🍛", dinner: "🌙", snack: "🍎" };

let me = null;                 // { user, profile, targets, ai_ready, demo_mode }
const charts = {};             // Chart.js instances, destroyed before redraw
let analysis = null;           // current scan result being reviewed
let reportState = { period: "week", offset: 0, data: null };

// ---------------- API helper ----------------
async function api(path, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && !path.startsWith("/api/auth")) { showAuth(); throw new Error("Please log in"); }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail || res.statusText);
  }
  return data;
}

function toast(msg, type = "ok") {
  const t = document.createElement("div");
  t.className = `toast ${type === "error" ? "error" : ""}`;
  t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

// ---------------- Theme ----------------
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("themeBtn").textContent = theme === "dark" ? "☀️" : "🌙";
  try { localStorage.setItem("mv-theme", theme); } catch { /* ignore */ }
  Object.values(charts).forEach((c) => c?.update());
}
$("themeBtn").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
const chartText = () => getComputedStyle(document.documentElement).getPropertyValue("--muted").trim();
const chartGrid = () => getComputedStyle(document.documentElement).getPropertyValue("--border").trim();

// ---------------- Auth ----------------
let authMode = "login";
document.querySelectorAll("[data-auth]").forEach((b) => b.addEventListener("click", () => {
  authMode = b.dataset.auth;
  document.querySelectorAll("[data-auth]").forEach((x) => x.classList.toggle("active", x === b));
  $("nameField").hidden = authMode !== "signup";
  $("authSubmit").textContent = authMode === "signup" ? "Create account" : "Log in";
  $("authError").hidden = true;
}));

$("authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { email: f.get("email"), password: f.get("password") };
  if (authMode === "signup") body.name = f.get("name");
  $("authSubmit").disabled = true;
  try {
    await api(`/api/auth/${authMode}`, { method: "POST", body });
    $("authError").hidden = true;
    await boot(authMode === "signup" ? "#/profile" : null);
    if (authMode === "signup") toast("Welcome! Set your profile to get accurate targets 🎯");
  } catch (err) {
    $("authError").textContent = err.message;
    $("authError").hidden = false;
  } finally { $("authSubmit").disabled = false; }
});

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  me = null; showAuth();
});

function showAuth() {
  $("appView").hidden = true;
  $("authView").hidden = false;
}

// ---------------- Router ----------------
const VIEWS = ["dashboard", "scan", "history", "reports", "profile"];
async function route() {
  if (!me) return;
  const view = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  const name = VIEWS.includes(view) ? view : "dashboard";
  VIEWS.forEach((v) => ($(`view-${v}`).hidden = v !== name));
  document.querySelectorAll("[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  window.scrollTo({ top: 0 });
  try {
    if (name === "dashboard") await loadDashboard();
    if (name === "history") await loadHistory();
    if (name === "reports") await loadReport();
    if (name === "profile") renderProfile();
  } catch (err) { if (err.message !== "Please log in") toast(err.message, "error"); }
}
window.addEventListener("hashchange", route);

async function boot(goTo = null) {
  me = await api("/api/me");
  $("authView").hidden = true;
  $("appView").hidden = false;
  const hour = new Date().getHours();
  $("greeting").textContent = `${hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"}, ${me.user.name.split(" ")[0]} 👋`;
  $("greetDate").textContent = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  $("aiBanner").hidden = me.ai_ready && !me.demo_mode;
  $("aiBanner").textContent = me.demo_mode
    ? "🧪 Demo mode: photo analysis returns a sample meal. Add ANTHROPIC_API_KEY and turn off MACROVISION_DEMO for real AI recognition."
    : "⚠️ AI recognition isn't configured. Add ANTHROPIC_API_KEY to the .env file and restart the server.";
  if (goTo && location.hash !== goTo) location.hash = goTo;   // hashchange will call route()
  else route();
}

// ---------------- Dashboard ----------------
async function loadDashboard() {
  const d = await api("/api/dashboard");
  const cal = d.progress.calories;
  const circumference = 326.7;
  const ratio = Math.min(cal.value / (cal.target || 1), 1);
  $("calRing").style.strokeDashoffset = circumference * (1 - ratio);
  $("calRing").classList.toggle("over", cal.value > cal.target * 1.05);
  $("calEaten").textContent = fmt(cal.value);
  $("calTarget").textContent = `of ${fmt(cal.target)} kcal`;
  $("calLeft").textContent = d.calories_left >= 0 ? `${fmt(d.calories_left)} kcal left today` : `${fmt(-d.calories_left)} kcal over target`;

  $("macroBars").innerHTML = ["protein_g", "carbs_g", "fat_g", "fiber_g"].map((k) => {
    const p = d.progress[k];
    return `<div><div class="mbar-top"><span>${LABELS[k]}</span><span>${fmt(p.value)} / ${fmt(p.target)} g</span></div>
      <div class="mbar"><div style="width:${Math.min(p.percent, 100)}%;background:${MACRO_COLORS[k]}"></div></div></div>`;
  }).join("");

  $("streak").textContent = d.streak;
  $("mealsToday").textContent = d.today_meals.length;
  $("fiberToday").textContent = `${fmt(d.progress.fiber_g.value)} g`;

  drawChart("weekChart", {
    type: "bar",
    data: { labels: d.last7.map((x) => x.label), datasets: [
      { label: "Calories", data: d.last7.map((x) => x.calories), backgroundColor: "#12B886", borderRadius: 8, maxBarThickness: 34 },
      { label: "Target", data: d.last7.map(() => d.targets.calories), type: "line", borderColor: "#F97316", borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
    ]},
  });
  const split = d.macro_split, hasSplit = split.protein + split.carbs + split.fat > 0;
  $("splitEmpty").hidden = hasSplit;
  drawChart("splitChart", hasSplit ? {
    type: "doughnut",
    data: { labels: ["Protein", "Carbs", "Fat"], datasets: [{ data: [split.protein, split.carbs, split.fat],
      backgroundColor: ["#6366F1", "#F59E0B", "#EC4899"], borderWidth: 0 }] },
    options: { cutout: "65%", plugins: { tooltip: { callbacks: { label: (c) => ` ${c.label}: ${c.raw}%` } } } },
  } : null);

  $("todayMeals").innerHTML = d.today_meals.length ? d.today_meals.map(mealRow).join("")
    : `<div class="empty"><div class="big-emoji">🍽️</div><p>No meals yet today. <a class="link" href="#/scan">Scan your first meal</a></p></div>`;
  $("dashTips").innerHTML = tipsHtml(d.suggestions);
}

function mealRow(m, withDelete = false) {
  const img = m.image_path ? `<img src="/api/images/${esc(m.image_path)}" alt="" loading="lazy" />`
                           : `<div class="meal-thumb">${MEAL_ICONS[m.meal_type] || "🍽️"}</div>`;
  const names = m.items.map((i) => i.name).join(", ");
  const time = new Date(m.eaten_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return `<div class="meal-row">${img}
    <div class="meal-info"><strong title="${esc(names)}">${esc(names)}</strong>
      <small>${MEAL_ICONS[m.meal_type]} ${esc(m.meal_type)} · ${time}${m.note ? " · " + esc(m.note) : ""}</small>
      <div class="macro-mini"><span>P <b>${fmt(m.protein_g)}g</b></span><span>C <b>${fmt(m.carbs_g)}g</b></span><span>F <b>${fmt(m.fat_g)}g</b></span></div>
    </div>
    <span class="meal-kcal">${fmt(m.calories)} kcal</span>
    ${withDelete ? `<button class="del-btn" data-delete="${m.id}" title="Delete meal" aria-label="Delete meal">🗑️</button>` : ""}
  </div>`;
}

function tipsHtml(tips) {
  return tips.map((t) => `<div class="tip ${esc(t.kind)}"><span>${t.icon}</span>
    <div><strong>${esc(t.title)}</strong><p>${esc(t.text)}</p></div></div>`).join("");
}

function drawChart(id, config) {
  charts[id]?.destroy();
  charts[id] = null;
  if (!config || typeof Chart === "undefined") return;
  config.options = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { labels: { color: chartText(), boxWidth: 12, usePointStyle: true } }, ...(config.options?.plugins || {}) },
    ...(config.type === "doughnut" ? {} : {
      scales: {
        x: { ticks: { color: chartText() }, grid: { display: false }, stacked: !!config.stacked },
        y: { ticks: { color: chartText() }, grid: { color: chartGrid() }, beginAtZero: true, stacked: !!config.stacked },
      },
    }),
    ...(config.options || {}),
  };
  charts[id] = new Chart($(id), config);
}

// ---------------- Scan & review ----------------
const photoInput = $("photoInput"), dropzone = $("dropzone");
let selectedFile = null;

photoInput.addEventListener("change", () => selectFile(photoInput.files[0]));
["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", (e) => selectFile(e.dataTransfer.files[0]));

function selectFile(file) {
  if (!file) return;
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { toast("Please choose a JPG, PNG or WEBP image", "error"); return; }
  selectedFile = file;
  $("photoPreview").src = URL.createObjectURL(file);
  $("photoPreview").hidden = false;
  $("dzEmpty").hidden = true;
  $("analyzeBtn").disabled = false;
  resetResult();
}

function resetResult() {
  analysis = null;
  $("resultEmpty").hidden = false; $("analyzing").hidden = true; $("resultBody").hidden = true;
}

$("analyzeBtn").addEventListener("click", async () => {
  if (!selectedFile) return;
  const fd = new FormData();
  fd.append("photo", selectedFile);
  $("analyzeBtn").disabled = true;
  $("resultEmpty").hidden = true; $("resultBody").hidden = true; $("analyzing").hidden = false;
  try {
    const res = await api("/api/analyze", { method: "POST", body: fd });
    if (!res.is_food) {
      resetResult();
      toast("No food detected in this photo. Try a clearer picture of your meal.", "error");
      return;
    }
    analysis = { ...res, items: res.items.map((i) => ({ ...i, base_grams: i.grams, base: { ...i } })) };
    renderAnalysis(res.totals);
  } catch (err) {
    resetResult();
    toast(err.message, "error");
  } finally { $("analyzeBtn").disabled = false; $("analyzing").hidden = true; }
});

function guessMealType() {
  const h = new Date().getHours();
  return h < 11 ? "breakfast" : h < 16 ? "lunch" : h < 19 ? "snack" : "dinner";
}
function localNow() {
  const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function renderAnalysis(totals) {
  $("resultBody").hidden = false;
  $("mealName").textContent = analysis.meal_name;
  $("sourcePill").textContent = analysis.source === "demo" ? "Demo result" : "AI analysed";
  $("mealType").value = guessMealType();
  $("eatenAt").value = localNow();
  $("mealNote").value = "";
  $("healthNotes").innerHTML = analysis.health_notes.map((n) => `<div class="note">💡 ${esc(n)}</div>`).join("");
  renderItems(totals);
}

function renderItems(totals) {
  $("resultTotals").innerHTML = [["calories", "kcal", "var(--primary)"], ["protein_g", "Protein", "#6366F1"],
    ["carbs_g", "Carbs", "#F59E0B"], ["fat_g", "Fat", "#EC4899"]].map(([k, label, c]) =>
    `<div class="total-box" style="--c:${c}"><strong>${fmt(totals[k])}${k === "calories" ? "" : "g"}</strong><small>${label}</small></div>`).join("");
  $("resultItems").innerHTML = analysis.items.map((it, idx) => `
    <div class="item">
      <div class="item-name">${esc(it.name)}${it.confidence ? `<span class="conf ${esc(it.confidence)}">${esc(it.confidence)}</span>` : ""}
        ${it.portion_description ? `<small class="muted">· ${esc(it.portion_description)}</small>` : ""}</div>
      <div class="grams"><input type="number" min="1" max="5000" step="1" value="${Math.round(it.grams)}" data-idx="${idx}" aria-label="Grams of ${esc(it.name)}" /> g
        <button class="remove-item" data-remove="${idx}" title="Remove item" aria-label="Remove ${esc(it.name)}">✕</button></div>
      <div class="macro-mini"><span><b>${fmt(it.calories)}</b> kcal</span><span>P <b>${fmt(it.protein_g, 1)}g</b></span>
        <span>C <b>${fmt(it.carbs_g, 1)}g</b></span><span>F <b>${fmt(it.fat_g, 1)}g</b></span><span>Fibre <b>${fmt(it.fiber_g, 1)}g</b></span></div>
    </div>`).join("");
}

// Items sent to the server: original nutrients at base_grams + the grams the user wants.
const itemPayload = () => analysis.items.map((it) => ({
  name: it.name, grams: it.grams, base_grams: it.base_grams,
  calories: it.base.calories, protein_g: it.base.protein_g, carbs_g: it.base.carbs_g, fat_g: it.base.fat_g,
  fiber_g: it.base.fiber_g, sugar_g: it.base.sugar_g, sodium_mg: it.base.sodium_mg,
}));

let previewTimer = null;
$("resultItems").addEventListener("input", (e) => {
  const idx = e.target.dataset.idx;
  if (idx === undefined) return;
  const grams = Number(e.target.value);
  if (!(grams > 0)) return;
  analysis.items[idx].grams = grams;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 300);   // debounce typing
});
$("resultItems").addEventListener("click", (e) => {
  const idx = e.target.dataset.remove;
  if (idx === undefined) return;
  if (analysis.items.length === 1) { toast("A meal needs at least one item", "error"); return; }
  analysis.items.splice(Number(idx), 1);
  refreshPreview();
});

async function refreshPreview() {
  try {
    const res = await api("/api/meals/preview", { method: "POST", body: { items: itemPayload() } });
    res.items.forEach((scaled, i) => Object.assign(analysis.items[i], scaled));   // server-scaled values
    const focused = document.activeElement?.dataset?.idx;
    renderItems(res.totals);
    if (focused !== undefined) {
      const input = document.querySelector(`[data-idx="${focused}"]`);
      input?.focus(); input?.setSelectionRange?.(input.value.length, input.value.length);
    }
  } catch (err) { toast(err.message, "error"); }
}

$("saveMealBtn").addEventListener("click", async () => {
  if (!analysis) return;
  $("saveMealBtn").disabled = true;
  try {
    await api("/api/meals", { method: "POST", body: {
      meal_type: $("mealType").value, eaten_at: $("eatenAt").value || null,
      note: $("mealNote").value.trim() || null, image_token: analysis.image_token, items: itemPayload(),
    }});
    toast("Meal saved ✅");
    selectedFile = null; photoInput.value = "";
    $("photoPreview").hidden = true; $("dzEmpty").hidden = false; $("analyzeBtn").disabled = true;
    resetResult();
    location.hash = "#/dashboard";
  } catch (err) { toast(err.message, "error"); }
  finally { $("saveMealBtn").disabled = false; }
});

// ---------------- History ----------------
$("historyRange").addEventListener("change", loadHistory);
async function loadHistory() {
  const { meals } = await api(`/api/meals?days=${$("historyRange").value}`);
  if (!meals.length) {
    $("historyList").innerHTML = `<div class="empty"><div class="big-emoji">📒</div><p>No meals logged in this period.</p></div>`;
    return;
  }
  const byDay = {};
  meals.forEach((m) => (byDay[m.eaten_at.slice(0, 10)] ||= []).push(m));
  $("historyList").innerHTML = Object.entries(byDay).map(([day, list]) => {
    const kcal = list.reduce((s, m) => s + m.calories, 0);   // display-only sum of server values
    const label = new Date(day + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
    return `<div class="day-group"><h4><span>${label}</span><span>${fmt(kcal)} kcal</span></h4>${list.map((m) => mealRow(m, true)).join("")}</div>`;
  }).join("");
}
$("historyList").addEventListener("click", async (e) => {
  const id = e.target.dataset.delete;
  if (!id || !confirm("Delete this meal from your log?")) return;
  try { await api(`/api/meals/${id}`, { method: "DELETE" }); toast("Meal deleted"); loadHistory(); }
  catch (err) { toast(err.message, "error"); }
});

// ---------------- Reports ----------------
document.querySelectorAll("[data-period]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("[data-period]").forEach((x) => x.classList.toggle("active", x === b));
  reportState = { period: b.dataset.period, offset: 0, data: null };
  loadReport();
}));
$("prevPeriod").addEventListener("click", () => { reportState.offset -= 1; loadReport(); });
$("nextPeriod").addEventListener("click", () => { if (reportState.offset < 0) { reportState.offset += 1; loadReport(); } });
$("printBtn").addEventListener("click", () => window.print());

async function loadReport() {
  const { period, offset } = reportState;
  const r = await api(`/api/reports/${period}?offset=${offset}`);
  reportState.data = r;
  $("reportTitle").textContent = r.title;
  $("nextPeriod").disabled = offset >= 0;
  $("coachBody").innerHTML = "Get a personalised review of this period from Claude, based on your logged meals and goals.";
  $("coachBody").className = "muted";

  const change = r.calorie_change;
  const changeHtml = change == null ? "no previous data"
    : `<span class="${change > 0 ? "up" : "down"}">${change > 0 ? "▲" : "▼"} ${fmt(Math.abs(change))} kcal</span> vs previous`;
  $("reportKpis").innerHTML = [
    ["Avg calories / day", fmt(r.averages.calories), `${r.avg_percent_of_target.calories}% of target · ${changeHtml}`],
    ["Avg protein / day", `${fmt(r.averages.protein_g)} g`, `${r.avg_percent_of_target.protein_g}% of ${fmt(r.targets.protein_g)} g target`],
    ["Days logged", `${r.days_logged}/${r.days_elapsed}`, `${r.logging_rate}% logging consistency`],
    ["On-target days", `${r.on_target_days}`, `${r.adherence}% of logged days within ±10%`],
  ].map(([l, v, s]) => `<div class="card kpi"><small>${l}</small><strong>${v}</strong><div class="sub">${s}</div></div>`).join("");

  const days = r.days;
  drawChart("reportCalChart", {
    type: "bar",
    data: { labels: days.map((d) => d.label), datasets: [
      { label: "Calories", data: days.map((d) => d.calories), borderRadius: 6, maxBarThickness: 30,
        backgroundColor: days.map((d) => d.calories > r.targets.calories * 1.1 ? "#F97316" : "#12B886") },
      { label: "Target", data: days.map(() => r.targets.calories), type: "line", borderColor: "#6366F1",
        borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
    ]},
  });
  drawChart("reportMacroChart", {
    type: "bar", stacked: true,
    data: { labels: days.map((d) => d.label), datasets: ["protein_g", "carbs_g", "fat_g"].map((k) => ({
      label: LABELS[k], data: days.map((d) => d[k]), backgroundColor: MACRO_COLORS[k], borderRadius: 4, maxBarThickness: 30 })) },
  });

  $("avgTable").innerHTML = Object.keys(LABELS).map((k) => {
    const pct = r.avg_percent_of_target[k];
    const limitKey = k === "sugar_g" || k === "sodium_mg";   // these are upper limits, not goals
    const color = limitKey ? (pct > 100 ? "var(--warn)" : "var(--primary)") : (pct < 80 ? "var(--warn)" : "var(--primary)");
    return `<div class="avg-row"><span>${LABELS[k]}</span>
      <div class="mbar"><div style="width:${Math.min(pct, 100)}%;background:${color}"></div></div>
      <b>${fmt(r.averages[k])}${unit(k) === "kcal" ? "" : unit(k)}</b></div>`;
  }).join("") + `<p class="muted small">Bars show your daily average as % of target (sugar &amp; sodium are limits).</p>`;

  $("topFoods").innerHTML = r.top_foods.length ? r.top_foods.map((f, i) =>
    `<div class="food-row"><strong>${i + 1}. ${esc(f.name)}</strong><span>${f.times}× · ${fmt(f.calories)} kcal</span></div>`).join("")
    : `<p class="muted">No foods logged yet.</p>`;

  const mt = r.meal_types;
  drawChart("mealTypeChart", Object.values(mt).some(Boolean) ? {
    type: "doughnut",
    data: { labels: ["Breakfast", "Lunch", "Dinner", "Snack"],
      datasets: [{ data: [mt.breakfast, mt.lunch, mt.dinner, mt.snack], backgroundColor: ["#F59E0B", "#12B886", "#6366F1", "#EC4899"], borderWidth: 0 }] },
    options: { cutout: "60%" },
  } : null);

  $("reportTips").innerHTML = tipsHtml(r.suggestions);
}

$("coachBtn").addEventListener("click", async () => {
  const { period, offset } = reportState;
  $("coachBtn").disabled = true;
  $("coachBody").className = "";
  $("coachBody").innerHTML = `<div class="empty"><div class="spinner"></div><p>Your AI coach is reviewing your meals…</p></div>`;
  try {
    const c = await api(`/api/reports/${period}/ai-coach?offset=${offset}`, { method: "POST" });
    $("coachBody").innerHTML = `<p class="coach-summary">${esc(c.summary)}</p>` +
      tipsHtml(c.tips.map((t) => ({ kind: "tip", icon: "✨", title: t.title, text: t.advice })));
  } catch (err) {
    $("coachBody").className = "muted";
    $("coachBody").textContent = err.message;
  } finally { $("coachBtn").disabled = false; }
});

// ---------------- Profile ----------------
function renderProfile() {
  const form = $("profileForm");
  Object.entries(me.profile).forEach(([k, v]) => { if (form.elements[k]) form.elements[k].value = v; });
  renderTargets(me.targets);
}
function renderTargets(t) {
  const items = [["calories", "Calories", "var(--primary)"], ["protein_g", "Protein", "#6366F1"], ["carbs_g", "Carbs", "#F59E0B"],
    ["fat_g", "Fat", "#EC4899"], ["fiber_g", "Fibre", "#10B981"], ["sugar_g", "Sugar (max)", "#F97316"]];
  $("targetsView").innerHTML = items.map(([k, l, c]) =>
    `<div class="target" style="--c:${c}"><small>${l}</small><strong>${fmt(t[k])} ${unit(k)}</strong></div>`).join("") +
    `<div class="target"><small>BMR</small><strong>${fmt(t.bmr)} kcal</strong></div>
     <div class="target"><small>Maintenance (TDEE)</small><strong>${fmt(t.tdee)} kcal</strong></div>`;
}
$("profileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const body = { sex: f.sex.value, age: Number(f.age.value), height_cm: Number(f.height_cm.value),
    weight_kg: Number(f.weight_kg.value), activity_level: f.activity_level.value, goal: f.goal.value, diet_type: f.diet_type.value };
  try {
    const res = await api("/api/profile", { method: "PUT", body });
    me.profile = res.profile; me.targets = res.targets;
    renderTargets(res.targets);
    $("profileError").hidden = true;
    toast("Targets updated 🎯");
  } catch (err) { $("profileError").textContent = err.message; $("profileError").hidden = false; }
});

// ---------------- Start ----------------
try { applyTheme(localStorage.getItem("mv-theme") || "light"); } catch { applyTheme("light"); }
boot().catch(() => showAuth());
