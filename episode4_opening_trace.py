"""Episode 4: 開幕をターンごとに直接トレース（メトリクス整合＋Explain）。

「T1終了時100%」と「初設置T2.0」の矛盾を解消するため、p0の全selectを turn付きでログ。
初期手札→ACTIVE→BENCH→ボール使用→各turnの盤面 を Universal と 専用bot で並べる。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
ST = {int(getattr(SelectType, x)): x for x in dir(SelectType) if x.isupper()}
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def board(me):
    a = (me.get("active") or [None])[0]
    b = [nm(x["id"]) for x in (me.get("bench") or []) if x]
    return f"A:{nm(a['id']) if a else '-'} B:{b}"


def opt_desc(ch, me):
    t = OT.get(ch.get("type"), ch.get("type"))
    idx = ch.get("index")
    hand = me.get("hand") or []
    if idx is not None and 0 <= idx < len(hand) and ch.get("area") in (None, 2):
        return f"{t} {nm(hand[idx]['id'])}"
    return f"{t}"


def trace(botfn, dl, label, max_p0=14):
    bot = botfn(dl); opp = UniversalBot(decklist=dl)
    obs, _ = battle_start(dl, dl); steps = 0; np0 = 0; hand0 = None
    print(f"\n--- {label} ---")
    while obs is not None and steps < 200 and np0 < max_p0:
        st = to_observation_class(obs).current
        if st and st.result != -1:
            break
        if not (obs.get("select") and obs["select"].get("option")):
            break
        who = st.yourIndex if st else 0; sel = obs["select"]
        if who == 0:
            cur = obs["current"]; me = cur["players"][0]; turn = cur.get("turn", 0)
            if hand0 is None:
                hand0 = [nm(c["id"]) for c in (me.get("hand") or [])]
                print(f"  初期手札: {hand0}")
            ret = bot.select(Observation.from_dict(obs)) or [0]
            ch = sel["option"][ret[0]] if ret and ret[0] < len(sel["option"]) else {}
            styp = ST.get(sel.get("type"), sel.get("type"))
            print(f"  T{turn} [{styp}] → {opt_desc(ch, me)}")
            obs = battle_select(ret); np0 += 1
            # 選択後の盤面
            st2 = to_observation_class(obs).current
            if st2 and st2.players:
                me2 = obs.get("current", {}).get("players", [{}])[0]
                if me2:
                    print(f"        盤面: {board(me2)}")
            steps += 1; continue
        ret = opp.select(Observation.from_dict(obs)) or [0]
        obs = battle_select(ret); steps += 1
    battle_finish()


def main(deck="deck", spec_key=None):
    dl = load(deck)
    print(f"=== 開幕トレース: {deck} ===")
    trace(lambda d: UniversalBot(decklist=d), dl, "UniversalBot")
    trace(lambda d: R.DECK_BOTS[spec_key or deck](decklist=d), dl, "専用bot")


if __name__ == "__main__":
    main("deck", "deck")
