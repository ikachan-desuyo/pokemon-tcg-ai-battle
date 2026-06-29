"""Archaludon（ブリジュラスex / 鋼軸）専用 bot。

回し方の方針: ジュラルドン→ブリジュラスex(1進化, HP300)を立てる。
ブリジュラスex の特性「ごうきんビルド」(進化時にトラッシュから基本【鋼】エネを2枚加速)
が火力エンジン。＝先に鋼エネをトラッシュへ置いてから進化すると、メタルディフェンダー
(鋼3=220)を最速で起動できる。非exブリジュラス(170)の特性で鋼ポケは逃げエネ0=自由入替。

TODO(作り込み): ハイパボ等で鋼エネを意図的にトラッシュへ送ってから進化し、
ごうきんビルドの加速を最大化するカスタムロジック（現状は設定のみ）。
"""
from .deck_bot import DeckBot, DeckPlan

PLAN = DeckPlan(
    name="Archaludon",
    go_first=True,
    attackers=(190, 170, 169),            # ブリジュラスex / ブリジュラス / ジュラルドン
    key_cards=(190, 169),
    preferred_attacks=(),
    energy_rules=((8, 190), (8, 170), (None, 190)),  # 鋼→ブリジュラス
    play_priority={169: 84, 190: 86, 1205: 88},  # ジュラルドン/ブリジュラスex/シアノ
    card_values={190: 100, 170: 84, 169: 80, 8: 84},
    lethal=True,
    est_var_damage=True,
    smart_take=True,
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
)


METAL = 8        # 基本【鋼】エネルギー
DURALUDON = 169  # ジュラルドン
ARCH_EX = 190    # ブリジュラスex


class ArchaludonBot(DeckBot):
    plan = PLAN

    def _want_metal_in_discard(self) -> bool:
        """ごうきんビルド(進化時にトラッシュから鋼エネ2枚加速)の燃料を仕込むべきか。
        進化線が育っており、手札に鋼エネが余り、トラッシュの鋼がまだ2枚未満なら、捨てて仕込む。"""
        me = self._me()
        if not me:
            return False
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        has_line = any(sp and sp.get("id") in (DURALUDON, ARCH_EX) for sp in spots) \
            or any(c.get("id") in (DURALUDON, ARCH_EX) for c in (me.get("hand") or []))
        if not has_line:
            return False
        hand_metal = sum(1 for c in (me.get("hand") or []) if c.get("id") == METAL)
        disc_metal = sum(1 for c in (me.get("discard") or []) if c.get("id") == METAL)
        return hand_metal >= 2 and disc_metal < 2

    def _take(self, sel, prefer_high: bool, take_max: bool):
        # 捨てる(give)場面では、ごうきんビルドの燃料として鋼エネを優先的にトラッシュへ送る。
        if not prefer_high and self._want_metal_in_discard():
            n = len(sel.options)
            k = sel.max_count if take_max else sel.min_count
            k = max(0, min(k, n))
            if k > 0:
                metal = [i for i in range(n) if self._opt_card_id(sel.options[i]) == METAL]
                if metal:
                    rest = sorted((i for i in range(n) if i not in metal),
                                  key=lambda i: self._opt_value(sel.options[i]))
                    return sorted((metal + rest)[:k])
        return super()._take(sel, prefer_high, take_max)
