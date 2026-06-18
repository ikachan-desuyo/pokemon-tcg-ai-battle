"""Bot の基底クラス。

サブクラスは `select()` を実装し、与えられた選択肢の中から選んだ
インデックスのリストを返す。インデックスは `Observation.options` に対する
0 始まりの添字で、要素数は `min_count <= len <= max_count` を満たすこと。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Observation


class Bot(ABC):
    """対戦エージェントの基底クラス。"""

    @abstractmethod
    def select(self, obs: Observation) -> list[int]:
        """選択肢インデックスのリストを返す。"""
        raise NotImplementedError

    def on_search_begin(self, obs: Observation) -> str | None:
        """探索開始時、相手の予想デッキ等を返す（任意・未使用なら None）。"""
        return None

    def __call__(self, obs: Observation) -> list[int]:
        return self.select(obs)

    # ----- 共通ユーティリティ ---------------------------------------

    @staticmethod
    def clamp_count(n: int, obs: Observation) -> int:
        """選ぶ個数を [min_count, max_count] かつ選択肢数以内に収める。"""
        sel = obs.select
        if sel is None:
            return 0
        lo = max(0, sel.min_count)
        hi = min(sel.max_count, len(sel.options))
        return max(lo, min(n, hi))
