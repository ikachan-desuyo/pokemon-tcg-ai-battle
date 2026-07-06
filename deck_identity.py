"""Deck Identity メトリクス(Benchmark Phase / Phase6)。

目的: ベンチマークbotの強化を「勝率」でなく「そのデッキらしいプレイ率」で測る。
勝率だけだと PLAN が Universal の癖を狩っただけでも上がる。Identityは勝敗と独立に
「Lucarioの勝ち方を説明できるPLANか」を数値化する(ユーザ設計 2026-07-06)。

各メトリクスは事実のみを数える(Analyzer原則)。デッキごとに識別関数群を登録し、
対メガスターミーbot N戦の記録から рート を算出する。

使い方: python deck_identity.py lucario [N] [--universal]
        (--universal で Universal版を測定。既定はPLAN版)
"""
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from cabt_bot.arena import run_match
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import universal_for

C = load_cards()
NAME = {cid: c.name for cid, c in C.items()}


def record_games(mk_subject, subject_deck, n):
    """対メガスターミーbot n戦、被験bot(side=1)の決定列を返す。"""
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    games = []
    for _ in range(n):
        rows = []
        me_bot = R.DECK_BOTS["deck"](decklist=dl)
        sub = mk_subject()

        def agent(bot, side):
            def f(o):
                sel = bot.select(Observation.from_dict(o)) or [0]
                if side == 1 and o.get("current"):
                    rows.append((o, list(sel)))
                return sel
            return f
        res = run_match(agent(me_bot, 0), agent(sub, 1), dl, subject_deck)
        w = getattr(res, "winner", None) if not isinstance(res, dict) else res.get("winner")
        games.append({"rows": rows, "won": w == 1})
    return games


def _my(cur):
    return cur["players"][cur["yourIndex"]]


def _in_play(me):
    return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]


def _names_in_play(me):
    return [NAME.get(sp.get("id"), "?") for sp in _in_play(me)]


# ===== Lucario Identity =====
RIOLU, ML, MAKUHITA, HARIYAMA, LUNATONE, SOLROCK = 677, 678, 673, 674, 675, 676


def lucario_metrics(games):
    """Lucarioらしさ: 各項目=(成立回数, 機会回数)。"""
    m = defaultdict(lambda: [0, 0])
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
            names = _names_in_play(me)
            # ML立ち上げ: 最初にMLが場に出たターン
            if ml_turn is None and "Mega Lucario ex" in names:
                ml_turn = tn
            if s.get("type") != 0:      # MAIN以外はここまで
                continue
            hand = me.get("hand") or []
            hand_ids = [c.get("id") for c in hand]
            bench_n = len([b for b in (me.get("bench") or []) if b])
            key = (id(g), tn)
            # ① 土台供給: リオル在手×ベンチ空き×場のリオル系<2 → その決定でリオルを置いたか
            #    (ターン内のどこかで置けば成立: PLAY Riolu選択肢がある決定のみ機会に数える)
            riolu_play_opt = any(op.get("type") == 7 and op.get("index") is not None
                                 and op["index"] < len(hand) and hand[op["index"]].get("id") == RIOLU
                                 for op in opts)
            if riolu_play_opt and bench_n < 5 and names.count("Riolu") + names.count("Mega Lucario ex") < 2:
                m["①リオル土台供給"][1] += 1
                if (ch.get("type") == 7 and ch.get("index") is not None
                        and ch["index"] < len(hand) and hand[ch["index"]].get("id") == RIOLU):
                    m["①リオル土台供給"][0] += 1
            # ② 攻撃機会: ATTACK選択肢がある最後のMAINで攻撃したか(=撃てるのにENDしない)
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
            # ③ エネ配分: エネATTACHの対象がアタッカー線(ML/リオル/ハリテヤマ/マクノシタ)か
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
            # ④ 同名渋滞なし: このターンの場にソルロック/ルナトーン各1体以下
            if key not in seen_turns:
                seen_turns.add(key)
                m["④ソル/ルナ各1体以下"][1] += 1
                if names.count("Solrock") <= 1 and names.count("Lunatone") <= 1:
                    m["④ソル/ルナ各1体以下"][0] += 1
            # ⑤ ルナサイクル: ABILITY選択肢があるターンで(ターン内のどこかで)使ったか
            #    → 決定単位だと遅延使用が失敗に見えるため「ABILITY選択後 or 後続決定で消えた」を成立と近似:
            #    ここでは簡略化して ABILITY を選んだ決定/選ばず攻撃した決定の比率を出す
            ab_opt = any(op.get("type") == 15 for op in opts)
            if ab_opt and ch.get("type") in (15, 13, 14):
                m["⑤特性(ルナサイクル)活用"][1] += 1
                if ch.get("type") == 15:
                    m["⑤特性(ルナサイクル)活用"][0] += 1
        # ⑥ ML立ち上げ速度: T5までにMLが立ったか(ゲーム単位)
        m["⑥ML T5までに着地"][1] += 1
        if ml_turn is not None and ml_turn <= 5:
            m["⑥ML T5までに着地"][0] += 1
    return m


METRICS = {"lucario": ("decks/ladder_lucario.csv", lucario_metrics)}


def main():
    deck = sys.argv[1] if len(sys.argv) > 1 else "lucario"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    use_universal = "--universal" in sys.argv
    path, fn = METRICS[deck]
    od = [int(x) for x in open(path).read().split() if x.strip()]
    if use_universal:
        mk = lambda: universal_for(path.split("/")[-1][:-4])(decklist=od)
        label = "Universal版"
    else:
        from cabt_bot.bots.ladder_plans import LadderLucarioBot
        mk = lambda: LadderLucarioBot(decklist=od)
        label = "PLAN版"
    games = record_games(mk, od, n)
    m = fn(games)
    won = sum(1 for g in games if g["won"])
    print(f"=== {deck} Identity ({label}, 対メガスターミーbot {n}戦, 勝ち{won}) ===")
    tot_hit = tot_opp = 0
    for k in sorted(m):
        hit, opp = m[k]
        tot_hit += hit; tot_opp += opp
        rate = f"{100*hit/opp:.0f}%" if opp else "-"
        print(f"  {k:<20} {hit:>3}/{opp:<3} {rate}")
    if tot_opp:
        print(f"  {'Identity総合':<20} {tot_hit:>3}/{tot_opp:<3} {100*tot_hit/tot_opp:.0f}%")


if __name__ == "__main__":
    main()
