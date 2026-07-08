"""Episode 4: UniversalBot vs 専用bot の「同一局面・決定差分」監査（interpret_trainer 着手前の検証）。

仮説「残りの差はトレーナー運用」を実装前にデータで確認する（measure-first）。
方法: Universal が実際にプレイした各 MAIN 局面で、同じ観測を専用bot(shadow)にも問い合わせ、
      選択が食い違った局面の「専用の選択」をカード/カテゴリ別に集計する。
      選択の比較は index でなく内容(type+対象カード)＝同一内容ならタイブレーク扱いで一致。
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def desc(ch, me):
    """optionを内容で表す: 'PLAY Boss's Orders' / 'ATTACH{W}→active' / 'ATTACK 1488' 等。"""
    if not ch:
        return "?"
    t = OT.get(ch.get("type"), str(ch.get("type")))
    hand = me.get("hand") or []
    idx = ch.get("index")
    card = nm(hand[idx]["id"]) if (idx is not None and 0 <= idx < len(hand) and ch.get("area") in (None, 2)) else ""
    if t == "ATTACK":
        return f"ATTACK#{ch.get('attackId')}"
    tgt = ""
    if ch.get("inPlayArea") is not None:
        tgt = f"→{'act' if ch.get('inPlayArea') == 4 else 'bench' + str(ch.get('inPlayIndex', 0))}"
    return f"{t} {card}{tgt}".strip()


def category(label):
    """専用の選択をカテゴリへ(集計用)。カード名ベース。"""
    if label.startswith("ATTACK"):
        return "Attack選択"
    if label.startswith("ATTACH"):
        return "Attach"
    if label.startswith("EVOLVE"):
        return "Evolution"
    if label.startswith("RETREAT"):
        return "Retreat/配置"
    if label.startswith("END"):
        return "End"
    if label.startswith("PLAY"):
        name = label[5:].split("→")[0].strip()
        cid = next((i for i in C if C[i].name == name), None)
        if cid and C[cid].is_pokemon:
            return "Pokemon展開"
        if "Boss" in name:
            return "Trainer:Boss"
        if "Stretcher" in name or "Rescue" in name:
            return "Trainer:Recover"
        if "Switch" in name or "いれかえ" in name:
            return "Trainer:Switch"
        if any(k in name for k in ("Professor", "Lillie", "Judge", "Carmine", "Hilda", "Dawn", "Salvatore", "Wally")):
            return "Trainer:Supporter"
        if any(k in name for k in ("Ball", "Poffin", "Pad", "Pokégear", "Gear")):
            return "Trainer:Search"
        return "Trainer:その他"
    return "その他"


def main(deck="deck", spec_key=None, games=10):
    spec_key = spec_key or deck
    dl = load(deck)
    n_dec = 0; n_diff = 0
    spec_choice = Counter(); pair_examples = Counter()
    for g in range(games):
        uni = UniversalBot(decklist=dl)
        shadow = R.DECK_BOTS[spec_key](decklist=dl)      # 同一観測を影として問い合わせ
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
                    me = obs["current"]["players"][0]
                    u = uni.select(Observation.from_dict(obs)) or [0]
                    s = shadow.select(Observation.from_dict(obs)) or [0]
                    ud = desc(sel["option"][u[0]] if u[0] < len(sel["option"]) else None, me)
                    sd = desc(sel["option"][s[0]] if s[0] < len(sel["option"]) else None, me)
                    n_dec += 1
                    if ud != sd:                          # 内容が同じなら一致(タイブレーク除去)
                        n_diff += 1
                        spec_choice[category(sd)] += 1
                        pair_examples[f"専用:{sd}  ⇔  Uni:{ud}"] += 1
                    ret = u
                else:
                    ret = uni.select(Observation.from_dict(obs)) or [0]
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
    print(f"=== {deck}: 同一局面の決定差分 ({n_dec}決定中 {n_diff}件 = {100*n_diff//max(1,n_dec)}% 不一致) ===")
    print("  専用botだけが選んだ決定(カテゴリ):")
    for cat, n in spec_choice.most_common():
        print(f"    {cat:<20} {n:>3} ({100*n//max(1,n_diff)}%)")
    print("  頻出の差分例:")
    for ex, n in pair_examples.most_common(6):
        print(f"    x{n}  {ex}")
    return spec_choice


if __name__ == "__main__":
    total = Counter()
    for d, k in [("deck", "deck"), ("archaludon_real", "archaludon"), ("lightning", "lightning")]:
        total += main(d, k); print()
    print("=== 全デッキ合計(専用だけの決定カテゴリ) ===")
    s = sum(total.values())
    for cat, n in total.most_common():
        print(f"  {cat:<20} {n:>3} ({100*n//max(1,s)}%)")
