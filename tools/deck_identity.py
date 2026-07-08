"""Deck Identity 測定ハーネス(Benchmark Phase / Phase6)。

デッキ固有の定義(PLAN/IDENTITYメトリクス)は cabt_bot/decks/<deck>.py に住む。
ここは汎用装置のみ: 対メガスターミーbot N戦を記録し、デッキモジュールの
identity_metrics で「そのデッキらしいプレイ率」を集計する。

勝率だけだと PLAN が Universal の癖を狩っただけでも上がる。Identityは勝敗と独立に
「そのデッキの勝ち方を説明できるPLANか」を数値化する(ユーザ設計 2026-07-06)。
将来: UniversalBot自動導出の卒業試験スイート(既知デッキ全てでIdentity 80%+)。

使い方: python deck_identity.py <deck> [N] [--universal]
        (--universal で Universal版を測定。既定はPLAN版)
"""
import sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
from cabt_bot.arena import run_match
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import universal_for
from cabt_bot.decks import DECKS

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


def main():
    deck = sys.argv[1] if len(sys.argv) > 1 else "lucario"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    use_universal = "--universal" in sys.argv
    mod = DECKS[deck]
    od = [int(x) for x in open(mod.DECK_CSV).read().split() if x.strip()]
    if use_universal:
        stem = mod.DECK_CSV.split("/")[-1][:-4]
        mk = lambda: universal_for(stem)(decklist=od)
        label = "Universal版"
    else:
        mk = lambda: mod.Bot(decklist=od)
        label = "PLAN版"
    games = record_games(mk, od, n)
    m = mod.identity_metrics(games, C=C, NAME=NAME)
    won = sum(1 for g in games if g["won"])
    print(f"=== {deck} Identity ({label}, 対メガスターミーbot {n}戦, 勝ち{won}) ===")
    tot_hit = tot_opp = 0
    for k in sorted(m):
        hit, opp = m[k]
        tot_hit += hit
        tot_opp += opp
        rate = f"{100*hit/opp:.0f}%" if opp else "-"
        print(f"  {k:<20} {hit:>3}/{opp:<3} {rate}")
    if tot_opp:
        print(f"  {'Identity総合':<20} {tot_hit:>3}/{tot_opp:<3} {100*tot_hit/tot_opp:.0f}%")


if __name__ == "__main__":
    main()
