"""Outprompt player client: every player plays through their own agent, and this connects yours.
Standard library only. Keys, model and prompts stay on your machine; the arena only sends questions.

  python arena_connect.py --link CODE --cmd "claude -p"          # code from the website: queue there, play here
  python arena_connect.py --name alice --mode quiz --cmd "…"     # or run everything from here (queue, --room, --host,
                                                                 #   --format 2v2 --party-host / --party CODE)
--server defaults to the public lobby's live server. The identity is saved (~/.config/agent-arena, mode 600).
For agents that should queue and answer through their own tools, use the MCP bridge arena_mcp.py.

Security: questions are untrusted. They reach stdin inside an "untrusted data" fence; --cmd runs in a fresh
temp directory as its own process group, killed on timeout. If your agent has tools, limit them yourself.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, NoReturn

LANGS = ("zh-TW", "zh-CN", "en", "ja")
DEFAULT_LANG = "en"
MAX_ANSWER_CHARS = 4000  # server-side limit
MAX_EVENT_BYTES = 256 * 1024  # cap per SSE event so a malicious server cannot exhaust memory


def _bounded_lines(resp: Any, limit: int) -> Iterator[bytes | None]:
    """Read line by line, at most `limit` bytes per line: an over-long line is discarded up to its
    newline and yields None, so a peer that never sends a newline cannot grow memory without bound."""
    while True:
        raw = resp.readline(limit + 1)
        if not raw:
            return
        if len(raw) > limit and not raw.endswith(b"\n"):
            while raw and not raw.endswith(b"\n"):
                raw = resp.readline(limit + 1)
            yield None
            continue
        yield raw
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# ---------------- Localized messages ----------------
try:  # package (python -m clients.arena_connect) or files side by side in one folder
    from clients.arena_messages import MESSAGES
except ImportError:  # pragma: no cover - single-folder layout
    from arena_messages import MESSAGES  # type: ignore

_lang = DEFAULT_LANG


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else DEFAULT_LANG


def t(key: str, **params: Any) -> str:
    table = MESSAGES.get(_lang, MESSAGES[DEFAULT_LANG])
    text = table.get(key) or MESSAGES[DEFAULT_LANG][key]
    # Params mostly come from server responses: strip control chars so ESC/OSC sequences never reach the terminal
    return text.format(**{k: clean_line(v) for k, v in params.items()}) if params else text


def normalize_lang(tag: str | None) -> str | None:
    """Map a LANG-style string (zh_TW.UTF-8, en_US, ja_JP, zh_Hans_CN…) to a supported language, or None."""
    if not tag:
        return None
    base = tag.split(".")[0].split("@")[0].replace("_", "-").lower()
    if base in ("c", "posix", ""):
        return None
    if base.startswith("zh"):
        if any(x in base for x in ("-cn", "-sg", "-hans")) or base == "zh":
            return "zh-CN"
        return "zh-TW"  # zh-TW / zh-HK / zh-MO / zh-Hant
    if base.startswith("en"):
        return "en"
    if base.startswith("ja"):
        return "ja"
    return None


def detect_lang(env: dict[str, str] | None = None) -> str:
    """Infer from LC_ALL > LC_MESSAGES > LANG (POSIX order); fall back to English."""
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        lang = normalize_lang(env.get(var))
        if lang:
            return lang
    return DEFAULT_LANG


# ---------------- Untrusted-content fence (same as arena.security.wrap_untrusted; the client does not import arena) ----------------
def neutralize_fences(text: str) -> str:
    return str(text).replace("<<<", "＜＜＜").replace(">>>", "＞＞＞")


def wrap_untrusted(text: str, source: str | None = None) -> str:
    nonce = secrets.token_hex(4)
    src = neutralize_fences(source if source is not None else t("source"))
    return f"{t('fence_open', nonce=nonce, source=src)}\n{neutralize_fences(text)}\n{t('fence_close', nonce=nonce)}"


# ---------------- Argument parsing ----------------
def int_range(lo: int, hi: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            n = int(str(value).strip())
        except ValueError:
            raise argparse.ArgumentTypeError(t("bad_int", lo=lo, hi=hi, value=value)) from None
        if not lo <= n <= hi:
            raise argparse.ArgumentTypeError(t("bad_int", lo=lo, hi=hi, value=value))
        return n
    return parse


def positive_float(value: str) -> float:
    try:
        x = float(str(value).strip())
    except ValueError:
        raise argparse.ArgumentTypeError(t("bad_float", value=value)) from None
    if not x > 0 or x != x or x == float("inf"):
        raise argparse.ArgumentTypeError(t("bad_float", value=value))
    return x


# ---------------- HTTP ----------------
MAX_JSON_BYTES = 1024 * 1024     # the lobby API never sends more; a bigger body is a hostile server


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The arena API never redirects. Following one would re-send X-Player-* headers to wherever the
    server points (another host, a LAN address, plain http)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def _read_json(fp: Any) -> Any:
    raw = fp.read(MAX_JSON_BYTES + 1) or b"{}"
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("response too large")
    return json.loads(raw)


RATE_LIMIT_RETRIES = 4
MAX_RETRY_WAIT = 20.0


def _retry_after(value: str | None) -> float:
    try:
        return min(max(float(value or 1), 0.5), MAX_RETRY_WAIT)
    except ValueError:
        return 2.0


class ApiError(Exception):
    def __init__(self, code: int, detail: str, key: str = ""):
        super().__init__(f"{code}：{detail}")
        self.code, self.detail, self.key = code, detail, key   # key: the server's message key ("code" in the body)


class Api:
    def __init__(self, server: str, lang: str = DEFAULT_LANG):
        self.base = server.rstrip("/")
        self.lang = lang
        self.pid: str | None = None
        self.secret: str | None = None

    def auth_headers(self) -> dict[str, str]:
        h = {"Accept-Language": self.lang}
        if self.pid and self.secret:
            h.update({"X-Player-Id": self.pid, "X-Player-Secret": self.secret})
        return h

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
        headers = {"content-type": "application/json", **self.auth_headers()}
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
            try:
                with _opener.open(req, timeout=timeout) as r:
                    data = _read_json(r)
                    if not isinstance(data, dict):
                        raise ValueError("unexpected response")
                    return data
            except urllib.error.HTTPError as e:
                key = ""
                try:
                    body_json = _read_json(e)
                    detail, key = str(body_json.get("detail", str(e))), str(body_json.get("code", ""))
                except Exception:  # noqa: BLE001
                    detail = str(e)
                # 429 means the server did not handle the request, so waiting and resending is safe.
                # Several players behind one router share a per-IP budget; backing off beats exiting.
                if e.code == 429 and attempt < RATE_LIMIT_RETRIES:
                    time.sleep(_retry_after(e.headers.get("Retry-After")))
                    continue
                raise ApiError(e.code, detail, key) from e
        raise AssertionError("unreachable")

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self.call("POST", path, body or {})

    def stream_url(self, token: str) -> str:
        q = urllib.parse.urlencode({"lang": self.lang})
        return f"{self.base}/api/connect/{urllib.parse.quote(token, safe='')}/stream?{q}"


# ---------------- Server discovery, identity (shared with the MCP bridge) ----------------
DISCOVERY_URL = "https://zhixuli0406.github.io/agent-arena/server.json"
PAGES_LOBBY = "https://zhixuli0406.github.io/agent-arena/web/index.html"
IDENTITY_PATH = Path(os.environ.get("ARENA_IDENTITY", Path.home() / ".config" / "agent-arena" / "identity.json"))
LINK_CODE_RE = re.compile(r"[A-Z0-9]{6,12}")
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MATCH_ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")                    # server/runtime.py MATCH_ID_RE
SERVER_URL_RE = re.compile(r"https://[a-z0-9.-]+(:\d{1,5})?")
_public_bases: set[str] = set()          # servers that server.json actually pointed to (this run)


def discover_server(url: str = DISCOVERY_URL) -> str:
    """The public lobby's live server (the free server rotates its URL every few hours)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=15) as r:
        server = str(json.loads(r.read(64 * 1024).decode()).get("server", ""))
    server = server.rstrip("/")
    # Just an origin: anything else in it would reach the agent as text (arena_status shows the server URL)
    if not SERVER_URL_RE.fullmatch(server):
        raise ValueError("server.json does not point to an https server")
    _public_bases.add(server)
    return server


