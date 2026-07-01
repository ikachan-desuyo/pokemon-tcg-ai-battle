"""Dark Control（メガズルズキンex896, 悪・1進化）専用bot。

Control/リソース否定の原理を代表するベンチマーク。勝ち筋:
高耐久(HP330＝Nebula 210を耐える)のメガズルズキンexで「アウトローレッグ[悪悪●]160＋相手手札を1枚
トラッシュ＋山札1枚削り」を毎ターン叩き込み、**相手のドローエンジン/リソースを削りながら殴る**。
進化前ズルッグ895も「はたきおとす」で手札破壊。Judge(1213)も併用して手札干渉。
弱点は草（Mega Starmieは水＝弱点無し）。攻撃しながら妨害する型なので汎用DeckBotで実行可能。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan

SCRAFTY_PLAN = DeckPlan(
    name="Scrafty",
    attackers=(896, 140),                      # メガズルズキンex / フェザンディピティex(悪の補助)
    key_cards=(896, 895),
    energy_rules=((7, 896), (7, 140)),         # 基本悪→アタッカー
    play_priority={895: 84, 896: 90, 140: 70},
    card_values={896: 100, 895: 86, 7: 82, 140: 70},
    lethal=True,
    boss_cards=(1182,),                        # ボスはKO時のみ
    recover_cards=(1097,),                     # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),                      # いれかえは攻撃役を前に出す時のみ
    smart_take=True,
)


class ScraftyBot(DeckBot):
    plan = SCRAFTY_PLAN
