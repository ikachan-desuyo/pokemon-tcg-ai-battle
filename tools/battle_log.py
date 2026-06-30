"""Archaludon(自) vs MegaStarmie(敵) の詳細対戦ログ(GPTレビュー用)。
両者の攻撃(実ダメージ)・KO・サイド枚数・自分の全決定を時系列で記録する。"""
import sys
sys.path.insert(0, ".")
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class, all_attack
from cabt_bot import Observation, load_cards
from cabt_bot.enums import OptionType
from cabt_bot.bots import deck_registry as R

C = load_cards(); nm = lambda c: C[c].name if c in C else f"#{c}"
AN = {a.attackId: a.name for a in all_attack()}
OT = {int(getattr(OptionType, x)): x for x in ("PLAY","ATTACH","EVOLVE","ATTACK","ABILITY","RETREAT","END")}
METAL = 8
def load(p): return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]

def spot(s):
    if not s: return "なし"
    e = s.get("energyCards") or s.get("energies") or []
    mt = sum(1 for x in e if (x.get("id") if isinstance(x, dict) else x) == METAL)
    tot = len(e); hp = s.get("hp"); mhp = s.get("maxHp")
    dmg = f" 被ダメ{mhp-hp}" if (mhp and hp is not None and mhp > hp) else ""
    return f"{nm(s['id'])} HP{hp}/{mhp} エネ{tot}(鋼{mt}){dmg}"

def prize_n(p):
    pr = p.get("prize") or p.get("prizes") or []
    return sum(1 for x in pr if x) if pr and any(isinstance(x, (dict, int)) for x in pr) else len(pr)

def board(cur, who, label):
    p = cur["players"][who]
    a = (p.get("active") or [None])[0]
    bn = [f"{nm(s['id'])}(エネ{len(s.get('energyCards') or s.get('energies') or [])})" for s in (p.get("bench") or []) if s]
    return f" {label}: バトル場[{spot(a)}] ベンチ{bn} サイド残{prize_n(p)}"

def run(games=3):
    d = load("archaludon"); opp_deck = load("deck")
    out = []
    for game in range(games):
        bot = R.DECK_BOTS["archaludon"](decklist=d); opp = R.DECK_BOTS["deck"]()
        obs, sd = battle_start(d, opp_deck); steps = 0; res = None; lastturn = -1; seen_logs = 0
        out.append(f"\n{'='*72}\nGAME {game+1}   自分=Archaludon(ブリジュラスex)   相手=MegaStarmie\n{'='*72}")
        while obs is not None and steps < 1500:
            o = to_observation_class(obs); st = o.current; cur = obs.get("current")
            # 新しいログ(攻撃/KO)を時系列で吐く
            logs = obs.get("logs") or []
            for lg in logs[seen_logs:]:
                if lg.get("type") == 15:  # 攻撃
                    who = lg.get("playerIndex"); side = "自" if who == 0 else "敵"
                    out.append(f"      >> {side} が {AN.get(lg.get('attackId'),'?')} で攻撃")
            seen_logs = len(logs)
            if st and st.result != -1: res = st.result; break
            rs = obs.get("select")
            if not rs or not rs.get("option"): break
            who = st.yourIndex if st else 0; parsed = Observation.from_dict(obs)
            if who == 0 and cur:
                t = cur.get("turn")
                if t != lastturn:
                    out.append(f"\n[自分のターン {t}]")
                    out.append(board(cur, 0, "自"))
                    out.append(board(cur, 1, "敵"))
                    lastturn = t
                ch = bot.select(parsed); opts = rs["option"]
                op = opts[ch[0]] if ch else None
                if op:
                    ty = op.get("type"); tp = OT.get(ty, None)
                    hand = cur["players"][0].get("hand") or []
                    desc = ""
                    if ty in (int(OptionType.PLAY), int(OptionType.ATTACH), int(OptionType.EVOLVE)):
                        ix = op.get("index"); desc = nm(hand[ix]["id"]) if ix is not None and ix < len(hand) else "?"
                    elif ty == int(OptionType.ATTACK):
                        aid = op.get("attackId"); dmg = bot._dmg(parsed.select.options[ch[0]])
                        atk_opts = [AN.get(o.get("attackId")) for o in opts if o.get("type") == int(OptionType.ATTACK)]
                        desc = f"{AN.get(aid,'?')} 実ダメージ{dmg} (選べた技:{atk_opts})"
                    elif ty == int(OptionType.ABILITY):
                        cid = bot._opt_card_id(parsed.select.options[ch[0]]); desc = nm(cid or 0)
                    if tp and desc:
                        out.append(f"    [{tp}] {desc}")
                ret = ch
            else:
                ret = opp.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()
        out.append(f"\n>>> 結果: {'★自分(Archaludon)の勝ち' if res==0 else '×相手(MegaStarmie)の勝ち' if res==1 else '不明'}")
    return "\n".join(out)

if __name__ == "__main__":
    print(run(3))
