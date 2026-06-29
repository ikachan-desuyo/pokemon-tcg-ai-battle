"""Iwapa（イワパレス＋マシマシラ）専用 bot。

回し方の方針: イシズマイ→イワパレスを立てつつ、マシマシラ(悪エネ)のダメカン移動と
ボスの指令で相手を崩す。エネは悪をマシマシラへ、攻撃役へ集約。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="Iwapa",
    go_first=True,
    attackers=(345, 112, 344),                 # イワパレス / マシマシラ
    key_cards=(345, 344, 112),
    preferred_attacks=(),
    energy_rules=((7, 112), (None, 345)),  # 悪→マシマシラ, 任意→イワパレス
    play_priority={344: 82, 112: 84, 970: 70},  # イシズマイ/マシマシラ/キチキギス
    card_values={345: 100, 112: 85, 344: 70},
    est_var_damage=True,   # 可変ダメージ技を評価（A/Bで +0.082）
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
    smart_take=True,               # ポケギアの取得を効果×盤面で選ぶ（共通ノブ A/B +0.042）
    strict_lillie_guard=True,      # コンボ素材(マシマシラ等)を抱えるため、キー所持時はリーリエ抑制（緩和は -0.025）
)


class IwapaBot(DeckBot):
    plan = PLAN
