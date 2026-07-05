"""提出前・最終QA(人間レビュー)用のローカル対戦セッション。

標準プロセス: 実装→ReplayReviewer→QA Gate PASS→ローカル対戦→人間レビュー→提出。
- 60戦(ミラー20+ladder_lucario20+ladder_archaludon20)をKaggle互換形式で完全記録(ビューアHTML化可能)
- 全試合をQA検出器にかけ(大標本の再確認)、選定条件で代表3-5本を抽出:
  負け > 接戦(サイド差<=1) > 難しい勝ち(長期戦の勝ち) > 長期戦 / 対面の多様性を確保
"""
import json, os, sys, pathlib, subprocess
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
import replay_reviewer as RR

SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
OUT = SC / "local_replays"; OUT.mkdir(exist_ok=True)


def play_recorded(mk_me, mk_opp, deck_me, deck_opp, label):
    """1試合をKaggle互換のreplay JSONとして記録(+検出器用decisions)。自分=agent0。"""
    me_bot = mk_me(); opp_bot = mk_opp()
    steps = []
    decisions = [[], []]   # 両サイドの意思決定(相手ベンチマークbotも監査対象)
    obs, _sd = battle_start(deck_me, deck_opp)
    n = 0; final_cur = None; winner = -1
    try:
        while obs is not None and n < 3000:
            o = to_observation_class(obs); st = o.current
            if st and st.result != -1:
                winner = st.result; final_cur = obs.get("current")
                steps.append([{"status": "DONE", "observation": obs},
                              {"status": "DONE", "observation": obs}])
                break
            if o.select is None or not o.select.option:
                break
            who = st.yourIndex if st else 0
            bot = me_bot if who == 0 else opp_bot
            sel = bot.select(Observation.from_dict(obs)) or [0]
            entry = [{"status": "INACTIVE", "observation": {}},
                     {"status": "INACTIVE", "observation": {}}]
            entry[who] = {"status": "ACTIVE", "observation": obs, "action": list(sel)}
            steps.append(entry)
            if obs.get("current"):
                decisions[who].append((len(steps) - 1, obs, list(sel)))
                if who == 0:
                    final_cur = obs.get("current")
            obs = battle_select(sel); n += 1
    finally:
        battle_finish()
    rewards = [0, 0]
    if winner in (0, 1):
        rewards = [1, -1] if winner == 0 else [-1, 1]
    rj = {"steps": steps, "rewards": rewards,
          "info": {"Agents": [{"Name": "1000PARTY"}, {"Name": label.split("-")[0]}]}}
    stats = {"label": label, "win": winner == 0, "turns": 0, "my_pz": 6, "opp_pz": 6}
    if final_cur:
        stats["turns"] = final_cur.get("turn", 0)
        stats["my_pz"] = len(final_cur["players"][0].get("prize") or [])
        stats["opp_pz"] = len(final_cur["players"][1].get("prize") or [])
    path = OUT / f"{label}.json"
    json.dump(rj, open(path, "w"))
    games = [{"ep": label, "my": 0, "decisions": decisions[0]},
             {"ep": f"{label}(相手bot)", "my": 1, "decisions": decisions[1]}]
    return games, stats, path


