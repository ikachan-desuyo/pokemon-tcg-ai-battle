"""Opponent Rollout 用の薄いインターフェース（Plan AI Episode 3）。

Planの評価を「特定デッキのbot」に直結させないための1枚の抽象。
evaluate_plan は相手手番で opponent.act(ob) だけを呼ぶ＝中身(DeckBot/ArchaludonBot/将来のUniversalBot)を
差し替えてもPlan側は不変。**新しいAnalyzerではない**（既存botをそのまま相手役に使うだけ）。
"""
from __future__ import annotations

import dataclasses

from .. import Observation
from ..enums import OptionType

_END = int(OptionType.END)


class OpponentPolicy:
    """相手手番の選択を返す薄い方策。ob = search forward model の生observation(dataclass)。"""
    def act(self, ob) -> list:
        raise NotImplementedError


class MinimalOpponent(OpponentPolicy):
    """最小行動（可能ならEND、強制選択は先頭）。Episode2までの基準＝相手の攻めを入れない。"""
    def act(self, ob) -> list:
        opt = ob.select.option if (ob.select and ob.select.option) else None
        if opt:
            for i, o_ in enumerate(opt):
                if getattr(o_, "type", None) == _END:
                    return [i]
        return [0]


class BotOpponent(OpponentPolicy):
    """既存bot(DeckBot等)を相手役に。相手も普通に打つ＝相手の攻めがPlanに入る。
    botは手番の観測から自分(yourIndex)を判断するので、相手手番の観測を渡せば相手として動く。"""
    def __init__(self, bot):
        self.bot = bot

    def act(self, ob) -> list:
        try:
            return self.bot.select(Observation.from_dict(dataclasses.asdict(ob))) or [0]
        except Exception:
            return [0]
