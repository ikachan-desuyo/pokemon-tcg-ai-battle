"""Episode 4: Support/Trainer 運用の Explain 監査（最初から役割別・一括にしない）。

役割分類: Draw / Search / Boss / Recovery / Switch / Tool / Energy補給 / その他
測定:
  ① 同一局面のTrainer選択差: 専用が選んだ役割 ⇔ Uniが選んだ役割 のペア集計
     (「Support差○%」でなく、どの役割で何をどう間違えるかを最初から見る)
  ② Draw→Use遅延: 役割別に「手札に来たターン→使ったターン」を Uni / 専用 それぞれの実プレイで比較
"""
import sys, os
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN); PLAY = int(OptionType.PLAY)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def role(cid):
    """Trainerの役割分類(監査用・カード名/種別ベース)。ポケモン/エネはNone。"""
    ci = C.get(cid)
    if not ci or ci.is_pokemon:
        return None
    name = ci.name or ""
    if "Energy" in name:
        return None
    if "Boss" in name:
        return "Boss"
    if any(k in name for k in ("Stretcher", "Rescue", "Salvatore")):
        return "Recovery"
    if "Switch" in name:
        return "Switch"
    if any(k in name for k in ("Cape", "Belt", "Band", "Helmet")):
        return "Tool"
    if any(k in name for k in ("Ball", "Poffin", "Pad", "Pokégear", "Gear")):
        return "Search"
    if any(k in name for k in ("Crispin", "Dawn")):
        return "Energy補給"
    if any(k in name for k in ("Professor", "Judge", "Carmine", "Hilda", "Lillie", "Iono", "Wally")):
        return "Draw"
    return "その他T"


def same_state_diff(deck, spec_key, games=8):
    dl = load(deck)
    pairs = Counter()
    for g in range(games):
        uni = UniversalBot(decklist=dl); shadow = R.DECK_BOTS[spec_key](decklist=dl)
        opp = R.DECK_BOTS[spec_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                if sel.get("type") == MAIN and len(sel["option"]) >= 2:
                    me = obs["current"]["players"][0]; hand = me.get("hand") or []
                    u = uni.select(Observation.from_dict(obs)) or [0]
                    s = shadow.select(Observation.from_dict(obs)) or [0]

                    def lab(r):
                        ch = sel["option"][r[0]] if r and r[0] < len(sel["option"]) else {}
                        if ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(hand):
                            cid = hand[ch["index"]]["id"]
                            ro = role(cid)
                            return f"T:{ro}" if ro else ("Pokemon" if C.get(cid) and C[cid].is_pokemon else "他")
                        from cabt_bot.enums import OptionType as _O
                        t = ch.get("type")
                        return {int(_O.ATTACH): "Attach", int(_O.ATTACK): "Attack", int(_O.EVOLVE): "Evolve",
                                int(_O.END): "End", int(_O.RETREAT): "Retreat"}.get(t, "他")
                    ul, sl_ = lab(u), lab(s)
                    if ul != sl_ and (ul.startswith("T:") or sl_.startswith("T:")):
                        pairs[f"Uni:{ul} ⇔ 専用:{sl_}"] += 1
                    ret = u
                else:
                    ret = uni.select(Observation.from_dict(obs)) or [0]
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    return pairs


def draw_use_delay(deck, botfn, opp_key, games=8):
    """役割別: トレーナーが手札に来てから使うまでの遅延(自ターン数)。"""
    dl = load(deck)
    delays = defaultdict(list)
    for g in range(games):
        bot = botfn(dl); opp = R.DECK_BOTS[opp_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        first_seen = {}; my_turn = 0; last_turn = None
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0:
                cur = obs["current"]; me = cur["players"][0]; turn = cur.get("turn", 0)
                if turn != last_turn:
                    last_turn = turn; my_turn += 1
                hand = me.get("hand") or []
                for c in hand:
                    r = role(c.get("id"))
                    if r and c.get("id") not in first_seen:
                        first_seen[c["id"]] = my_turn
                ret = bot.select(Observation.from_dict(obs)) or [0]
                if sel.get("type") == MAIN and ret and ret[0] < len(sel["option"]):
                    ch = sel["option"][ret[0]]
                    if ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(hand):
                        cid = hand[ch["index"]]["id"]; r = role(cid)
                        if r and cid in first_seen:
                            delays[r].append(my_turn - first_seen.pop(cid))
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    return {r: (sum(v) / len(v), len(v)) for r, v in delays.items()}


if __name__ == "__main__":
    deck, key = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("deck", "deck")
    print(f"=== {deck}: ① 同一局面のTrainer選択差(役割ペア) ===")
    for p, n in same_state_diff(deck, key).most_common(12):
        print(f"  x{n:<3} {p}")
    print(f"\n=== {deck}: ② Draw→Use遅延(自ターン数, 役割別) ===")
    uni_d = draw_use_delay(deck, lambda d: UniversalBot(decklist=d), key)
    spec_d = draw_use_delay(deck, lambda d: R.DECK_BOTS[key](decklist=d), key)
    roles = sorted(set(uni_d) | set(spec_d))
    print(f"{'役割':<10} {'Uni遅延(件)':>14} {'専用遅延(件)':>14}")
    for r in roles:
        u = f"{uni_d[r][0]:.1f} ({uni_d[r][1]})" if r in uni_d else "-"
        s = f"{spec_d[r][0]:.1f} ({spec_d[r][1]})" if r in spec_d else "-"
        print(f"{r:<10} {u:>14} {s:>14}")
