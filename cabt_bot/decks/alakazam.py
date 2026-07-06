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

# ==== 操縦側: PLAN ====
PLAN = DeckPlan(
    name="Alakazam",
    go_first=False,                        # ドロー枚数(後攻8枚)重視のコンボ系
    attackers=(ALAKAZAM, DUDUNSPARCE, FEZ),
    key_cards=(ALAKAZAM, KADABRA, ABRA),
    preferred_attacks=("Powerful Hand",),
    energy_rules=((TELEPATH, ALAKAZAM), (P_ENERGY, ALAKAZAM), (None, ABRA)),
    play_priority={ABRA: 86, DUNSPARCE: 76, SHAYMIN: 70, FEZ: 66},
    card_values={ALAKAZAM: 100, KADABRA: 88, ABRA: 85, DUNSPARCE: 62, SHAYMIN: 58},
    lethal=True,
    reposition=True,
    hp_boost_tools={CAPE: 100},
    boss_cards=(BOSS,),
    recover_cards=(NIGHT_STRETCHER, SACRED_ASH),
    smart_take=True,
    setup_wall=(DUNSPARCE,),               # 開幕はドュンスパルスを壁に(アタッカー線を晒さない)
    dup_play_caps={SHAYMIN: 1, FEZ: 1, DUNSPARCE: 2},
    conserve_hand=True,               # 手札=打点(PH)。コストを進めないエネ貼り/超過展開をしない
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
