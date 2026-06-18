"""ランダムに合法手を選ぶベースライン bot。

公式ドキュメントの最小例:
    random.sample(range(len(options)), maxCount)
を、min/max と選択肢数に対して安全になるよう整えたもの。
"""

from __future__ import annotations

import random

from ..models import Observation
from .base import Bot


class RandomBot(Bot):
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def select(self, obs: Observation) -> list[int]:
        n_options = len(obs.options)
        if n_options == 0:
            return []
        # min..max の範囲でランダムに個数を決める（多くの選択は max=1）。
        sel = obs.select
        lo = self.clamp_count(sel.min_count if sel else 1, obs)
        hi = self.clamp_count(sel.max_count if sel else 1, obs)
        k = self._rng.randint(lo, hi) if hi >= lo else lo
        return self._rng.sample(range(n_options), k)
