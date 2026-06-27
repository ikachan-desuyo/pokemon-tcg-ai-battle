"""ルールベースの実戦エージェント。

設計の核:
- 1ターン内は「特性 → 進化 → 場の展開/サポート → エネ加速」を先にやり切り、
  他にやることが無くなってから**最大ダメージで攻撃**する（攻撃はターンを終える）。
  GreedyBot が即攻撃で自滅していた問題への対策。
- カード選択は文脈 (SelectContext) で「得る/捨てる」を判断し、カード価値で優先付け。
- どんな場面でも合法手を返す（例外時は最小合法手にフォールバック）。

エンジン非依存でテスト可能。攻撃ダメージ表のみ、利用可能なら cg.api.all_attack() を使う。
"""

from __future__ import annotations

from ..cards import load_cards
from ..enums import OptionType, SelectContext, SelectType
from ..models import Observation, Option
from .base import Bot

# MAIN でのアクション優先度（大きいほど先に実行）。攻撃は最後。
_MAIN_PRIORITY: dict[OptionType, int] = {
    OptionType.ABILITY: 90,
    OptionType.EVOLVE: 80,
    OptionType.PLAY: 70,
    OptionType.ATTACH: 60,
    OptionType.ATTACK: 20,   # 展開を終えてから
    OptionType.RETREAT: 8,   # 基本避ける（エネを無駄にしがち）
    OptionType.END: 5,
    OptionType.DISCARD: 2,
}

# 「取りに行く」と得な文脈（最大数を取る）。
_TAKE_CONTEXTS = {
    SelectContext.TO_HAND, SelectContext.TO_FIELD, SelectContext.TO_ACTIVE,
    SelectContext.TO_BENCH, SelectContext.SETUP_ACTIVE_POKEMON,
    SelectContext.SETUP_BENCH_POKEMON, SelectContext.EVOLVES_FROM,
    SelectContext.EVOLVES_TO, SelectContext.TO_HAND_ENERGY,
    SelectContext.HEAL, SelectContext.REMOVE_DAMAGE_COUNTER,
}
# 「手放す」文脈（最小数で済ませ、価値の低いものから）。
_GIVE_CONTEXTS = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.TO_PRIZE, SelectContext.DISCARD_ENERGY,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.TO_DECK_ENERGY,
    SelectContext.DEVOLVE,
}
# YesNo を YES にしたい文脈。
_YES_CONTEXTS = {
    SelectContext.IS_FIRST, SelectContext.ACTIVATE, SelectContext.FIRST_EFFECT,
    SelectContext.COIN_HEAD,
}


