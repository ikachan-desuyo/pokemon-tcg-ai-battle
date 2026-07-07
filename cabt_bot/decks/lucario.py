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

DECK_CSV = "decks/ladder_lucario_v2.csv"  # v9ラダー蒸留: 実構築へ更新(2026-07-08)

# 主要カードID
RIOLU, ML, MAKUHITA, HARIYAMA, LUNATONE, SOLROCK = 677, 678, 673, 674, 675, 676
CAPE, BOSS, SWITCH = 1159, 1182, 1123

# ==== 操縦側: PLAN(Phase7卒業形 = infer_plan(deck) + 薄い差分) ====
# 卒業証書(2026-07-06, N=50検収): Universal 79-81% ≒ 旧手書きPLAN 81% = Gap 0。
# 旧PLANの主要知識は全てUniversalへ蒸留済み(主火力集中/土台優先/1ターン1回特性cap/ケープ/ボスGate)。
import dataclasses as _dc

from ..bots.universal_bot import infer_plan as _infer

from pathlib import Path as _P
_deck = [int(x) for x in (_P(__file__).resolve().parents[2] / DECK_CSV).read_text().split() if x.strip()]
_base = _infer(_deck)
PLAN = _dc.replace(
    _base,
    name="LadderLucario",
    # 差分①(一般化候補): ソルロックは相方特性(ルナサイクル)の相棒=1体で充足。
    #   「1ターン1回」テキストはルナトーン側にしか無いため相棒側capは未導出
    # 差分②(デッキ固有): マクノシタはハリテヤマ(どすこい)土台=2枚まで
    dup_play_caps={**_base.dup_play_caps, 676: 1, 673: 2},    # 差分(v2構築): Wally's Compassion×2=回復サポ。inferはトレーナー効果を読めないため明示
    # (QA: HealMissed/LillieOverLiveHeal=Wallyゲート全休眠の検出で発覚)
    heal_return_cards=(1229,),
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
