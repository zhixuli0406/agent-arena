/* Play screen: game type + format, party rail, persistent queue dock, ready check, cooldown. */
(function () {
"use strict";
const L = window.LOBBY;
const { S, t, th, fmtNum, $, node, ava, mmss, modeName, api, enc, tk, say, toast, copy } = L;
const MODES = {
  quiz: ["m_quiz", "m_quiz_d", "?"],
  task: ["m_task", "m_task_d", "{}"],
  ctf: ["m_ctf", "m_ctf_d", "⚑"],
};
const SIZES = { 2: "s_2", 3: "s_3", 4: "s_4" };
const FORMATS = { ffa: ["f_ffa", "f_ffa_d"], "2v2": ["f_2v2", "f_2v2_d"], "3v3": ["f_3v3", "f_3v3_d"] };
const inParty = () => !!(S.party && S.party.members && S.party.members.length > 1);
const isFollower = () => inParty() && S.party.leader !== S.pid;
let cooldownUntil = 0, cdTimer = 0;

/* ---------- selection ---------- */
const fmtLabel = (fmt, size) => (fmt === "ffa" ? t(SIZES[size] || "s_2") : t(FORMATS[fmt][0]));
const summary = () => `${modeName(S.mode)} · ${fmtLabel(S.fmt, S.size)}`;
function renderQuick() {
  const m = $("qModes"); m.replaceChildren();
  for (const k in MODES) {
    const b = node("button", "choice" + (k === S.mode ? " sel" : "")); b.type = "button";
    b.setAttribute("aria-pressed", String(k === S.mode));
    b.append(node("div", "art", MODES[k][2]), node("div", "t", t(MODES[k][0])), node("div", "d", t(MODES[k][1])));
    b.addEventListener("click", () => { S.mode = k; renderQuick(); });
    m.appendChild(b);
  }
  if (inParty() && S.fmt === "ffa") S.fmt = "2v2";            // parties can only queue team formats
  const f = $("qFormats"); f.replaceChildren();
  for (const k in FORMATS) {
    const b = node("button", k === S.fmt ? "on" : ""); b.type = "button";
    b.append(node("b", null, t(FORMATS[k][0])), node("span", null, t(FORMATS[k][1])));
    b.disabled = k === "ffa" && inParty();
    if (b.disabled) b.title = t("p_ffa_locked");
    b.setAttribute("aria-pressed", String(k === S.fmt));
    b.addEventListener("click", () => { S.fmt = k; renderQuick(); });
    f.appendChild(b);
  }
  $("qSizeBox").classList.toggle("hide", S.fmt !== "ffa");
  const z = $("qSizes"); z.replaceChildren();
  for (const k in SIZES) {
    const b = node("button", +k === S.size ? "on" : "", t(SIZES[k])); b.type = "button";
    b.addEventListener("click", () => { S.size = +k; renderQuick(); });
    z.appendChild(b);
  }
  $("qSummary").textContent = summary();
  $("qFmtHelp").textContent = S.fmt === "ffa" ? "" : t("q_fmt_team");
  renderQueueButton();
}
function renderQueueButton() {
  const b = $("btnQueue"), left = Math.ceil((cooldownUntil - Date.now()) / 1000);
  if (left > 0) { b.disabled = true; b.textContent = t("btn_cooldown", { t: mmss(left) }); return; }
  if (S.pid && !S.agentOnline) { b.disabled = true; b.textContent = t("btn_need_agent"); return; }   // own agent required
  if (isFollower()) { b.disabled = true; b.textContent = t("btn_wait_leader"); return; }
  b.disabled = !!(S.ticket && ["searching", "ready_check"].includes(S.ticket.status));
  b.textContent = t("btn_queue");
}
function startCooldown(sec) {
  cooldownUntil = Date.now() + Math.max(0, Number(sec) || 0) * 1000;
  clearInterval(cdTimer);
  cdTimer = setInterval(() => { renderQueueButton(); if (Date.now() >= cooldownUntil) clearInterval(cdTimer); }, 500);
  renderQueueButton();
}

/* ---------- party rail ---------- */
let pPoll = null;
const partyPath = suffix => `/api/lobby/parties/${enc(S.party.code)}${suffix || ""}`;
function inviteLink(code) {
  const u = new URL(location.href); u.hash = "";
  ["party", "room", "match"].forEach(k => u.searchParams.delete(k));
  u.searchParams.set("party", code); u.searchParams.set("lang", window.I18N.lang());
  return u.toString();
}
function renderParty(v) {
  S.party = v;
  $("pNone").classList.toggle("hide", !!v); $("pIn").classList.toggle("hide", !v);
  $("pCount").textContent = v ? `${v.members.length}/${v.max}` : "";
  if (!v) { clearInterval(pPoll); renderQuick(); return; }
  $("pCodeShow").textContent = v.code;
  $("pCopy").replaceChildren(L.copyBtn(() => v.code, "copied"), linkBtn(v.code));
  const box = $("pMembers"); box.replaceChildren();
  for (const m of v.members) {
    const row = node("div", "prow"); row.appendChild(ava(m.name));
    const nm = node("div", "pn", m.name);
    if (m.leader) nm.appendChild(node("span", "crown", "♛ " + t("p_leader")));
    row.append(nm, node("div", "pr", fmtNum(m.rating)));
    if (v.leader === S.pid && m.id !== S.pid) {
      const k = node("button", "kick", t("p_kick")); k.type = "button";
      k.addEventListener("click", async () => { try { renderParty(await api("POST", partyPath("/kick"), { player_id: m.id })); } catch (e) { say("pMsg", e.message, 1); } });
      row.appendChild(k);
    }
    box.appendChild(row);
  }
  const slots = $("pSlots"); slots.replaceChildren();
  for (let i = v.members.length; i < v.max; i++) {
    const s = node("button", "pslot", t("p_invite")); s.type = "button";
    s.addEventListener("click", () => copy(inviteLink(v.code), "p_link_copied"));
    slots.appendChild(s);
  }
  $("pHint").textContent = v.leader === S.pid ? t("p_hint_leader", { n: v.max }) : t("p_hint_member");
  renderQuick();
  // members follow the party's ticket: it shows up as soon as the leader queues
  if (v.ticket_id && !S.ticket) { S.ticket = { ticket_id: v.ticket_id, status: "searching" }; pollTicket(); }
}
function linkBtn(code) {
  const b = node("button", "btn ghost sm", t("p_copy_link")); b.type = "button";
  b.addEventListener("click", () => copy(inviteLink(code), "p_link_copied")); return b;
}
function pollParty() {
  clearInterval(pPoll);
  pPoll = setInterval(async () => {
    if (!S.party) { clearInterval(pPoll); return; }
    try { renderParty(await api("GET", partyPath())); }
    catch (e) { if (e.status === 403 || e.status === 404) { renderParty(null); say("pMsg", tk("p_gone"), 1); } }
  }, 2000);
}
$("btnPartyCreate").addEventListener("click", async () => {
  say("pMsg", ""); if (!L.needPlayer("pMsg")) return;
  try { renderParty(await api("POST", "/api/lobby/parties")); pollParty(); } catch (e) { say("pMsg", e.message, 1); }
});
async function joinParty() {
  say("pMsg", ""); if (!L.needPlayer("pMsg")) return;
  const code = $("pCode").value.trim().toUpperCase();
  if (!/^[A-Z0-9]+$/.test(code)) { say("pMsg", tk("r_codelen", { n: S.codeLen }), 1); return; }
  try { renderParty(await api("POST", `/api/lobby/parties/${enc(code)}/join`)); pollParty(); say("pMsg", ""); }
  catch (e) { say("pMsg", e.message, 1); }
}
$("btnPartyJoin").addEventListener("click", joinParty);
$("pCode").addEventListener("keydown", e => { if (e.key === "Enter") joinParty(); });
$("btnPartyLeave").addEventListener("click", async () => {
  if (!S.party) return;
  try { await api("POST", partyPath("/leave")); }
  catch (e) { if (e.status === 409) { say("pMsg", e.message, 1); return; } }   // e.g. can't leave during a ready check
  renderParty(null); say("pMsg", tk("p_left"));
});

/* ---------- queue + persistent dock ---------- */
let tPoll = null, tickClock = null, searchBase = 0, searchAt = 0, tPause = 0;
const ticketPath = suffix => `/api/lobby/tickets/${enc(S.ticket.ticket_id)}${suffix || ""}`;
$("btnQueue").addEventListener("click", async () => {
  if (!L.needPlayer("qMsg")) return;
  try {
    S.lastQueue = { mode: S.mode, size: S.size, format: S.fmt };
    S.ticket = await api("POST", "/api/lobby/queue", S.lastQueue); renderTicket(S.ticket); pollTicket();
  } catch (e) { toast(e.message, "err"); }
});
L.requeue = async () => {                                   // "Play again" from the result screen
  if (S.lastQueue && !isFollower()) {
    S.mode = S.lastQueue.mode; S.size = S.lastQueue.size; S.fmt = S.lastQueue.format;
    L.openTab("quick"); renderQuick();
    if (!$("btnQueue").disabled) $("btnQueue").click();
  } else L.openTab("quick");
};
$("btnCancel").addEventListener("click", async () => { if (!S.ticket) return; try { renderTicket(await api("POST", ticketPath("/cancel"))); } catch (e) { toast(e.message, "err"); } });
$("btnAccept").addEventListener("click", async () => {
  if (!S.ticket) return; $("btnAccept").disabled = true;
  try { renderTicket(await api("POST", ticketPath("/accept"))); } catch (e) { $("btnAccept").disabled = false; toast(e.message, "err"); }
});
$("btnDecline").addEventListener("click", async () => { if (!S.ticket) return; try { renderTicket(await api("POST", ticketPath("/decline"))); } catch (e) { toast(e.message, "err"); } });
function pollTicket() {
  clearInterval(tPoll);
  tPoll = setInterval(async () => {
    if (!S.ticket) { clearInterval(tPoll); return; }
    if (Date.now() < tPause) return;                       // backing off after 429
    try { renderTicket(await api("GET", ticketPath())); }
    catch (e) { if (e.status === 429) { tPause = Date.now() + e.retryAfter * 1000; return; } toast(e.message, "err"); }
  }, 1000);
}
function renderSearchFacts(v) {
  $("qIn").innerHTML = th("q_in", { n: fmtNum(v.in_queue) });
  $("qWin").innerHTML = th("q_win", { n: fmtNum(v.window) });
  // only a recent average: an "estimate" that is often wrong is worse than none
  $("qAvg").innerHTML = v.avg_wait != null ? th("q_avg", { t: mmss(v.avg_wait) }) : "";
}
function dockMode(v) {
  const fmt = v.format || "ffa";
  return `${modeName(v.mode || S.mode)} · ${fmtLabel(fmt, v.size || S.size)}` + (v.members && v.members.length > 1 ? " · " + t("p_party_n", { n: v.members.length }) : "");
}
function renderTicket(v) {
  const prev = S.ticket && S.ticket.status;
  S.ticket = v;
  const searching = v.status === "searching", ready = v.status === "ready_check";
  $("qSearch").classList.toggle("hide", !(searching || ready));
  if (searching || ready) {
    $("qbLabel").textContent = t(ready ? "q_found" : "q_searching");
    $("qbMode").textContent = dockMode(v);
    if (window.FX) window.FX.mode(ready ? "found" : "search");
  }
  if (searching) {
    searchBase = Number(v.waited) || 0; searchAt = performance.now(); renderSearchFacts(v);
    if (!tickClock) tickClock = setInterval(() => { $("qTimer").textContent = mmss(searchBase + (performance.now() - searchAt) / 1000); }, 250);
  }
  if (ready && v.ready) { renderReady(v.ready, prev !== "ready_check"); } else { $("readyVeil").classList.add("hide"); L.stopFlash(); }
  if (v.status === "confirmed") {
    stopTicket();
    L.seat(v.match_id, (S.lastPlayers || []).map(p => ({ id: p.name, sub: p.agent, side: p.side })), v.ranked !== false);
  }
  if (v.status === "declined") { stopTicket(); toast(tk("q_declined", { n: v.cooldown }), "err"); startCooldown(v.cooldown); }
  if (v.status === "cancelled") { stopTicket(); toast(tk("q_cancelled")); }
  renderQueueButton();
}
function stopTicket() {
  clearInterval(tPoll); clearInterval(tickClock); tickClock = null; S.ticket = null;
  $("readyVeil").classList.add("hide"); $("qSearch").classList.add("hide"); $("btnAccept").disabled = false;
  L.stopFlash();
  if (window.FX && !L.matchLive()) window.FX.mode("idle");
}
function renderReady(r, first) {
  S.lastPlayers = r.players; S.lastReady = r;
  $("readyVeil").classList.remove("hide");
  if (first) {
    L.beep([[523, 0.14], [784, 0.14], [1046, 0.3]]);
    L.flashTitle("doc_found");
    if (window.FX) window.FX.burstAt($("rcTitle"), { color: "signal", count: 90, speed: 520 });
    $("btnAccept").focus();
  }
  $("rcMode").textContent = S.ticket ? dockMode(S.ticket) : "";
  const left = Number(r.deadline_in) || 0; $("ringNum").textContent = Math.ceil(left);
  $("ringArc").style.strokeDashoffset = String(263.9 * (1 - Math.max(0, left) / 15));
  $("readyCount").textContent = t("rc_count", { a: r.accepted, t: r.total }) + (r.you_accepted ? t("rc_wait") : "");
  const pips = $("rcPips"); pips.replaceChildren();
  for (let i = 0; i < r.total; i++) pips.appendChild(node("i", i < r.accepted ? "y" : ""));
  $("btnAccept").disabled = !!r.you_accepted; $("btnAccept").textContent = r.you_accepted ? t("btn_accepted") : t("btn_accept");
  const box = $("readyPlayers"); box.replaceChildren();
  const players = (r.players || []).slice();
  if (r.your_side) players.sort((a, b) => (b.side === r.your_side) - (a.side === r.your_side));   // my side first
  players.forEach(p => {
    const row = node("div", "prow" + (p.side ? " side-" + p.side : "")); row.appendChild(ava(p.name));
    row.append(node("div", "pn", p.name + (p.agent ? "　·　" + p.agent : "")));
    if (p.side) row.appendChild(node("span", "sidetag " + p.side, t(p.side === r.your_side ? "rc_us" : "rc_them")));
    row.appendChild(node("div", "pr", fmtNum(p.rating)));
    box.appendChild(row);
  });
}

/* ---------- hooks ---------- */
L.hooks.init.push(renderQuick);
L.hooks.agent.push(renderQueueButton);
L.hooks.lang.push(() => {
  renderQuick();
  if (S.party) renderParty(S.party);
  if (S.lastReady && !$("readyVeil").classList.contains("hide")) renderReady(S.lastReady, false);
  if (S.ticket && S.ticket.status === "searching") { renderSearchFacts(S.ticket); $("qbLabel").textContent = t("q_searching"); $("qbMode").textContent = dockMode(S.ticket); }
});
L.hooks.refresh.push(m => {
  if (m.ticket && !S.ticket) { S.ticket = m.ticket; renderTicket(m.ticket); pollTicket(); }
  if (m.party && !S.party) { renderParty(m.party); pollParty(); }
});
L.hooks.entered.push(() => {
  // invite link: ?party=CODE pre-fills the join box (joining is still the player's click)
  const code = new URLSearchParams(location.search).get("party");
  if (code && /^[A-Za-z0-9]{4,12}$/.test(code) && !S.party) {
    $("pCode").value = code.toUpperCase();
    if (S.pid) toast(tk("p_from_link", { c: code.toUpperCase() }));
  }
});
})();
