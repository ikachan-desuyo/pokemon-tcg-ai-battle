"""Marnie's Grimmsnarl ex デッキ知識(悪コントロール)。

勝ち筋: イムプ→(アメ)→マリィのオーロンゲex(320)。Punk Up(進化時に山から悪エネ加速)で
即Shadow Bullet {D}{D} 180+ベンチ30スナイプ。フロスラス(Freezing Shroud=チェックアップ毎に
特性持ち全員へダメカン1)とマシマシラ(Adrena-Brain=悪エネ付きでダメカン3個移動)で
盤面全体を削るエンジンダメージが本体。PLANはノブ最小主義(arch/dragapultの教訓:
Universalの素の挙動が正しい部分に触ると壊れる)。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

DECK_CSV = "decks/meta_grimmsnarl.csv"

IMPIDIMP, MORGREM, GRIMMSNARL = 646, 647, 648
MUNKIDORI, SNORUNT, FROSLASS = 112, 860, 104
D_E = 7
BOSS, NIGHT_STRETCHER = 1182, 1097
LINE = (IMPIDIMP, MORGREM, GRIMMSNARL)

# ==== 操縦側: PLAN ====
PLAN = DeckPlan(
    name="MetaGrimmsnarl",
    go_first=True,
    attackers=(GRIMMSNARL, MORGREM),
    key_cards=(GRIMMSNARL, IMPIDIMP),
    preferred_attacks=("Shadow Bullet",),
    energy_rules=((D_E, GRIMMSNARL), (D_E, MUNKIDORI)),  # 悪→オーロンゲ、次点マシマシラ(Adrena起動)
    play_priority={IMPIDIMP: 86, MUNKIDORI: 82, SNORUNT: 74},
    card_values={GRIMMSNARL: 100, IMPIDIMP: 90, MORGREM: 85, MUNKIDORI: 80, FROSLASS: 70, SNORUNT: 64},
    lethal=True,
    boss_cards=(BOSS,),
    recover_cards=(NIGHT_STRETCHER,),
    smart_take=True,
    dup_play_caps={FROSLASS: 1, MUNKIDORI: 2},
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 2,
    "max_line_damage": 180,                 # Shadow Bullet(+ベンチ30スナイプ)
    "spread": 30,                           # SBのベンチ30=急所スナイプ
    "bases": (IMPIDIMP, SNORUNT),
    "ability_damage": {FROSLASS: 10, MUNKIDORI: 30},  # 特性エンジン(チェックアップ毎+移動)
    "hand_disruption": 1,                   # Unfair Stamp(KO時に手札2枚へ)
}


# ==== 検収側: IDENTITY ====
def identity_metrics(games, C=None, NAME=None):
    """Grimmsnarlらしさ: ①オーロンゲT5着地 ②攻撃機会 ③エネ配分(悪→オーロンゲ/マシマシラ)
    ④Adrena起動(D付きマシマシラがT5までに存在) ⑤土台複線化(T3までにイムプ系2体)。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    def _in_play(me):
        return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]

    for g in games:
        snarl_turn = None
        adrena_by5 = False
        imp2_by3 = False
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            spots_all = _in_play(me)
            ids_play = [sp.get("id") for sp in spots_all]
            if snarl_turn is None and GRIMMSNARL in ids_play:
                snarl_turn = tn
            if tn <= 5 and any(sp.get("id") == MUNKIDORI and (sp.get("energyCards") or [])
                               for sp in spots_all):
                adrena_by5 = True
            if tn <= 3 and sum(ids_play.count(x) for x in LINE) >= 2:
                imp2_by3 = True
            if s.get("type") != 0:
                continue
            hand = me.get("hand") or []
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
            if ch.get("type") == 8 and ch.get("index") is not None and ch["index"] < len(hand):
                cid = hand[ch["index"]].get("id")
                ci = C.get(cid)
                if ci and "Energy" in (ci.name or ""):
                    m["③エネ配分(悪)"][1] += 1
                    area = ch.get("inPlayArea")
                    idx = ch.get("inPlayIndex")
                    spots = (me.get("active") if area == 4 else me.get("bench")) or []
                    tgt = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                    if tgt and tgt.get("id") in LINE + (MUNKIDORI,):
                        m["③エネ配分(悪)"][0] += 1
        m["①オーロンゲT5までに着地"][1] += 1
        if snarl_turn is not None and snarl_turn <= 5:
            m["①オーロンゲT5までに着地"][0] += 1
        m["④Adrena起動(T5までにD付きマシマシラ)"][1] += 1
        if adrena_by5:
            m["④Adrena起動(T5までにD付きマシマシラ)"][0] += 1
        m["⑤T3までにイムプ系2体"][1] += 1
        if imp2_by3:
            m["⑤T3までにイムプ系2体"][0] += 1
    return m