class HeuristicBot(Bot):
    def __init__(self) -> None:
        self._cards = load_cards()
        self._attack_dmg: dict[int, int] | None = None

    # ----- 公開 ------------------------------------------------------

    def select(self, obs: Observation) -> list[int]:
        sel = obs.select
        if sel is None or not sel.options:
            return []
        t = sel.type
        if t == SelectType.MAIN:
            return self._main(sel.options)
        if t == SelectType.ATTACK:
            return [self._best_attack(sel.options)]
        if t == SelectType.COUNT:
            return [self._best_count(sel.options)]
        if t == SelectType.YES_NO:
            return [self._yes_no(obs)]
        if t in (SelectType.CARD, SelectType.ATTACHED_CARD,
                 SelectType.CARD_OR_ATTACHED_CARD, SelectType.ENERGY):
            return self._pick_cards(obs)
        # EVOLVE / SKILL / SPECIAL_CONDITION など: 最小数を先頭から。
        return self._take(obs, prefer_high=True)

    # ----- MAIN ------------------------------------------------------

    def _main(self, options: list[Option]) -> list[int]:
        # 展開系（攻撃以外）があれば最優先のものを実行。
        best_i, best_p = None, -1
        attack_idxs: list[int] = []
        for i, op in enumerate(options):
            if op.type == OptionType.ATTACK:
                attack_idxs.append(i)
            p = _MAIN_PRIORITY.get(op.type, 30) if isinstance(op.type, OptionType) else 30
            # 攻撃は「展開を終えてから」なので、ここでは展開系のみ比較。
            if isinstance(op.type, OptionType) and op.type in (
                OptionType.ABILITY, OptionType.EVOLVE, OptionType.PLAY, OptionType.ATTACH
            ):
                if p > best_p:
                    best_p, best_i = p, i
        if best_i is not None:
            return [best_i]
        # 展開が尽きた → 攻撃可能なら最大ダメージで攻撃。
        if attack_idxs:
            return [max(attack_idxs, key=lambda i: self._dmg_of(options[i]))]
        # 攻撃も無ければ END、無ければ先頭。
        for i, op in enumerate(options):
            if op.type == OptionType.END:
                return [i]
        return [0]

    # ----- カード/エネルギー選択 ------------------------------------

    def _pick_cards(self, obs: Observation) -> list[int]:
        ctx = obs.select.context
        if isinstance(ctx, SelectContext) and ctx in _GIVE_CONTEXTS:
            return self._take(obs, prefer_high=False, take_max=False)
        if isinstance(ctx, SelectContext) and ctx in _TAKE_CONTEXTS:
            return self._take(obs, prefer_high=True, take_max=True)
        # 不明な文脈: 最小数を、価値の高い方から（無難）。
        return self._take(obs, prefer_high=True, take_max=False)

    def _take(self, obs: Observation, prefer_high: bool, take_max: bool = False) -> list[int]:
        sel = obs.select
        n = len(sel.options)
        k = sel.max_count if take_max else sel.min_count
        k = max(0, min(k, n))
        if k == 0:
            return []
        ranked = sorted(
            range(n),
            key=lambda i: self._opt_value(sel.options[i]),
            reverse=prefer_high,
        )
        return sorted(ranked[:k])

    # ----- 個別ヘルパ ------------------------------------------------

    def _yes_no(self, obs: Observation) -> int:
        ctx = obs.select.context
        want_yes = isinstance(ctx, SelectContext) and ctx in _YES_CONTEXTS
        # MULLIGAN（引き直し）は受ける、それ以外の既定は YES（有益効果が多い）。
        if not isinstance(ctx, SelectContext):
            want_yes = True
        elif ctx == SelectContext.MORE_DEVOLVE:
            want_yes = False
        elif ctx not in _YES_CONTEXTS:
            want_yes = True
        target = OptionType.YES if want_yes else OptionType.NO
        for i, op in enumerate(obs.select.options):
            if op.type == target:
                return i
        return 0

    def _best_count(self, options: list[Option]) -> int:
        # 引く/置く枚数などは基本「最大」。number があればそれで比較。
        return max(range(len(options)), key=lambda i: options[i].number or 0)

    def _best_attack(self, options: list[Option]) -> int:
        return max(range(len(options)), key=lambda i: self._dmg_of(options[i]))

    def _dmg_of(self, op: Option) -> int:
        if op.attack_id is None:
            return 0
        return self._attack_table().get(op.attack_id, 0)

    def _attack_table(self) -> dict[int, int]:
        if self._attack_dmg is None:
            self._attack_dmg = {}
            try:
                import sys
                from pathlib import Path
                root = str(Path(__file__).resolve().parents[2])
                if root not in sys.path:
                    sys.path.insert(0, root)
                from cg.api import all_attack  # type: ignore
                self._attack_dmg = {a.attackId: (a.damage or 0) for a in all_attack()}
            except Exception:
                self._attack_dmg = {}
        return self._attack_dmg

    def _opt_value(self, op: Option) -> int:
        cid = op.card_id
        if cid is None:
            return 10
        return self._card_value(cid)

    def _card_value(self, card_id: int) -> int:
        c = self._cards.get(card_id)
        if c is None:
            return 10
        stage = c.stage or ""
        if c.hp is not None:  # ポケモン
            if c.rule and "ex" in c.rule.lower():
                return 100
            if "Stage 2" in stage:
                return 85
            if "Stage 1" in stage:
                return 80
            return 70  # たね
        if "Special Energy" in stage:
            return 60
        if "Basic Energy" in stage:
            return 50
        if "Supporter" in stage:
            return 40
        if "Tool" in stage:
            return 30
        if "Stadium" in stage:
            return 25
        return 30  # Item など
