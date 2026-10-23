/* Match view: seat (agent command or answer in the browser), per-question timer, live scoreboard,
 * team versus bar, and the post-match screen (victory/defeat/draw, rating change, play again). */
(function () {
"use strict";
const L = window.LOBBY;
const { S, t, th, fmtNum, $, node, ava, modeName, statusLabel, badgeClass, fmtPts, api, base, enc, tk, say } = L;
const { MATCH_RE, sq } = window.ARENA;
const STEP_SECONDS = 120;          // server-side limit per question
let live = false;                  // my own match is still running

/* ---------- agent commands (also used by the connect panel) ---------- */
function clientCmd(args) {
  return ["python", "arena_connect.py", "--server", sq(base()), ...args, "--lang", window.I18N.lang(), "--cmd", sq("claude -p")].join(" ");
}
L.clientCmd = clientCmd;
const tokenCmd = () => clientCmd(["--token", sq(S.token)]);
L.fillCmd = (id, get) => { $(id).replaceChildren(document.createTextNode(get()), L.copyBtn(get)); };

/* ---------- seat ---------- */
function setRanked(ranked) {
  S.seatRanked = ranked;
  const e = $("mRanked"); e.className = "tag " + (ranked ? "ranked" : "unranked"); e.textContent = t(ranked ? "r_ranked" : "r_unranked");
}
L.seat = (token, match, players, ranked) => {
  S.token = token; S.match = match; live = true;
  S.ratingBefore = S.me ? Number(S.me.rating) : null;
  $("matchPanel").classList.remove("hide"); $("result").classList.add("hide"); $("resDelta").classList.add("hide");
  resetHuman();
  setRanked(ranked !== false);
  L.fillCmd("cmdToken", tokenCmd);
  watch(match, players, true);
  L.showMatchView();
};
L.matchLive = () => live && !!S.match;

/* ---------- answering in the browser ---------- */
let hES = null, answered = new Set(), curRound = null, hOver = false, hPhase = "pick", qAt = 0, qTimer = 0;
function resetHuman() {
  if (hES) { hES.close(); hES = null; }
  answered = new Set(); curRound = null; hOver = false; hPhase = "pick"; stopTimer();
  $("hRound").textContent = t("h_pick"); $("hQ").textContent = ""; $("hRow").classList.add("hide");
  $("hChoose").classList.remove("hide"); $("agentBox").open = false;
}
function startTimer() {
  stopTimer(); qAt = performance.now(); $("hTimer").classList.remove("hide");
  const tickT = () => {
    const left = Math.max(0, STEP_SECONDS - (performance.now() - qAt) / 1000);
    const low = left <= 15;
    $("hTimer").querySelector("i").style.transform = `scaleX(${left / STEP_SECONDS})`;
    $("hTimer").classList.toggle("low", low);
    $("hTimeTxt").textContent = t("h_time", { s: Math.ceil(left) }); $("hTimeTxt").classList.toggle("low", low);
  };
  tickT(); qTimer = setInterval(tickT, 1000);
}
function stopTimer() { clearInterval(qTimer); $("hTimer").classList.add("hide"); $("hTimeTxt").textContent = ""; }
function openHumanStream() {
  if (hES) hES.close();
  hES = new EventSource(`${base()}/api/connect/${enc(S.token)}/stream?lang=${enc(window.I18N.lang())}`);
  hES.onmessage = e => {
    let o; try { o = JSON.parse(e.data); } catch (_) { return; }
    if (!o || answered.has(o.round)) return;
    curRound = o.round; hPhase = "q";
    $("hRound").textContent = t("h_round", { n: o.round });
    $("hQ").textContent = (o.instructions ? o.instructions + "\n\n" : "") + (o.task || "");
    $("hRow").classList.remove("hide"); $("hAns").value = ""; $("hAns").focus();
    startTimer();
  };
  hES.addEventListener("end", () => {
    hOver = true; hPhase = "end"; hES.close(); hES = null; stopTimer();
    $("hRound").textContent = t("h_end"); $("hQ").textContent = t("h_end2"); $("hRow").classList.add("hide");
  });
  hES.onerror = () => { if (!hOver) say("mMsg", tk("h_unstable")); };
}
$("btnHuman").addEventListener("click", () => {
  if (!S.token) return;
  answered = new Set(); hOver = false; hPhase = "wait";
  $("hChoose").classList.add("hide"); $("hRow").classList.remove("hide");
  $("hRound").textContent = t("h_wait"); $("hQ").textContent = "";
  openHumanStream();
});
async function submit() {
  const r = curRound; if (r == null || answered.has(r)) return; const a = $("hAns").value.trim();
  answered.add(r);   // lock this round first: the next question may arrive before the response does
  try {
    await api("POST", `/api/connect/${enc(S.token)}/action`, { round: r, content: a });
    if (curRound === r && !hOver) { hPhase = "sent"; stopTimer(); $("hRound").textContent = t("h_sent", { n: r }); $("hRow").classList.add("hide"); }
  } catch (e) {
    if (e.status !== 410) answered.delete(r);   // 410: match already over, keep it locked
    say("mMsg", e.message, 1);
  }
}
$("btnSubmit").addEventListener("click", submit);
$("hAns").addEventListener("keydown", e => { if (e.key === "Enter") submit(); });

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
function feed(html) { const d = node("div"); d.innerHTML = html; $("bFeed").prepend(d); }
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
  else if (ev.type === "action") feed(th("f_act", { a: ev.agent }));
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
  box.className = "result" + (o ? " " + o : "");
  $("resKicker").textContent = !own ? t("res_k_spec") : t(S.seatRanked ? "res_k_ranked" : "res_k_unranked");
  $("resTitle").textContent = t(o ? "res_" + o : "res_done");
  $("resSub").textContent = $("bWin").textContent;
  $("btnAgain").classList.toggle("hide", !own);
  const mine = own && myId && B[myId];
  $("resMine").textContent = mine ? t("res_me", { c: fmtNum(mine.correct), p: fmtPts(mine.val) }) : "";
  if (own) {                                  // the question card has nothing left to do: give the board the room
    $("matchPanel").classList.add("hide"); document.querySelector(".match").classList.add("spectate");
  }
  const wasHidden = box.classList.contains("hide");
  box.classList.remove("hide");
  if (wasHidden) window.scrollTo({ top: 0, behavior: "smooth" });
  if (window.FX && o) {
    window.FX.mode(o === "win" ? "win" : o === "loss" ? "loss" : "match");
    if (o === "win" && !celebrated) {
      celebrated = true;
      setTimeout(() => {                       // after the scroll to the top, so the burst lands on the banner
        const r = $("resTitle").getBoundingClientRect();
        [0.15, 0.5, 0.85].forEach((f, i) => setTimeout(() => window.FX.burst(r.left + r.width * f, r.top + r.height / 2,
          { color: i === 1 ? "warn" : "good", count: 90, speed: 640, size: 8 }), i * 160));
      }, 450);
    }
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
  S.token = S.match = null; live = false; resetHuman();
  if (bES) { bES.close(); bES = null; }
  $("matchPanel").classList.add("hide"); $("result").classList.add("hide"); $("resDelta").classList.add("hide");
  document.querySelector(".match").classList.remove("spectate");
  if (window.FX) { window.FX.mode("idle"); window.FX.team(false); }
}

/* ---------- hooks ---------- */
L.hooks.lang.push(() => {
  if (S.token) L.fillCmd("cmdToken", tokenCmd);
  if (S.seatRanked != null) setRanked(S.seatRanked);
  const bs = $("bStatus"); if (bs.dataset.s) setBadge(bs.dataset.s);
  renderMeta(); renderWin(); if (bResult) renderResult();
  if (hPhase === "pick") $("hRound").textContent = t("h_pick");
  else if (hPhase === "wait") $("hRound").textContent = t("h_wait");
  else if (hPhase === "sent" && curRound != null) $("hRound").textContent = t("h_sent", { n: curRound });
  else if (hPhase === "end") { $("hRound").textContent = t("h_end"); $("hQ").textContent = t("h_end2"); }
  if (hES && !hOver && S.token) openHumanStream();   // re-subscribe so questions come in the new language
});
})();
