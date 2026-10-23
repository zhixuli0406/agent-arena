/* Lobby core (index.html): shared state, API, toasts, tiers, settings, sound, navigation, boot.
 * Screens live in play.js (queue, party, ready check), match.js (seat, HUD, results) and panels.js
 * (rooms, spectate list, ladder, connect). They register on window.LOBBY.hooks. */
(function () {
"use strict";
const { t, th, fmtNum } = window.I18N;
const { safeApi, apiFetch, qs } = window.ARENA;
const $ = id => document.getElementById(id);
const PALETTE = ["#e08a5f", "#4fbf8a", "#6b9cf0", "#e3b04a", "#b98ae6", "#46bcc9", "#e46f8e", "#93b85a"];
const MODE_KEY = { quiz: "m_quiz", task: "m_task", ctf: "m_ctf" };
const STATUS_RE = /^[A-Z_]{1,20}$/;
const PLACEMENT_GAMES = 5;
// Rating tiers (display only; the ladder itself is plain ELO). Everyone starts at 1500.
const TIERS = [
  [1800, "tier_master", "oklch(0.72 0.17 330)"], [1700, "tier_diamond", "oklch(0.78 0.11 220)"],
  [1600, "tier_platinum", "oklch(0.8 0.09 180)"], [1500, "tier_gold", "oklch(0.82 0.14 85)"],
  [1400, "tier_silver", "oklch(0.8 0.01 250)"], [-Infinity, "tier_bronze", "oklch(0.66 0.1 55)"],
];

const hash = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
const color = s => PALETTE[hash(String(s)) % PALETTE.length];
const initials = s => (String(s || "?").trim().slice(0, 2) || "?").toUpperCase();
const mmss = sec => { sec = Math.max(0, Math.floor(sec)); return String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0"); };
const modeName = m => (MODE_KEY[m] ? t(MODE_KEY[m]) : String(m || ""));
function node(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function ava(name) { const d = node("div", "ava", initials(name)); d.style.background = color(name); return d; }
const emptyNote = text => node("div", "empty", text);
const statusLabel = s => (s === "RUNNING" ? t("b_running") : s === "COMPLETE" ? t("b_done") : String(s || ""));
const badgeClass = s => "badge " + (STATUS_RE.test(String(s)) ? s : "PARTIAL");
function fmtPts(v) {
  const n = Number(v) || 0;
  return n === 0 ? "0" : new Intl.NumberFormat(window.I18N.lang(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}
function tierOf(rating, games) {
  const r = Number(rating) || 0;
  const [, key, c] = TIERS.find(([min]) => r >= min);
  const placing = Number.isFinite(Number(games)) && Number(games) < PLACEMENT_GAMES;
  return { key, color: c, placing, label: placing ? t("tier_placement", { n: fmtNum(games), m: PLACEMENT_GAMES }) : t(key) };
}
function tierEl(rating, games) {
  const x = tierOf(rating, games);
  const e = node("span", "tier"); e.style.setProperty("--tc", x.color);
  e.append(node("i"), document.createTextNode(x.label));
  return e;
}

/* ---------- state ---------- */
const S = { server: "", manualServer: "", pid: "", secret: "", me: null, srv: "wait", codeLen: 7, stats: null,
  ticket: null, party: null, room: null, roomView: null, mode: "quiz", size: 2, fmt: "ffa", token: null, match: null };
const store = {
  load() { try { return JSON.parse(localStorage.getItem("arena.v2") || "{}") || {}; } catch (_) { return {}; } },
  save() { try { localStorage.setItem("arena.v2", JSON.stringify({ server: S.manualServer, pid: S.pid, secret: S.secret })); } catch (_) { /* storage blocked */ } },
};
const prefs = Object.assign({ sound: true, fx: true, cb: false }, (() => { try { return JSON.parse(localStorage.getItem("arena.prefs") || "{}"); } catch (_) { return {}; } })());
const savePrefs = () => { try { localStorage.setItem("arena.prefs", JSON.stringify(prefs)); } catch (_) { /* storage blocked */ } };
const base = () => (S.server || location.origin).replace(/\/$/, "");
function api(method, path, body) {
  const h = S.pid ? { "X-Player-Id": S.pid, "X-Player-Secret": S.secret } : {};
  return apiFetch(base(), method, path, body, h);
}
const enc = encodeURIComponent;

/* ---------- messages: inline next to forms, toasts for everything else (one at a time) ---------- */
const tk = (key, params) => ({ key, params });
const TOAST_IDS = new Set(["qMsg", "mMsg", "wMsg"]);
const sayState = {};
let toastTimer = 0, toastState = null;
function toast(msg, kind) {
  const box = $("toasts");
  toastState = msg ? { msg, kind } : null;
  box.replaceChildren();
  clearTimeout(toastTimer);
  if (!msg) return;
  const el = node("div", "toast" + (kind ? " " + kind : ""), typeof msg === "object" ? t(msg.key, msg.params) : msg);
  el.setAttribute("role", kind === "err" ? "alert" : "status");
  box.appendChild(el);
  toastTimer = setTimeout(() => { box.replaceChildren(); toastState = null; }, kind === "err" ? 7000 : 4500);
}
function say(id, msg, err) {
  if (TOAST_IDS.has(id)) { if (msg) toast(msg, err ? "err" : ""); return; }
  const e = $(id);
  sayState[id] = msg && typeof msg === "object" ? { msg, err: !!err } : null;
  e.textContent = msg && typeof msg === "object" ? t(msg.key, msg.params) : (msg || "");
  e.classList.toggle("err", !!err);
}
function copyBtn(get, okKey) {
  const b = node("button", "btn sec sm", t("btn_copy")); b.type = "button";
  b.addEventListener("click", () => copy(get(), okKey)); return b;
}
async function copy(text, okKey) {
  try { await navigator.clipboard.writeText(text); toast(tk(okKey || "copied"), "ok"); }
  catch (_) { toast(text); }
}

/* ---------- sound + attention (ready check must not be missed in a background tab) ---------- */
let audio = null;
function beep(seq) {
  if (!prefs.sound) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    let at = audio.currentTime + 0.02;
    for (const [freq, dur] of seq) {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = "triangle"; o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(0.18, at + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      o.connect(g).connect(audio.destination); o.start(at); o.stop(at + dur + 0.02);
      at += dur * 0.85;
    }
  } catch (_) { /* audio blocked until the user interacts; the title flash still works */ }
}
let titleTimer = 0, baseTitle = "";
function flashTitle(key) {
  stopFlash();
  if (!document.hidden) return;
  baseTitle = document.title;
  let n = 0;
  titleTimer = setInterval(() => { document.title = n++ % 2 ? baseTitle : t(key); }, 800);
}
function stopFlash() { if (titleTimer) { clearInterval(titleTimer); titleTimer = 0; document.title = baseTitle || t("title"); } }
document.addEventListener("visibilitychange", () => { if (!document.hidden) stopFlash(); });

/* ---------- server discovery, health, stats ---------- */
async function discover() {
  const fromUrl = qs("api");
  if (fromUrl) { const v = safeApi(fromUrl); if (v) { S.server = v; return; } }
  const saved = store.load();
  if (saved.server) { const v = safeApi(saved.server); if (v) { S.server = S.manualServer = v; return; } }
  for (const p of ["../server.json", "server.json"]) {
    try {
      const r = await fetch(p, { cache: "no-store" });
      if (r.ok) { const j = await r.json(); const v = j && safeApi(j.server); if (v) { S.server = v; return; } }
    } catch (_) { /* try next */ }
  }
}
function setSrv(state) {
  S.srv = state;
  $("srvDot").className = "dot" + (state === "on" ? " on" : state === "off" ? " off" : "");
  $("srvText").textContent = t("srv_" + state);
  $("netBar").classList.toggle("hide", state !== "off");
}
async function health() {
  try { await api("GET", "/api/health"); setSrv("on"); return true; }
  catch (e) { if (e.status === 429) return true; setSrv("off"); return false; }
}
let statsPause = 0;
async function stats() {
  if (Date.now() < statsPause) return;
  try { S.stats = await api("GET", "/api/lobby/stats"); $("stOnline").textContent = fmtNum(S.stats.online); setSrv("on"); }
  catch (e) { if (e.status === 429) { statsPause = Date.now() + e.retryAfter * 1000; return; } setSrv("off"); }
}

/* ---------- identity ---------- */
function showMe(p) {
  S.me = p;
  $("enter").classList.add("hide"); $("mePanel").classList.remove("hide"); $("btnLogout").classList.remove("hide");
  const a = $("meAva"); a.textContent = initials(p.name); a.style.background = color(p.name);
  $("meName").textContent = p.name;
  $("meSub").textContent = p.agent || t("me_games", { n: fmtNum(p.games) });
  const placing = Number(p.games) < PLACEMENT_GAMES;
  $("meRating").textContent = fmtNum(p.rating) + (placing ? "?" : "");
  $("meTier").replaceChildren(...tierEl(p.rating, p.games).childNodes);
  $("meTier").style.setProperty("--tc", tierOf(p.rating, p.games).color);
  $("mePanel").title = t("me_games", { n: fmtNum(p.games) }) + (placing ? " · " + t("rk_tiers_help") : "");
  L.hooks.me.forEach(f => f(p));
}
function needPlayer(msgId) {
  if (S.pid) return true;
  say(msgId, tk("e_need"), 1);
  if (msgId !== "enterMsg") toast(tk("e_need"), "err");
  $("inName").focus(); return false;
}
async function refreshMe() {
  const m = await api("GET", "/api/lobby/me");
  showMe(m.player);
  L.hooks.refresh.forEach(f => f(m));
  return m;
}
$("btnEnter").addEventListener("click", async () => {
  const name = $("inName").value.trim(); if (!name) { say("enterMsg", tk("e_noname"), 1); return; }
  say("enterMsg", tk("e_entering"));
  try {
    const r = await api("POST", "/api/lobby/players", { name, agent: $("inAgent").value.trim() });
    S.pid = r.player.id; S.secret = r.secret; store.save(); showMe(r.player); say("enterMsg", ""); openTab("quick");
    L.hooks.entered.forEach(f => f());
  } catch (e) { say("enterMsg", tk("e_enterfail", { e: e.message }), 1); }
});
$("inName").addEventListener("keydown", e => { if (e.key === "Enter") $("btnEnter").click(); });
$("btnServer").addEventListener("click", async () => {
  const v = safeApi($("inServer").value.trim());
  if (v === null) { say("enterMsg", tk("e_bad_url"), 1); return; }
  S.server = S.manualServer = v; store.save();
  const ok = await health();
  say("enterMsg", ok ? tk("e_srv_ok") : tk("e_srv_bad"), !ok);
  L.hooks.lang.forEach(f => f());
});
$("btnLogout").addEventListener("click", () => { S.pid = S.secret = ""; store.save(); location.reload(); });

/* ---------- navigation: tabs, plus the match view that takes over while you play or spectate ---------- */
const TABS = ["quick", "room", "watch", "rank", "connect"];
let currentTab = "quick", inMatchView = false;
function openTab(tab) {
  currentTab = tab; inMatchView = false;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  TABS.forEach(x => $("tab-" + x).classList.toggle("hide", x !== tab));
  $("matchView").classList.add("hide");
  $("btnBackMatch").classList.toggle("hide", !L.matchLive());
  L.hooks.tab.forEach(f => f(tab));
}
function showMatchView() {
  inMatchView = true;
  TABS.forEach(x => $("tab-" + x).classList.add("hide"));
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("on"));
  $("matchView").classList.remove("hide"); $("btnBackMatch").classList.add("hide");
  window.scrollTo({ top: 0, behavior: "smooth" });
}
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => openTab(b.dataset.tab)));
$("btnBackMatch").addEventListener("click", showMatchView);

/* ---------- settings ---------- */
function applyPrefs() {
  document.body.classList.toggle("cb", !!prefs.cb);
  if (window.FX) { window.FX.setCb(prefs.cb); window.FX.enable(prefs.fx); }
  $("setSound").setAttribute("aria-checked", String(!!prefs.sound));
  $("setFx").setAttribute("aria-checked", String(!!prefs.fx));
  $("setCb").setAttribute("aria-checked", String(!!prefs.cb));
}
function toggleMenu(open) {
  const m = $("settingsMenu"), show = open == null ? m.classList.contains("hide") : open;
  m.classList.toggle("hide", !show); $("btnSettings").setAttribute("aria-expanded", String(show));
}
$("btnSettings").addEventListener("click", e => { e.stopPropagation(); toggleMenu(); });
document.addEventListener("click", e => { if (!$("settingsMenu").contains(e.target)) toggleMenu(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape") toggleMenu(false); });
for (const [id, key] of [["setSound", "sound"], ["setFx", "fx"], ["setCb", "cb"]]) {
  $(id).addEventListener("click", e => { e.stopPropagation(); prefs[key] = !prefs[key]; savePrefs(); applyPrefs(); if (key === "sound" && prefs.sound) beep([[660, 0.12]]); });
}

/* ---------- language switch: re-render everything that holds translated text ---------- */
document.addEventListener("arena:lang", () => {
  setSrv(S.srv);
  for (const id in sayState) if (sayState[id]) say(id, sayState[id].msg, sayState[id].err);
  if (toastState && typeof toastState.msg === "object") toast(toastState.msg, toastState.kind);
  if (S.me) showMe(S.me);
  L.hooks.lang.forEach(f => f());
});

/* ---------- shared namespace ---------- */
const L = window.LOBBY = {
  S, t, th, fmtNum, $, node, ava, color, emptyNote, mmss, modeName, statusLabel, badgeClass, fmtPts, tierOf, tierEl,
  api, base, enc, tk, say, toast, copy, copyBtn, beep, flashTitle, stopFlash, needPlayer, refreshMe, openTab, showMatchView,
  isMatchView: () => inMatchView, currentTab: () => currentTab, prefs,
  matchLive: () => false,                    // match.js replaces this
  hooks: { init: [], lang: [], me: [], refresh: [], tab: [], entered: [] },
};

/* ---------- boot (after every deferred module has registered its hooks) ---------- */
document.addEventListener("DOMContentLoaded", async () => {
  window.I18N.mountSwitcher($("langHost"));
  window.I18N.apply();
  applyPrefs();
  L.hooks.init.forEach(f => f());
  const saved = store.load(); S.pid = saved.pid || ""; S.secret = saved.secret || "";
  await discover();
  $("inServer").value = S.manualServer || (S.server && S.server !== location.origin ? S.server : "");
  L.hooks.lang.forEach(f => f());
  try {
    const cfg = await api("GET", "/api/lobby/config");
    const n = Number(cfg && cfg.room_code_len);
    if (Number.isInteger(n) && n >= 4 && n <= 12) S.codeLen = n;
  } catch (_) { /* keep default length */ }
  await health(); stats(); setInterval(stats, 5000);
  if (S.pid) { try { await refreshMe(); } catch (e) { if (e.status === 401) { S.pid = S.secret = ""; store.save(); } } }
  if (!S.pid) $("enter").classList.remove("hide");
  if (!L.isMatchView()) openTab(S.pid ? "quick" : (qs("party") || qs("room") ? "quick" : "watch"));
  L.hooks.entered.forEach(f => f());
});
})();
