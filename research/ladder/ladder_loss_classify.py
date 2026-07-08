"""MegaLucario負け23試合の敗因分類(①統計→②頻度)。修正はしない・DecisionDiffもまだ使わない。

リプレイ(自分視点の全observation)からゲーム特徴を抽出して分類:
  無攻撃事故 / 展開負け(Mega未着地 or サイド0-1) / 競り負け(2-4) / あと一歩(5) / ベンチ切れ
補助特徴: 初攻撃T, Mega着地T, 相手の初KO T, KO間隔(相手のテンポ), 終局サイド。
"""
import json, os, sys, pathlib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import load_cards

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path("/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad")
ATTACK = 13; MEGA = 1031


def analyze(ep):
    rj = json.load(open(SC / "replays" / f"{ep}.json"))
    d0 = rj["steps"][1][0]["action"]
    my = 0 if (d0 and MEGA in d0) else 1
    attacks = 0; first_atk = None; mega_turn = None
    my_pz_hist = []; opp_pz_hist = []; last_board = []
    opp_ko_turns = []
    prev_my_pz = 6
    end_my_pz = 6; end_opp_pz = 6; last_turn = 0
    for t in range(2, len(rj["steps"])):
        ag = rj["steps"][t][my]
        ob = ag.get("observation") or {}
        cur = ob.get("current")
        if not cur:
            continue
        turn = cur.get("turn", 0); last_turn = max(last_turn, turn)
        me = cur["players"][cur.get("yourIndex", my)] if cur.get("yourIndex") is not None else cur["players"][my]
        opp = cur["players"][1 - (cur.get("yourIndex", my))]
        my_pz = len(me.get("prize") or []); opp_pz = len(opp.get("prize") or [])
        end_my_pz, end_opp_pz = my_pz, opp_pz
        if my_pz < prev_my_pz:      # 自分のサイドが減る=×ではなく: prizeは自分が取る山→減る=自分が取った
            pass
        prev_my_pz = my_pz
        board = [s.get("id") for s in ([(me.get("active") or [None])[0]] + list(me.get("bench") or [])) if s]
        last_board = board
        if mega_turn is None and MEGA in board:
            mega_turn = turn
        sel = ob.get("select") or {}
        act = ag.get("action")
        if sel.get("type") == 0 and act and sel.get("option"):
            i = act[0] if isinstance(act, list) else act
            if isinstance(i, int) and 0 <= i < len(sel["option"]) and (sel["option"][i] or {}).get("type") == ATTACK:
                attacks += 1
                if first_atk is None:
                    first_atk = turn
    taken = 6 - end_my_pz          # 自分が取った枚数(自分のprize山が減った分)
    opp_taken = 6 - end_opp_pz
    # 分類
    if attacks == 0:
        cat = "無攻撃事故"
    elif mega_turn is None:
        cat = "展開負け(Mega未着地)"
    elif taken <= 1:
        cat = "展開負け(サイド0-1)"
    elif taken <= 4:
        cat = "競り負け(2-4)"
    else:
        cat = "あと一歩(5)"
    benchout = (end_my_pz > 0 and end_opp_pz > 0)
    return {"ep": ep, "cat": cat, "attacks": attacks, "first_atk": first_atk,
            "mega_turn": mega_turn, "taken": taken, "opp_taken": opp_taken,
            "turns": last_turn, "benchout": benchout,
            "final_board": [nm(i) for i in last_board]}


def main():
    rows = json.load(open(SC / "ladder_rows.json"))
    losses = [r["ep"] for r in rows if r["arch"] == "MegaLucario" and not r["win"]]
    wins = [r["ep"] for r in rows if r["arch"] == "MegaLucario" and r["win"]]
    print(f"MegaLucario: 負け{len(losses)} / 勝ち{len(wins)}")
    cats = Counter(); details = []
    for ep in losses:
        try:
            d = analyze(ep)
        except Exception as ex:
            d = {"ep": ep, "cat": f"解析失敗:{ex}"}
        cats[d["cat"]] += 1; details.append(d)
    print("\n=== ① 敗因分類 ===")
    for c, n in cats.most_common():
        print(f"  {c:<22} {n}")
    print("\n=== 詳細(全敗戦) ===")
    for d in details:
        if "attacks" in d:
            bo = " ベンチ/山切れ" if d.get("benchout") else ""
            print(f"  ep{d['ep']}: {d['cat']:<16} 取得{d['taken']}-{d['opp_taken']}被 "
                  f"初攻撃T{d['first_atk']} MegaT{d['mega_turn']} {d['turns']}T{bo}")
    # 参考: 勝ち試合の特徴(比較用ベースライン)
    wfeat = []
    for ep in wins[:10]:
        try:
            wfeat.append(analyze(ep))
        except Exception:
            pass
    if wfeat:
        avg = lambda k: sum((w.get(k) or 0) for w in wfeat) / len(wfeat)
        lavg = lambda k: sum((d.get(k) or 0) for d in details if "attacks" in d) / max(1, sum(1 for d in details if "attacks" in d))
        print(f"\n=== 勝敗比較(平均) ===")
        for k, lab in [("first_atk", "初攻撃T"), ("mega_turn", "Mega着地T"), ("taken", "取得サイド"), ("turns", "試合長")]:
            print(f"  {lab:<10} 負け{lavg(k):.1f} / 勝ち{avg(k):.1f}")


if __name__ == "__main__":
    main()
