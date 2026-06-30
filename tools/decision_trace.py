"""意思決定トレース: 各P0決定で『全候補手＋評価値＋ゲート結果』と選択を出す。
候補生成で落ちたのか評価で負けたのかを切り分けるためのデバッグツール。"""
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

def opp_board(cur):
    p = cur["players"][1]
    a = (p.get("active") or [None])[0]
    bn = []
    for s in (p.get("bench") or []):
        if s: bn.append(f"{nm(s['id'])}(HP{s.get('hp')})")
    av = f"{nm(a['id'])}(HP{a.get('hp')})" if a else "なし"
    return av, bn

def trace_select(bot, parsed, cur, rs):
    """1つの選択の全候補手評価を文字列リストで返す。"""
    out = []
    opts = rs["option"]; ch = bot.select(parsed)
    chosen = ch[0] if ch else None
    hand = cur["players"][0].get("hand") or []
    me = cur["players"][0]
    stype = str(rs.get("type")).split(".")[-1]; ctx = str(rs.get("context")).split(".")[-1]
    # 攻撃選択か、メイン選択か
    atk_opts = [i for i in range(len(opts)) if opts[i].get("type") == int(OptionType.ATTACK)]
    play_opts = [i for i in range(len(opts)) if opts[i].get("type") == int(OptionType.PLAY)]
    if atk_opts:
        oa = (cur["players"][1].get("active") or [None])[0]; ohp = oa.get("hp") if oa else None
        out.append(f"  [攻撃選択] 相手バトル場HP={ohp}")
        for i in atk_opts:
            d = bot._dmg(parsed.select.options[i]); lethal = (ohp is not None and d >= ohp)
            mark = " ★選択" if i == chosen else ""
            out.append(f"      {AN.get(opts[i].get('attackId'),'?')}: ダメージ{d}{' [KO可]' if lethal else ''}{mark}")
    if play_opts:
        out.append(f"  [プレイ候補] ({stype}/{ctx})")
        for i in play_opts:
            ix = opts[i].get("index"); cid = hand[ix]["id"] if ix is not None and ix < len(hand) else None
            sc = bot._play_score(cid, hand) if cid is not None else None
            mark = " ★選択" if i == chosen else ""
            scs = "却下(None)" if sc is None else f"score={sc}"
            out.append(f"      {nm(cid)}: {scs}{mark}")
    # 選択がプレイ/攻撃でない場合(ATTACH/EVOLVE/END等)も一応表示
    if chosen is not None and not (atk_opts or play_opts):
        op = opts[chosen]; t = OT.get(op.get("type"), op.get("type"))
        d = ""
        if op.get("type") in (int(OptionType.ATTACH), int(OptionType.EVOLVE)):
            ix = op.get("index"); d = nm(hand[ix]["id"]) if ix is not None and ix < len(hand) else ""
        out.append(f"  [{t}] {d} ★選択")
    return out, ch

def run(games=2):
    d = load("archaludon"); opp_deck = load("deck")
    for game in range(games):
        bot = R.DECK_BOTS["archaludon"](decklist=d); opp = R.DECK_BOTS["deck"]()
        obs, sd = battle_start(d, opp_deck); steps = 0; res = None; lastturn = -1
        print(f"\n{'='*72}\nGAME {game+1}  自=Archaludon vs 敵=MegaStarmie\n{'='*72}")
        while obs is not None and steps < 1500:
            o = to_observation_class(obs); st = o.current; cur = obs.get("current")
            if st and st.result != -1: res = st.result; break
            rs = obs.get("select")
            if not rs or not rs.get("option"): break
            who = st.yourIndex if st else 0; parsed = Observation.from_dict(obs)
            if who == 0 and cur:
                t = cur.get("turn")
                if t != lastturn:
                    me = cur["players"][0]; act = (me.get("active") or [None])[0]
                    av, bn = opp_board(cur)
                    actE = len(act.get("energyCards") or act.get("energies") or []) if act else 0
                    boss_in_hand = any(c.get("id") == 1182 for c in (me.get("hand") or []))
                    print(f"\n── 自T{t} | 自場:{nm(act['id'])if act else '-'}(エネ{actE}) | 敵場:{av} 敵ベンチ:{bn}")
                    print(f"   [Boss判定] 手札にボス={boss_in_hand} / _should_play_boss={bot._should_play_boss()}")
                    lastturn = t
                lines, ch = trace_select(bot, parsed, cur, rs)
                for ln in lines: print(ln)
                ret = ch
            else:
                ret = opp.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()
        print(f"\n>>> 結果: {'自勝ち' if res==0 else '敵勝ち' if res==1 else '?'}")

if __name__ == "__main__":
    run(2)
