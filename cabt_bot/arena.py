"""ローカル対戦アリーナ（公式エンジン cg/ を直接利用）。

kaggle-environments を介さず、cg.game の battle_start/battle_select で
2 つのエージェント関数を対戦させる。デッキ最適化や bot の自己対戦に使う。

前提: リポジトリ直下に公式エンジン cg/（コンペ配布物・git 管理外）があること。
cg/ は input_data 展開先からコピーしておく:
    cp -r input_data/extracted/.../cg ./cg

エージェント関数は提出と同じシグネチャ: agent(obs_dict: dict) -> list[int]
（obs.select が None のデッキ選択フェーズはここでは発生しない。デッキは引数で渡す）
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parent.parent

Agent = Callable[[dict], list[int]]


def _ensure_cg_importable() -> None:
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))


@dataclass
class MatchResult:
    winner: int  # 0 / 1、引き分けは 2、未決着は -1
    turns: int
    steps: int
    reason: int | None = None  # RESULT ログの reason（判明すれば）

    @property
    def is_draw(self) -> bool:
        return self.winner == 2


def _legal_fallback(select: dict) -> list[int]:
    n = len(select.get("option", []))
    k = min(max(1, int(select.get("minCount", 1))), n)
    return list(range(k))


def run_match(
    agent0: Agent,
    agent1: Agent,
    deck0: list[int],
    deck1: list[int],
    max_steps: int = 5000,
) -> MatchResult:
    """2 エージェントを 1 試合対戦させ結果を返す。"""
    _ensure_cg_importable()
    from cg.api import to_observation_class
    from cg.game import battle_finish, battle_select, battle_start

    agents = (agent0, agent1)
    obs, _sd = battle_start(deck0, deck1)
    if obs is None:
        raise RuntimeError("battle_start に失敗しました（デッキが不正な可能性）。")

    last_turn = 0
    try:
        for step in range(1, max_steps + 1):
            o = to_observation_class(obs)
            state = o.current
            if state is not None:
                last_turn = state.turn
                if state.result != -1:
                    return MatchResult(winner=state.result, turns=state.turn, steps=step)
            if o.select is None or len(o.select.option) == 0:
                break
            who = state.yourIndex if state is not None else 0
            try:
                sel = agents[who](obs)
            except Exception:
                sel = _legal_fallback(obs["select"])
            obs = battle_select(sel)
        return MatchResult(winner=-1, turns=last_turn, steps=max_steps)
    finally:
        battle_finish()


def run_series(
    agent0: Agent,
    agent1: Agent,
    deck0: list[int],
    deck1: list[int],
    games: int = 100,
    seed: int | None = None,
) -> dict:
    """複数試合を回し勝率を集計する（先後はゲーム毎に入れ替え）。"""
    _ = random.Random(seed)  # 予約（将来の先後ランダム化用）
    wins = [0, 0]
    draws = 0
    for g in range(games):
        # 先後を入れ替えて偏りを減らす。
        if g % 2 == 0:
            r = run_match(agent0, agent1, deck0, deck1)
            w = r.winner
        else:
            r = run_match(agent1, agent0, deck1, deck0)
            w = (1 - r.winner) if r.winner in (0, 1) else r.winner
        if w == 2 or w == -1:
            draws += 1
        else:
            wins[w] += 1
    total = max(1, games - draws)
    return {
        "games": games,
        "agent0_wins": wins[0],
        "agent1_wins": wins[1],
        "draws": draws,
        "agent0_winrate": wins[0] / total,
    }
