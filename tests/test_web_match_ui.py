"""Static contract tests for the dependency-free spectator and result UI."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_match_ui_has_public_summary_timeline_and_cinematic_result_structure():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/match.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/lobby.css").read_text(encoding="utf-8")
    fx = (ROOT / "web/js/fx.js").read_text(encoding="utf-8")

    for element_id in ("resScene", "resChampion", "resPodium", "resMoment"):
        assert f'id="{element_id}"' in html
    assert 'ev.type === "commentary"' in js
    assert "public_summary" in js and "textContent" in js
    assert ".result-scene" in css and ".thought" in css
    assert "ceremony" in fx and "prefers-reduced-motion" in fx


def test_match_ui_does_not_render_public_summary_as_html():
    js = (ROOT / "web/js/match.js").read_text(encoding="utf-8")
    assert "thought.innerHTML" not in js
    assert "summary.innerHTML" not in js


def test_live_player_count_stays_visible_on_narrow_screens():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/lobby.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/lobby.css").read_text(encoding="utf-8")

    assert 'class="pill online-pill"' in html
    assert 'id="onlinePill"' in html and 'aria-live="polite"' in html
    assert 'id="onlineDot"' in html and 'class="online-label"' in html
    assert 'href="css/lobby.css?v=20261024.1"' in html
    assert 'src="js/i18n.js?v=20261024.3"' in html
    assert 'src="js/agent.js?v=20261024.3"' in html
    assert 'src="js/lobby.js?v=20261024.1"' in html
    assert 'value !== null && Number.isFinite(n)' in js
    assert 'const next = ok ? fmtNum(count) : "–"' in js
    assert 'if ($("stOnline").textContent !== next)' in js
    assert '.online-pill .online-label{display:none}' in css
    assert '.pill.opt,.me .sub' not in css


def test_agent_setup_uses_installed_commands_and_explains_live_verification():
    agent = (ROOT / "web/js/agent.js").read_text(encoding="utf-8")
    i18n = (ROOT / "web/js/i18n.js").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'outprompt-mcp = "clients.arena_mcp:main"' in project
    assert 'outprompt-connect = "clients.arena_connect:main"' in project
    assert "archive/refs/heads/main.zip" in agent
    assert 'claude mcp add --scope user outprompt --' in agent
    assert 'codex mcp add outprompt --' in agent
    assert "arena_mcp.py" not in agent
    assert "arena_connect.py" not in agent
    assert "ag_verify" in agent
    assert "arena_status" in i18n


def test_agent_setup_keeps_browser_and_agent_on_one_player_identity():
    agent = (ROOT / "web/js/agent.js").read_text(encoding="utf-8")
    i18n = (ROOT / "web/js/i18n.js").read_text(encoding="utf-8")
    readme = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")

    assert 'const who = ["--link", link.code]' in agent
    assert '"--name", sq(t("cmd_name"))' not in agent
    assert 'if (!signedIn)' in agent and 'ag_enter_first' in agent
    assert "網頁與代理一定是同一個身分" in i18n
    assert "必須請代理呼叫 `arena_website_link`" in readme
