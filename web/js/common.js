/* Shared helpers for index.html and arena.html (no DOM-specific logic). */
(function () {
"use strict";
const { t } = window.I18N;

// Match ids look like 20261023-014512-a1b2c3.
const MATCH_RE = /^\d{8}-\d{6}-[0-9a-f]{6}$/;
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
// Path characters we allow in a server base (keeps shell commands and URLs unambiguous).
const SAFE_PATH = /^[A-Za-z0-9/._~-]*$/;

// Accept only https:// anywhere, or http:// on localhost/127.0.0.1. Returns a normalized base or null.
function safeApi(input) {
  const s = String(input == null ? "" : input).trim();
  if (!s) return "";
  let u;
  try { u = new URL(s); } catch (_) { return null; }
  if (u.username || u.password || u.search || u.hash) return null;
  const okProto = u.protocol === "https:" || (u.protocol === "http:" && LOCAL_HOSTS.has(u.hostname));
  if (!okProto) return null;
  if (u.protocol === "https:" && LOCAL_HOSTS.has(u.hostname) === false && !u.hostname.includes(".")) return null;
  if (!SAFE_PATH.test(u.pathname)) return null;
  return (u.origin + u.pathname).replace(/\/+$/, "");
}

// POSIX single-quote escaping: 'it'\''s'. Also valid PowerShell when the value has no quote.
function sq(v) { return "'" + String(v).replace(/'/g, "'\\''") + "'"; }

function detailOf(j) {
  if (!j) return "";
  if (typeof j.detail === "string") return j.detail;
  if (Array.isArray(j.detail)) return j.detail.map(d => (d && d.msg) || "").filter(Boolean).join("; ");
  return "";
}

// JSON fetch with Accept-Language and translated server errors.
// Errors carry .status, .code (server message key) and .retryAfter (seconds, for 429/503).
async function apiFetch(base, method, path, body, extraHeaders) {
  const h = Object.assign({ "Accept": "application/json", "Accept-Language": window.I18N.lang() }, extraHeaders || {});
  const init = { method, headers: h };
  if (body !== undefined) { h["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(base + path, init); }
  catch (_) { const e = new Error(t("e_network")); e.status = 0; throw e; }
  let j = null;
  try { j = await r.json(); } catch (_) { /* non-JSON body */ }
  if (!r.ok) {
    const msg = detailOf(j) || t("e_http", { s: r.status });
    const e = new Error(msg.slice(0, 300));
    e.status = r.status;
    e.code = j && typeof j.code === "string" ? j.code : "";
    const ra = parseFloat(r.headers.get("Retry-After") || "");
    e.retryAfter = Number.isFinite(ra) && ra > 0 ? Math.min(ra, 300) : (r.status === 429 ? 5 : 0);
    throw e;
  }
  return j || {};
}

function qs(name) { try { return new URLSearchParams(location.search).get(name); } catch (_) { return null; } }

window.ARENA = Object.freeze({ MATCH_RE, safeApi, sq, apiFetch, qs });
})();
