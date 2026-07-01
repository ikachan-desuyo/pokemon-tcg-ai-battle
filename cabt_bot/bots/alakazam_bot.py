"""Alakazam（フーディン743, 超・2進化）専用bot。

1位(ShumpeiNomura)の対戦相手ログから再構成した超コンボデッキ。勝ち筋:
ドローエンジン(ノココッチ66=にげあしドロー / ヒカリ1231 / ヒルダ1225 / Poffin / ポケパッド)で
手札を最大化し、フーディンの「ハンドパワー[超1]＝手札枚数×2個のダメカン(=×20ダメージ)」で殴る。
進化線 Abra741→Kadabra742→フーディン743（ふしぎなアメ1079で加速）。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan

ALAKAZAM_PLAN = DeckPlan(
    name="Alakazam",
    attackers=(743, 66),                       # フーディン(ハンドパワー) / ノココッチ(ランドクラッシュ90)
    key_cards=(743, 741),
    energy_rules=((19, 743), (5, 743), (19, 66), (5, 66)),  # 超エネ(テレパス/基本)→アタッカー
    play_priority={741: 84, 743: 90, 66: 78, 305: 55, 65: 55},
    card_values={743: 100, 741: 88, 19: 85, 5: 80, 66: 78},
    lethal=True,
    est_var_damage=True,                       # ハンドパワー(手札×20)等の可変ダメージを効果文から推定
    boss_cards=(1182,),                        # ボスはKO時のみ
    recover_cards=(1097,),                     # 夜タンカは回収価値がある時のみ
    smart_take=True,
)


class AlakazamBot(DeckBot):
    plan = ALAKAZAM_PLAN