def main():
    dl = [int(x) for x in open("decks/deck.csv").read().split() if x.strip()]
    matchups = [("mirror", "deck", "deck", 10),
                ("lucario", "ladder_lucario", "ladder_lucario", 10),
                ("arch", "ladder_archaludon", "ladder_archaludon", 10),
                ("dragapult", "dragapult", "dragapult", 10),
                ("alakazam", "alakazam", "alakazam", 10),
                ("grimmsnarl", "grimmsnarl", "meta_grimmsnarl", 10)]
    counts = Counter(); reps = defaultdict(list); all_stats = []
    fam_side = {"self": Counter(), "opp": Counter()}   # 検出ファミリ別×側(自bot/相手bot)

    def sig(key, ep, turn):
        counts[key] += 1
        fam_side["opp" if "(相手bot)" in ep else "self"][key.split("|")[0]] += 1
        if len(reps[key]) < 3:
            reps[key].append(f"{ep}:T{turn}")
    for tag, opp_key, opp_deck, n_games in matchups:
        od = [int(x) for x in open(f"decks/{opp_deck}.csv").read().split() if x.strip()]
        for gi in range(n_games):
            games, stats, path = play_recorded(
                lambda: R.DECK_BOTS["deck"](decklist=dl),
                lambda: R.DECK_BOTS[opp_key](decklist=od),
                dl, od, f"{tag}-{gi}")
            all_stats.append(stats)
            for game in games:
                for det in RR.DETECTORS:
                    det(game, sig)
    n = len(all_stats)
    wins = sum(1 for s in all_stats if s["win"])
    print(f"=== ローカル最終QAセッション: {n}戦 (勝率 {100*wins//n}%) ===")
    # Known推移の機械比較: サイクル毎に同形式で保存し、前回比(再発件数の増減)を必ず出す。
    # =Reviewerの成熟でなく「改善ループが収束しているか」の測定(ユーザ指示)。
    trend_path = SC / "known_trend.json"
    prev = json.load(open(trend_path)) if trend_path.exists() else {}
    for side, label in (("self", "自bot"), ("opp", "相手bot")):
        print(f"--- Known推移({label}側・件/60戦, 前回比) ---")
        pv = prev.get(side, {})
        for f in sorted(set(fam_side[side]) | set(pv)):
            c = fam_side[side].get(f, 0); d = c - pv.get(f, 0)
            mark = f"{'+' if d > 0 else ''}{d}" if pv else "初回計測"
            print(f"  {f}: {c} (前回比 {mark})")
    json.dump({s: dict(c) for s, c in fam_side.items()}, open(trend_path, "w"))
    # Issue Tracker: ライフサイクル(Open→Confirmed→Fix Applied→Graduated→Regressed)を更新。
    # 卒業済みIssueが再発したら⚠警告(品質管理システムとしてのReplayReviewer)。
    import issue_tracker
    reg, alerts = issue_tracker.update(dict(counts))
    for a in alerts:
        print(a)
    print(issue_tracker.report(reg))
    from qa_gate import BLOCKING_PREFIXES
    blocking = [(k, c) for k, c in counts.items() if any(k.startswith(p) for p in BLOCKING_PREFIXES)]
    print(f"QA検出器(大標本再確認): BLOCKING {sum(c for _, c in blocking)}件")
    for k, c in sorted(blocking, key=lambda x: -x[1]):
        print(f"  ❌ {k}: {c} {reps[k]}")
    # 対面別
    by = defaultdict(lambda: [0, 0])
    for s in all_stats:
        t = s["label"].split("-")[0]; by[t][0] += int(s["win"]); by[t][1] += 1
    for t, (w, tot) in by.items():
        print(f"  {t}: {w}/{tot}")
    # ===== 代表リプレイ選定 =====
    losses = [s for s in all_stats if not s["win"]]
    # 接戦=両者ともサイドを4枚以上取った(残り<=2)試合(ユーザ基準: サイド4-6, 5-6)
    close = [s for s in all_stats if s["my_pz"] <= 2 and s["opp_pz"] <= 2]
    hard_wins = sorted([s for s in all_stats if s["win"]], key=lambda s: -s["turns"])
    longest = sorted(all_stats, key=lambda s: -s["turns"])
    picked = []; seen = set()

    def pick(s, why):
        if s and s["label"] not in seen and len(picked) < 5:
            seen.add(s["label"]); picked.append((s, why))
    # 負け(重点対面優先・対面の多様性)
    for pref in ("lucario", "arch", "mirror"):
        pick(next((s for s in losses if s["label"].startswith(pref)), None), f"負け({pref})")
    pick(next((s for s in close if s["label"] not in seen), None), "接戦(サイド差<=1)")
    pick(next((s for s in hard_wins if s["label"] not in seen), None), "難しい勝ち(最長の勝ち試合)")
    pick(next((s for s in longest if s["label"] not in seen), None), "長期戦")
    print("\n=== 人間レビュー用 代表リプレイ ===")
    sel_files = []
    for s, why in picked:
        print(f"  {s['label']}: {why} | {'勝' if s['win'] else '負'} {s['turns']}T サイド残 自{s['my_pz']}-相{s['opp_pz']}")
        sel_files.append(str(OUT / f"{s['label']}.json"))
    json.dump(sel_files, open(SC / "review_selection.json", "w"))


if __name__ == "__main__":
    main()