def identity_key(base: str) -> str:
    """The public lobby rotates its URL, so it shares one saved identity ("public"). Only a server that server.json
    really points to counts as the public lobby: anyone can open a *.trycloudflare.com tunnel, and it must not
    receive your public-lobby secret. Every other server gets its own entry, keyed by its exact URL."""
    base = base.rstrip("/")
    host = urllib.parse.urlparse(base).hostname or ""
    if base not in _public_bases and host.endswith(".trycloudflare.com"):
        try:
            discover_server()
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return "public" if base in _public_bases else base


def load_identity(base: str) -> dict | None:
    try:
        data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get(identity_key(base)) if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) and entry.get("pid") and entry.get("secret") else None


def save_identity(base: str, pid: str, secret: str) -> None:
    """Read-modify-write under a lock, then an atomic replace: two bridges (say Claude and Codex) may save at once,
    and this file is the only copy of the secret."""
    key = identity_key(base)
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(IDENTITY_PATH) + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except ImportError:                       # Windows: no flock; the atomic replace still avoids torn files
            pass
        try:
            data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[key] = {"pid": pid, "secret": secret}
        fd, tmp = tempfile.mkstemp(dir=IDENTITY_PATH.parent, prefix=".identity-", suffix=".json")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, IDENTITY_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        os.close(lock_fd)


