/* Pixel theatre (arena.html): replays a transcript or a live match as an 8-bit show. */
(function () {
"use strict";
const { t, th, fmtNum } = window.I18N;
const { MATCH_RE, safeApi, apiFetch, qs } = window.ARENA;
const $ = id => document.getElementById(id);
const PALETTE = ["#51d1f6", "#ff6b6b", "#8affc1", "#ffa857", "#c08bff", "#ffe066", "#6bd5ff", "#ff8ad1"];
const MODE_KEY = { quiz: "m_quiz", task: "m_task", ctf: "m_ctf" };
const STATUS_RE = /^[A-Z_]{1,20}$/;
const modeName = m => (MODE_KEY[m] ? t(MODE_KEY[m]) : String(m || ""));
const clip = (s, n) => String(s == null ? "" : s).slice(0, n);

// Built-in sample (mock quiz, no real secrets). Rebuilt per language.
function sample() {
  return [
    { type: "match_start", round: 0, data: { match_id: "sample-quiz", mode: "quiz", agents: [
      { id: "alpha", model: "mock-smart", prompt_author: "author-x" },
      { id: "beta", model: "mock-dumb", prompt_author: "author-y" }] } },
    { type: "observation", round: 1, agent: "alpha", data: { task: t("a_s_q1") } },
    { type: "action", round: 1, agent: "alpha", data: { content: t("a_s_a1") } },
    { type: "grade", round: 1, agent: "alpha", data: { qid: "cap-jp", correct: true } },
    { type: "action", round: 1, agent: "beta", data: { content: t("a_s_b1") } },
    { type: "grade", round: 1, agent: "beta", data: { qid: "cap-jp", correct: false } },
    { type: "observation", round: 2, agent: "alpha", data: { task: t("a_s_q2") } },
    { type: "action", round: 2, agent: "alpha", data: { content: "391" } },
    { type: "grade", round: 2, agent: "alpha", data: { qid: "math-1", correct: true } },
    { type: "action", round: 2, agent: "beta", data: { content: "390" } },
    { type: "grade", round: 2, agent: "beta", data: { qid: "math-1", correct: false } },
    { type: "observation", round: 3, agent: "alpha", data: { task: t("a_s_q3") } },
    { type: "action", round: 3, agent: "alpha", data: { content: "C" } },
    { type: "grade", round: 3, agent: "alpha", data: { qid: "logic-1", correct: true } },
    { type: "action", round: 3, agent: "beta", data: { content: "A" } },
    { type: "grade", round: 3, agent: "beta", data: { qid: "logic-1", correct: false } },
    { type: "result", round: 3, data: { scores: { alpha: 3, beta: 0 }, ranking: ["alpha", "beta"], status: "COMPLETE" } },
    { type: "elo", round: 3, data: { alpha: { model: 16, prompt: 16 }, beta: { model: -16, prompt: -16 } } },
  ];
}

/* ---------- helpers ---------- */
function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
function spriteCells(id) {
  const h = hash(id); const c1 = PALETTE[h % PALETTE.length]; const c2 = PALETTE[(h >> 5) % PALETTE.length];
  const cells = [];
  for (let y = 0; y < 8; y++) {
    const row = [];
    for (let x = 0; x < 4; x++) { const bit = (hash(id + ":" + y + ":" + x)) % 100; row[x] = bit < 46 ? (bit < 20 ? c2 : c1) : null; }
    cells.push(...row, ...row.slice().reverse());
  }
  return { cells, c1 };
}
function renderAvatar(nodeEl, id) {
  nodeEl.replaceChildren();
  for (const c of spriteCells(String(id)).cells) { const i = document.createElement("i"); if (c) i.style.background = c; nodeEl.appendChild(i); }
}

/* ---------- state ---------- */
let EVENTS = [], MODEL = null, idx = 0, timer = null, speed = 1, fighters = {}, serverNode = null, isSample = false;
let tickerState = null;   // {key, params} so the ticker can be re-rendered on language change
const SPEEDS = [1, 2, 4];

function parseTranscript(text) {
  const out = [];
  for (const line of text.split("\n")) {
    const s = line.trim(); if (!s) continue;
    try { const o = JSON.parse(s); if (o && typeof o === "object" && typeof o.type === "string") out.push(o); } catch (_) { /* skip bad line */ }
  }
  return out;
}
function buildModel(events) {
  const ms = events.find(e => e.type === "match_start");
  const d = (ms && ms.data) || {};
  const agents = (Array.isArray(d.agents) ? d.agents : []).filter(a => a && a.id != null).map(a => ({ ...a, id: String(a.id) }));
  return { matchId: String(d.match_id || "—"), mode: String(d.mode || "quiz"), agents, events };
}

function renderStage() {
  const stage = $("stage"); stage.replaceChildren(); fighters = {}; serverNode = null;
  const left = el("div", "side left"), right = el("div", "side right"), center = el("div", "center");
  MODEL.agents.forEach((a, i) => {
    const f = el("div", "fighter");
    const av = el("i", "avatar"); renderAvatar(av, a.id);
    const meta = el("div", "meta");
    const color = PALETTE[hash(String(a.team || a.id)) % PALETTE.length];
    meta.appendChild(el("div", "nm", (a.team ? ("[" + a.team + "] ") : "") + a.id)).style.color = color;
    meta.appendChild(el("div", "sub", (a.model || "—") + " · " + (a.prompt_author || "—")));
    const hp = el("div", "hpbar"); const hpi = el("i"); hp.appendChild(hpi); meta.appendChild(hp);
    const sc = el("div", "score", t("a_pts", { n: 0 })); meta.appendChild(sc);
    const bub = el("div", "bubble", t("a_standby")); meta.appendChild(bub);
    f.append(av, meta);
    (i % 2 === 0 ? left : right).appendChild(f);
    fighters[a.id] = { node: f, hp: hpi, score: sc, bubble: bub, val: 0, idle: true };
  });
  if (MODEL.mode === "ctf") {
    const srv = el("div", "server"); renderAvatar(srv, "THE-SERVER:" + MODEL.matchId);
    serverNode = srv; center.append(el("div", "lock", "🔒 TARGET"), srv);
  } else {
    const q = el("div", "qbanner", "QUIZ"); q.id = "qbanner"; center.appendChild(q);
  }
  stage.append(left, center, right);
  $("matchId").textContent = MODEL.matchId; $("matchId").title = MODEL.matchId;
  $("modeChip").textContent = modeName(MODEL.mode);
}

function setStatus(s) { const b = $("statusBadge"); const v = STATUS_RE.test(String(s || "")) ? s : null; b.className = "badge " + (v || "PARTIAL"); b.textContent = v || "—"; }
// All ticker text goes through th(): template is trusted, every param is escaped.
// Points per correct answer: 1 + speed bonus (server-computed); older transcripts have no points → 1.
const round2 = v => Math.round(v * 100) / 100;
function gradePoints(d) { const p = Number(d.points); return Number.isFinite(p) && p >= 0 && p <= 10 ? round2(p) : 1; }
function ticker(key, params) { tickerState = { key, params }; $("ticker").innerHTML = th(key, params); }
function floatText(fid, txt, color) {
  const f = fighters[fid]; if (!f) return;
  const n = el("div", "float", txt); n.style.color = color || "var(--gold)";
  f.node.appendChild(n); setTimeout(() => n.remove(), 1000);
}
function refreshBars() {
  const vals = Object.values(fighters).map(f => f.val); const max = Math.max(1, ...vals);
  for (const id in fighters) { const f = fighters[id]; f.hp.style.width = Math.round(f.val / max * 100) + "%"; f.score.textContent = t("a_pts", { n: fmtNum(f.val) }); }
}

function applyEvent(ev) {
  const r = Number(ev.round) || 0;
  if (r) $("roundLbl").textContent = "ROUND " + r;
  const id = ev.agent != null ? String(ev.agent) : null;
  const f = id ? fighters[id] : null;
  const d = (ev.data && typeof ev.data === "object") ? ev.data : {};
  switch (ev.type) {
    case "observation":
      if (MODEL.mode !== "ctf") { const q = $("qbanner"); if (q) q.textContent = clip(d.task, 80); }
      break;
    case "action":
      if (f) { f.bubble.textContent = "▶ " + clip(d.content, 80); f.idle = false; }
      ticker("a_act", { a: id, c: clip(d.content, 90) });
      break;
    case "grade":
      if (f) {
        if (d.correct || d.ok) {
          const pts = gradePoints(d);
          f.val = round2(f.val + pts); f.node.classList.add("attack"); setTimeout(() => f.node.classList.remove("attack"), 250);
          floatText(id, "+" + fmtNum(pts) + " ✓", "var(--hp)");
          if (Number.isFinite(Number(d.seconds))) ticker("a_graded", { a: id, s: fmtNum(round2(Number(d.seconds))), p: fmtNum(pts) });
          for (const o in fighters) { if (o !== id) { fighters[o].node.classList.add("hit"); setTimeout(() => fighters[o].node.classList.remove("hit"), 300); } }
        } else { floatText(id, "✗", "var(--muted)"); }
        refreshBars();
      }
      break;
    case "request":
      if (f) { f.bubble.textContent = "⌨ " + clip(d.method, 10) + " " + clip(d.path, 80); f.idle = false; }
      if (serverNode) { serverNode.classList.add("jab"); setTimeout(() => serverNode.classList.remove("jab"), 250); }
      ticker("a_req", { a: id, m: clip(d.method, 10), p: clip(d.path, 80), s: clip(d.status, 5) });
      break;
    case "solve":
      if (f) { f.val += d.first ? 2000 : 1000; floatText(id, d.first ? "FIRST BLOOD!" : "SOLVED", "var(--win)"); }
      if (serverNode) serverNode.classList.add("broken");
      ticker("a_solve", { a: id, f: d.first ? t("a_first") : "" });
      refreshBars();
      break;
    case "submit_wrong": if (f) floatText(id, "FLAG?✗", "var(--danger)"); break;
    case "result": showResult(d); break;
    case "elo": MODEL.elo = d; break;
    case "teams": MODEL.teamScores = d.team_scores; MODEL.teamRanking = d.team_ranking; MODEL.teamMembers = d.members; break;
    case "team_elo": MODEL.teamElo = d; break;
    case "startup_error": ticker("a_startfail", { e: clip(d.error, 200) }); break;
    default: break;
  }
}

function deltaSpan(v) {
  const n = Math.round(Number(v) || 0);
  return el("span", "delta " + (n >= 0 ? "pos" : "neg"), (n > 0 ? "+" : "") + n);
}
function showResult(data) {
  MODEL.lastResult = data;
  setStatus(data.status || "COMPLETE");
  const body = $("resultBody"); body.replaceChildren();
  const scores = (data.scores && typeof data.scores === "object") ? data.scores : {};
  const ranking = (Array.isArray(data.ranking) ? data.ranking : Object.keys(scores)).map(String);
  const elo = MODEL.elo || {};
  ranking.forEach((id, i) => {
    const a = MODEL.agents.find(x => x.id === id) || {};
    const d = elo[id] || { model: 0, prompt: 0 };
    const tr = el("tr", i === 0 ? "rank1" : "");
    tr.append(el("td", null, "#" + (i + 1)), el("td", null, id), el("td", null, a.model || "—"), el("td", null, a.prompt_author || "—"),
      el("td", "r", fmtNum(round2(Number(scores[id]) || 0))));
    const dc = el("td", "r"); dc.append(deltaSpan(d.model), document.createTextNode(" / "), deltaSpan(d.prompt));
    tr.appendChild(dc); body.appendChild(tr);
  });
  let title = ranking[0] ? t("a_win", { w: ranking[0] }) : t("a_over");
  let foot = t("a_foot", { s: data.status || "—", m: modeName(MODEL.mode), id: MODEL.matchId });
  if (MODEL.teamScores && typeof MODEL.teamScores === "object") {
    const tr = (Array.isArray(MODEL.teamRanking) ? MODEL.teamRanking : Object.keys(MODEL.teamScores)).map(String);
    if (tr[0]) title = t("a_team_win", { w: tr[0] });
    foot = t("a_teams", { t: tr.map(x => {
      const dd = (MODEL.teamElo || {})[x];
      return x + " " + fmtNum(MODEL.teamScores[x]) + (dd != null ? (" (ELO " + (dd > 0 ? "+" : "") + Math.round(Number(dd) || 0) + ")") : "");
    }).join("　") }) + foot;
  }
  $("winTitle").textContent = title;
  $("resultFoot").textContent = foot;
  $("overlay").classList.add("show");
}

/* ---------- playback ---------- */
function step() { if (idx >= EVENTS.length) return false; applyEvent(EVENTS[idx]); idx++; return idx < EVENTS.length; }
function playLabel() { $("btnPlay").textContent = timer ? t("a_pause") : t("a_play"); }
function play() { if (timer) { pause(); return; } timer = setInterval(() => { if (!step()) pause(); }, 900 / speed); playLabel(); }
function pause() { if (timer) clearInterval(timer); timer = null; playLabel(); }
function reset() { pause(); idx = 0; $("overlay").classList.remove("show"); load(isSample ? sample() : EVENTS, isSample); }
function speedLabel() { $("btnSpeed").textContent = t("a_speed", { n: speed }); }

function load(events, fromSample) {
  pause(); isSample = !!fromSample; EVENTS = events; MODEL = buildModel(events); idx = 0;
  renderStage(); setStatus(null); $("roundLbl").textContent = "ROUND 0";
  ticker("a_loaded", { id: MODEL.matchId, m: modeName(MODEL.mode), n: MODEL.agents.length });
}

$("btnStep").addEventListener("click", () => { pause(); step(); });
$("btnPlay").addEventListener("click", play);
$("btnReset").addEventListener("click", reset);
$("btnClose").addEventListener("click", () => $("overlay").classList.remove("show"));
$("btnSpeed").addEventListener("click", () => {
  speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; speedLabel();
  if (timer) { pause(); play(); }
});
$("btnLoad").addEventListener("click", () => $("fileIn").click());
$("fileIn").addEventListener("change", e => {
  const file = e.target.files[0]; if (!file) return;
  const rd = new FileReader();
  rd.onload = () => { const evs = parseTranscript(String(rd.result)); if (evs.length) load(evs, false); else ticker("a_parse_err"); };
  rd.readAsText(file);
  e.target.value = "";
});

/* ---------- demo match (server-side fixed config) ---------- */
// Keeps the message keys (not the rendered text) so a language switch can re-render it.
let lmsgState = null;
function lmsg(keys, params, err) {
  lmsgState = { keys: [].concat(keys), params, err: !!err };
  const e = $("lobbyMsg");
  e.textContent = lmsgState.keys.map(k => t(k, params)).join(" ");
  e.classList.toggle("err", lmsgState.err); e.style.color = lmsgState.err ? "var(--danger)" : "var(--muted)";
}
function apiBase() {
  const v = safeApi($("api").value);
  if (v === null) return null;
  return v || location.origin;
}
$("btnDemo").addEventListener("click", async () => {
  const b = apiBase();
  if (b === null) { lmsg("e_bad_url", null, 1); return; }
  const btn = $("btnDemo"); btn.disabled = true; lmsg("a_demo_creating");
  try {
    const r = await apiFetch(b, "POST", "/api/demo");
    if (!MATCH_RE.test(String(r.match_id || ""))) throw new Error(t("e_http", { s: "?" }));
    lmsg("a_demo_ok", { id: r.match_id });
    connectLive(r.match_id, b, Array.isArray(r.players) ? r.players.map(String) : []);
  } catch (e) { lmsg("a_demo_fail", { e: e.message }, 1); }
  finally { btn.disabled = false; }
});

/* ---------- live spectating over SSE ---------- */
let liveES = null;
function connectLive(matchId, base, players) {
  if (!MATCH_RE.test(String(matchId))) return;
  base = String(base || "").replace(/\/$/, "");
  if (liveES) liveES.close();
  pause(); isSample = false;
  MODEL = { matchId, mode: "quiz", agents: (players || []).map(p => ({ id: p })), events: [] };
  EVENTS = []; idx = 0;
  renderStage(); setStatus("RUNNING");
  ticker("a_live", { id: matchId });
  const es = new EventSource(`${base}/api/matches/${encodeURIComponent(matchId)}/stream?lang=${encodeURIComponent(window.I18N.lang())}`);
  liveES = es;
  es.onmessage = e => {
    let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
    if (!ev || typeof ev.type !== "string") return;
    EVENTS.push(ev); idx = EVENTS.length;
    if (ev.type === "match_start") { MODEL = buildModel([ev]); renderStage(); setStatus("RUNNING"); }
    else applyEvent(ev);
  };
  es.addEventListener("end", () => { es.close(); if (liveES === es) liveES = null; });
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) ticker("a_stream_err"); };
}

