"""Crustle二重壁デッキ知識(実ラダー上位、sub 54405730系 / episode 84619410から採取 2026-07-08)。

上位1043点grimmを2-0で完封した対grimm構造カウンター。二重壁:
  - イワパレス(345) Rock Inn: 相手のポケモンexからワザのダメージを受けない
  - オーガポン いしずえのめんex(117): 相手の特性を持つポケモンからワザのダメージを受けない
grimmの主力は全員ex or 特性持ち(オーロンゲ=ex+特性/マシマシラ/キチキギス/ノココッチ)のため
素のYveltal等しか通らない。ダメージ源はマシマシラ(Adrena-Brain=ダメカン3個移動)+
ジャンボアイス(エネ3+のバトポケHP80回復)の消耗戦。攻撃技は両壁とも効果無視
(グレートシザー120/ぶちやぶる140=「かかっている効果を計算しない」)。
イシズマイ(344)のかくせい(●)=山から進化を乗せる自己進化=準備技。
PLANはノブ最小主義(Universalの素の挙動を信頼)。
"""
from __future__ import annotations

import dataclasses as _dc
from pathlib import Path as _P

from ..bots.deck_bot import DeckBot
from ..bots.universal_bot import infer_plan as _infer

DECK_CSV = "decks/crustle_wall.csv"

DWEBBLE, CRUSTLE = 344, 345
OGERPON, MUNKIDORI, ARTICUNO = 117, 112, 414

_deck = [int(x) for x in (_P(__file__).resolve().parents[2] / DECK_CSV).read_text().split() if x.strip()]
_base = _infer(_deck)
PLAN = _dc.replace(
    _base,
    name="CrustleWall",
    # かくせい(Ascension系=山から進化を乗せる)は準備技: 火力が立つ前はこれで壁を立てる。
    # attackIdはAscension同名系を全登録(同一意味論。Dwebbleの個体idはエンジン内部で解決)
    setup_attacks=tuple(set(_base.setup_attacks) | {39, 234, 478, 620, 1262}),
    # 静的壁特性は1体で充足しない(壁は複数枚並べて釣り出しに備える)が、
    # オーガポンexは2枚积みでベンチ温存が正しい→キャップなし(素の挙動)
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 0,
    "max_line_damage": 140,                 # ぶちやぶる(闘●●・効果無視)/グレートシザー120(効果無視)
    "spread": 0,
    "bases": (DWEBBLE, OGERPON, MUNKIDORI, ARTICUNO),
    "ability_damage": {MUNKIDORI: 30},      # Adrena-Brain(ダメカン3個移動)
    "hand_disruption": 0,
    # 二重壁: Crustle=ex技無効 / Cornerstone Ogerpon=特性持ちの技無効。
    # 攻略はどちらにも当たらない「素の非ex・無特性」アタッカーかベンチ狙撃・エンジン破壊
    "walls": {CRUSTLE: "ex", OGERPON: "ability"},
}