def sign_in(api: Api, name: str | None, agent: str, link_code: str | None, quiet: bool = False) -> dict:
    """Become a player: a link code from the website, else the saved identity, else register with --name."""
    say = (lambda *_: None) if quiet else print
    ident = load_identity(api.base)
    if link_code:
        try:
            r = api.post("/api/lobby/link/redeem", {"code": link_code.strip()})
        except ApiError as e:
            # MCP configs keep passing the same --link on every restart: once used, fall back to the saved identity
            if e.code != 404 or not ident:
                raise
        else:
            api.pid, api.secret = r["player"]["id"], r["secret"]
            save_identity(api.base, api.pid, api.secret)
            say(t("linked", name=clean(r["player"]["name"]), rating=clean(r["player"]["rating"])))
            return r["player"]
    if ident:
        api.pid, api.secret = ident["pid"], ident["secret"]
        try:
            me = api.get("/api/lobby/me")["player"]
            say(t("entered", name=clean(me["name"]), rating=clean(me["rating"])))
            return me
        except ApiError as e:
            if e.code != 401:
                raise
            # A guest the server forgot (never played) may simply register again. A revoked credential
            # ("sign out all agents" on the website) must not: the website would keep queueing the old
            # player while this agent quietly played as a new one.
            if e.key != "player_unknown" or not name:
                raise SystemExit(t("ident_revoked", path=str(IDENTITY_PATH))) from None
            api.pid = api.secret = None
    if not name:
        raise SystemExit(t("need_name_or_link"))
    r = api.post("/api/lobby/players", {"name": name, "agent": agent})
    api.pid, api.secret = r["player"]["id"], r["secret"]
    save_identity(api.base, api.pid, api.secret)
    say(t("entered", name=clean(r["player"]["name"]), rating=clean(r["player"]["rating"])))
    return r["player"]


