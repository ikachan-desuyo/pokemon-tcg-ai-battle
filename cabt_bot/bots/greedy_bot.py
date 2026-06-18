"""簡単なヒューリスティック bot。

OptionType をもとに「攻撃できるなら攻撃、できなければ進化/エネ付け、
最後にターン終了」といった素朴な優先順位で1手を選ぶ。
複数選択 (max_count > 1) が要求された場面では先頭から必要数を取る。

あくまで RandomBot より少し賢いだけのサンプル。本格的な思考ルーチンは
このクラスを差し替える形で実装すると良い。
"""

from __future__ import annotations

from ..enums import OptionType
from ..models import Observation, Option
from .base import Bot

# 1手選択時の OptionType 優先度（大きいほど優先）。
_PRIORITY: dict[OptionType, int] = {
    OptionType.ATTACK: 100,
    OptionType.ABILITY: 80,
    OptionType.EVOLVE: 70,
    OptionType.ATTACH: 60,
    OptionType.PLAY: 50,
    OptionType.RETREAT: 20,
    OptionType.YES: 10,
    OptionType.END: 5,
    OptionType.NO: 1,
}


def _score(opt: Option) -> int:
    if isinstance(opt.type, OptionType):
        return _PRIORITY.get(opt.type, 30)
    return 30  # 未知種別は中程度


class GreedyBot(Bot):
    def select(self, obs: Observation) -> list[int]:
        options = obs.options
        if not options:
            return []

        # 優先度の高い順に並べた添字。
        ranked = sorted(range(len(options)), key=lambda i: _score(options[i]), reverse=True)

        sel = obs.select
        lo = self.clamp_count(sel.min_count if sel else 1, obs)
        hi = self.clamp_count(sel.max_count if sel else 1, obs)
        k = max(lo, min(hi, 1)) if hi >= 1 else lo
        # max_count が大きい場面では下限ぶんだけ確実に取る。
        k = max(k, lo)
        return ranked[:k]
