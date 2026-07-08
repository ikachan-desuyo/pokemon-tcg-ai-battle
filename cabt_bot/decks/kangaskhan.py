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
    # 妨害(Eri/Xerosic)=相手手札が肥えた時。Petrel(1219)は実測=山サーチ(妨害ではない)
    # →常用80点(Mega 88%調査の当初分類を実測で訂正)
    disruption_supporters=(1186, 1197),
    play_priority={**_base.play_priority, 1219: 80},
)


class Bot(DeckBot):
    plan = PLAN

    # K2(2026-07-08, 検証済み・不採用): 対Mega=1位フル蒸留(エネ31/31をCrustle集中+Kanga非露出)
    # をmatchup_planで実装しA/B → 10/100 vs 基準8-9%=中立。自mega bot(Nebula 210連鎖が完璧)には
    # Crustle 150の消耗戦が成立しない=対自megaは~10%が構造上限近傍。1位の1-2は「実ラダーの
    # 不完全なmega」相手の数字。kangaの伸び代は対Grimm(1位9-0 vs 自bot54%)等の別対面にある。


    # K3(2026-07-08): 対Grimm=1位の9-0蒸留。攻撃57/60・手貼り59/79をCrustle線に集中。
    # 機構は構造的: GrimmsnarlのSB(ex技)はRock Innに遮断=grimmの主砲が完全無効
    # (crustle_ogerponが自grimmに80%勝つのと同一機構)。Kanga(SBの2枚的)は出さない。
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.matchup_signatures = {"grimm": [648, 646]}
        self.matchup_plans = {"grimm": {
            "attackers": (344, 345),
            "energy_rules": ((18, 345), (14, 345), (11, 345), (1, 345)),
        }}


    # K4根治(2026-07-09): 型を考慮したエネ貼り順序をデッキ知識として明示。
    # 実測した3層問題: ①Crustle{G}●●の{G}枠に無色を積むと山のG5枚待ちで凍結
    # ②重退却のactiveがe0だと交代不能の牢獄 ③70HP進化前への投資が敵圧で蒸発。
    # 方針: G系はCrustle線の{G}枠へ最優先/無色はKanga(●●●)か「G済みCrustle」の仕上げへ。
    # 汎用keyの外科手術は相互作用で3連続失敗(K4)→デッキ固有ロジックとしてdecks層に置く。
    G_LIKE = (1, 18)          # Basic{G}, Grow Grass
    LINE = (344, 345)         # Dwebble, Crustle

    def _pick_attach(self, idxs, options, hand, me):
        from ..bots.deck_bot import AreaType

        def spot_of(op):
            spots = (me.get("active") if op.in_play_area == AreaType.ACTIVE else me.get("bench")) or []
            i = op.in_play_index
            return spots[i] if i is not None and 0 <= i < len(spots) else None

        def has_g(sp):
            return any(self._energy_provides_syms(ec.get("id"), sp.get("id")) == ["G"]
                       or "G" in self._energy_provides_syms(ec.get("id"), sp.get("id"))
                       for ec in (sp.get("energyCards") or []))

        best = None   # (priority, invested, is_active, idx)
        for i in idxs:
            op = options[i]
            energy = self._hand_id(hand, op.index)
            if not self._is_energy(energy):
                continue
            sp = spot_of(op)
            if not sp:
                continue
            tid = sp.get("id")
            syms = self._energy_provides_syms(energy, tid)
            inv = len(sp.get("energyCards") or [])
            pri = None
            if "G" in syms and tid in self.LINE and not has_g(sp):
                pri = 5                     # G→{G}枠が空のCrustle線(最優先)
            elif "G" not in syms and tid == 345 and has_g(sp) and inv < 3:
                pri = 4                     # 無色→G済みCrustleの仕上げ(●●)
            elif "G" not in syms and tid == 756 and inv < 3:
                pri = 3                     # 無色→Kanga(●●●=何でも可)
            elif "G" in syms and tid == 756 and inv < 3:
                pri = 1                     # GをKangaに使うのは最後(希少資源の温存)
            if pri is not None:
                cand = (pri, inv, 1 if op.in_play_area == AreaType.ACTIVE else 0, i)
                if best is None or cand > best:
                    best = cand
        if best is not None:
            return best[3]
        return super()._pick_attach(idxs, options, hand, me)


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
