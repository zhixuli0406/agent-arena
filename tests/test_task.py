"""task mode: automatic grading and matches for everyday/document tasks."""

from __future__ import annotations

from arena.engine import run_match
from arena.modes.task import check_output
from arena.types import AgentSpec, MatchConfig


def test_check_json_array():
    assert check_output({"kind": "json_keys", "min_items": 2}, '["a@x.com","b@y.com"]')
    assert check_output({"kind": "json_keys", "min_items": 2}, 'emails: ["a@x.com","b@y.com"] done')
    assert not check_output({"kind": "json_keys", "min_items": 2}, '["only@x.com"]')


def test_check_json_keys():
    assert check_output({"kind": "json_keys", "keys": ["name", "age"]}, '{"name":"a","age":1}')
    assert not check_output({"kind": "json_keys", "keys": ["name", "age"]}, '{"name":"a"}')


def test_check_regex_and_words():
    assert check_output({"kind": "regex", "pattern": r"\d{4}-\d{2}-\d{2}"}, "日期：2026-01-15")
    assert not check_output({"kind": "regex", "pattern": r"\d{4}-\d{2}-\d{2}"}, "沒有日期")
    assert check_output({"kind": "max_words", "n": 3}, "a b c")
    assert not check_output({"kind": "max_words", "n": 2}, "a b c")


def test_check_contains_all_any():
    assert check_output({"kind": "contains_all", "values": ["預算", "客戶"]}, "本季預算與客戶")
    assert not check_output({"kind": "contains_all", "values": ["預算", "客戶"]}, "只有預算")
    assert check_output({"kind": "contains_any", "values": ["盈餘", "客戶"]}, "談到客戶")


async def test_task_match(tmp_path):
    tasks = [
        {"id": "t1", "prompt": "抽 email 成 JSON 陣列", "context": "ann@a.com 與 bob@b.com", "check": {"kind": "json_keys", "min_items": 2}},
        {"id": "t2", "prompt": "摘要", "check": {"kind": "contains_all", "values": ["預算"]}},
    ]
    cfg = MatchConfig(
        mode="task", mode_config={"tasks": tasks}, ratings_path=str(tmp_path / "r.json"),
        agents=[
            AgentSpec(id="good", adapter="mock", model="g", prompt_author="x",
                      params={"answers": ['["ann@a.com","bob@b.com"]', "本季預算成長"]}),
            AgentSpec(id="bad", adapter="mock", model="b", prompt_author="y",
                      params={"answers": ["none", "略"]}),
        ],
    )
    rep = await run_match(cfg, runs_dir=str(tmp_path / "runs"))
    assert rep.status == "COMPLETE"
    assert 2.0 < rep.result.scores["good"] <= 3.0  # both correct + speed bonus
    assert rep.result.scores["bad"] == 0.0


def test_json_keys_array_items_must_have_keys():
    from arena.modes.task import check_output
    chk = {"kind": "json_keys", "keys": ["name"], "min_items": 1}
    assert not check_output(chk, "[1]")
    assert check_output(chk, '[{"name": "a"}]')


def test_json_keys_min_items_rejects_empty_object():
    from arena.modes.task import check_output
    assert not check_output({"kind": "json_keys", "min_items": 2}, "{}")
    assert check_output({"kind": "json_keys", "min_items": 2}, "[1, 2]")
