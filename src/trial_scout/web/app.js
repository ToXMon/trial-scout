"use strict";

const VERDICT_LABELS = {
  "candidate": "Good match",
  "dbs-conflict": "DBS conflict",
  "watch": "Keep an eye on",
  "needs-verification": "Ask the doctor",
  "likely-excluded": "Not a fit",
};

const CITY_LABELS = {
  jackson_ms: "Jackson, MS", gulfport_ms: "Gulfport, MS",
  southaven_ms: "Southaven, MS", hattiesburg_ms: "Hattiesburg, MS",
  biloxi_ms: "Biloxi, MS", meridian_ms: "Meridian, MS",
  tupelo_ms: "Tupelo, MS", greenville_ms: "Greenville, MS",
  oxford_ms: "Oxford, MS", starkville_ms: "Starkville, MS",
  columbus_ms: "Columbus, MS", vicksburg_ms: "Vicksburg, MS",
  natchez_ms: "Natchez, MS", laurel_ms: "Laurel, MS",
  memphis_tn: "Memphis, TN", new_orleans_la: "New Orleans, LA",
  baton_rouge_la: "Baton Rouge, LA", shreveport_la: "Shreveport, LA",
  birmingham_al: "Birmingham, AL", mobile_al: "Mobile, AL",
  little_rock_ar: "Little Rock, AR", huntsville_al: "Huntsville, AL",
  houston_tx: "Houston, TX", other: "Other",
};

let TRIALS = [];
let PROFILE = {};
let ACTIVE_FILTER = "all";
const FAV_KEY = "trialscout-favorites";

function favorites() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
  catch (e) { return []; }
}
function toggleFav(nct) {
  const favs = favorites();
  const i = favs.indexOf(nct);
  if (i >= 0) { favs.splice(i, 1); } else { favs.push(nct); }
  localStorage.setItem(FAV_KEY, JSON.stringify(favs));
}

async function api(path, options) {
  const res = await fetch(path, options);
  return res.json();
}

function fmtSite(t) {
  if (!t.nearest_site) return "No site location listed";
  const s = t.nearest_site;
  return `${s.city}, ${s.state} - about ${Math.round(s.miles)} miles away`;
}

