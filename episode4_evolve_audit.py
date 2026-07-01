"""Episode 4 Decision監査の拡張: EVOLVE / PLAY Timing を UniversalBot vs 専用bot で比較。

仮説: Attach/Attack は健全だったが、勝率差は「進化・展開の遅れ」から来るのでは?
専用T2進化 / Universal T4進化 のような差を定量化する（measure-first）。
測定(audited bot を p0 として):
  - 進化遅延 = 「進化可能(前段が場+進化カード手札)」ターン → 実際に進化形が場に出たターン
  - 主役ライン初設置ターン / 進化形完成ターン / 平均ベンチ数
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot, infer_plan
from cabt_bot.enums import SelectType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def evo_line(evolved_id, deck_ids):
    """evolved_id の前段id集合(デッキ内・名前チェーンで辿る)。"""
    name2id = {C[i].name: i for i in deck_ids if C.get(i)}
    chain = set(); cur = C.get(evolved_id)
    while cur and cur.previous_stage and cur.previous_stage in name2id:
        pid = name2id[cur.previous_stage]
        if pid in chain:
            break
        chain.add(pid); cur = C.get(pid)
    return chain


def audit(botfn, dl, evolved_id, preevo, games):
    """botfn(dl)->bot を p0 として games 試合、進化/展開timingを集計。相手はUniversal(固定)。"""
    delays = []; evolved_turns = []; place_turns = []; bench_avg = []
    for g in range(games):
        me_bot = botfn(dl); opp = UniversalBot(decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        t_could = None; t_evolved = None; t_place = None; bench_samples = []
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0
            if who == 0:
                cur = obs["current"]; me = cur["players"][0]; turn = cur.get("turn", 0)
                in_play = [s for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s]
                ids_play = {s.get("id") for s in in_play}
                hand_ids = {c.get("id") for c in (me.get("hand") or [])}
                if t_place is None and (ids_play & (preevo | {evolved_id})):
                    t_place = turn
                if t_could is None and (ids_play & preevo) and evolved_id in hand_ids:
                    t_could = turn
                if t_evolved is None and evolved_id in ids_play:
                    t_evolved = turn
                bench_samples.append(len([b for b in (me.get("bench") or []) if b]))
                ret = me_bot.select(Observation.from_dict(obs)) or [0]
            else:
                ret = opp.select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
        if t_evolved is not None:
            evolved_turns.append(t_evolved)
            if t_could is not None:
                delays.append(max(0, t_evolved - t_could))
        if t_place is not None:
            place_turns.append(t_place)
        if bench_samples:
            bench_avg.append(sum(bench_samples) / len(bench_samples))
    avg = lambda x: (sum(x) / len(x)) if x else float("nan")
    return {"evolve_delay": avg(delays), "evolved_turn": avg(evolved_turns),
            "place_turn": avg(place_turns), "bench": avg(bench_avg),
            "evolved_rate": len(evolved_turns) / games}


def main(deck="deck", spec_key=None, games=16):
    spec_key = spec_key or deck
    dl = load(deck); plan = infer_plan(dl)
    evolved_id = (plan.key_cards or (None,))[0]
    if not evolved_id or C[evolved_id].is_basic:
        print(f"{deck}: 主役がたね=進化timing対象外"); return
    preevo = evo_line(evolved_id, list(dict.fromkeys(dl)))
    print(f"=== EVOLVE/PLAY Timing 監査: {deck} (進化形={nm(evolved_id)}, 前段={[nm(i) for i in preevo]}) ===")
    uni = audit(lambda d: UniversalBot(decklist=d), dl, evolved_id, preevo, games)
    spec = audit(lambda d: R.DECK_BOTS[spec_key](decklist=d), dl, evolved_id, preevo, games)
    print(f"{'指標':<22}{'Universal':>12}{'専用bot':>12}")
    for k, lab in [("place_turn", "主役ライン初設置T"), ("evolved_turn", "進化完成T"),
                   ("evolve_delay", "進化遅延(可能→実行)"), ("evolved_rate", "進化到達率"), ("bench", "平均ベンチ数")]:
        print(f"{lab:<22}{uni[k]:>12.2f}{spec[k]:>12.2f}")


if __name__ == "__main__":
    for d, k in [("deck", "deck"), ("archaludon_real", "archaludon")]:
        main(d, k); print()
