/* Match view: your agent plays the seat (it gets the token over its standby stream, never the page),
 * live scoreboard, team versus bar, and the post-match screen (victory/defeat/draw, rating change, play again). */
(function () {
"use strict";
const L = window.LOBBY;
const { S, t, th, fmtNum, $, node, ava, modeName, statusLabel, badgeClass, fmtPts, base, enc } = L;
const { MATCH_RE } = window.ARENA;
let live = false;                  // my own match is still running

/* ---------- seat ---------- */
function setRanked(ranked) {
  S.seatRanked = ranked;
  const e = $("mRanked"); e.className = "tag " + (ranked ? "ranked" : "unranked"); e.textContent = t(ranked ? "r_ranked" : "r_unranked");
}
function renderSeatAgent() {
  const on = !!S.agentOnline;
  $("seatDot").className = "dot " + (on ? "on" : "off");
  $("seatAgentText").textContent = t(on ? "seat_on" : "seat_off");
  $("seatCard").classList.toggle("warn", !on);
}
L.seat = (match, players, ranked) => {
  S.match = match; live = true;
  S.ratingBefore = S.me ? Number(S.me.rating) : null;
  $("matchPanel").classList.remove("hide"); $("result").classList.add("hide"); $("resDelta").classList.add("hide");
  setRanked(ranked !== false);
  renderSeatAgent();
  watch(match, players, true);
  L.showMatchView();
};
L.matchLive = () => live && !!S.match;

/* ---------- scoreboard ---------- */
let bES = null, B = {}, bMatch = null, bMode = null, bResult = null, bTeams = null, myId = null, mySide = null, own = false, celebrated = false;
function watch(match, players, mine) {
  if (!MATCH_RE.test(String(match || ""))) return;
  if (bES) bES.close();
  B = {}; bMatch = match; bMode = null; bResult = null; bTeams = null; myId = null; mySide = null; own = !!mine; celebrated = false;
  $("bWin").classList.add("hide"); $("bFeed").replaceChildren(); $("bRows").replaceChildren();
  $("versus").classList.add("hide"); $("vsRedScore").textContent = "0"; $("vsBlueScore").textContent = "0";
  $("result").classList.add("hide");
  document.querySelector(".match").classList.toggle("spectate", !own);
  if (!own) { $("matchPanel").classList.add("hide"); }
  setBadge("RUNNING"); $("bMeta").textContent = match;
  (players || []).forEach(p => row(p.id, p.sub, p.side));
  if (window.FX) { window.FX.mode("match"); window.FX.team(false); }
  bES = new EventSource(`${base()}/api/matches/${enc(match)}/stream?lang=${enc(window.I18N.lang())}`);
  bES.onmessage = e => { let ev; try { ev = JSON.parse(e.data); } catch (_) { return; } if (ev) onEvent(ev); };
  bES.addEventListener("end", () => bES.close());
  bES.onerror = () => { if (bES && bES.readyState === EventSource.CLOSED) bES = null; };
}
L.watch = (match, players) => { watch(match, players, false); L.showMatchView(); };
const sideName = side => t(side === "red" ? "side_red" : side === "blue" ? "side_blue" : "b_over");
function row(id, sub, side) {
  if (B[id]) { if (side && !B[id].side) markSide(B[id], side); return B[id]; }
  const r = node("div", "contest"); r.appendChild(ava(id));
  const m = node("div", "cmeta"), name = node("div", "cname", id), s = node("div", "csub", sub || "");
  const bar = node("div", "bar"), bi = node("i"); bar.appendChild(bi);
  m.append(name, s, bar);
  const p = node("div", "pts", "0"); r.append(m, p); $("bRows").appendChild(r);
  B[id] = { bar: bi, pts: p, val: 0, sub: s, node: r, name, correct: 0 };
  if (side) markSide(B[id], side);
  return B[id];
}
function markSide(c, side) {
  c.side = side; c.node.classList.add("side-" + side);
  c.name.prepend(node("span", "sidetag " + side, sideName(side)));
  $("versus").classList.remove("hide");
  if (window.FX) window.FX.team(true);
}
function markMe(id) {
  const c = B[id]; if (!c || c.node.classList.contains("me")) return;
  c.node.classList.add("me"); c.name.appendChild(node("span", "youtag", t("you")));
}
function redraw() {
  const max = Math.max(1, ...Object.values(B).map(x => x.val));
  let red = 0, blue = 0;
  for (const k in B) {
    B[k].bar.style.width = Math.round(B[k].val / max * 100) + "%"; B[k].pts.textContent = fmtPts(B[k].val);
    if (B[k].side === "red") red += B[k].val; if (B[k].side === "blue") blue += B[k].val;
  }
  $("vsRedScore").textContent = fmtPts(red); $("vsBlueScore").textContent = fmtPts(blue);
}
function feedNode(d) {
  const host = $("bFeed"); host.prepend(d);
  while (host.children.length > 80) host.lastElementChild.remove();
}
function feed(html) { const d = node("div"); d.innerHTML = html; feedNode(d); }
function feedThought(ev) {
  // public_summary arrives as plain text in a commentary event; never promote it to trusted HTML.
  const publicSummary = String((ev.data || {}).text || "").trim().slice(0, 280);
  if (!publicSummary) return;
  const thought = node("article", "thought");
  const head = node("div", "thought-head");
  const agent = node("span", "thought-agent"); agent.textContent = String(ev.agent || "").slice(0, 80);
  const label = node("span", "thought-label"); label.textContent = t("f_thought", { n: ev.round || "–" });
  const summary = node("p", "thought-summary"); summary.textContent = publicSummary;
  head.append(agent, label); thought.append(head, summary); feedNode(thought);
}
function setBadge(s) { const b = $("bStatus"); b.className = badgeClass(s); b.dataset.s = s; b.textContent = statusLabel(s); }
function renderMeta() { if (bMatch) $("bMeta").textContent = bMode ? `${bMatch}・${modeName(bMode)}` : bMatch; }
function onEvent(ev) {
  if (ev.type === "match_start") {
    const d = ev.data || {};
    (d.agents || []).forEach(a => {
      const side = a.team === "red" || a.team === "blue" ? a.team : null;
      row(a.id, a.model, side);
      if (own && S.pid && a.prompt_author === S.pid) { myId = a.id; mySide = side; markMe(a.id); }
    });
    bMode = d.mode; renderMeta();
  } else if (ev.type === "teams") { bTeams = ev.data || null; renderWin(); renderResult(); }
  else if (ev.type === "commentary") feedThought(ev);
  else if (ev.type === "action") { if (bMode !== "ctf") feed(th("f_act", { a: ev.agent })); }
  else if (ev.type === "request") {
    const d = ev.data || {}; feed(th("f_ctf_req", { a: ev.agent, m: d.method || "HTTP", s: d.status == null ? "?" : d.status }));
  } else if (ev.type === "solve") feed(th("f_ctf_solve", { a: ev.agent }));
  else if (ev.type === "submit_wrong") feed(th("f_ctf_wrong", { a: ev.agent }));
  else if (ev.type === "grade") {
    const d = ev.data || {}; const ok = d.correct || d.ok;
    const p = Number(d.points), pts = Number.isFinite(p) && p >= 0 && p <= 10 ? Math.round(p * 100) / 100 : 1;
    const sec = Number(d.seconds), c = row(ev.agent);
    if (ok && Number.isFinite(sec)) {
      feed(th("f_ok_b", { a: ev.agent, n: ev.round, s: fmtNum(Math.round(sec * 10) / 10), b: fmtPts(Math.max(0, pts - 1)) }));
    } else feed(th(ok ? "f_ok" : "f_bad", { a: ev.agent, n: ev.round }));
    if (ok) {
      c.val += pts; c.correct += 1; redraw();
      c.node.classList.add("hit"); setTimeout(() => c.node.classList.remove("hit"), 600);
      if (window.FX) window.FX.burstAt(c.pts, { color: c.side || (ev.agent === myId ? "signal" : "good"), count: ev.agent === myId ? 46 : 18, speed: 280, size: 6 });
    }
  } else if (ev.type === "agent_error") feed(th("f_err", { a: ev.agent }));
  else if (ev.type === "result") finish(ev.data || {});
}
function renderWin() {
  if (!bResult) return;
  if (bTeams && Array.isArray(bTeams.team_ranking) && bTeams.team_ranking.length) {
    const sc = bTeams.team_scores || {}, [a, b] = bTeams.team_ranking;
    const draw = b != null && Number(sc[a]) === Number(sc[b]);
    const totals = ["red", "blue"].filter(k => k in sc).map(k => `${sideName(k)} ${fmtPts(sc[k])}`).join(" · ");
    $("bWin").textContent = (draw ? t("b_draw_team") : t("b_win_team", { w: sideName(a) })) + (totals ? `（${totals}）` : "");
    return;
  }
  const rank = bResult.ranking || [];
  $("bWin").textContent = rank.length ? t("b_win", { w: rank[0] }) : t("b_over");
}
function finish(d) {
  bResult = d; setBadge(d.status || "COMPLETE");
  const scores = d.scores || {};
  for (const id in scores) row(id).val = Number(scores[id]) || 0;
  redraw();
  $("bWin").classList.remove("hide"); renderWin();
  if (own) live = false;
  renderResult();
  if (S.pid) setTimeout(() => L.refreshMe().then(renderDelta).catch(() => {}), 900);
}

/* ---------- post-match screen ---------- */
function winner() {
  if (bTeams && Array.isArray(bTeams.team_ranking) && bTeams.team_ranking.length) {
    const sc = bTeams.team_scores || {}, [a, b] = bTeams.team_ranking;
    return b != null && Number(sc[a]) === Number(sc[b]) ? null : sideName(a);
  }
  const rank = bResult && Array.isArray(bResult.ranking) ? bResult.ranking : [];
  if (!rank.length) return null;
  const scores = bResult.scores || {}, top = Number(scores[rank[0]]);
  return rank.length > 1 && Number(scores[rank[1]]) === top ? null : rank[0];
}
function renderPodium() {
  const host = $("resPodium"); host.replaceChildren();
  let ranking = [], scores = {}, members = null;
  if (bTeams && Array.isArray(bTeams.team_ranking)) {
    ranking = bTeams.team_ranking; scores = bTeams.team_scores || {}; members = bTeams.members || {};
  } else if (bResult) { ranking = bResult.ranking || []; scores = bResult.scores || {}; }
  ranking.slice(0, 4).forEach((id, i) => {
    const li = node("li", i === 0 ? "first" : "");
    const rank = node("span", "podium-rank", String(i + 1).padStart(2, "0"));
    const who = node("span", "podium-name"); who.textContent = members ? sideName(id) : id;
    if (members && Array.isArray(members[id])) {
      const sub = node("small", "podium-members"); sub.textContent = members[id].join(" · "); who.appendChild(sub);
    }
    const score = node("span", "podium-score", fmtPts(Number(scores[id]) || 0));
    li.append(rank, who, score); host.appendChild(li);
  });
}
function outcome() {
  if (!bResult) return null;
  if (bTeams && mySide && Array.isArray(bTeams.team_ranking)) {
    const sc = bTeams.team_scores || {}, [a, b] = bTeams.team_ranking;
    if (b != null && Number(sc[a]) === Number(sc[b])) return "draw";
    return a === mySide ? "win" : "loss";
  }
  if (!myId) return null;
  const scores = bResult.scores || {}, top = Math.max(...Object.values(scores).map(Number));
  const leaders = Object.keys(scores).filter(k => Number(scores[k]) === top);
  if (!leaders.includes(myId)) return "loss";
  return leaders.length > 1 ? "draw" : "win";
}
function renderResult() {
  if (!bResult) return;
  const box = $("result"), o = own ? outcome() : null;
  const entering = box.classList.contains("hide");
  box.className = "result " + (o || "spec");
  $("resKicker").textContent = !own ? t("res_k_spec") : t(S.seatRanked ? "res_k_ranked" : "res_k_unranked");
  const victor = winner();
  $("resTitle").textContent = t(o ? "res_" + o : victor ? "res_victor" : "res_draw");
  $("resChampion").textContent = victor || t("res_no_winner");
  $("resMoment").textContent = victor ? t("res_moment", { w: victor }) : t("res_moment_draw");
  $("resSub").textContent = $("bWin").textContent;
  $("btnAgain").classList.toggle("hide", !own);
  const mine = own && myId && B[myId];
  $("resMine").textContent = mine ? t("res_me", { c: fmtNum(mine.correct), p: fmtPts(mine.val) }) : "";
  if (own) {                                  // the question card has nothing left to do: give the board the room
    $("matchPanel").classList.add("hide"); document.querySelector(".match").classList.add("spectate");
  }
  renderPodium();
  if (entering) {
    void box.offsetWidth;
    box.classList.add("reveal");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else box.classList.add("revealed");
  if (window.FX && !celebrated) {
    celebrated = true;
    const scene = o === "loss" ? "loss" : victor ? "win" : "match";
    if (window.FX.ceremony) window.FX.ceremony(scene); else window.FX.mode(scene);
  }
}
function renderDelta(me) {
  const el = $("resDelta");
  if (!own || !me || !me.player || S.ratingBefore == null || !S.seatRanked) { el.classList.add("hide"); return; }
  const delta = Math.round(Number(me.player.rating) - S.ratingBefore);
  el.className = "delta " + (delta > 0 ? "up" : delta < 0 ? "down" : "");
  const from = Math.round(S.ratingBefore), sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const start = performance.now(), dur = 900;
  const step = now => {                                   // count the rating up/down like a scoreboard
    const k = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - k, 4);
    $("resDeltaN").textContent = `${sign}${Math.abs(Math.round(delta * e))}`;
    $("resRating").textContent = t("res_rating", { r: fmtNum(Math.round(from + delta * e)) });
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
$("btnAgain").addEventListener("click", () => { leaveMatch(); L.requeue(); });
$("btnLobby").addEventListener("click", () => { leaveMatch(); L.openTab(S.pid ? "quick" : "watch"); });
function leaveMatch() {
  S.match = null; live = false;
  if (bES) { bES.close(); bES = null; }
  $("matchPanel").classList.add("hide"); $("result").classList.add("hide"); $("resDelta").classList.add("hide");
  document.querySelector(".match").classList.remove("spectate");
  if (window.FX) { window.FX.mode("idle"); window.FX.team(false); }
}

/* ---------- hooks ---------- */
L.hooks.lang.push(() => {
  if (S.seatRanked != null) setRanked(S.seatRanked);
  if (S.match) renderSeatAgent();
  const bs = $("bStatus"); if (bs.dataset.s) setBadge(bs.dataset.s);
  renderMeta(); renderWin(); if (bResult) renderResult();
});
L.hooks.agent.push(() => { if (S.match) renderSeatAgent(); });
})();
