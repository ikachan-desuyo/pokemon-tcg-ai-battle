"""Observation のパースと bot の合法性に関する基本テスト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cabt_bot import Observation, OptionType, SelectType  # noqa: E402
from cabt_bot.bots import GreedyBot, RandomBot  # noqa: E402

SAMPLE_OBS = {
    "select": {
        "type": SelectType.MAIN,
        "minCount": 1,
        "maxCount": 1,
        "option": [
            {"type": OptionType.ATTACK, "attackId": 12, "index": 0},
            {"type": OptionType.RETREAT, "index": 0},
            {"type": OptionType.END},
        ],
    },
    "logs": [],
    "current": None,
    "search_begin_input": None,
}


def test_observation_parsing():
    obs = Observation.from_dict(SAMPLE_OBS)
    assert obs.select is not None
    assert obs.select.type == SelectType.MAIN
    assert len(obs.options) == 3
    assert obs.options[0].type == OptionType.ATTACK
    assert obs.options[0].attack_id == 12


def test_observation_missing_keys():
    obs = Observation.from_dict({})
    assert obs.select is None
    assert obs.options == []


def _assert_legal(indices, obs):
    sel = obs.select
    assert sel.min_count <= len(indices) <= sel.max_count
    assert len(set(indices)) == len(indices)  # 重複なし
    assert all(0 <= i < len(obs.options) for i in indices)


def test_random_bot_legal():
    obs = Observation.from_dict(SAMPLE_OBS)
    for seed in range(20):
        _assert_legal(RandomBot(seed=seed).select(obs), obs)


def test_greedy_bot_prefers_attack():
    obs = Observation.from_dict(SAMPLE_OBS)
    indices = GreedyBot().select(obs)
    _assert_legal(indices, obs)
    # ATTACK が最優先なので添字 0 を選ぶはず。
    assert indices == [0]


def test_multi_select():
    multi = {
        "select": {
            "type": SelectType.CARD,
            "minCount": 2,
            "maxCount": 2,
            "option": [{"type": OptionType.CARD, "index": i} for i in range(4)],
        }
    }
    obs = Observation.from_dict(multi)
    _assert_legal(RandomBot(seed=1).select(obs), obs)
    _assert_legal(GreedyBot().select(obs), obs)


def test_enum_values_match_official():
    # 公式 cg/api.py と一致していること（過去の推測誤りの回帰防止）。
    from cabt_bot import AreaType, EnergyType, SpecialConditionType
    assert AreaType.DECK == 1 and AreaType.ACTIVE == 4 and AreaType.BENCH == 5
    assert SpecialConditionType.POISON == 0 and SpecialConditionType.CONFUSE == 4
    assert EnergyType.COLORLESS == 0 and EnergyType.DRAGON == 9


def test_card_data_loads():
    from cabt_bot import card_name, load_cards
    cards = load_cards()
    assert len(cards) == 1267
    c = cards[30]
    assert c.name == "Magcargo ex" and c.hp == 270 and c.is_pokemon
    assert len(c.moves) == 3
    assert card_name(40) == "Greninja ex"


def test_agent_entrypoint_never_crashes():
    import main
    # 不正な observation でも例外を投げず list[int] を返す。
    out = main.agent({"select": {"option": [{"type": 14}], "minCount": 1, "maxCount": 1}})
    assert isinstance(out, list) and out == [0]
    # 壊れた入力でもフォールバックする。
    assert isinstance(main.agent({"select": {"option": [], "minCount": 0, "maxCount": 0}}), list)


if __name__ == "__main__":
    test_observation_parsing()
    test_observation_missing_keys()
    test_random_bot_legal()
    test_greedy_bot_prefers_attack()
    test_multi_select()
    test_enum_values_match_official()
    test_card_data_loads()
    test_agent_entrypoint_never_crashes()
    print("all tests passed")