function reasonsHtml(t) {
  return t.reasons.map(r => {
    const cls = r.kind === "positive" ? "pos" : (r.kind === "negative" ? "neg" : "");
    return `<li class="${cls}">${escapeHtml(r.text)}</li>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function cardHtml(t) {
  const favs = favorites();
  const starred = favs.includes(t.nct_id);
  return `
  <article class="card" data-nct="${t.nct_id}">
    <div class="card-top">
      <span class="badge ${t.verdict}">${VERDICT_LABELS[t.verdict] || t.verdict}</span>
      <button class="star ${starred ? "on" : ""}" data-star="${t.nct_id}"
              aria-label="Star this trial">${starred ? "★" : "☆"}</button>
    </div>
    <h3>${escapeHtml(t.title)}</h3>
    <p class="meta"><strong>${t.nct_id}</strong> &middot; ${escapeHtml(t.status)}</p>
    <p class="meta">${escapeHtml(fmtSite(t))}</p>
    <ul class="reasons">${reasonsHtml(t)}</ul>
    <div class="card-actions">
      <a class="linkbtn" href="${t.url}" target="_blank" rel="noopener">Full details</a>
      <button class="linkbtn" data-open="${t.nct_id}">How to ask about it</button>
    </div>
  </article>`;
}

function render() {
  const list = document.getElementById("trial-list");
  let rows = TRIALS;
  if (ACTIVE_FILTER === "favorites") {
    const favs = favorites();
    rows = rows.filter(t => favs.includes(t.nct_id));
  } else if (ACTIVE_FILTER !== "all") {
    rows = rows.filter(t => t.verdict === ACTIVE_FILTER);
  }
  if (!rows.length) {
    list.innerHTML = `<p class="muted">Nothing in this view right now.</p>`;
    return;
  }
  list.innerHTML = rows.map(cardHtml).join("");
}

async function loadTrials() {
  const data = await api("/api/trials");
  TRIALS = data.trials || [];
  const updated = document.getElementById("updated-text");
  if (data.updated) {
    const d = new Date(data.updated);
    updated.textContent = "Updated " + d.toLocaleDateString() + " at " +
      d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) +
      " - " + TRIALS.length + " studies checked";
  }
  const err = document.getElementById("error-text");
  if (data.error) { err.hidden = false; err.textContent = data.error; }
  render();
}

async function loadContext() {
  const ctx = await api("/api/context");
  const section = document.getElementById("research-section");
  if (ctx.digest_available) {
    section.hidden = false;
    document.getElementById("digest-content").textContent = ctx.digest;
  }
}

function callScript(t) {
  const site = t.nearest_site
    ? `the site in ${t.nearest_site.city}, ${t.nearest_site.state}`
    : "the site listed on the study page";
  return [
    "What to say when you call:",
    "",
    `Hello, I am calling about study ${t.nct_id}.`,
    `My father has Parkinson's disease.`,
    `I have a few questions before we think about joining:`,
    "",
    "1. Is the study still enrolling new people?",
    `2. Is the site at ${site} the closest place to participate?`,
    "3. Does having deep brain stimulation, or planning to have it,",
    "   affect whether he can join?",
    "4. What are the main requirements for joining?",
    "5. How many visits are there, and how long do they take?",
    "6. Who can we talk to if we have more questions?",
  ].join("\n");
}

function openTrialModal(t) {
  const body = document.getElementById("modal-body");
  body.innerHTML = `
    <span class="badge ${t.verdict}">${VERDICT_LABELS[t.verdict] || t.verdict}</span>
    <h2>${escapeHtml(t.title)}</h2>
    <p><strong>${t.nct_id}</strong> &middot; ${escapeHtml(t.status)}</p>
    <p>${escapeHtml(fmtSite(t))}</p>
    <ul class="reasons">${reasonsHtml(t)}</ul>
    <p><a href="${t.url}" target="_blank" rel="noopener">Read the official study page</a></p>
    <div class="callscript">${escapeHtml(callScript(t))}</div>`;
  document.getElementById("trial-modal").hidden = false;
}

async function openProfileModal() {
  PROFILE = (await api("/api/profile")).profile || {};
  document.getElementById("p-age").value = PROFILE.age || "";
  document.getElementById("p-dbs").value = PROFILE.dbs || "none";
  document.getElementById("p-stage").value = PROFILE.stage || "unsure";
  document.getElementById("p-levodopa").value = PROFILE.levodopa_years || 0;
  document.getElementById("p-travel").value = PROFILE.travel || "half_day";
  const citySel = document.getElementById("p-city");
  if (!citySel.options.length) {
    for (const [key, label] of Object.entries(CITY_LABELS)) {
      const opt = document.createElement("option");
      opt.value = key; opt.textContent = label;
      citySel.appendChild(opt);
    }
  }
  citySel.value = PROFILE.home_city || "jackson_ms";
  document.getElementById("profile-modal").hidden = false;
}

function closeModal(id) { document.getElementById(id).hidden = true; }

document.addEventListener("click", async (ev) => {
  const star = ev.target.closest("[data-star]");
  if (star) { toggleFav(star.dataset.star); render(); return; }
  const open = ev.target.closest("[data-open]");
  if (open) {
    const t = TRIALS.find(x => x.nct_id === open.dataset.open);
    if (t) openTrialModal(t);
    return;
  }
  const filter = ev.target.closest(".filter");
  if (filter) {
    document.querySelectorAll(".filter").forEach(f => f.classList.remove("active"));
    filter.classList.add("active");
    ACTIVE_FILTER = filter.dataset.filter;
    render();
  }
});

document.getElementById("modal-close").addEventListener("click",
  () => closeModal("trial-modal"));
document.getElementById("profile-close").addEventListener("click",
  () => closeModal("profile-modal"));
document.getElementById("btn-profile").addEventListener("click", openProfileModal);

document.getElementById("profile-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  PROFILE = {
    age: parseInt(document.getElementById("p-age").value, 10) || 70,
    dbs: document.getElementById("p-dbs").value,
    stage: document.getElementById("p-stage").value,
    levodopa_years: parseInt(document.getElementById("p-levodopa").value, 10) || 0,
    travel: document.getElementById("p-travel").value,
    home_city: document.getElementById("p-city").value,
    willing_observational: "yes",
  };
  await api("/api/profile", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(PROFILE),
  });
  closeModal("profile-modal");
  const btn = document.getElementById("btn-rescan");
  btn.disabled = true; btn.textContent = "Checking...";
  await api("/api/rescan", {method: "POST"});
  setTimeout(async () => {
    await loadTrials();
    btn.disabled = false; btn.textContent = "Check for new trials";
  }, 90000);
  alert("Saved. The list will refresh in about a minute.");
});

document.getElementById("btn-rescan").addEventListener("click", async function () {
  this.disabled = true; this.textContent = "Checking...";
  await api("/api/rescan", {method: "POST"});
  const btn = this;
  setTimeout(async () => {
    await loadTrials();
    btn.disabled = false; btn.textContent = "Check for new trials";
  }, 90000);
});

const chatPanel = document.getElementById("chat-panel");
document.getElementById("chat-fab").addEventListener("click", () => {
  chatPanel.hidden = !chatPanel.hidden;
});
document.getElementById("chat-close").addEventListener("click",
  () => { chatPanel.hidden = true; });

const chatLog = document.getElementById("chat-log");
const CHAT_HISTORY = [];

document.getElementById("chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = document.getElementById("chat-text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  CHAT_HISTORY.push({role: "user", content: text});
  const thinking = addMsg("bot", "...");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({messages: CHAT_HISTORY}),
    });
    thinking.textContent = data.reply || "No answer came back. Try again.";
    CHAT_HISTORY.push({role: "assistant", content: data.reply || ""});
  } catch (e) {
    thinking.textContent = "Connection problem. Try again.";
  }
});

function addMsg(kind, text) {
  const div = document.createElement("div");
  div.className = "msg " + kind;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

loadTrials();
loadContext();
setInterval(loadTrials, 5 * 60 * 1000);
