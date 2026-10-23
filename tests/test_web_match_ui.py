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