/* ---------- language change ---------- */
document.addEventListener("arena:lang", () => {
  playLabel(); speedLabel();
  if (lmsgState) lmsg(lmsgState.keys, lmsgState.params, lmsgState.err);
  if (!MODEL) return;
  $("modeChip").textContent = modeName(MODEL.mode);
  if (isSample && idx === 0) { load(sample(), true); return; }
  for (const id in fighters) { const f = fighters[id]; f.score.textContent = t("a_pts", { n: fmtNum(f.val) }); if (f.idle) f.bubble.textContent = t("a_standby"); }
  if (tickerState) ticker(tickerState.key, tickerState.params);
  if (MODEL.lastResult && $("overlay").classList.contains("show")) showResult(MODEL.lastResult);
});

/* ---------- boot: ?match=<id>[&api=<base>] spectates live; otherwise play the sample ---------- */
window.I18N.mountSwitcher($("langHost"));
window.I18N.apply();
playLabel(); speedLabel();
const rawApi = qs("api");
let apiFromUrl = "";
if (rawApi) {
  const v = safeApi(rawApi);
  if (v) { apiFromUrl = v; $("api").value = v; }
}
const rawMatch = qs("match");
if (rawMatch && MATCH_RE.test(rawMatch)) {
  connectLive(rawMatch, apiFromUrl || location.origin, []);
} else {
  load(sample(), true);
}
const bootWarn = [rawMatch && !MATCH_RE.test(rawMatch) ? "a_bad_match" : "", rawApi && !apiFromUrl ? "a_bad_api" : ""].filter(Boolean);
if (bootWarn.length) lmsg(bootWarn, null, 1);
})();
