"""Mega Kangaskhan ex + Crustle デッキ知識(上位ラダー新型・妨害耐久)。

上位ラダー抽出(2026-07-07, 1200-1309点帯で24面中5=2番手)。勝ち筋:
- Mega Kangaskhan ex(300, 逃げ3): Run Errand(active時ドロー2)+Rapid-Fire Combo ●●● 200+コイン表×50
- Crustle(150): Mysterious Rock Inn=**Pokémon {ex}からのダメージを全て防ぐ**(エンジン実測:
  Jetting(Mega ex)→0/Nebula(効果無視)→貫通)。ex主体デッキへのハードカウンター壁。
  Superb Scissors {G}●● 120(相手activeの効果無視)
- 特殊エネ12(Mist/Spiky/Grow Grass)+妨害(Petrel/Eri/Xerosic/Handheld Fan)+Jumbo Ice Cream×4

壁の成立はPLANノブでなくエンジン意味論(_ex_shield_blocks: 脅威評価がex遮断を知る=
Crustleが「ex相手に不死」と正しく評価され自然に前へ残る)。PLANはノブ最小主義。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot
from ..cards import load_cards

DECK_CSV = "decks/kangaskhan.csv"

MEGA_KANGA, DWEBBLE, CRUSTLE = 756, 344, 345

import dataclasses as _dc

from ..bots.universal_bot import infer_plan as _infer

from pathlib import Path as _P
_deck = [int(x) for x in (_P(__file__).resolve().parents[2] / DECK_CSV).read_text().split() if x.strip()]
_base = _infer(_deck)
PLAN = _dc.replace(
    _base,
    name="Kangaskhan",
    # Crustleは攻撃役(120)かつex遮断壁=主役線として扱う(inferの主役集中50%規則が
    # Kangaskhan単独に寄せる場合の補正)。カード価値はinfer準拠。
    attackers=tuple(sorted(set(_base.attackers) | {MEGA_KANGA, CRUSTLE})),
    # Dwebble/Crustle線は3枚: 壁の回転を想定しcapは設けない(exデッキ相手は複数壁が正)
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 4,                    # Boss's Orders ×4(最大搭載)
    "max_line_damage": 200,             # Rapid-Fire Combo基礎(コインで+50×)
    "spread": 0,
    "bases": (DWEBBLE,),
    "ex_shield": (CRUSTLE,),            # ex遮断壁=効果無視技(Nebula)か非exでしか触れない
    "hand_disruption": 2,               # Eri/Xerosic/Petrel系
}


# ==== 検収側: IDENTITY ====
def identity_metrics(games, C=None, NAME=None):
    """Kangaskhanらしさ: ①Mega KangaskhanのT5着地 ②攻撃機会 ③対ex時にCrustleが前
    (壁運用) ④エネ配分(主役線へ)。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    for g in games:
        kanga_turn = None
        wall_hits = [0, 0]   # [Crustle前, 対ex対面の機会]
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            opp = cur["players"][1 - cur["yourIndex"]]
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            ids_play = [sp.get("id") for sp in
                        [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]
            if kanga_turn is None and MEGA_KANGA in ids_play:
                kanga_turn = tn
            oa = (opp.get("active") or [None])[0]
            oc = C.get((oa or {}).get("id"))
            act = (me.get("active") or [None])[0]
            if oc and "ex" in (oc.rule or "").lower() and act and CRUSTLE in ids_play:
                wall_hits[1] += 1
                if act.get("id") == CRUSTLE:
                    wall_hits[0] += 1
            if s.get("type") != 0:
                continue
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
        m["①Mega KangaskhanT5までに着地"][1] += 1
        if kanga_turn is not None and kanga_turn <= 5:
            m["①Mega KangaskhanT5までに着地"][0] += 1
        m["③対ex時Crustle前(壁運用)"][0] += wall_hits[0]
        m["③対ex時Crustle前(壁運用)"][1] += wall_hits[1]
    return m