def web_login_link(api: Api) -> str:
    """A one-time link that opens the website as this same player."""
    code = str(api.post("/api/lobby/link").get("code", ""))
    if not LINK_CODE_RE.fullmatch(code):                   # never paste server text into a URL we print
        raise ValueError("the server returned a malformed link code")
    if identity_key(api.base) == "public":
        return f"{PAGES_LOBBY}?" + urllib.parse.urlencode({"login": code})
    return f"{api.base}/game/index.html?" + urllib.parse.urlencode({"login": code, "api": api.base})


MAX_HELD = 8          # seats kept waiting for pickup; a real player has at most a couple at once


class AgentLink:
    """The agent's standby stream: keeps the player's agent "online" (required to queue or ready up)
    and receives seats when a match starts, whether it was queued from here or from the website."""

    def __init__(self, api: Api):
        self.api = api
        self.seats: "queue.Queue[dict]" = queue.Queue()
        self.seen: "collections.deque[str]" = collections.deque(maxlen=64)
        self.online = threading.Event()
        self.revoked = threading.Event()       # the server rejected our credential: stop, don't retry forever
        self._stop = threading.Event()
        self._held: list[dict] = []

    def start(self) -> "AgentLink":
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                for event, data in sse_events(self.api.base + "/api/lobby/agent/stream", self.api.auth_headers()):
                    delay = 1.0
                    if event == "hello":
                        self.online.set()
                    elif event == "match" and isinstance(data, dict) and isinstance(data.get("token"), str):
                        mid = str(data.get("match_id", ""))
                        # a reconnect re-sends recent seats; remember an id only once its seat is really queued
                        if MATCH_ID_RE.fullmatch(mid) and mid not in self.seen and self.seats.qsize() < MAX_HELD:
                            self.seen.append(mid)
                            self.seats.put(data)
                    if self._stop.is_set():
                        return
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.online.clear()
                    self.revoked.set()
                    return
            except Exception:                    # noqa: BLE001 -- whatever the server sends, the standby thread must survive
                pass
            self.online.clear()
            self._stop.wait(delay)
            delay = min(delay * 2, 30.0)

    def take(self, match_id: str | None = None, timeout: float | None = None) -> dict | None:
        """Next seat (or the seat for match_id). None on timeout, or once the server has signed this agent out."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            for i, seat in enumerate(self._held):
                if match_id is None or seat.get("match_id") == match_id:
                    return self._held.pop(i)
            left = None if deadline is None else deadline - time.monotonic()
            if (left is not None and left <= 0) or (self.revoked.is_set() and self.seats.empty()):
                return None
            try:
                self._held = (self._held + [self.seats.get(timeout=min(left, 2.0) if left is not None else 2.0)])[-MAX_HELD:]
            except queue.Empty:
                continue                          # re-check the deadline and whether we were signed out


def clean(text: Any) -> str:
    """Strip control chars before printing (server/agent output may carry ANSI/OSC codes, e.g. OSC 52 clipboard writes)."""
    return _CTRL_RE.sub("", str(text))


def clean_line(text: Any) -> str:
    """One-line fields (names, rosters, ids): line breaks would let someone else's name fake a status line."""
    return " ".join(clean(text).split())


def status(msg: str) -> None:
    sys.stdout.write("\r\033[K" + msg)
    sys.stdout.flush()


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


# ---------------- Entry flow ----------------
def matchmake(api: Api, mode: str, size: int, fmt: str = "ffa") -> str:
    tk = api.post("/api/lobby/queue", {"mode": mode, "size": size, "format": fmt})
    if fmt == "ffa":
        print(t("queued", mode=mode, size=size))
    else:
        print(t("queued_team", mode=mode, fmt=fmt, n=len(tk.get("members") or [1])))
    return follow_ticket(api, tk["ticket_id"])


def _roster(players: list[dict[str, Any]]) -> str:
    """Ready-check roster; team matches are grouped by side and joined with "vs"."""
    sides: dict[str, list[str]] = {}
    for p in players:
        sides.setdefault(p.get("side") or "", []).append(f"{p['name']}（{p['rating']}）")
    return clean_line(" vs ".join("、".join(v) for v in sides.values()))


