"""Episode 4 卒業試験 cycle-1: UniversalBot(デッキ固有ロジック無し) を 4 基準デッキで測る。

各デッキで: UniversalBot(deckX) vs 専用bot(deckX) のミラー。
  ① 無攻撃率 < 15%   (機能するか)
  ② ミラー勝率 ≥ 45% (専用に匹敵＝DeckBot不要に近いか)
先後入替・毎ゲーム新インスタンス。勝者は state.result(arena準拠)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot.arena import run_match
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import OptionType

ATTACK = int(OptionType.ATTACK)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def make_agent(bot, track=None):
    def agent(obs_dict):
        sel = bot.select(Observation.from_dict(obs_dict)) or [0]
        if track is not None:
            opts = obs_dict.get("select", {}).get("option", [])
            if sel and 0 <= sel[0] < len(opts) and opts[sel[0]].get("type") == ATTACK:
                track["att"] = True
        return sel
    return agent


EXAM = [
    ("MegaStarmie", "deck", "deck"),
    ("Archaludon", "archaludon_real", "archaludon"),
    ("Lightning", "lightning", "lightning"),
    ("Froslass", "froslass", "froslass"),
]


def main(games=30):
    print(f"=== Episode 4 卒業試験 cycle-1 (UniversalBot vs 専用bot, ミラー{games}戦) ===")
    print(f"{'デッキ':<12} {'無攻撃率':>8} {'ミラー勝率':>10} {'判定'}")
    for name, deckfile, spec_key in EXAM:
        dl = load(deckfile)
        wins = 0; decided = 0; never_att = 0
        for g in range(games):
            uni = UniversalBot(decklist=dl)
            spec = R.DECK_BOTS[spec_key](decklist=dl)
            track = {"att": False}
            ua = make_agent(uni, track); sa = make_agent(spec)
            if g % 2 == 0:
                r = run_match(ua, sa, dl, dl); uni_won = (r.winner == 0)
            else:
                r = run_match(sa, ua, dl, dl); uni_won = (r.winner == 1)
            if r.winner in (0, 1):
                decided += 1; wins += int(uni_won)
            if not track["att"]:
                never_att += 1
        na = never_att / games
        wr = wins / max(1, decided)
        ok1 = "○" if na < 0.15 else "×"
        ok2 = "○" if wr >= 0.45 else "×"
        verdict = "合格" if (na < 0.15 and wr >= 0.45) else "不合格"
        print(f"{name:<12} {na:>7.0%}{ok1} {wr:>9.0%}{ok2}  {verdict}")


if __name__ == "__main__":
    main()
