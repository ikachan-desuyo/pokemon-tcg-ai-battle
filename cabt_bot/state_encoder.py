"""盤面の状態ベクトル化(カード能力ベース)。学習価値モデルと ValueModelBot で共有。

GPTレビュー指針: カードIDのEmbedding単独でなく『カード→能力ベクトル』を特徴に。
盤面の汎用統計(サイド/HP/エネ/ベンチ)に加え、active/ベンチの『カードが何をできるか』
(最大ダメージ/最小コスト/進化段階/特性有無/サイド価値/弱点相性)を符号化する。
＝MegaStarmie/Archaludon/Dragapultが“同じ盤面”に見える問題を解消し、汎用化を狙う。
"""
import csv, re
from collections import defaultdict

_CSV = "input_data/extracted/JP_Card_Data.csv"
_COLORED = set("水超悪鋼闘草炎雷竜妖")
_CAPS = None


_FWD = None   # 進化前名 -> その進化先のカードid群(forward evolution map)
_NAME = {}    # cid -> name


def _load_caps():
    rows = defaultdict(list)
    try:
        for r in csv.DictReader(open(_CSV, encoding="utf-8")):
            rows[r["カード ID"]].append(r)
    except Exception:
        return {}
    caps = {}
    global _FWD
    _FWD = defaultdict(list)
    for cid, rs in rows.items():
        r0 = rs[0]
        stage_s = r0.get("ポケモンの進化の段階/エネルギー・トレーナーズの種類") or ""
        name = r0.get("カード名") or ""
        prev = (r0.get("進化前") or "").strip()
        _NAME[int(cid)] = name
        if prev and prev != "n/a":
            _FWD[prev].append(int(cid))
        hp = int(r0["HP"]) if (r0.get("HP") or "").isdigit() else 0
        typ = (r0.get("タイプ") or "").strip()
        weak = (r0.get("弱点") or "").strip()
        retreat = int(r0["にげる"]) if (r0.get("にげる") or "").isdigit() else 0
        evo = 1 if "1進化" in stage_s else (2 if "2進化" in stage_s else 0)
        pv = 3 if ("メガ" in name and "ex" in name) else (2 if "ex" in name else 1)
        max_dmg = 0; min_cost = 99; has_ability = 0
        for r in rs:
            wn = r.get("ワザ名") or ""
            if "特性" in wn:
                has_ability = 1; continue
            cost = (r.get("コスト") or "").strip()
            if cost and cost != "n/a":
                c = sum(1 for ch in cost if ch in _COLORED or ch == "●")
                if c:
                    min_cost = min(min_cost, c)
            m = re.match(r"(\d+)", (r.get("ダメージ") or "").strip())
            if m:
                max_dmg = max(max_dmg, int(m.group(1)))
        if min_cost == 99:
            min_cost = 0
        caps[int(cid)] = dict(hp=hp, type=typ, weak=weak, retreat=retreat, evo=evo,
                              pv=pv, max_dmg=max_dmg, min_cost=min_cost, has_ability=has_ability)
    return caps


_EMPTY = dict(hp=0, type="", weak="", retreat=0, evo=0, pv=1, max_dmg=0, min_cost=0, has_ability=0)


def caps(cid):
    global _CAPS
    if _CAPS is None:
        _CAPS = _load_caps()
    return _CAPS.get(cid, _EMPTY)


def line_threat(cid):
    """このポケモンの進化ライン(自分＋進化先を辿った全カード)の最大ワザダメージ。
    ＝『進化前を倒すとどれだけの脅威の芽を摘めるか』。例: リオル→メガルカリオex(270)なら270。"""
    caps(cid)  # 初期化
    best = _CAPS.get(cid, _EMPTY)["max_dmg"]
    seen = set()
    frontier = [cid]
    while frontier:
        c = frontier.pop()
        if c in seen:
            continue
        seen.add(c)
        nm = _NAME.get(c)
        for nxt in (_FWD.get(nm, []) if _FWD else []):
            best = max(best, _CAPS.get(nxt, _EMPTY)["max_dmg"])
            frontier.append(nxt)
    return best


def _en(s):
    e = (s.get("energyCards") if isinstance(s, dict) else None) or s.get("energies") or []
    return len(e)


def _board(p):
    act = (p.get("active") or [None])[0]
    bench = [s for s in (p.get("bench") or []) if s]
    pr = p.get("prize") or p.get("prizes") or []
    return act, bench, (sum(1 for x in pr if x) if pr else 6)


# 特徴量名(順序固定)。盤面16 + active能力(自/相)12 + 弱点相性2 + ベンチ能力3 = 33
FEATURES = [
    # 盤面の汎用統計
    "my_prizes", "opp_prizes", "prize_diff", "my_hp_ratio", "opp_hp_ratio",
    "my_active_energy", "opp_active_energy", "my_bench", "opp_bench",
    "my_board_energy", "opp_board_energy", "my_hand", "opp_hand", "turn",
    "my_has_active", "opp_has_active",
    # active のカード能力(自)
    "my_act_maxdmg", "my_act_mincost", "my_act_evo", "my_act_ability", "my_act_pv", "my_act_hp",
    # active のカード能力(相)
    "opp_act_maxdmg", "opp_act_mincost", "opp_act_evo", "opp_act_ability", "opp_act_pv", "opp_act_hp",
    # 弱点相性
    "my_exploits_weak", "opp_exploits_weak",
    # ベンチの攻撃力
    "my_bench_maxdmg", "my_bench_attackers", "opp_bench_attackers",
]


def encode_state(cur, who):
    me = cur["players"][who]; op = cur["players"][1 - who]
    ma, mb, mpz = _board(me); oa, ob, opz = _board(op)
    mac = caps(ma["id"]) if ma else _EMPTY
    oac = caps(oa["id"]) if oa else _EMPTY
    mhp = (ma.get("hp", 0) / ma["maxHp"]) if (ma and ma.get("maxHp")) else 0.0
    ohp = (oa.get("hp", 0) / oa["maxHp"]) if (oa and oa.get("maxHp")) else 0.0
    # 弱点相性: 自active タイプ == 相active 弱点 なら自分有利
    my_exploit = 1 if (ma and oa and mac["type"] and oac["weak"] and mac["type"] == oac["weak"]) else 0
    opp_exploit = 1 if (ma and oa and oac["type"] and mac["weak"] and oac["type"] == mac["weak"]) else 0
    bench_dmgs = [caps(s["id"])["max_dmg"] for s in mb]
    my_bench_maxdmg = max(bench_dmgs) if bench_dmgs else 0
    my_bench_atk = sum(1 for d in bench_dmgs if d >= 100)
    opp_bench_atk = sum(1 for s in ob if caps(s["id"])["max_dmg"] >= 100)
    return [
        mpz, opz, opz - mpz, mhp, ohp,
        _en(ma) if ma else 0, _en(oa) if oa else 0, len(mb), len(ob),
        (_en(ma) if ma else 0) + sum(_en(s) for s in mb),
        (_en(oa) if oa else 0) + sum(_en(s) for s in ob),
        len(me.get("hand") or []), len(op.get("hand") or []), cur.get("turn", 0),
        1 if ma else 0, 1 if oa else 0,
        mac["max_dmg"], mac["min_cost"], mac["evo"], mac["has_ability"], mac["pv"], mac["hp"],
        oac["max_dmg"], oac["min_cost"], oac["evo"], oac["has_ability"], oac["pv"], oac["hp"],
        my_exploit, opp_exploit,
        my_bench_maxdmg, my_bench_atk, opp_bench_atk,
    ]
