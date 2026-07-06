"""Alakazam (Powerful Hand) デッキ知識(1位ログ由来の超コンボ)。

勝ち筋: Powerful Hand {P} = 手札1枚につきダメカン2個(=手札×20点)。手札17枚で340=メガ一撃。
アイデンティティは「手札を抱えて育てる」: ドロー特性(サイコドロー=進化時/ノシメドロー=
ドュデュンスパルス自身を山に戻して3ドロー/フェザンのFlip the Script)を回し続け、
不要な手札消費(余分なベンチ置き・余分なエネ貼り)=打点の切り売りをしない。
シェイミ(フラワーカーテン)がルールボックス無しベンチを技ダメージから守る(対スプラッシュ)。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

DECK_CSV = "decks/alakazam.csv"

ABRA, KADABRA, ALAKAZAM = 741, 742, 743
DUNSPARCE, DUDUNSPARCE, FEZ, SHAYMIN = 65, 66, 140, 343
P_ENERGY, TELEPATH = 5, 19
CAPE, BOSS, NIGHT_STRETCHER, SACRED_ASH = 1159, 1182, 1097, 1129
LINE = (ABRA, KADABRA, ALAKAZAM)

# ==== 操縦側: PLAN(Phase7卒業形 = infer_plan(deck) + 薄い差分) ====
# 卒業証書(2026-07-06, N=50検収): Universal 76-80% ≒ 旧手書きPLAN 78% = Gap 2(分解能内)。
# 蒸留済み: conserve_hand(手札=打点)/「1ターン1回」cap(フェザン)/P集中/コンボ素材保持。
import dataclasses as _dc

from ..bots.universal_bot import infer_plan as _infer

_deck = [int(x) for x in open(DECK_CSV).read().split() if x.strip()]
_base = _infer(_deck)
PLAN = _dc.replace(
    _base,
    name="Alakazam",
    # 差分①(デッキ固有): コンボ系はドロー枚数(後攻8枚)優先
    go_first=False,
    # 差分②(デッキ固有): 主技はPH(火力推定では他技と拮抗するため明示)
    preferred_attacks=("Powerful Hand",),
    # 差分③(データ欠如=固有): Telepathエネはtype欄が無くpayability導出不能(Comfey監査の既知問題)
    energy_rules=((19, 743),) + tuple(_base.energy_rules),
    # 差分④(Residual候補: 開幕壁条件): アタッカー線を晒さない非土台壁
    setup_wall=(65,),
    # 差分⑤(一般化候補: 静的特性cap): シェイミ(フラワーカーテン)1体/ドュンスパルス2体
    dup_play_caps={**_base.dup_play_caps, 343: 1, 65: 2},
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 1,
    "variable_damage": "hand",             # PH=手札×20点(手札成長+4〜5/ターン)。確殺圏は手札で動く
    "max_line_damage": 400,                # 手札20枚時のPH(実測は相手手札枚数から都度計算)
    "bases": (ABRA,),                      # 土台=進化前狩りの標的(HP50=スプラッシュ圏)
    "bench_shield": SHAYMIN,               # フラワーカーテン=非ルールボックスのベンチを技から守る
}


# ==== 検収側: IDENTITY ====
def identity_metrics(games, C=None, NAME=None):
    """Alakazamらしさ: ①手札を抱える(攻撃時10枚+) ②攻撃機会 ③エネはアタッカー線へ
    ④アラカザムT5確立 ⑤ドロー特性の活用。①=手札温存全般 ③=energy_rules ④=立ち上げの検収。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    def _in_play(me):
        return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]

    for g in games:
        zam_turn = None
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            names = [NAME.get(sp.get("id"), "?") for sp in _in_play(me)]
            if zam_turn is None and "Alakazam" in names:
                zam_turn = tn
            if s.get("type") != 0:
                continue
            hand = me.get("hand") or []
            # ② 攻撃機会を逃さない
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
                # ① 手札を抱える: 攻撃時(=手札消費が終わった時点)の手札10枚+ = PH200点+
                if ch.get("type") == 13:
                    m["①攻撃時に手札10枚+"][1] += 1
                    if len(hand) >= 10:
                        m["①攻撃時に手札10枚+"][0] += 1
            # ③ エネ配分: attach対象がアラカザム線
            if ch.get("type") == 8 and ch.get("index") is not None and ch["index"] < len(hand):
                cid = hand[ch["index"]].get("id")
                ci = C.get(cid)
                if ci and "Energy" in (ci.name or ""):
                    m["③エネはアラカザム線へ"][1] += 1
                    area = ch.get("inPlayArea")
                    idx = ch.get("inPlayIndex")
                    spots = (me.get("active") if area == 4 else me.get("bench")) or []
                    tgt = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                    if tgt and tgt.get("id") in LINE + (DUDUNSPARCE, FEZ):
                        m["③エネはアラカザム線へ"][0] += 1
            # ⑤ ドロー特性の活用(Run Away Draw / Flip the Script): ABILITY(10)を後回しにしない
            ab_opt = any(op.get("type") == 10 for op in opts)
            if ab_opt and ch.get("type") in (10, 13, 14):
                m["⑤ドロー特性の活用"][1] += 1
                if ch.get("type") == 10:
                    m["⑤ドロー特性の活用"][0] += 1
        # ④ 立ち上げ(ゲーム単位)
        m["④アラカザムT5までに着地"][1] += 1
        if zam_turn is not None and zam_turn <= 5:
            m["④アラカザムT5までに着地"][0] += 1
    return m
