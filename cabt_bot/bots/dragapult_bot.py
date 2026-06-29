"""Dragapult ex 専用 bot（ばらまき）。

回し方の方針: ドラメシヤ→(ふしぎなアメ)→ドラパルトex を立て、ファントムダイブ
(200＋ベンチに6ダメカン) でばらまき。ヨノワール/サマヨールのカースドボムや
マシマシラ(悪エネ)のダメカン移動と合わせて多面KO。エネは炎+超をドラパルトへ、
悪をマシマシラへ。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="Dragapult",
    go_first=True,
    attackers=(121, 120, 119),                 # ドラパルトex / ドロンチ
    key_cards=(121, 119),                 # ドラパルトex / ドラメシヤ
    preferred_attacks=("Phantom Dive",),
    energy_rules=((7, 112), (None, 121)),  # 悪→マシマシラ, 任意→ドラパルト
    play_priority={119: 82, 131: 80, 112: 84},  # ドラメシヤ/ヨマワル/マシマシラを展開
    card_values={121: 100, 112: 80, 133: 78, 119: 70},
)


class DragapultBot(DeckBot):
    plan = PLAN