def follow_ticket(api: Api, tid: str) -> str:
    """Follow a queue ticket through the ready check (party members use this too; each accepts on their own)."""
    try:
        while True:
            v = api.get(f"/api/lobby/tickets/{tid}")
            st = v["status"]
            if st == "searching":
                avg = t("avg_wait", t=mmss(v["avg_wait"])) if v.get("avg_wait") else ""
                status(t("searching", waited=mmss(v["waited"]), n=v["in_queue"], window=v["window"]) + avg)
            elif st == "ready_check":
                r = v["ready"]
                if not r["you_accepted"]:
                    print("\n" + t("found", rivals=_roster(r["players"])))
                    api.post(f"/api/lobby/tickets/{tid}/accept")
                else:
                    status(t("waiting_accept", a=r["accepted"], t=r["total"], s=f"{r['deadline_in']:.0f}"))
            elif st == "confirmed":
                print("\n" + t("confirmed", mid=v["match_id"]))
                return v["match_id"]
            elif st == "declined":
                raise SystemExit("\n" + t("declined", s=v.get("cooldown", 0)))
            elif st == "cancelled":
                raise SystemExit("\n" + t("queue_cancelled"))
            time.sleep(1)
    except KeyboardInterrupt:
        try:
            api.post(f"/api/lobby/tickets/{tid}/cancel")
        finally:
            raise SystemExit("\n" + t("queue_cancelled"))


def host_party(api: Api, mode: str, fmt: str, need: int) -> str:
    """Create a party, wait for `need` members, then queue for the team match as the leader."""
    code = api.post("/api/lobby/parties")["code"]
    print(t("party_created", code=code, n=need))
    try:
        while True:
            v = api.get(f"/api/lobby/parties/{code}")
            roster = clean_line("、".join(m["name"] for m in v["members"]))
            status(t("party_status", code=code, roster=roster, n=len(v["members"]), need=need))
            if len(v["members"]) >= need:
                print()
                return matchmake(api, mode, 2, fmt)
            time.sleep(1)
    except KeyboardInterrupt:
        _leave_party(api, code)


def join_party(api: Api, code: str) -> str:
    """Join a party and wait for the leader to queue; follow the party's ticket once it appears (you still accept yourself)."""
    code = code.strip().upper()
    api.post(f"/api/lobby/parties/{code}/join")
    print(t("party_joined", code=code))
    try:
        while True:
            v = api.get(f"/api/lobby/parties/{code}")
            if v.get("ticket_id"):
                print()
                return follow_ticket(api, v["ticket_id"])
            roster = clean_line("、".join(m["name"] for m in v["members"]))
            status(t("party_status", code=code, roster=roster, n=len(v["members"]), need=v["max"]))
            time.sleep(1)
    except KeyboardInterrupt:
        _leave_party(api, code)


def _leave_party(api: Api, code: str) -> NoReturn:
    try:
        api.post(f"/api/lobby/parties/{code}/leave")
    finally:
        raise SystemExit("\n" + t("left_party"))


def join_room(api: Api, code: str) -> str:
    code = code.strip().upper()
    api.post(f"/api/lobby/rooms/{code}/join")
    api.post(f"/api/lobby/rooms/{code}/ready", {"ready": True})
    print(t("joined_room", code=code))
    return _wait_room(api, code, host=False, min_players=2)


def host_room(api: Api, mode: str, size: int, min_players: int) -> str:
    r = api.post("/api/lobby/rooms", {"mode": mode, "size": size})
    print(t("room_created", code=r["code"], n=min_players))
    return _wait_room(api, r["code"], host=True, min_players=min_players)


