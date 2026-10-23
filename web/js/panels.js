/* Secondary screens: custom rooms, spectate list + demo, ladder, connect-your-agent. */
(function () {
"use strict";
const L = window.LOBBY;
const { S, t, th, fmtNum, $, node, ava, emptyNote, modeName, statusLabel, badgeClass, api, base, enc, tk, say, toast, copy } = L;
const { sq } = window.ARENA;
const { fmtTime } = window.I18N;
const ROOM_SIZES = [2, 3, 4, 6, 8];
const MODES = ["quiz", "task"];

/* ---------- custom rooms (unranked) ---------- */
let rPoll = null, rPause = 0;
const roomPath = suffix => `/api/lobby/rooms/${enc(S.room)}${suffix || ""}`;
function renderRoomSetup() {
  const mode = $("rMode"), size = $("rSize");
  const mv = mode.value || "quiz", sv = size.value || "4";
  mode.replaceChildren(...MODES.map(k => { const o = node("option", null, modeName(k)); o.value = k; return o; }));
  size.replaceChildren(...ROOM_SIZES.map(n => { const o = node("option", null, t("n_people", { n })); o.value = String(n); return o; }));
  mode.value = mv; size.value = sv;
  const code = $("rCode"); code.maxLength = S.codeLen; code.placeholder = t("ph_code", { n: S.codeLen });
}
$("btnCreate").addEventListener("click", async () => {
  say("rMsg", ""); if (!L.needPlayer("rMsg")) return;
  try { const r = await api("POST", "/api/lobby/rooms", { mode: $("rMode").value, size: +$("rSize").value }); S.room = r.code; renderRoom(r); pollRoom(); }
  catch (e) { say("rMsg", e.message, 1); }
});
$("rCode").addEventListener("input", e => { const v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, S.codeLen); if (v !== e.target.value) e.target.value = v; });
$("rCode").addEventListener("keydown", e => { if (e.key === "Enter") $("btnJoin").click(); });
$("btnJoin").addEventListener("click", async () => {
  if (!L.needPlayer("rMsg")) return;
  const code = $("rCode").value.trim().toUpperCase();
  if (!/^[A-Z0-9]+$/.test(code) || code.length !== S.codeLen) { say("rMsg", tk("r_codelen", { n: S.codeLen }), 1); return; }
  try { const r = await api("POST", `/api/lobby/rooms/${enc(code)}/join`); S.room = r.code; say("rMsg", ""); renderRoom(r); pollRoom(); }
  catch (e) { say("rMsg", e.message, 1); }
});
$("btnReady").addEventListener("click", async () => {
  const mine = ((S.roomView && S.roomView.members) || []).find(m => m.id === S.pid);
  try { renderRoom(await api("POST", roomPath("/ready"), { ready: !(mine && mine.ready) })); } catch (e) { say("rMsg", e.message, 1); }
});
$("btnStart").addEventListener("click", async () => { try { renderRoom(await api("POST", roomPath("/start"))); } catch (e) { say("rMsg", e.message, 1); } });
function resetRoomUI(msg, err) {
  clearInterval(rPoll); S.room = null; S.roomView = null;
  $("rRoom").classList.add("hide"); $("rSetup").classList.remove("hide"); say("rMsg", msg || "", err);
}
$("btnLeave").addEventListener("click", async () => {
  try { await api("POST", roomPath("/leave")); } catch (_) { /* leaving anyway */ }
  resetRoomUI(tk("r_left"));
});
$("btnCopyCode").addEventListener("click", () => {
  const u = new URL(location.href); u.hash = ""; ["party", "match"].forEach(k => u.searchParams.delete(k));
  u.searchParams.set("room", S.room); u.searchParams.set("lang", window.I18N.lang());
  copy(t("r_invite", { c: S.room, u: u.toString() }));
  say("rMsg", tk("copied"));
});
async function kick(m) {
  if (!S.room) return;
  if (!window.confirm(t("r_kick_q", { n: m.name }))) return;
  try {
    const r = await api("POST", roomPath("/kick"), { player_id: m.id });
    if (r && Array.isArray(r.members)) renderRoom(r); else renderRoom(await api("GET", roomPath()));
    say("rMsg", tk("r_kicked_ok", { n: m.name }));
  } catch (e) { say("rMsg", e.message, 1); }
}
function pollRoom() {
  clearInterval(rPoll);
  rPoll = setInterval(async () => {
    if (!S.room) { clearInterval(rPoll); return; }
    if (Date.now() < rPause) return;
    try { renderRoom(await api("GET", roomPath())); }
    catch (e) {
      if (e.status === 429) { rPause = Date.now() + e.retryAfter * 1000; return; }
      if (e.status === 401 || e.status === 403 || e.status === 404) { resetRoomUI(tk("r_gone"), 1); return; }
      say("rMsg", e.message, 1);
    }
  }, 1500);
}
function renderRoom(r) {
  if (!r || !Array.isArray(r.members)) return;
  S.roomView = r;
  $("rSetup").classList.add("hide"); $("rRoom").classList.remove("hide");
  $("rCodeBig").textContent = r.code;
  $("rInfo").textContent = t("r_info", { m: modeName(r.mode), n: r.members.length, s: r.size });
  const ranked = r.ranked === true;
  const rk = $("rRanked"); rk.className = "tag " + (ranked ? "ranked" : "unranked"); rk.textContent = t(ranked ? "r_ranked" : "r_unranked");
  const isHost = r.host === S.pid, me = r.members.find(m => m.id === S.pid);
  const box = $("rSlots"); box.replaceChildren();
  r.members.forEach(m => {
    const s = node("div", "slot"); s.appendChild(ava(m.name));
    const n = node("div", "pn", m.name);
    if (m.host) n.appendChild(node("span", "crown", "♛"));
    const st = node("div", "st " + (m.ready ? "y" : "n"), m.host ? t("sl_host") : (m.ready ? t("sl_ready") : t("sl_notready")));
    s.append(n, st);
    if (isHost && !m.host && m.id !== S.pid && r.status === "open") {
      const k = node("button", "kick", t("btn_kick")); k.type = "button";
      k.addEventListener("click", () => kick(m));
      s.appendChild(k);
    }
    box.appendChild(s);
  });
  for (let i = r.members.length; i < r.size; i++) box.appendChild(node("div", "slot empty", t("sl_empty")));
  $("btnStart").classList.toggle("hide", !isHost || r.status !== "open"); $("btnReady").classList.toggle("hide", isHost || r.status !== "open");
  $("btnReady").textContent = me && me.ready ? t("btn_unready") : t("btn_ready");
  const allReady = r.members.length >= 2 && r.members.every(m => m.ready); $("btnStart").disabled = !allReady;
  const st = $("rStatus");
  if (r.status === "started") {
    st.className = "badge COMPLETE"; st.textContent = t("r_started"); clearInterval(rPoll);
    if (r.token && S.token !== r.token) L.seat(r.token, r.match_id, r.members.map(m => ({ id: m.name, sub: m.agent })), ranked);
  } else { st.className = "badge RUNNING"; st.textContent = allReady ? t("r_allready") : t("r_waiting"); }
}

/* ---------- spectate ---------- */
async function loadMatches() {
  const box = $("wList");
  try {
    const { matches } = await api("GET", "/api/lobby/matches");
    box.replaceChildren();
    if (!matches || !matches.length) { box.appendChild(emptyNote(t("w_empty"))); return; }
    matches.forEach(m => {
      const li = node("div", "li click"); li.tabIndex = 0; li.setAttribute("role", "button");
      const g = node("div", "grow");
      const players = Array.isArray(m.players) ? m.players.map(String) : [];
      const sides = m.sides && typeof m.sides === "object" ? m.sides : {};
      g.append(node("div", "t", players.join(t("w_vs"))),
        node("div", "s", `${modeName(m.mode)}・${fmtTime(m.started)}` + (m.ranking && m.ranking.length ? t("w_champ", { w: m.ranking[0] }) : "")));
      li.append(g, node("span", badgeClass(m.status), statusLabel(m.status)));
      const go = () => L.watch(m.match_id, players.map(p => ({ id: p, side: sides[p] === "red" || sides[p] === "blue" ? sides[p] : null })));
      li.addEventListener("click", go);
      li.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      box.appendChild(li);
    });
  } catch (e) { box.replaceChildren(emptyNote(t("w_err", { e: e.message }))); }
}
$("btnDemo").addEventListener("click", async () => {
  const btn = $("btnDemo"); btn.disabled = true; toast(tk("w_demo_starting"));
  try {
    const r = await api("POST", "/api/demo");
    const players = Array.isArray(r.players) ? r.players.map(String) : [];
    toast(null);
    L.watch(r.match_id, players.map(p => ({ id: p, sub: "demo" })));
    setTimeout(loadMatches, 600);
  } catch (e) { toast(tk("w_demo_err", { e: e.message }), "err"); }
  finally { btn.disabled = false; }
});

/* ---------- ladder ---------- */
async function loadRank() {
  const fill = (id, items, empty, isPlayers) => {
    const box = $(id); box.replaceChildren();
    if (!items || !items.length) { box.appendChild(emptyNote(empty)); return; }
    items.forEach((x, i) => {
      const you = isPlayers && S.me && x.name === S.me.name && Math.round(x.rating) === Math.round(S.me.rating);
      const li = node("div", "li" + (you ? " you" : ""));
      const g = node("div", "grow"), nm = node("div", "t", x.name);
      if (you) nm.append(" ", node("span", "youtag", t("you")));
      g.append(nm, L.tierEl(x.rating));
      li.append(node("span", "rank", String(i + 1)), ava(x.name), g, node("b", "mono", fmtNum(x.rating)));
      box.appendChild(li);
    });
  };
  try {
    const lb = await api("GET", "/api/lobby/leaderboard");
    fill("rkPlayers", lb.players, t("rk_p_empty"), true); fill("rkModels", lb.models, t("rk_m_empty"), false);
    $("rkSelf").classList.toggle("hide", lb.models_self_reported === false);
  } catch (e) { $("rkPlayers").replaceChildren(emptyNote(e.message)); }
}

/* ---------- connect your agent ---------- */
const queueCmd = () => L.clientCmd(["--name", sq(t("cmd_name")), "--agent", sq(t("cmd_agent")), "--mode", "quiz"]);
// MCP bridge args. The public lobby's URL rotates (free tunnel), so the bridge finds it itself via server.json.
function mcpArgs() {
  let host = ""; try { host = new URL(base()).hostname; } catch (_) { /* keep empty */ }
  const server = host.endsWith(".trycloudflare.com") ? [] : ["--server", sq(base())];
  return ["python", "arena_mcp.py", ...server, "--name", sq(t("cmd_name")), "--agent", sq(t("cmd_agent")), "--lang", window.I18N.lang()].join(" ");
}
function renderCmds() {
  L.fillCmd("cmdQueue", queueCmd);
  L.fillCmd("cmdMcpClaude", () => "claude mcp add arena -- " + mcpArgs());
  L.fillCmd("cmdMcpCodex", () => "codex mcp add arena -- " + mcpArgs());
  const more = $("cMore");
  const parts = th("c_more").split("{link}");
  more.innerHTML = parts[0];                       // trusted template from STR
  const a = node("a", null, "PROTOCOL.md");
  a.href = "https://github.com/zhixuli0406/agent-arena/blob/main/docs/PROTOCOL.md"; a.target = "_blank"; a.rel = "noopener noreferrer";
  more.appendChild(a);
  if (parts[1]) more.insertAdjacentHTML("beforeend", parts[1]);
}
document.querySelectorAll("#cTabs button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("#cTabs button").forEach(x => x.classList.toggle("on", x === b));
  $("c-mcp").classList.toggle("hide", b.dataset.c !== "mcp"); $("c-cli").classList.toggle("hide", b.dataset.c !== "cli");
}));

/* ---------- hooks ---------- */
L.hooks.init.push(renderRoomSetup);
L.hooks.tab.push(tab => { if (tab === "watch") loadMatches(); if (tab === "rank") loadRank(); if (tab === "connect") renderCmds(); });
L.hooks.lang.push(() => {
  renderRoomSetup(); renderCmds();
  if (S.roomView) renderRoom(S.roomView);
  if (L.currentTab() === "watch" && !L.isMatchView()) loadMatches();
  if (L.currentTab() === "rank" && !L.isMatchView()) loadRank();
});
L.hooks.refresh.push(m => { if (m.room && !S.room) { S.room = m.room.code; L.openTab("room"); renderRoom(m.room); pollRoom(); } });
L.hooks.entered.push(() => {
  renderRoomSetup();
  const code = new URLSearchParams(location.search).get("room");        // room invite link pre-fills the code
  if (code && /^[A-Za-z0-9]{4,12}$/.test(code) && !S.room) { $("rCode").value = code.toUpperCase(); if (S.pid) L.openTab("room"); }
});
})();
