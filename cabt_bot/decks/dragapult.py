"""Dragapult ex デッキ知識(ダメカン撒き/多面KO)。

勝ち筋: ドラメシヤ→(ふしぎなアメ)→ドラパルトex(320)。Phantom Dive {R}{P} 200+ベンチに
ダメカン6個(任意配分)で多面を育て、ヨノワール線のカースドボム(5/13個・自滅)と
マシマシラ(悪エネ+Adrena-Brain=ダメカン3個移動)で〆る。Tera=ベンチのドラパルトは
技ダメージを受けない(2体目はベンチで無敵待機)。二色コスト(R+P)の正確な貼り分けが生命線。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

DECK_CSV = "decks/dragapult.csv"

DREEPY, DRAKLOAK, DRAGAPULT = 119, 120, 121
MUNKIDORI, DUSKULL, DUSCLOPS, DUSKNOIR = 112, 131, 132, 133
R_E, P_E, D_E = 2, 5, 7
BOSS, NIGHT_STRETCHER, SWITCH = 1182, 1097, 1123
LINE = (DREEPY, DRAKLOAK, DRAGAPULT)

# ==== 操縦側: PLAN(旧DragapultBotのPLANをベースにBenchmark Phase強化) ====
PLAN = DeckPlan(
    name="Dragapult",
    go_first=True,
    attackers=(DRAGAPULT, DRAKLOAK, DREEPY),
    key_cards=(DRAGAPULT, DREEPY),
    preferred_attacks=("Phantom Dive",),
    energy_rules=((D_E, MUNKIDORI), (None, DRAGAPULT)),  # 悪→マシマシラ、他(R/P)→ドラパルト
    play_priority={DREEPY: 86, MUNKIDORI: 84, DUSKULL: 80},
    card_values={DRAGAPULT: 100, DREEPY: 90, DRAKLOAK: 72, DUSKNOIR: 78, MUNKIDORI: 76},
    # ↑土台ドラメシヤ>支援ポケ。card_valuesはattackers既定(95)を上書きするため、
    #   DREEPYを低く書くとUltra Ballがマシマシラを優先し竜線が立たない(precision読みで実証)
    lethal=True,
    reposition=True,
    boss_cards=(BOSS,),
    recover_cards=(NIGHT_STRETCHER,),
    switch_cards=(SWITCH,),
    smart_take=True,
    strict_lillie_guard=True,              # コンボ素材(アメ/進化)を抱える
    sacrifice_abilities=(DUSCLOPS, DUSKNOIR),
    sacrifice_damage={DUSCLOPS: 50, DUSKNOIR: 130},
    setup_wall=(MUNKIDORI,),               # 開幕はマシマシラ壁(ドラメシヤ線を晒さない)
    dup_play_caps={MUNKIDORI: 2, DUSKULL: 2},
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 3,                       # ボス3枚+プライムキャッチャー1
    "max_line_damage": 200,                # PD本体(+ベンチ60+カースド130の面圧)
    "spread": 60,                          # PDのベンチ撒き(6個任意=進化前狩り)
    "bases": (DREEPY, DUSKULL),
    "bench_immune": (DRAGAPULT,),          # Tera: ベンチのドラパルトは技ダメージ無効
    "ability_damage": {DUSKNOIR: 130, DUSCLOPS: 50, MUNKIDORI: 30},  # 特性ダメ(脅威モデル外の既知盲点)
}


# ==== 検収側: IDENTITY ====
def identity_metrics(games, C=None, NAME=None):
    """Dragapultらしさ: ①ドラパルトT5着地(アメ線) ②攻撃機会 ③エネ貼り分け(悪→マシマシラ/
    他→ドラパルト線) ④土台の複線化(T3までにドラメシヤ2体) ⑤特性の活用(ABILITY選択率)。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    def _in_play(me):
        return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]

    for g in games:
        pult_turn = None
        dreepy2_by3 = False
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            ids_play = [sp.get("id") for sp in _in_play(me)]
            if pult_turn is None and DRAGAPULT in ids_play:
                pult_turn = tn
            if tn <= 3 and ids_play.count(DREEPY) + ids_play.count(DRAKLOAK) + ids_play.count(DRAGAPULT) >= 2:
                dreepy2_by3 = True
            if s.get("type") != 0:
                continue
            hand = me.get("hand") or []
            # ② 攻撃機会を逃さない
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
            # ③ エネ貼り分け: 悪→マシマシラ / R,P→ドラパルト線
            if ch.get("type") == 8 and ch.get("index") is not None and ch["index"] < len(hand):
                cid = hand[ch["index"]].get("id")
                ci = C.get(cid)
                if ci and "Energy" in (ci.name or ""):
                    m["③エネ貼り分け(悪/二色)"][1] += 1
                    area = ch.get("inPlayArea")
                    idx = ch.get("inPlayIndex")
                    spots = (me.get("active") if area == 4 else me.get("bench")) or []
                    tgt = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                    ok = (tgt and ((cid == D_E and tgt.get("id") == MUNKIDORI)
                                   or (cid != D_E and tgt.get("id") in LINE)))
                    if ok:
                        m["③エネ貼り分け(悪/二色)"][0] += 1
            # ⑤ 特性の活用(Recon/Adrena): ABILITY(10)を選べる時に使う。
            #    自滅特性(カースドボム)は「価値打ちの見送り」が正なので機会から除外
            def _ab_src(op):
                if op.get("type") != 10:
                    return None
                spots = (me.get("active") if op.get("area") == 4 else me.get("bench")) or []
                idx = op.get("index")
                sp = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                return sp.get("id") if sp else None
            ab_nonsac = any(op.get("type") == 10 and _ab_src(op) not in (DUSCLOPS, DUSKNOIR)
                            for op in opts)
            if ab_nonsac and ch.get("type") in (10, 13, 14):
                m["⑤特性の活用"][1] += 1
                if ch.get("type") == 10:
                    m["⑤特性の活用"][0] += 1
        m["①ドラパルトT5までに着地"][1] += 1
        if pult_turn is not None and pult_turn <= 5:
            m["①ドラパルトT5までに着地"][0] += 1
        m["④T3までに竜線2体"][1] += 1
        if dreepy2_by3:
            m["④T3までに竜線2体"][0] += 1
    return m
