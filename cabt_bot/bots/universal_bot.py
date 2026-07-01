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


def _dmg(move) -> int:
    if not move.damage:
        return 0
    m = re.match(r"(\d+)", str(move.damage))
    return int(m.group(1)) if m else 0


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

    def maxdmg(i):
        return max((_dmg(mv) for mv in C[i].moves), default=0)

    damaging = [i for i in pokes if maxdmg(i) > 0]
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

    # 主アタッカー(最大火力順) の主技コストから energy_rules / setup_energy を導出
    main = sorted(damaging, key=maxdmg, reverse=True)
    rules = []; setup = 0
    for atk in main[:3]:
        best = max(C[atk].moves, key=_dmg, default=None)
        if not best:
            continue
        syms = _cost_syms(best.cost)
        setup = max(setup, len(syms))
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
