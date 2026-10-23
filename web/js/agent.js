/* "Connect your agent": every player plays through their own agent (MCP bridge or command-line client).
 * Signed in: get a one-time link code; the commands carry it, and the agent becomes this player.
 * Not signed in yet: the agent can register you itself (--name), then hand the website a sign-in link. */
(function () {
"use strict";
const L = window.LOBBY;
const { S, t, th, $, node, api, base, toast } = L;
const { sq } = window.ARENA;
const PACKAGE = "https://github.com/zhixuli0406/agent-arena/archive/refs/heads/main.zip";
const BIN = '"$HOME/.local/share/outprompt/bin/';
let link = null, ticker = 0;            // { code, until }

function serverArgs() {
  let host = ""; try { host = new URL(base()).hostname; } catch (_) { /* keep empty */ }
  return host.endsWith(".trycloudflare.com") ? [] : ["--server", sq(base())];   // the public lobby rotates URLs
}
function commands() {
  // link.code was checked against [A-Z0-9] in getCode(), so it is safe unquoted in a shell command
  const who = link ? ["--link", link.code] : ["--name", sq(t("cmd_name")), "--agent", sq(t("cmd_agent"))];
  const lang = ["--lang", window.I18N.lang()];
  const install = ['python3 -m venv "$HOME/.local/share/outprompt"',
    BIN + 'python" -m pip install --upgrade ' + sq(PACKAGE)].join(" && ");
  const mcp = [BIN + 'outprompt-mcp"', ...serverArgs(), ...who, ...lang].join(" ");
  return {
    install,
    claude: "claude mcp add --scope user outprompt -- " + mcp,
    codex: "codex mcp add outprompt -- " + mcp,
    cli: [BIN + 'outprompt-connect"', ...serverArgs(), ...who, ...lang, "--cmd", sq("claude -p")].join(" "),
  };
}
async function getCode() {
  try {
    const r = await api("POST", "/api/lobby/link");
    const code = String((r && r.code) || "");
    if (!/^[A-Z0-9]{6,12}$/.test(code)) throw new Error(t("e_srv_bad"));   // it goes into commands people paste into a shell
    link = { code, until: Date.now() + Math.min(Math.max(Number(r.expires_in) || 600, 30), 3600) * 1000 };
    render();
    clearInterval(ticker);
    ticker = setInterval(() => {
      if (!link || Date.now() >= link.until) { link = null; clearInterval(ticker); render(); return; }
      document.querySelectorAll(".agentcard .exp").forEach(e => { e.textContent = t("ag_exp", { t: L.mmss((link.until - Date.now()) / 1000) }); });
    }, 1000);
  } catch (e) { toast(e.message, "err"); }
}
async function resetAll() {
  if (!window.confirm(t("ag_reset_q"))) return;
  try { await api("POST", "/api/lobby/credentials/reset"); link = null; clearInterval(ticker); toast(t("ag_reset_ok"), "ok"); L.setAgent(false, true); }
  catch (e) { toast(e.message, "err"); }
}
function cmdBox(text) { const d = node("div", "cmd"); d.append(document.createTextNode(text), L.copyBtn(() => text)); return d; }
function step(label, html, cmd) {
  const li = node("li"), d = node("div");
  if (html) d.innerHTML = th(label); else d.textContent = t(label);
  if (cmd) d.appendChild(cmdBox(cmd));
  li.appendChild(d); return li;
}
function choices(c) {
  const li = node("li"), d = node("div");
  d.appendChild(node("div", null, t("ag_choose")));
  [["ag_mcp_claude", false, c.claude], ["ag_mcp_codex", false, c.codex],
    ["ag_mcp_other", true, null], ["ag_cli", false, c.cli]].forEach(([label, html, cmd]) => {
    const item = node("div", "help");
    if (html) item.innerHTML = th(label); else item.textContent = t(label);
    if (cmd) item.appendChild(cmdBox(cmd));
    d.appendChild(item);
  });
  li.appendChild(d); return li;
}
function renderInto(box, big) {
  if (!box) return;
  box.replaceChildren();
  const signedIn = !!S.pid, on = signedIn && !!S.agentOnline;
  box.classList.toggle("on", on);
  if (!signedIn && !big) { box.classList.add("hide"); return; }
  box.classList.remove("hide");
  const head = node("div", "aghead");
  head.append(node("span", "dot" + (on ? " on" : " off")), node("div", "h2", t(on ? "ag_on_h" : big ? "ag_off_h" : "ag_h")));   // the Agents tab already has the "Connect" title
  box.append(head, node("p", "note", t(on ? "ag_on_note" : signedIn ? "ag_need" : "ag_first")));
  if (on && !big) return;                                    // linked: the Play screen only needs the green light
  if (signedIn) {
    const row = node("div", "row codebox");
    if (link) {
      row.append(node("span", "k", t("ag_code")), node("b", null, link.code), node("span", "note exp", t("ag_exp", { t: L.mmss((link.until - Date.now()) / 1000) })));
      const again = node("button", "btn ghost sm", t("ag_new")); again.type = "button"; again.addEventListener("click", getCode);
      row.appendChild(again);
    } else {
      const b = node("button", "btn", t("ag_get")); b.type = "button"; b.addEventListener("click", getCode);
      row.append(b, node("span", "note", t("ag_get_note")));
    }
    box.appendChild(row);
  }
  if (signedIn && !link) return;                             // commands only make sense with a code (or for agent-first)
  const c = commands(), ol = node("ol", "steps");
  ol.append(step("ag_install", false, c.install), choices(c), step("ag_verify", false));
  box.appendChild(ol);
  if (signedIn && !on) box.appendChild(node("p", "note waiting", t("ag_wait")));
}
function renderReset(box) {
  if (!box || !S.pid) return;
  const row = node("div", "row reset"), b = node("button", "btn ghost sm", t("ag_reset"));
  b.type = "button"; b.addEventListener("click", resetAll);
  row.append(b, node("span", "note", t("ag_reset_note")));
  box.appendChild(row);
}
function render() { renderInto($("agentCard"), false); renderInto($("agentCardBig"), true); renderReset($("agentCardBig")); renderMore(); }
function renderMore() {
  const more = $("cMore"); if (!more) return;
  const parts = th("c_more").split("{link}");
  more.innerHTML = parts[0];                                 // trusted template from STR
  const a = node("a", null, "PROTOCOL.md");
  a.href = "https://github.com/zhixuli0406/agent-arena/blob/main/docs/PROTOCOL.md"; a.target = "_blank"; a.rel = "noopener noreferrer";
  more.appendChild(a);
  if (parts[1]) more.insertAdjacentHTML("beforeend", parts[1]);
}

L.hooks.init.push(render);
L.hooks.lang.push(render);
L.hooks.me.push(render);
L.hooks.agent.push(on => { if (on) { link = null; clearInterval(ticker); } render(); });
L.hooks.tab.push(tab => { if (tab === "connect" || tab === "quick") render(); });
})();
