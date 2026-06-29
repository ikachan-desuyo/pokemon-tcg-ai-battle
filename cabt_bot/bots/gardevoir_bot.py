"""Mega Gardevoir ex（メガサーナイトex）専用 bot。

回し方の方針: ラルテス→キルリア→(ふしぎなアメ)→メガサーナイトex を立て、
「あふれるねがい」(山札からベンチ全員に基本超エネを1枚ずつ＝盤面一括加速)で
盤面の超エネを育ててから、「メガシンフォニア」(自分の全ポケの超エネ数×50)で
大ダメージを通す。キルリア「コールサイン」/シアノ/メガシグナルでサーチ。
エネは超をサーナイト線へ。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="MegaGardevoir",
    go_first=True,
    attackers=(747, 746, 745),            # メガサーナイトex / キルリア / ラルトス
    key_cards=(747, 746),
    preferred_attacks=(),
    energy_rules=((5, 747), (None, 747)),  # 超→メガサーナイトex
    play_priority={745: 80, 746: 80, 1079: 90},  # ラルトス/キルリア/ふしぎなアメ
    card_values={747: 100, 746: 84, 745: 80, 5: 84},
    lethal=True,
    est_var_damage=True,           # メガシンフォニア(超×50)等の可変技を評価
    smart_take=True,               # ポケギア等のサポ取得を効果×盤面で
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
    setup_attack=1078,             # 「あふれるねがい」(加速技)。火力が弱い序盤に盤面エネを育てる
    setup_attack_until=2,          # 盤面エネ<2 の間だけ加速（以降はメガシンフォニアへ。A/B: until=2が最良）
)


class MegaGardevoirBot(DeckBot):
    plan = PLAN