def _wait_room(api: Api, code: str, host: bool, min_players: int) -> str:
    try:
        while True:
            r = api.get(f"/api/lobby/rooms/{code}")
            if r["status"] == "started":
                print("\n" + t("started", mid=r["match_id"]))
                return r["match_id"]
            members = r["members"]
            roster = clean_line("、".join(m["name"] + ("✓" if m["ready"] else "…") for m in members))
            status(t("room_status", code=r["code"], n=len(members), size=r["size"], roster=roster))
            if host and len(members) >= min_players and all(m["ready"] for m in members):
                try:
                    api.post(f"/api/lobby/rooms/{code}/start")
                except ApiError as e:
                    status(t("cant_start", detail=clean(e.detail)))
            time.sleep(1)
    except KeyboardInterrupt:
        try:
            api.post(f"/api/lobby/rooms/{code}/leave")
        finally:
            raise SystemExit("\n" + t("left_room"))


# ---------------- Playing ----------------
def build_prompt(system: str, obs: dict[str, Any]) -> str:
    """Only the player's own system prompt sits outside the fence. Everything the server sent, including its
    answer instructions, goes inside: the server may be someone else's (or compromised)."""
    parts = [system.strip()] if system.strip() else []
    sent = str(obs.get("task", ""))
    if obs.get("instructions"):
        sent = f"{obs['instructions']}\n\n{sent}"
    parts.append(wrap_untrusted(sent))
    return "\n\n".join(parts)


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the whole process group (--cmd runs in a shell and the agent may spawn children);
    on Windows fall back to taskkill /T or kill.

    On POSIX the group gets SIGKILL even if the shell already exited, to clean up children left in the background.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True → pgid == pid
        except (ProcessLookupError, PermissionError, OSError):
            pass
    elif proc.poll() is None:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass


def _pump_in(stream: Any, data: bytes) -> None:
    try:
        stream.write(data)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _pump_out(stream: Any, sink: list[bytes]) -> None:
    try:
        for chunk in iter(lambda: stream.read(65536), b""):
            sink.append(chunk)
    except (OSError, ValueError):
        pass


def run_cmd(cmd: str, prompt: str, timeout: float) -> str:
    """Run the player's command in a throwaway temp directory as its own process group.

    We wait for the command itself to exit, not for stdout to close: once it exits, the whole group is
    reaped (including background children still holding stdout) and the answer is kept; on timeout the
    group is killed and a blank answer is submitted.
    """
    workdir = tempfile.mkdtemp(prefix="arena_cmd_")
    popen_kw: dict[str, Any] = {}
    if os.name == "posix":
        popen_kw["start_new_session"] = True
    else:  # pragma: no cover — Windows
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        try:
            proc = subprocess.Popen(cmd, shell=True, cwd=workdir, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **popen_kw)
        except OSError as e:
            print(t("solver_failed", err=e))
            return ""
        out: list[bytes] = []
        threads = [
            threading.Thread(target=_pump_in, args=(proc.stdin, prompt.encode()), daemon=True),
            threading.Thread(target=_pump_out, args=(proc.stdout, out), daemon=True),
        ]
        for th in threads:
            th.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            _kill_group(proc)  # kill the group on timeout; on normal exit, clean up leftover background children
            for th in threads:
                th.join(timeout=5)
            try:
                proc.stdout.close()
            except OSError:
                pass
        if timed_out:
            print(t("solver_timeout"))
            return ""
        return b"".join(out).decode("utf-8", "replace").strip()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def submit(api: Api, token: str, rnd: Any, ans: str) -> bool:
    """Submit an answer; returns False if the match is already over (410)."""
    if len(ans) > MAX_ANSWER_CHARS:
        print(t("truncated", n=MAX_ANSWER_CHARS))
        ans = ans[:MAX_ANSWER_CHARS]
    try:
        api.post(f"/api/connect/{urllib.parse.quote(token, safe='')}/action", {"round": rnd, "content": ans})
    except ApiError as e:
        if e.code == 410:
            print(t("match_over"))
            return False
        print(t("answer_rejected", err=clean(e.detail)))
    except (urllib.error.URLError, OSError) as e:
        print(t("answer_rejected", err=e))
    return True


