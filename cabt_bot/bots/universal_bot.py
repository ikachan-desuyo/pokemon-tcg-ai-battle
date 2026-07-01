"""UniversalBot（Plan AI Episode 4）: デッキ固有の手書き DeckPlan を使わず、
デッキリスト＋カードデータから **最小限の plan（attackers / energy_rules / setup_energy）だけを自動導出**し、
既存の DeckBot エンジン（Analyzer / evaluate_position / Decision Kernel）で回す。

方針(Episode 4 ルール): 新しい Analyzer は作らない。チューニングノブ(boss/recover/wall/spread/reposition…)は
全て OFF のまま。「専用ロジックを書けば勝てる」でなく「Universal が自然に対応できる」ことを目指す。
"""
from __future__ import annotations

import re

from .deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

_SYM = re.compile(r"\{([A-Z])\}|(●)")


def _cost_syms(cost: str | None) -> list[str]:
    """技コスト "{R}{R}●" → ['R','R','C'](●/無色=C)。"""
    if not cost:
        return []
    out = []
    for m in _SYM.finditer(cost):
        out.append("C" if m.group(2) else m.group(1))
    return out


_ABILITY = "[Ability]"
_EST_COUNT = 5      # 可変ダメージの代表個数(手札/ベンチ枚数などの想定値)


def interpret_move(mv) -> dict:
    """Move を総合解釈する（Episode4 の心臓）。damage欄と effect文を統合して
    「攻撃か / 実効ダメージ / コスト記号」を返す。個別if でなく Move全体の解釈能力。
      - "[Ability]" は攻撃でない。
      - damage欄が空でも effect文の「does N damage」「N damage counters ... for each」等からダメージを推定
        ＝可変ダメージ主役(フーディン ハンドパワー / Cruel Arrow 等)を取りこぼさない。
    返り値: {is_attack, est_damage, cost_syms}。"""
    name = mv.name or ""
    if name.startswith(_ABILITY):
        return {"is_attack": False, "est_damage": 0, "cost_syms": []}
    syms = _cost_syms(mv.cost)
    est = 0
    if mv.damage:
        m = re.match(r"(\d+)", str(mv.damage))
        if m:
            est = int(m.group(1))
    if est == 0 and mv.effect:                 # damage欄が空 → 効果文から推定
        eff = mv.effect
        m = re.search(r"does (\d+) damage", eff)
        if m:
            est = int(m.group(1))              # 効果文の固定ダメージ(Cruel Arrow=100)
        else:
            m = re.search(r"(\d+) damage counters?.*?for each", eff)
            if m:
                est = int(m.group(1)) * 10 * _EST_COUNT    # counters×10dmg×代表個数(可変)
            elif re.search(r"for each|times the number|damage .*×|×.*damage", eff):
                est = 60                        # 倍率不明の可変=中程度と見なし攻撃役認識
    return {"is_attack": (mv.cost is not None) and est > 0, "est_damage": est, "cost_syms": syms}


def _energy_type(ci) -> str | None:
    """基本エネカードの型記号。"Basic {W} Energy" → 'W'。エネでなければ None。"""
    if not ci or ci.is_pokemon:
        return None
    nm = ci.name or ""
    if "Energy" not in nm:
        return None
    m = re.search(r"\{([A-Z])\}", nm)
    return m.group(1) if m else None


def infer_plan(decklist) -> DeckPlan:
    """デッキリストから最小 plan を推論（デッキ非依存）。attackers / energy_rules / setup_energy / lethal。"""
    C = load_cards()
    ids = list(dict.fromkeys(int(x) for x in decklist))
    pokes = [i for i in ids if C.get(i) and C[i].is_pokemon]

    def moves_of(i):
        return [interpret_move(mv) for mv in C[i].moves]

    def maxdmg(i):
        return max((im["est_damage"] for im in moves_of(i) if im["is_attack"]), default=0)

    def best_attack(i):
        atks = [im for im in moves_of(i) if im["is_attack"]]
        return max(atks, key=lambda im: im["est_damage"]) if atks else None

    damaging = [i for i in pokes if any(im["is_attack"] for im in moves_of(i))]
    # 進化線(previous_stage 名で辿る)を含めて attacker 役を集める＝前段のたねも役に含める
    name2id = {C[i].name: i for i in pokes}

    def line(i):
        chain = [i]; cur = C[i]
        seen = {i}
        while cur and cur.previous_stage and cur.previous_stage in name2id:
            pid = name2id[cur.previous_stage]
            if pid in seen:
                break
            chain.append(pid); seen.add(pid); cur = C[pid]
        return chain

    attackers = set()
    for i in damaging:
        attackers.update(line(i))

    # 基本エネカード: id → 型
    energy_type = {i: _energy_type(C[i]) for i in ids}
    energy_type = {i: t for i, t in energy_type.items() if t}

    # 主アタッカー(最大火力順) の"最初に使う技=主役の最良技"から energy_rules / setup_energy を導出
    main = sorted(damaging, key=maxdmg, reverse=True)
    # setup_energy は最強デッキ全体でなく「主役(main[0])の主技」のコスト＝最初に使う技(ユーザ指摘)
    setup = 0
    if main:
        b0 = best_attack(main[0])
        if b0:
            setup = len(b0["cost_syms"])
    rules = []
    for atk in main[:3]:
        best = best_attack(atk)
        if not best:
            continue
        syms = best["cost_syms"]
        needed = [t for t in syms if t != "C"] or (["C"] if syms else [])
        for t in needed:
            # 必要型に一致する基本エネ、無ければ任意の基本エネ(無色枠用)
            eid = next((e for e, et in energy_type.items() if et == t), None)
            if eid is None and t == "C" and energy_type:
                eid = next(iter(energy_type))
            if eid is not None:
                rules.append((eid, atk))

    # card_values / play_priority を火力から自動導出（デッキ固有チューニングでなくカードデータ由来）
    #   主役ほど高価値=守る/出す。専用botの手書き値を、火力という普遍指標で代替する。
    card_values = {}
    play_priority = {}
    for rank, i in enumerate(main):
        d = maxdmg(i)
        card_values[i] = min(100, 50 + d // 3)        # 火力比例(主役ほど高い)
        play_priority[i] = max(45, 88 - rank * 6)      # 火力順に早く出す
    for e in energy_type:
        card_values.setdefault(e, 82)                  # エネは温存価値やや高め

    return DeckPlan(
        name="Universal",
        attackers=tuple(attackers),
        key_cards=tuple(main[:2]),
        energy_rules=tuple(dict.fromkeys(rules)),
        lethal=True,                       # KOできる技を優先(デッキ非依存の普遍原則)
        setup_energy=setup or 0,
        card_values=card_values,
        play_priority=play_priority,
    )


class UniversalBot(DeckBot):
    """デッキ固有 plan を持たず、デッキリストから自動導出した最小 plan で既存エンジンを回す。"""
    def __init__(self, decklist=None, plan: DeckPlan | None = None) -> None:
        if plan is None and decklist is not None:
            plan = infer_plan(decklist)
        super().__init__(plan=plan, decklist=decklist)
