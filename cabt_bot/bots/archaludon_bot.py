"""Archaludon（ブリジュラスex / 鋼軸）専用 bot。

回し方の方針: ジュラルドン→ブリジュラスex(1進化, HP300)を立てる。
ブリジュラスex の特性「ごうきんビルド」(進化時にトラッシュから基本【鋼】エネを2枚加速)
が火力エンジン。＝先に鋼エネをトラッシュへ置いてから進化すると、メタルディフェンダー
(鋼3=220)を最速で起動できる。非exブリジュラス(170)の特性で鋼ポケは逃げエネ0=自由入替。

TODO(作り込み): ハイパボ等で鋼エネを意図的にトラッシュへ送ってから進化し、
ごうきんビルドの加速を最大化するカスタムロジック（現状は設定のみ）。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="Archaludon",
    go_first=True,
    attackers=(190, 170, 169),            # ブリジュラスex / ブリジュラス / ジュラルドン
    key_cards=(190, 169),
    preferred_attacks=(),
    energy_rules=((8, 190), (8, 170), (None, 190)),  # 鋼→ブリジュラス
    play_priority={169: 84, 190: 86, 1205: 88},  # ジュラルドン/ブリジュラスex/シアノ
    card_values={190: 100, 170: 84, 169: 80, 8: 84},
    lethal=True,
    est_var_damage=True,
    smart_take=True,
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
)


class ArchaludonBot(DeckBot):
    plan = PLAN
