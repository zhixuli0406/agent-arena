"""Players must bring their own agent: link codes, the standby stream, presence checks, seat dispatch."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server import guard
from server import runtime as rt
from server.agents import GRACE, AgentHub
from server.app import app
from server.lobby import LINK_TTL, Lobby


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    guard.limiter.reset()
    monkeypatch.setattr(rt, "lobby", Lobby(rt._lobby_start))
    monkeypatch.setattr(rt, "hub", AgentHub())
    monkeypatch.setattr(rt, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(rt, "RUNS_DIR", str(tmp_path / "runs"))
    yield
    guard.limiter.reset()


def hdr(r):
    return {"X-Player-Id": r["player"]["id"], "X-Player-Secret": r["secret"]}


def reg(c, name):
    return c.post("/api/lobby/players", json={"name": name}).json()


def test_queue_and_ready_need_the_players_own_agent():
    with TestClient(app) as c:
        a = reg(c, "NoAgent")
        r = c.post("/api/lobby/queue", json={"mode": "quiz"}, headers={**hdr(a), "Accept-Language": "en"})
        assert r.status_code == 409 and r.json()["code"] == "agent_offline" and "NoAgent" in r.json()["detail"]
        rt.hub.connect(a["player"]["id"])
        assert c.post("/api/lobby/queue", json={"mode": "quiz"}, headers=hdr(a)).status_code == 200
        # rooms: readying up needs your agent; starting needs everyone's
        h, g = reg(c, "Host"), reg(c, "Guest")
        rt.hub.connect(h["player"]["id"])
        code = c.post("/api/lobby/rooms", json={"mode": "quiz", "size": 2}, headers=hdr(h)).json()["code"]
        c.post(f"/api/lobby/rooms/{code}/join", headers=hdr(g))
        assert c.post(f"/api/lobby/rooms/{code}/ready", json={"ready": True}, headers=hdr(g)).json()["code"] == "agent_offline"


def test_party_queue_names_the_member_without_agent(monkeypatch):
    monkeypatch.setattr("server.lobby._net_key", lambda ip: "")
    with TestClient(app) as c:
        lead, mate = reg(c, "Lead"), reg(c, "Mate")
        rt.hub.connect(lead["player"]["id"])
        code = c.post("/api/lobby/parties", headers=hdr(lead)).json()["code"]
        c.post(f"/api/lobby/parties/{code}/join", headers=hdr(mate))
        r = c.post("/api/lobby/queue", json={"mode": "quiz", "format": "2v2"}, headers=hdr(lead))
        assert r.status_code == 409 and "Mate" in r.json()["detail"] and "Lead" not in r.json()["detail"]


def test_link_code_mints_a_new_credential_once():
    with TestClient(app) as c:
        a = reg(c, "Web")
        link = c.post("/api/lobby/link", headers=hdr(a)).json()
        assert len(link["code"]) == 8 and link["expires_in"] == int(LINK_TTL)
        got = c.post("/api/lobby/link/redeem", json={"code": link["code"].lower()}).json()
        assert got["player"]["id"] == a["player"]["id"] and got["secret"] != a["secret"]
        for secret in (a["secret"], got["secret"]):              # both the browser's and the agent's credential work
            assert c.get("/api/lobby/me", headers={"X-Player-Id": a["player"]["id"], "X-Player-Secret": secret}).status_code == 200
        again = c.post("/api/lobby/link/redeem", json={"code": link["code"]})
        assert again.status_code == 404 and again.json()["code"] == "link_invalid"   # single use


def test_link_code_expires_and_new_code_replaces_old():
    lb = Lobby(lambda *a, **k: ("m", {}), clock=lambda: t[0])
    t = [1000.0]
    p = lb.register("P")
    old, _ = lb.create_link(p)
    new, _ = lb.create_link(p)
    with pytest.raises(Exception):
        lb.redeem_link(old)                                      # replaced by the newer code
    t[0] += LINK_TTL + 1
    with pytest.raises(Exception):
        lb.redeem_link(new)                                      # expired


def test_link_credentials_survive_a_restart():
    lb = Lobby(lambda *a, **k: ("m", {}))
    p = lb.register("P"); p.games = 1
    code, _ = lb.create_link(p)
    _, agent_secret = lb.redeem_link(code)
    lb2 = Lobby(lambda *a, **k: ("m", {}))
    lb2.restore(json.loads(json.dumps(lb.dump())))
    assert lb2.auth(p.id, agent_secret).id == p.id


def test_seats_go_to_the_agent_stream_not_the_lobby_views(monkeypatch):
    monkeypatch.setattr("server.lobby._net_key", lambda ip: "")
    with TestClient(app) as c:
        a, b = reg(c, "A"), reg(c, "B")
        for x in (a, b):
            rt.hub.connect(x["player"]["id"])
        ta = c.post("/api/lobby/queue", json={"mode": "quiz"}, headers=hdr(a)).json()
        tb = c.post("/api/lobby/queue", json={"mode": "quiz"}, headers=hdr(b)).json()
        rt.lobby.tick()
        for x, t in ((a, ta), (b, tb)):
            v = c.post(f"/api/lobby/tickets/{t['ticket_id']}/accept", headers=hdr(x)).json()
        assert v["status"] == "confirmed" and "token" not in v
        # the agent's standby stream delivers the seat
        with c.stream("GET", "/api/lobby/agent/stream", headers=hdr(a)) as s:
            lines = []
            for line in s.iter_lines():
                lines.append(line)
                if line.startswith("data:") and "token" in line:
                    break
        assert any(l.startswith("event: hello") for l in lines) and any(l.startswith("event: match") for l in lines)
        item = json.loads([l for l in lines if l.startswith("data:") and "token" in l][0][5:])
        assert item["match_id"] == v["match_id"] and item["token"] and "_id" not in item
        rt.matches[item["match_id"]]["task"].cancel()


def test_agent_presence_has_a_short_grace_after_disconnect():
    t = [0.0]
    hub = AgentHub(clock=lambda: t[0])
    assert not hub.online("p")
    hub.connect("p"); assert hub.online("p")
    hub.disconnect("p"); assert hub.online("p")              # reconnecting
    t[0] += GRACE + 1; assert not hub.online("p")


def test_reset_credentials_signs_out_every_other_agent_and_browser():
    with TestClient(app) as c:
        a = reg(c, "Owner")
        code = c.post("/api/lobby/link", headers=hdr(a)).json()["code"]
        agent = c.post("/api/lobby/link/redeem", json={"code": code}).json()
        assert c.get("/api/lobby/me", headers=hdr(agent)).status_code == 200
        pending = c.post("/api/lobby/link", headers=hdr(a)).json()["code"]
        assert c.post("/api/lobby/credentials/reset", headers=hdr(a)).json() == {"ok": True}
        assert c.get("/api/lobby/me", headers=hdr(agent)).status_code == 401                # linked agent signed out
        assert c.post("/api/lobby/link/redeem", json={"code": pending}).status_code == 404  # unused code dies too
        assert c.get("/api/lobby/me", headers=hdr(a)).status_code == 200                    # the caller stays in
        # an agent may also be the one to reset: then the browser is the one signed out
        code = c.post("/api/lobby/link", headers=hdr(a)).json()["code"]
        agent2 = c.post("/api/lobby/link/redeem", json={"code": code}).json()
        c.post("/api/lobby/credentials/reset", headers=hdr(agent2))
        assert c.get("/api/lobby/me", headers=hdr(a)).status_code == 401
        assert c.get("/api/lobby/me", headers=hdr(agent2)).status_code == 200


def test_agent_stream_stops_dispatch_after_sign_out():
    lob = rt.lobby
    p = lob.register("Owner", "")
    code, _ = lob.create_link(p)
    _, secret = lob.redeem_link(code)
    from server.lobby import _hash
    assert lob.has_credential(p.id, _hash(secret))
    lob.reset_credentials(p, p.secret)
    assert not lob.has_credential(p.id, _hash(secret)) and lob.has_credential(p.id, _hash(p.secret))


def test_agent_streams_are_capped_per_network(monkeypatch):
    monkeypatch.setattr(guard, "MAX_AGENT_STREAMS_PER_IP", 0)
    with TestClient(app) as c:
        a = reg(c, "Capped")
        r = c.get("/api/lobby/agent/stream", headers=hdr(a))
        assert r.status_code == 429
        assert guard.streams.open.get("agent:" + a["player"]["id"]) is None            # per-player slot released


def test_sign_out_takes_other_agents_offline_without_grace():
    t = [0.0]
    hub = AgentHub(clock=lambda: t[0])
    hub.connect("p", "agent")
    hub.connect("p", "browser-agent")
    hub.sign_out("p", keep="browser-agent")
    assert hub.online("p")                         # the kept credential's stream is still live
    hub.disconnect("p", "browser-agent")
    t[0] += 1
    assert hub.online("p")                         # ...and gets the usual grace when it drops
    t[0] += GRACE
    hub.disconnect("p", "agent")                   # the signed-out stream finally closes: no new grace
    assert not hub.online("p")
    hub2 = AgentHub(clock=lambda: t[0])
    hub2.connect("q", "a")
    hub2.sign_out("q", keep="other")
    assert not hub2.online("q")