def sse_events(url: str, headers: dict[str, str], timeout: float = 60) -> Iterator[tuple[str, Any]]:
    """Read one SSE connection, yielding (event name, parsed JSON data or None). Size-capped per event.
    Network errors propagate; callers decide whether to reconnect."""
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream", **headers})
    with _opener.open(req, timeout=timeout) as resp:
        event, data, size = "message", [], 0
        for raw in _bounded_lines(resp, MAX_EVENT_BYTES):
            if raw is None:              # over-long line: already discarded, drop this event too
                data, size = [], 0
                continue
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
                continue
            if line.startswith("data:"):
                size += len(raw)
                if size > MAX_EVENT_BYTES:   # oversized event: drop it
                    data, size = [], 0
                    continue
                data.append(line[5:].lstrip())
                continue
            if line:                       # ignore other fields
                continue
            parsed: Any = None
            if data:
                try:
                    parsed = json.loads("\n".join(data))
                except (ValueError, RecursionError):      # RecursionError: absurdly nested JSON from a hostile server
                    parsed = None
            yield event, parsed
            event, data, size = "message", [], 0


def stream_events(api: Api, token: str) -> Iterator[tuple[str, dict | None]]:
    """Open the question stream once and yield ("question", obs) / ("end", None) / ("bad", None).
    The MCP bridge (arena_mcp.py) uses this too."""
    for event, obs in sse_events(api.stream_url(token), {"Accept-Language": api.lang}):
        if event == "end":
            yield "end", None
            return
        if event != "message":
            continue
        rnd = obs.get("round") if isinstance(obs, dict) else None
        ok = isinstance(rnd, int) and not isinstance(rnd, bool) and 0 < rnd < 10_000      # the server numbers rounds 1, 2, …
        if not isinstance(obs, dict) or not ok:
            yield "bad", None
        else:
            yield "question", obs


def play(api: Api, token: str, solver: Callable[[str], str], system: str) -> None:
    answered: set[Any] = set()
    retries = 0
    while True:
        try:
            for kind, obs in stream_events(api, token):
                retries = 0
                if kind == "end":
                    print("\n" + t("match_end"))
                    return
                if kind == "bad" or obs is None:
                    print(t("bad_event"))
                    continue
                rnd = obs["round"]
                if rnd not in answered:   # answer a question resent after reconnect only once
                    answered.add(rnd)
                    print("\n" + t("question", rnd=clean(rnd)) + "\n" + clean(str(obs.get("task", ""))[:600]))
                    ans = solver(build_prompt(system, obs))
                    print(t("answer", ans=clean(ans[:300])))
                    if not submit(api, token, rnd, ans):
                        return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            retries += 1
            if retries > 6:
                raise SystemExit(t("reconnect_failed", err=e)) from e
            print("\n" + t("reconnect", n=retries))
            time.sleep(retries)


