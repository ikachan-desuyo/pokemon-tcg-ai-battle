"""Episode 4 卒業試験(最終): 4デッキ × 100戦 ミラー(UniversalBot vs 専用bot)。

レポート様式(ユーザ指定):
  ① Bot Quality: 無攻撃率 / 進化到達率 / 過積みAttach / Boss使用 / Recovery使用
  ② Universal指標: Infer Score(静的) / Opening一致 は別途
  ③ 最終結果: ミラー勝率 / 勝敗数 / 平均ターン / 対戦数
  ④ 45%未満のデッキ: 負け原因の自動分類(Top5)
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot.arena import run_match
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot, interpret_move
from cabt_bot.enums import OptionType, SelectType

C = load_cards()
ATTACH = int(OptionType.ATTACH); ATTACK = int(OptionType.ATTACK); PLAY = int(OptionType.PLAY)
MAIN = int(SelectType.MAIN)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def max_cost(cid):
    ci = C.get(cid)
    if not ci:
        return None
    lens = [len(im["cost_syms"]) for im in (interpret_move(mv) for mv in ci.moves) if im["is_attack"]]
    return max(lens) if lens else None


def make_tracked(bot, plan, track):
    boss_ids = set(plan.boss_cards or ()); rec_ids = set(plan.recover_cards or ())
    evolved_ids = {a for a in (plan.attackers or ()) if C.get(a) and not C[a].is_basic}

    def agent(obs_dict):
        sel = bot.select(Observation.from_dict(obs_dict)) or [0]
        s = obs_dict.get("select") or {}
        opts = s.get("option") or []
        cur = obs_dict.get("current") or {}
        me_idx = cur.get("yourIndex", 0)
        me = (cur.get("players") or [{}, {}])[me_idx]
        # 進化到達
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if sp and sp.get("id") in evolved_ids:
                track["evolved"] = True
        if s.get("type") == MAIN and sel and sel[0] < len(opts):
            ch = opts[sel[0]]
            t = ch.get("type")
            if t == ATTACK:
                track["attacked"] = True
            elif t == PLAY:
                hand = me.get("hand") or []
                idx = ch.get("index")
                if idx is not None and 0 <= idx < len(hand):
                    cid = hand[idx]["id"]
                    if cid in boss_ids:
                        track["boss"] += 1
                    if cid in rec_ids:
                        track["recover"] += 1
            elif t == ATTACH:
                area = ch.get("inPlayArea"); i2 = ch.get("inPlayIndex", 0)
                spots = (me.get("active") if area == 4 else me.get("bench")) or []
                sp = spots[i2] if (i2 is not None and 0 <= i2 < len(spots)) else None
                if sp:
                    mc = max_cost(sp.get("id"))
                    if mc and len(sp.get("energyCards") or []) >= mc:
                        track["overstack"] += 1
        # 終局スナップショット(敗因分類用): 相手サイド残→自分が取った枚数
        opp = (cur.get("players") or [{}, {}])[1 - me_idx]
        pz = opp.get("prize")
        if pz is not None:
            track["prizes_taken"] = 6 - len(pz)
        return sel
    return agent


def exam(deck, spec_key, games=100):
    dl = load(deck)
    uni_plan = UniversalBot(decklist=dl).plan
    wins = 0; decided = 0; draws = 0
    never_att = 0; evolved_n = 0; overstack = 0; boss = 0; recover = 0
    turns = []; loss_cats = Counter()
    has_evo = any(C.get(a) and not C[a].is_basic for a in (uni_plan.attackers or ()))
    for g in range(games):
        uni = UniversalBot(decklist=dl); spec = R.DECK_BOTS[spec_key](decklist=dl)
        track = {"attacked": False, "evolved": False, "overstack": 0, "boss": 0,
                 "recover": 0, "prizes_taken": 0}
        ua = make_tracked(uni, uni_plan, track)
        sa = (lambda b: (lambda o: b.select(Observation.from_dict(o)) or [0]))(spec)
        if g % 2 == 0:
            r = run_match(ua, sa, dl, dl); uni_won = (r.winner == 0)
        else:
            r = run_match(sa, ua, dl, dl); uni_won = (r.winner == 1)
        turns.append(r.turns)
        if r.winner in (0, 1):
            decided += 1; wins += int(uni_won)
        else:
            draws += 1
        never_att += int(not track["attacked"])
        evolved_n += int(track["evolved"])
        overstack += track["overstack"]; boss += track["boss"]; recover += track["recover"]
        if r.winner in (0, 1) and not uni_won:
            if not track["attacked"]:
                loss_cats["無攻撃"] += 1
            elif has_evo and not track["evolved"]:
                loss_cats["進化未達"] += 1
            elif track["prizes_taken"] <= 1:
                loss_cats["サイド0-1(展開負け)"] += 1
            elif track["prizes_taken"] <= 4:
                loss_cats["サイド2-4(競り負け)"] += 1
            else:
                loss_cats["サイド5(あと一歩)"] += 1
    wr = wins / max(1, decided)
    na = never_att / games
    print(f"\n===== {deck} (vs {spec_key}, {games}戦) =====")
    print(f"③ ミラー勝率: {wr:.1%} ({wins}勝{decided - wins}敗{draws}分)  平均ターン {sum(turns)/len(turns):.1f}")
    print(f"① Bot Quality: 無攻撃率 {na:.1%} | 進化到達 {evolved_n/games:.0%}{'(進化デッキ)' if has_evo else '(たね=対象外)'} | "
          f"過積みAttach {overstack}回 | Boss使用 {boss}回 | Recovery使用 {recover}回")
    ok1 = na < 0.15; ok2 = wr >= 0.45
    print(f"判定: 無攻撃<15% {'○' if ok1 else '×'} / 勝率≥45% {'○' if ok2 else '×'} → {'合格' if ok1 and ok2 else '不合格'}")
    if not ok2 and loss_cats:
        print(f"④ 負け原因Top5: {loss_cats.most_common(5)}")
    return ok1 and ok2, wr, na


if __name__ == "__main__":
    results = {}
    for d, k in [("deck", "deck"), ("archaludon_real", "archaludon"),
                 ("lightning", "lightning"), ("froslass", "froslass")]:
        results[d] = exam(d, k, games=100)
    print("\n===== 卒業試験 総括 =====")
    npass = sum(1 for ok, _, _ in results.values() if ok)
    for d, (ok, wr, na) in results.items():
        print(f"  {d:<16} 勝率{wr:.0%} 無攻撃{na:.0%} {'合格' if ok else '不合格'}")
    print(f"  合格 {npass}/4")
