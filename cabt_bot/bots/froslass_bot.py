"""Mega Froslass ex（メガユキメノコex861, 水・1進化）専用bot。

1位(ShumpeiNomura)の対戦相手ログから再構成した水デッキ。勝ち筋:
Snorunt860→メガユキメノコex861 に進化し、「うらみぶし[水1]＝相手手札枚数×50」で手札の多い相手を
咎める / 「アブソリュートスノー[水●●]＝150＋ねむり」。Mega Starmie ex(1031)混の水軸。
※観測35枚からの部分再構成（水エネ・基本枚数は補完）。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan

FROSLASS_PLAN = DeckPlan(
    name="Froslass",
    attackers=(861, 1031),                     # メガユキメノコex / メガスターミーex
    key_cards=(861, 860),
    energy_rules=((3, 861), (3, 1031)),        # 水→アタッカー
    play_priority={860: 84, 861: 90, 1030: 78, 1031: 88},
    card_values={861: 100, 1031: 92, 860: 84, 3: 80},
    lethal=True,
    est_var_damage=True,                       # うらみぶし(相手手札×50)の可変ダメージを推定
    boss_cards=(1182,),                        # ボスはKO時のみ
    recover_cards=(1097,),                     # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),                      # いれかえは攻撃役を前に出す時のみ
    smart_take=True,
)


class FroslassBot(DeckBot):
    plan = FROSLASS_PLAN