def make_solver(args: argparse.Namespace) -> Callable[[str], str]:
    if args.cmd:
        return lambda prompt: run_cmd(args.cmd, prompt, args.solve_timeout)
    raise SystemExit(t("need_agent"))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Plug the agent you tuned yourself into Outprompt")
    ap.add_argument("--server", default="", help="Arena URL (default: the public lobby's live server)")
    ap.add_argument("--token", help="Enter directly with a connect token (private servers)")
    ap.add_argument("--link", help="Link code from the website: your agent plays for that player")
    ap.add_argument("--standby", action="store_true",
                    help="Just stand by: queue on the website and matches come here (default with --link)")
    ap.add_argument("--web-link", action="store_true", help="Print a one-time link that opens the website as this player")
    ap.add_argument("--name", help="Your player name (first run only; the identity is then saved)")
    ap.add_argument("--agent", default="", help="Your agent's name (shown in match reports and the model leaderboard; self-reported)")
    ap.add_argument("--mode", default="quiz", choices=["quiz", "task"])
    ap.add_argument("--size", type=int_range(2, 4), default=2, help="Players per free-for-all match (2-4)")
    ap.add_argument("--format", default="ffa", choices=["ffa", "2v2", "3v3"],
                    help="ffa = free-for-all; 2v2, 3v3 = team queue (solo, or as a party with --party-host / --party)")
    ap.add_argument("--party-host", action="store_true", help="Create a party; once teammates join, you queue for the team match")
    ap.add_argument("--party-size", type=int_range(2, 3), default=None, help="Queue once the party has this many members (default = team size)")
    ap.add_argument("--party", help="Join a friend's party by code (the leader queues)")
    ap.add_argument("--room", help="Join a room by code")
    ap.add_argument("--host", action="store_true", help="Open your own room")
    ap.add_argument("--min-players", type=int_range(2, 4), default=2, help="When hosting, start once this many players are in and ready (2-4)")
    ap.add_argument("--loop", action="store_true", help="Queue again automatically after each match")
    ap.add_argument("--cmd", help="Your agent command (question on stdin, answer on stdout)")
    ap.add_argument("--system", default="", help="Your system prompt")
    ap.add_argument("--system-file", help="Read the system prompt from a file")
    ap.add_argument("--solve-timeout", type=positive_float, default=100,
                    help="Max seconds your agent gets per question (server cap 120)")
    ap.add_argument("--lang", choices=LANGS, default=None,
                    help="Language for questions and messages (default: inferred from LANG, else en)")
    return ap


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # Read --lang first so argument errors also use the right language
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=LANGS, default=None)
    known, _ = pre.parse_known_args(argv)
    set_lang(known.lang or detect_lang())
    args = build_parser().parse_args(argv)
    args.lang = args.lang or detect_lang()
    set_lang(args.lang)
    return args


def _play_seat(api: Api, seat: dict | None, solver: Callable[[str], str], system: str) -> None:
    if seat is None:
        print(t("no_seat"))
        return
    play(api, seat["token"], solver, system)
    me = api.get("/api/lobby/me")["player"]
    print(t("rating_now", rating=me["rating"], games=me["games"]))


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)     # progress shows up live even when output goes to a file or pipe
    args = parse_args(argv)
    system = args.system
    if args.system_file:
        with open(args.system_file, encoding="utf-8") as f:
            system = f.read()
    solver = make_solver(args)
    api = Api(args.server or discover_server(), lang=args.lang)
    parsed = urllib.parse.urlparse(api.base)
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        print(t("insecure_server"))
    try:
        if args.token:
            play(api, args.token, solver, system)
            return
        sign_in(api, args.name, args.agent, args.link)
        link = AgentLink(api).start()
        if not link.online.wait(15):
            print(t("agent_down"))
        else:
            print(t("agent_up"))
        if args.web_link:
            print(t("web_link", url=web_login_link(api)))
        operate = any([args.party, args.party_host, args.room, args.host])
        if args.standby or (args.link and not operate):
            print(t("standby"))
            while True:                       # the website (or a teammate) queues; seats arrive on the link
                seat = link.take()
                if seat is None:              # only when the server signed this agent out
                    raise SystemExit(t("ident_revoked", path=str(IDENTITY_PATH)))
                print(t("confirmed", mid=clean(seat.get("match_id"))))
                _play_seat(api, seat, solver, system)
        while True:
            if args.party:
                mid = join_party(api, args.party)
            elif args.party_host:
                if args.format == "ffa":
                    raise SystemExit(t("party_needs_team"))
                mid = host_party(api, args.mode, args.format, args.party_size or int(args.format[0]))
            elif args.room:
                mid = join_room(api, args.room)
            elif args.host:
                mid = host_room(api, args.mode, max(args.size, args.min_players), args.min_players)
            else:
                mid = matchmake(api, args.mode, args.size, args.format)
            print(t("wait_seat"))
            _play_seat(api, link.take(mid, timeout=30), solver, system)
            if not args.loop or operate:
                break
    except ApiError as e:
        raise SystemExit(t("server_error", err=clean(e))) from e
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
