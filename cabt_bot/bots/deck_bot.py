"""デッキ専用 bot の共通エンジン（設定駆動）。

各デッキ bot は DeckPlan（回し方の設定）を与えるだけでよい。共通の処理順
（特性→展開→進化→エネ加速→攻撃、攻撃は最後）と安全なフォールバックを提供し、
デッキ固有の判断は DeckPlan で表現する:

- go_first: 先攻するか
- attackers: 主要アタッカーの card_id（エネ/進化の対象として優先）
- key_cards: 抱えていたら引き直し系(リーリエ等)を切らない card_id
- preferred_attacks: 優先したい攻撃名（英語, 例 "Jetting Blow"）。空なら最大ダメージ
- energy_rules: [(energy_id|None, target_id)] 高優先のエネ付け規則
- play_priority: {card_id: score} PLAY 優先度（汎用既定に上書き）
- card_values: {card_id: value} サーチ/トラッシュ選択の価値（汎用既定に上書き）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Bot
from ..cards import load_cards
from ..enums import AreaType, OptionType, SelectContext, SelectType
from ..models import Observation, Option

# 汎用 PLAY 優先度（多くのデッキ共通の一貫性札）
POFFIN, HYPER_BALL, POKE_PAD, MEGA_SIGNAL = 1086, 1121, 1152, 1145
RARE_CANDY, POKEGEAR, SWITCH, BOSS = 1079, 1122, 1123, 1182
NIGHT_STRETCHER, LILLIE = 1097, 1227
_GENERIC_PLAY = {
    POFFIN: 100, RARE_CANDY: 86, MEGA_SIGNAL: 84, HYPER_BALL: 82, POKE_PAD: 78,
    SWITCH: 64, BOSS: 62, POKEGEAR: 55, NIGHT_STRETCHER: 50,
}
_GENERIC_TAKE = {
    SelectContext.TO_HAND, SelectContext.TO_FIELD, SelectContext.TO_ACTIVE,
    SelectContext.TO_BENCH, SelectContext.SETUP_ACTIVE_POKEMON,
    SelectContext.SETUP_BENCH_POKEMON, SelectContext.EVOLVES_FROM,
    SelectContext.EVOLVES_TO, SelectContext.TO_HAND_ENERGY,
    SelectContext.HEAL, SelectContext.REMOVE_DAMAGE_COUNTER,
}
_GENERIC_GIVE = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.TO_PRIZE, SelectContext.DISCARD_ENERGY,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.TO_DECK_ENERGY,
    SelectContext.DEVOLVE,
}


@dataclass
class DeckPlan:
    name: str
    go_first: bool = False
    attackers: tuple[int, ...] = ()
    key_cards: tuple[int, ...] = ()
    preferred_attacks: tuple[str, ...] = ()
    energy_rules: tuple[tuple, ...] = ()      # (energy_id|None, target_id)
    play_priority: dict[int, int] = field(default_factory=dict)
    card_values: dict[int, int] = field(default_factory=dict)


class DeckBot(Bot):
    plan: DeckPlan = DeckPlan(name="default")

    def __init__(self, plan: DeckPlan | None = None) -> None:
        if plan is not None:
            self.plan = plan
        try:
            self._cards = load_cards()
        except Exception:
            self._cards = {}
        self._atk_dmg = None
        self._atk_name = None
        self._cur = None
        self._sel = None

    # ===== entry =====
    def select(self, obs: Observation) -> list[int]:
        sel = obs.select
        if sel is None or not sel.options:
            return []
        self._cur, self._sel = obs.current, sel
        try:
            t = sel.type
            if t == SelectType.MAIN:
                return self._main(sel.options)
            if t == SelectType.ATTACK:
                return [self._best_attack(range(len(sel.options)), sel.options)]
            if t == SelectType.COUNT:
                return [max(range(len(sel.options)), key=lambda i: sel.options[i].number or 0)]
            if t == SelectType.YES_NO:
                return [self._yes_no(sel)]
            if t in (SelectType.CARD, SelectType.ATTACHED_CARD,
                     SelectType.CARD_OR_ATTACHED_CARD, SelectType.ENERGY):
                return self._cards(sel)
            return self._take(sel, prefer_high=True, take_max=False)
        except Exception:
            return self._fallback(sel)

    # ===== MAIN（処理順） =====
    def _main(self, options: list[Option]) -> list[int]:
        me = self._me()
        hand = (me.get("hand") or []) if me else []
        g: dict = {}
        for i, op in enumerate(options):
            g.setdefault(op.type, []).append(i)
        if OptionType.ABILITY in g:
            return [g[OptionType.ABILITY][0]]
        if OptionType.PLAY in g:
            c = self._pick_play(g[OptionType.PLAY], options, hand)
            if c is not None:
                return [c]
        if OptionType.EVOLVE in g:
            return [self._pick_evolve(g[OptionType.EVOLVE], options, hand)]
        if OptionType.ATTACH in g:
            return [self._pick_attach(g[OptionType.ATTACH], options, hand, me)]
        if OptionType.ATTACK in g:
            return [self._best_attack(g[OptionType.ATTACK], options)]
        if OptionType.END in g:
            return [g[OptionType.END][0]]
        return [0]

    def _pick_play(self, idxs, options, hand):
        scored = []
        for i in idxs:
            cid = self._hand_id(hand, options[i].index)
            s = self._play_score(cid, hand)
            if s is None:
                continue
            scored.append((s, i))
        return max(scored, key=lambda x: x[0])[1] if scored else None

    def _play_score(self, cid, hand):
        if cid == LILLIE:
            if self._has_key(hand) or len(hand) >= 4:
                return None
            return 28
        if cid in self.plan.play_priority:
            return self.plan.play_priority[cid]
        if cid in self.plan.attackers:   # 進化前/アタッカーをベンチに置くのは重要
            return 80
        return _GENERIC_PLAY.get(cid, 40)

    def _pick_evolve(self, idxs, options, hand) -> int:
        best, best_key = idxs[0], (-1, -1)
        for i in idxs:
            op = options[i]
            evo = self._hand_id(hand, op.index)
            key = (1 if evo in self.plan.attackers else 0,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if key > best_key:
                best_key, best = key, i
        return best

    def _pick_attach(self, idxs, options, hand, me) -> int:
        best, best_key = idxs[0], (-1, -1, -1)
        for i in idxs:
            op = options[i]
            energy = self._hand_id(hand, op.index)
            target = self._target_id(me, op.in_play_area, op.in_play_index)
            rule = self._energy_rule_rank(energy, target)
            key = (rule,
                   1 if target in self.plan.attackers else 0,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if key > best_key:
                best_key, best = key, i
        return best

    def _energy_rule_rank(self, energy, target) -> int:
        # energy_rules の上にあるものほど高ランク
        rules = self.plan.energy_rules
        for k, (eid, tid) in enumerate(rules):
            if (eid is None or energy == eid) and target == tid:
                return len(rules) - k
        return 0

    # ===== 攻撃 =====
    def _best_attack(self, idxs, options) -> int:
        idxs = list(idxs)
        for nm in self.plan.preferred_attacks:
            aid = self._attack_name_ids().get(nm)
            for i in idxs:
                if aid and options[i].attack_id == aid:
                    return i
        return max(idxs, key=lambda i: self._dmg(options[i]))

    def _dmg(self, op: Option) -> int:
        if op.attack_id is None:
            return 0
        return self._attack_table().get(op.attack_id, 0)

    # ===== YesNo =====
    def _yes_no(self, sel) -> int:
        ctx = sel.context
        want_yes = True
        if isinstance(ctx, SelectContext):
            if ctx == SelectContext.IS_FIRST:
                want_yes = self.plan.go_first
            elif ctx == SelectContext.MORE_DEVOLVE:
                want_yes = False
        target = OptionType.YES if want_yes else OptionType.NO
        for i, op in enumerate(sel.options):
            if op.type == target:
                return i
        return 0

    # ===== カード選択 =====
    def _cards(self, sel) -> list[int]:
        ctx = sel.context
        if isinstance(ctx, SelectContext) and ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            pref = self._first_of(sel, self.plan.attackers)  # 進化前が居れば前に
            if pref is not None:
                return [pref]
        give = isinstance(ctx, SelectContext) and ctx in _GENERIC_GIVE
        take = isinstance(ctx, SelectContext) and ctx in _GENERIC_TAKE
        if give:
            return self._take(sel, prefer_high=False, take_max=False)
        if take:
            return self._take(sel, prefer_high=True, take_max=True)
        return self._take(sel, prefer_high=True, take_max=False)

    def _take(self, sel, prefer_high: bool, take_max: bool) -> list[int]:
        n = len(sel.options)
        k = sel.max_count if take_max else sel.min_count
        k = max(0, min(k, n))
        if k == 0:
            return []
        ranked = sorted(range(n), key=lambda i: self._opt_value(sel.options[i]),
                        reverse=prefer_high)
        return sorted(ranked[:k])

    def _first_of(self, sel, want_ids) -> int | None:
        for cid in want_ids:
            for i, op in enumerate(sel.options):
                if self._opt_card_id(op) == cid:
                    return i
        return None

    # ===== ヘルパ =====
    def _me(self):
        cur = self._cur
        return cur["players"][cur["yourIndex"]] if cur else None

    @staticmethod
    def _hand_id(hand, idx):
        return hand[idx].get("id") if (idx is not None and 0 <= idx < len(hand)) else None

    @staticmethod
    def _target_id(me, area, idx):
        if idx is None:
            return None
        spots = (me.get("active") if area == AreaType.ACTIVE else me.get("bench")) or []
        return spots[idx].get("id") if (0 <= idx < len(spots) and spots[idx]) else None

    def _has_key(self, hand) -> bool:
        keys = self.plan.key_cards or self.plan.attackers
        return any(c.get("id") in keys for c in hand)

    def _opt_card_id(self, op: Option):
        if op.card_id is not None:
            return op.card_id
        me = self._me()
        area, idx = op.area, op.index
        if idx is None:
            return None
        if self._sel is not None and self._sel.deck and area == AreaType.DECK:
            if 0 <= idx < len(self._sel.deck):
                return self._sel.deck[idx].card_id
        if me is None:
            return None
        zone = {AreaType.HAND: me.get("hand"), AreaType.ACTIVE: me.get("active"),
                AreaType.BENCH: me.get("bench"), AreaType.DISCARD: me.get("discard")}.get(area)
        if zone and 0 <= idx < len(zone) and zone[idx]:
            return zone[idx].get("id")
        return None

    def _opt_value(self, op: Option) -> int:
        cid = self._opt_card_id(op)
        if cid is None:
            return 42
        if cid in self.plan.card_values:
            return self.plan.card_values[cid]
        if cid in self.plan.attackers:
            return 95
        c = self._cards.get(cid)
        if c and c.hp is not None:
            return 80 if (c.rule and "ex" in (c.rule or "").lower()) else 60
        return 42

    def _attack_table(self) -> dict:
        if self._atk_dmg is None:
            self._load_attacks()
        return self._atk_dmg

    def _attack_name_ids(self) -> dict:
        if self._atk_name is None:
            self._load_attacks()
        return self._atk_name

    def _load_attacks(self):
        self._atk_dmg, self._atk_name = {}, {}
        try:
            import sys
            from pathlib import Path
            root = str(Path(__file__).resolve().parents[2])
            if root not in sys.path:
                sys.path.insert(0, root)
            from cg.api import all_attack  # type: ignore
            for a in all_attack():
                self._atk_dmg[a.attackId] = a.damage or 0
                self._atk_name.setdefault(a.name, a.attackId)
        except Exception:
            pass

    @staticmethod
    def _fallback(sel) -> list[int]:
        n = len(sel.options)
        return list(range(min(max(1, sel.min_count), n)))
