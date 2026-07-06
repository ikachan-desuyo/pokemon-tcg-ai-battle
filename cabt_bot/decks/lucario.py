"""Mega Lucario デッキ知識(実ラダー最多33戦の最重要対面)。

勝ち筋: リオル→メガルカリオex(340)。Mega Brave 270 は次番使用不可ロックのため
Aura Jab 130(トラッシュからFエネ3枚をベンチへ加速)と自然交互になる=2体目の育成が回る。
ルナトーン(ルナサイクル=手札のFを捨てて3ドロー)がトラッシュ燃料を作り、
ハリテヤマ進化時のどすこいキャッチャー(ベンチ引きずり出し)が確定ボスとして機能する。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

DECK_CSV = "decks/ladder_lucario.csv"

# 主要カードID
RIOLU, ML, MAKUHITA, HARIYAMA, LUNATONE, SOLROCK = 677, 678, 673, 674, 675, 676
CAPE, BOSS, SWITCH = 1159, 1182, 1123

# ==== 操縦側: PLAN(観測済みの弱点=土台リオルのBoss/スプラッシュ狩り、への対策込み) ====
PLAN = DeckPlan(
    name="LadderLucario",
    go_first=True,
    attackers=(ML, HARIYAMA, SOLROCK),
    key_cards=(ML, RIOLU),
    preferred_attacks=(),                  # 既定=最大ダメージ(MB⇄AJは使用ロックで自然交互)
    energy_rules=((None, ML), (None, HARIYAMA)),
    play_priority={RIOLU: 86, MAKUHITA: 78, SOLROCK: 74, LUNATONE: 74},
    card_values={ML: 100, RIOLU: 85, HARIYAMA: 72, SOLROCK: 62, LUNATONE: 62},
    lethal=True,
    reposition=True,
    hp_boost_tools={CAPE: 100},
    boss_cards=(BOSS,),
    switch_cards=(SWITCH,),
    smart_take=True,
    setup_wall=(MAKUHITA,),                # 先攻T1はマクノシタ壁(土台リオルを晒さない)
    dup_play_caps={SOLROCK: 1, LUNATONE: 1, MAKUHITA: 2},  # 条件系特性は各1体で充足=渋滞防止
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル(対面時に参照。TODO: bot/reviewerの直書き推定をここへ移設) ====
THREAT = {
    "boss_count": 2,                # ボスの指令2枚(+どすこいキャッチャー=進化時ガスト実質+2)
    "gust_abilities": (HARIYAMA,),  # 進化トリガーの引きずり出し
    "max_line_damage": 270,         # Mega Brave(次番ロック=270は隔ターン)
    "bases": (RIOLU,),              # 土台=進化前狩りの標的
}


# ==== 検収側: IDENTITY(らしさメトリクス。deck_identity.pyが対メガスターミーbot戦で測定) ====
def identity_metrics(games, C=None, NAME=None):
    """Lucarioらしさ: 各項目=(成立回数, 機会回数)。PLANの各行の検収に対応:
    ①=play_priority(リオル) ②=攻撃ゲート全般 ③=energy_rules ④=dup_play_caps ⑥=立ち上げ全体。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    def _in_play(me):
        return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]

    for g in games:
        seen_turns = set()
        ml_turn = None
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            names = [NAME.get(sp.get("id"), "?") for sp in _in_play(me)]
            if ml_turn is None and "Mega Lucario ex" in names:
                ml_turn = tn
            if s.get("type") != 0:
                continue
            hand = me.get("hand") or []
            bench_n = len([b for b in (me.get("bench") or []) if b])
            key = tn
            # ① 土台供給: リオルを置けるのに置かない、をしない
            riolu_play_opt = any(op.get("type") == 7 and op.get("index") is not None
                                 and op["index"] < len(hand) and hand[op["index"]].get("id") == RIOLU
                                 for op in opts)
            if riolu_play_opt and bench_n < 5 and names.count("Riolu") + names.count("Mega Lucario ex") < 2:
                m["①リオル土台供給"][1] += 1
                if (ch.get("type") == 7 and ch.get("index") is not None
                        and ch["index"] < len(hand) and hand[ch["index"]].get("id") == RIOLU):
                    m["①リオル土台供給"][0] += 1
            # ② 攻撃機会: 撃てるのにENDしない
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
            # ③ エネ配分: attach対象がアタッカー線
            if ch.get("type") == 8 and ch.get("index") is not None and ch["index"] < len(hand):
                cid = hand[ch["index"]].get("id")
                ci = C.get(cid)
                if ci and "Energy" in (ci.name or ""):
                    m["③エネはアタッカー線へ"][1] += 1
                    area = ch.get("inPlayArea")
                    idx = ch.get("inPlayIndex")
                    spots = (me.get("active") if area == 4 else me.get("bench")) or []
                    tgt = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                    if tgt and tgt.get("id") in (ML, RIOLU, HARIYAMA, MAKUHITA):
                        m["③エネはアタッカー線へ"][0] += 1
            # ④ 同名渋滞なし
            if key not in seen_turns:
                seen_turns.add(key)
                m["④ソル/ルナ各1体以下"][1] += 1
                if names.count("Solrock") <= 1 and names.count("Lunatone") <= 1:
                    m["④ソル/ルナ各1体以下"][0] += 1
        # ⑥ 立ち上げ速度(ゲーム単位)
        m["⑥ML T5までに着地"][1] += 1
        if ml_turn is not None and ml_turn <= 5:
            m["⑥ML T5までに着地"][0] += 1
    return m
