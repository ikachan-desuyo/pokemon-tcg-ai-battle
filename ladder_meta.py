"""実ラダー(Kaggle)の対戦メタ分析: 1000PARTY の全エピソードを取得し、
相手デッキ(アーキタイプ)別の勝敗分布・相手Elo帯別の勝率を集計する。

提出Bot改善フェーズの入口: 「どのデッキに本当に負けているか」を実データで可視化する。
リプレイ: https://www.kaggleusercontent.com/episodes/{id}.json (steps[1]のactionが両者のデッキ60枚)
"""
import json, os, sys, time, urllib.request, pathlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import load_cards

C = load_cards()
SC = pathlib.Path(os.environ.get("SCRATCH",
    "/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad"))
REP = SC / "replays"; REP.mkdir(exist_ok=True)
MY_SUBS = {54177340: "v5", 54238141: "v6"}

# アーキタイプ判定: 代表カード(具体的→一般の順で判定)
SIGS = [
    ("MegaStarmie", {"Mega Starmie ex"}),
    ("MegaFroslass", {"Mega Froslass ex"}),
    ("Archaludon", {"Archaludon ex"}),
    ("Lightning", {"Miraidon ex", "Pikachu ex"}),
    ("Dragapult", {"Dragapult ex"}),
    ("MegaGardevoir", {"Mega Gardevoir ex"}),
    ("Alakazam", {"Alakazam"}),
    ("MegaScrafty", {"Mega Scrafty ex"}),
    ("MegaLucario", {"Mega Lucario ex"}),
    ("MegaLopunny", {"Mega Lopunny ex"}),
    ("MegaYukinooh", {"Mega Abomasnow ex"}),
    ("MegaKangaskhan", {"Mega Kangaskhan ex"}),
]


def archetype(deck_ids):
    names = {C[i].name for i in deck_ids if i in C}
    for label, sig in SIGS:
        if names & sig:
            return label
    # フォールバック: ex/進化の最大HPカード名
    best = None
    for i in set(deck_ids):
        ci = C.get(i)
        if ci and ci.is_pokemon and (ci.hp or 0) >= 200:
            if best is None or (ci.hp or 0) > (C[best].hp or 0):
                best = i
    return f"他({C[best].name})" if best else "不明"


def api_list(sub_id):
    req = urllib.request.Request(
        "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes",
        data=json.dumps({"submissionId": sub_id}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("episodes") or []


def fetch_replay(eid):
    p = REP / f"{eid}.json"
    if p.exists():
        return json.loads(p.read_text())
    url = f"https://www.kaggleusercontent.com/episodes/{eid}.json"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    p.write_bytes(data)
    time.sleep(0.4)
    return json.loads(data)


def main():
    rows = []
    for sub, tag in MY_SUBS.items():
        for e in api_list(sub):
            me = next((a for a in e["agents"] if a.get("submissionId") == sub), None)
            opp = next((a for a in e["agents"] if a.get("submissionId") != sub), None)
            if not me or not opp:
                continue
            my_idx = me.get("index", 0)
            try:
                rj = fetch_replay(e["id"])
                opp_deck = rj["steps"][1][1 - my_idx]["action"]
                arch = archetype(opp_deck)
            except Exception as ex:
                arch = f"取得失敗"
            rows.append({"tag": tag, "ep": e["id"], "win": me.get("reward") == 1,
                         "arch": arch, "opp_elo": opp.get("initialScore") or 0,
                         "my_elo": me.get("initialScore") or 0})
    json.dump(rows, open(SC / "ladder_rows.json", "w"))
    # 集計
    print(f"総試合: {len(rows)} (v5 {sum(1 for r in rows if r['tag']=='v5')} / v6 {sum(1 for r in rows if r['tag']=='v6')})")
    total_w = sum(1 for r in rows if r["win"])
    print(f"総合勝率: {total_w}/{len(rows)} = {100*total_w//max(1,len(rows))}%\n")
    print(f"{'アーキタイプ':<20}{'試合':>5}{'勝':>4}{'負':>4}{'勝率':>6}{'平均相手Elo':>10}")
    agg = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        a = agg[r["arch"]]; a[0] += 1; a[1] += int(r["win"]); a[2] += r["opp_elo"]
    for arch, (n, w, elo) in sorted(agg.items(), key=lambda x: -x[1][0]):
        print(f"{arch:<20}{n:>5}{w:>4}{n-w:>4}{100*w//max(1,n):>5}%{elo/max(1,n):>10.0f}")
    # Elo帯別
    print(f"\n{'相手Elo帯':<14}{'試合':>5}{'勝率':>6}")
    for lo, hi in [(0, 650), (650, 750), (750, 850), (850, 2000)]:
        b = [r for r in rows if lo <= r["opp_elo"] < hi]
        if b:
            w = sum(1 for r in b if r["win"])
            print(f"{lo}-{hi:<9}{len(b):>5}{100*w//len(b):>5}%")


if __name__ == "__main__":
    main()
