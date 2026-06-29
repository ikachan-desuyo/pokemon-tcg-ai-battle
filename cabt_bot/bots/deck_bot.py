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

from collections import Counter
from dataclasses import dataclass, field
from math import comb

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
    lethal: bool = False                      # 相手バトル場をKOできる技を優先
    skip_abilities: bool = False              # 特性を自動使用しない（自滅特性対策の検証用）
    hold_energies: tuple[int, ...] = ()       # これらのエネは energy_rules の付け先以外には貼らない（温存）
    volatile_energies: tuple[int, ...] = ()   # 番末トラッシュ系エネ(例:イグニ)。規則の付け先かつ「攻撃できる番の場(active,turn>1)」のみ付与
    conserve_volatile: bool = False           # 今のエネで相手バトル場をKOできるなら volatile(イグニ)を温存（番末トラッシュの無駄回避）
    heal_return_cards: tuple[int, ...] = ()   # 回復+エネ手札戻し系(例:ミツル)。アタッカーが十分ダメージ時のみ使用
    boss_cards: tuple[int, ...] = ()          # 引きずり出し系(例:ボスの指令)。KO(サイド)を生む時のみ使用
    recover_cards: tuple[int, ...] = ()       # トラッシュ回収系(例:夜のタンカ)。回収価値がある時のみ使用
    switch_cards: tuple[int, ...] = ()        # 入替系(例:ポケモンいれかえ)。攻撃役を前に出す必要がある時のみ使用
    smart_take: bool = False                  # サーチ/ポケギア取得時、状況依存サポを今役立つ時だけ優先
    strict_lillie_guard: bool = False         # True=手札にキーがあれば常にリーリエ抑制(コンボ系向け)。既定はこの番に展開できるキーのみ抑制
    setup_wall: tuple[int, ...] = ()          # 開幕バトル場に優先したい高HP壁(例:エースバーン)。先攻はT1攻撃不可なので壁を前に
    energy_supporters: tuple[int, ...] = ()   # エネ補給サポ(例:トウコ)。進化アタッカーが居てエネ切れ＝攻撃不可の時に優先して打つ
    eager_reposition: bool = False            # 壁→攻撃役の前進を「エネ付けの前」に行い、手札のエネ(イグニ等)で前進後に殴る
    setup_attack: int = 0                     # 加速/準備技のattackId(例:あふれるねがい)。火力が弱い間はこれで盤面エネを育てる
    setup_attack_until: int = 0               # 盤面エネがこの数未満なら setup_attack を優先（以上なら火力技へ移行）
    sacrifice_abilities: tuple[int, ...] = () # 自滅特性(例:カースドボム)。ベンチ backup有り＆相手をKOできる時のみ使う
    sacrifice_damage: dict = field(default_factory=dict)  # {特性カードid: 与ダメージ} 自滅特性のKO判定用
    est_var_damage: bool = False              # 可変ダメージ技(base=0)を効果文から推定して評価
    smart_gust: bool = False                  # ボス等で相手を選ぶとき、現HP最小（KOしやすい）を狙う
    reposition: bool = False                  # 非攻撃役が前なら、攻撃役(エネ有・ベンチ)を前に出してから殴る


class DeckBot(Bot):
    plan: DeckPlan = DeckPlan(name="default")

    def __init__(self, plan: DeckPlan | None = None, decklist=None) -> None:
        if plan is not None:
            self.plan = plan
        try:
            self._cardinfo = load_cards()
        except Exception:
            self._cardinfo = {}
        # 自分のデッキ構成（提出時の60枚）。あれば対戦中に山札の残り構成→確率を計算できる。
        self.deck_counts = Counter(int(x) for x in decklist) if decklist else None
        self._energy_ids = ({cid for cid in self.deck_counts if self._is_energy(cid)}
                            if self.deck_counts else set())
        self._atk_dmg = None
        self._atk_name = None
        self._atk_est = None
        self._atk_no_weak = None
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
        if OptionType.ABILITY in g and not self.plan.skip_abilities:
            ab = self._pick_ability(g[OptionType.ABILITY], options)
            if ab is not None:
                return [ab]
        if OptionType.PLAY in g:
            c = self._pick_play(g[OptionType.PLAY], options, hand)
            if c is not None:
                return [c]
        if OptionType.EVOLVE in g:
            return [self._pick_evolve(g[OptionType.EVOLVE], options, hand)]
        # （任意）エネ付けの前に壁を退いて攻撃役を前に出すと今ターン殴れるなら退く。
        # イグニはベンチに付けられないため、前進後に手札のイグニ→ネビュラを成立させる。
        if (self.plan.reposition and self.plan.eager_reposition
                and OptionType.RETREAT in g and self._should_reposition_eager(me, hand)):
            return [g[OptionType.RETREAT][0]]
        if OptionType.ATTACH in g:
            a = self._pick_attach(g[OptionType.ATTACH], options, hand, me)
            if a is not None:
                return [a]
        # 展開・進化・エネ付けを終えた後にリーリエ（手札を全部山に戻して引き直す）を判断。
        # ＝戻したくないエネ等を先に使い切ってから引き直す。
        if OptionType.PLAY in g and self._should_use_lillie():
            for i in g[OptionType.PLAY]:
                if self._hand_id(hand, options[i].index) == LILLIE:
                    return [i]
        # 攻撃役を前に出す（現アクティブが攻撃不可＝壁等でも、退かして攻撃役を前進）。
        if (self.plan.reposition and OptionType.RETREAT in g
                and self._should_reposition(me)):
            return [g[OptionType.RETREAT][0]]
        if OptionType.ATTACK in g:
            return [self._best_attack(g[OptionType.ATTACK], options)]
        if OptionType.END in g:
            return [g[OptionType.END][0]]
        return [0]

    def _pick_ability(self, idxs, options):
        """特性は基本そのまま使うが、自滅特性(カースドボム等)は条件を満たす時だけ使う。
        非自滅特性を優先し、無ければ自滅特性を『価値がある時のみ』使う。"""
        deferred = []
        for i in idxs:
            cid = self._opt_card_id(options[i])
            if cid in self.plan.sacrifice_abilities:
                deferred.append((i, cid))
                continue
            return i  # 非自滅特性(ドロー等)は即使用
        for i, cid in deferred:
            if self._sacrifice_worth_it(cid):
                return i
        return None  # 使うべき特性なし → 次フェーズへ

    def _sacrifice_worth_it(self, src_cid) -> bool:
        """自滅特性: ①ベンチに後続が居る(展開済み) ②与ダメージで相手をKOできる 時のみ。"""
        dmg = self.plan.sacrifice_damage.get(src_cid, 0)
        if dmg <= 0:
            return False
        cur = self._cur
        if not cur:
            return False
        me = cur["players"][cur["yourIndex"]]
        opp = cur["players"][1 - cur["yourIndex"]]
        if len([s for s in (me.get("bench") or []) if s]) < 1:
            return False  # ベンチが薄い＝先に展開すべき。自滅で盤面を失わない
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp and (sp.get("hp") or 9999) <= dmg:
                return True  # この自滅でKOできる相手が居る
        return False

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
            return None  # リーリエは展開・進化・エネ付けを終えた後（_main後段）で判断する
        # 回復+エネ手札戻し系(ミツル等): アタッカーが十分ダメージを負っている時のみ
        if cid in self.plan.heal_return_cards:
            return 50 if self._attacker_damaged() else None
        # エネ補給サポ(トウコ等): 進化アタッカーが居て攻撃できない(エネ切れ)なら優先＝攻撃を早める
        if cid in self.plan.energy_supporters and self._attacker_needs_energy():
            return 83
        # 引きずり出し系(ボス等): KO(サイド獲得)を生む時のみ
        if cid in self.plan.boss_cards:
            return 62 if self._should_play_boss() else None
        # 回収系(夜のタンカ等): トラッシュに回収価値がある時のみ（無駄打ち防止）
        if cid in self.plan.recover_cards:
            return 50 if self._has_recover_target() else None
        # 入替系(ポケモンいれかえ等): 攻撃役を前に出す必要がある時のみ
        if cid in self.plan.switch_cards:
            return 64 if self._should_switch() else None
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

    def _pick_attach(self, idxs, options, hand, me):
        best, best_key = None, (-1, -1, -1)
        for i in idxs:
            op = options[i]
            energy = self._hand_id(hand, op.index)
            target = self._target_id(me, op.in_play_area, op.in_play_index)
            rule = self._energy_rule_rank(energy, target)
            # 温存指定エネは規則の付け先以外には貼らない（無駄付け回避）
            if energy in self.plan.hold_energies and rule == 0:
                continue
            # 番末トラッシュ系エネ: 規則の付け先 かつ 攻撃できる番の場(active,turn>1)のみ
            # （基本ポケ/ベンチ/先攻T1への付与は番末に捨てられて丸損になるため抑止）
            if energy in self.plan.volatile_energies:
                turn = (self._cur or {}).get("turn", 99)
                if rule == 0 or op.in_play_area != AreaType.ACTIVE or turn <= 1:
                    continue
                # 今のエネで相手バトル場をKOできるなら、イグニは温存（より安い技で十分）
                if self.plan.conserve_volatile and self._active_lethal_now():
                    continue
            key = (rule,
                   1 if target in self.plan.attackers else 0,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if key > best_key:
                best_key, best = key, i
        return best  # None なら良い付け先なし → 付けずに次フェーズへ

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
        if self.plan.lethal:
            ko = self._lethal_choice(idxs, options)
            if ko is not None:
                return ko
        # 火力技がまだ弱い間は加速/準備技(例:あふれるねがい)を優先して盤面エネを増やす
        if self.plan.setup_attack:
            s = self._setup_attack_choice(idxs, options)
            if s is not None:
                return s
        for nm in self.plan.preferred_attacks:
            aid = self._attack_name_ids().get(nm)
            for i in idxs:
                if aid and options[i].attack_id == aid:
                    return i
        return max(idxs, key=lambda i: self._dmg(options[i]))

    def _setup_attack_choice(self, idxs, options):
        """加速/準備技(setup_attack)が払えて、①ベンチに加速先が居る ②盤面エネが閾値未満 なら、それを選ぶ。
        ＝メガシンフォニア等の“盤面エネ×N”火力を、撃つ前に育てる。"""
        si = next((i for i in idxs if options[i].attack_id == self.plan.setup_attack), None)
        if si is None:
            return None
        me = self._me()
        if not me:
            return None
        if not [s for s in (me.get("bench") or []) if s]:
            return None  # 加速先(ベンチ)が無い
        if self._board_energy_count() < self.plan.setup_attack_until:
            return si
        return None

    def _board_energy_count(self) -> int:
        """自分の場(active+bench)に付いているエネ総数。"""
        me = self._me()
        if not me:
            return 0
        n = 0
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if not sp:
                continue
            n += len(sp.get("energyCards") or sp.get("energies") or [])
        return n

    def _lethal_choice(self, idxs, options):
        """相手バトル場を倒せる技があれば、その中で最大ダメージを選ぶ。"""
        hp, weak = self._opp_active_hp_weak()
        if hp is None:
            return None
        my_type = self._my_active_type()
        best, best_eff = None, -1
        for i in idxs:
            base = self._dmg(options[i])
            # 弱点無視の技(例: Nebula Beam)は2倍にしない
            apply_weak = (weak and my_type and weak == my_type
                          and options[i].attack_id not in self._attack_no_weak())
            eff = base * 2 if apply_weak else base
            if eff >= hp and eff > best_eff:
                best_eff, best = eff, i
        return best

    def _opp_active_hp_weak(self):
        cur = self._cur
        if not cur:
            return None, None
        opp = cur["players"][1 - cur["yourIndex"]]
        act = opp.get("active") or []
        if act and act[0]:
            c = self._cardinfo.get(act[0].get("id"))
            return act[0].get("hp"), (c.weakness if c else None)
        return None, None

    def _my_active_type(self):
        cur = self._cur
        if not cur:
            return None
        act = (cur["players"][cur["yourIndex"]].get("active") or [])
        if act and act[0]:
            c = self._cardinfo.get(act[0].get("id"))
            return c.type if c else None
        return None

    def _dmg(self, op: Option) -> int:
        if op.attack_id is None:
            return 0
        base = self._attack_table().get(op.attack_id, 0)
        if base == 0 and self.plan.est_var_damage:
            return self._attack_est().get(op.attack_id, 0)
        return base

    def _attack_est(self) -> dict:
        if getattr(self, "_atk_est", None) is None:
            self._load_attacks()
        return self._atk_est or {}

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
        if self.plan.smart_gust or self.plan.boss_cards:
            g = self._ko_gust_pick(sel)
            if g is not None:
                return [g]
        ctx = sel.context
        if isinstance(ctx, SelectContext) and ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            # 先攻はT1攻撃不可 → 開幕は高HPの壁(エースバーン等)を前に置き、攻撃役はベンチで育てる
            if self.plan.go_first and self.plan.setup_wall:
                wall = self._first_of(sel, self.plan.setup_wall)
                if wall is not None:
                    return [wall]
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

    def _attacker_damaged(self, min_damage: int = 100) -> bool:
        """自分のアタッカー(plan.attackers)が min_damage 以上のダメージを負っているか。"""
        cur = self._cur
        if not cur:
            return False
        me = cur["players"][cur["yourIndex"]]
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        for sp in spots:
            if sp and sp.get("id") in self.plan.attackers:
                hp, mhp = sp.get("hp"), sp.get("maxHp")
                if hp is not None and mhp and hp <= mhp - min_damage:
                    return True
        return False

    def _has_recover_target(self) -> bool:
        """夜のタンカ等: トラッシュに回収する価値があるか。
        ①死んだアタッカー/キーがトラッシュに居る ②前のアタッカーがエネ0でトラッシュに基本エネがある。"""
        me = self._me()
        if not me:
            return False
        discard = me.get("discard") or []
        keys = set(self.plan.attackers) | set(self.plan.key_cards)
        if any(d.get("id") in keys for d in discard):
            return True
        act = (me.get("active") or [None])[0]
        if (act and act.get("id") in self.plan.attackers
                and not (act.get("energies") or [])):
            if any((d.get("id") or 99) < 10 for d in discard):  # 基本エネ(小ID)
                return True
        return False

    def _should_switch(self) -> bool:
        """入替系: バトル場が攻撃役(進化前含む)でなく、ベンチに攻撃役が居る時のみ。"""
        me = self._me()
        if not me or not self.plan.attackers:
            return False
        act = (me.get("active") or [None])[0]
        if not act or act.get("id") in self.plan.attackers:
            return False  # 場が空 or 既に攻撃役が前
        for sp in me.get("bench") or []:
            if sp and sp.get("id") in self.plan.attackers:
                return True
        return False

    def _take_rank(self, op: Option) -> int:
        """取得(サーチ/ポケギア等)時のカード評価。効果×盤面で「今/直近に最も活きるサポ」を選ぶ。
        - ボス: KOでサイドを取れる時に最優先。取れなくても将来用に中庸。
        - ミツル: アタッカーが重傷の時のみ高評価。
        - リーリエ: 手札が死んでいる時に高評価。
        - その他ドロー/展開サポ(トウコ/セイジ): アタッカー未起動なら最優先（展開加速）、起動後は安定札として中位。
        """
        cid = self._opt_card_id(op)
        if cid in self.plan.boss_cards:
            return 200 if self._should_play_boss() else 40
        if cid in self.plan.heal_return_cards:
            return 190 if self._attacker_damaged(150) else 10
        if cid == LILLIE:
            # 引き直しは「プレイ直前の手札が少ないほど純増が大きい」＝枚数でスケール。
            if self._should_use_lillie():
                me = self._me()
                hand_n = len(me.get("hand") or []) if me else 0
                prizes_left = len(me.get("prize") or []) if me else 6
                draw_n = 8 if prizes_left >= 6 else 6
                gain = max(0, draw_n - hand_n)        # 引いて増える枚数
                return 140 + gain * 18                # 手札僅少なら最優先級(最大~266)
            return 30
        c = self._cardinfo.get(cid)
        if c and c.stage == "Supporter":          # ドロー/展開系サポ
            return 170 if not self._evolved_attacker_in_play() else 100
        return self._opt_value(op)

    def _evolved_attacker_in_play(self) -> bool:
        me = self._me()
        if not me:
            return False
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if sp and sp.get("id") in self.plan.attackers:
                c = self._cardinfo.get(sp.get("id"))
                if c and not c.is_basic:
                    return True
        return False

    def _should_reposition(self, me) -> bool:
        if not me or not self.plan.attackers:
            return False
        act = me.get("active") or []
        if not act or not act[0]:
            return False
        if act[0].get("id") in self.plan.attackers:
            return False  # 既に攻撃役が前
        for sp in me.get("bench") or []:
            if sp and sp.get("id") in self.plan.attackers and (sp.get("energies") or []):
                return True  # エネ持ちの攻撃役がベンチに居る
        return False

    def _should_reposition_eager(self, me, hand) -> bool:
        """eager版: 進化アタッカーが①既にエネ有 or ②手札にエネがあり未アタッチ（前進後に付けて殴れる）なら退く。
        先攻T1(攻撃不可)では退かない。たねは前に出さない。"""
        if not me or not self.plan.attackers:
            return False
        cur = self._cur or {}
        if cur.get("turn") == 1 and cur.get("yourIndex") == cur.get("firstPlayer"):
            return False
        act = (me.get("active") or [None])[0]
        if not act or act.get("id") in self.plan.attackers:
            return False
        not_attached = not cur.get("energyAttached")
        have_energy = any(self._is_energy(c.get("id")) for c in (hand or []))
        for sp in me.get("bench") or []:
            if not sp or sp.get("id") not in self.plan.attackers:
                continue
            info = self._cardinfo.get(sp.get("id"))
            if info and info.is_basic:
                continue
            if sp.get("energies") or (not_attached and have_energy):
                return True
        return False

    def _active_attack_potential(self):
        """現バトル場アタッカーの (払えるワザの最大ダメージ, 弱点無視か)。攻撃不可なら(0,False)。"""
        import re
        cur = self._cur
        if not cur:
            return 0, False
        me = cur["players"][cur["yourIndex"]]
        act = (me.get("active") or [None])[0]
        if not act or act.get("id") not in self.plan.attackers:
            return 0, False
        info = self._cardinfo.get(act.get("id"))
        if not info:
            return 0, False
        # 実効エネ数: イグニ等の volatile エネは進化ポケ上で無3として数える
        evolved = not info.is_basic
        e = 0
        for ec in act.get("energyCards") or []:
            e += 3 if (ec.get("id") in self.plan.volatile_energies and evolved) else 1
        if e <= 0:
            return 0, False
        best, ign = 0, False
        for m in info.moves:
            if not m.damage:
                continue
            cost = m.cost or ""
            need = len(re.findall(r"\{[A-Z]\}", cost)) + cost.count("●")
            if need > e:                       # 概算: 付与エネ数で払えるワザのみ
                continue
            mt = re.match(r"(\d+)", m.damage)
            dm = int(mt.group(1)) if mt else 0
            if dm > best:
                best, ign = dm, ("affected by Weakness" in (m.effect or ""))
        return best, ign

    def _active_lethal_now(self) -> bool:
        """今バトル場アタッカーに付いているエネだけで、相手バトル場をKOできるか
        （新たにエネを付けずに）。＝より安い技で足りる＝volatile(イグニ)を温存できる。"""
        dmg, ign = self._active_attack_potential()
        if dmg <= 0:
            return False
        cur = self._cur
        if not cur:
            return False
        opp = cur["players"][1 - cur["yourIndex"]]
        act = (opp.get("active") or [None])[0]
        if not act:
            return False
        return self._eff_dmg(dmg, ign, act.get("id")) >= (act.get("hp") or 9999)

    def _eff_dmg(self, base, ign, target_id) -> int:
        """対象(target_id)へ与える実効ダメージ（弱点2倍を考慮、弱点無視技は据置）。"""
        my_type = self._my_active_type()
        c = self._cardinfo.get(target_id)
        weak = c.weakness if c else None
        return base * 2 if (weak and my_type and weak == my_type and not ign) else base

    def _prize_value(self, cid) -> int:
        """KOされた時に相手が取るサイド枚数。メガex=3, ex=2, それ以外=1。"""
        c = self._cardinfo.get(cid)
        rule = (c.rule or "").lower() if c else ""
        if "mega" in rule and "ex" in rule:
            return 3
        return 2 if "ex" in rule else 1

    # ===== 確率（対戦中に分かっている情報から計算）=====
    def _is_energy(self, cid) -> bool:
        c = self._cardinfo.get(cid)
        return bool(c and c.stage and c.stage.endswith("Energy"))

    def _seen_counts(self, include_hand: bool) -> Counter:
        """山札の外で見えているカード枚数（decklist から引くと山＋サイドの残り構成が出る）。"""
        me = self._me()
        c: Counter = Counter()
        if not me:
            return c
        if include_hand:
            for cd in me.get("hand") or []:
                c[cd.get("id")] += 1
        for cd in (me.get("discard") or []) + (me.get("lostZone") or me.get("lost") or []):
            c[cd.get("id")] += 1
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if not sp:
                continue
            c[sp.get("id")] += 1
            for key in ("preEvolution", "energyCards", "tools"):
                for cc in sp.get(key) or []:
                    c[cc.get("id")] += 1
        return c

    @staticmethod
    def _hyp_at_least1(pop: int, succ: int, n: int) -> float:
        """母集団 pop 枚(成功 succ 枚)から n 枚引いて成功を1枚以上引く確率（超幾何）。"""
        if succ <= 0 or n <= 0 or pop <= 0:
            return 0.0
        n = min(n, pop)
        if pop - succ < n:
            return 1.0
        return 1.0 - comb(pop - succ, n) / comb(pop, n)

    def _p_draw(self, success_ids, n: int, include_hand: bool) -> float:
        """山(＋サイド)から n 枚引いて success_ids のカードを1枚以上引く確率。
        include_hand=True は「手札を山に戻してから引く」(リーリエ)用＝手札も母集団に含む。
        decklist 未提供なら -1（呼び出し側は従来ロジックにフォールバック）。"""
        if not self.deck_counts:
            return -1.0
        me = self._me()
        if not me:
            return -1.0
        deck_n = me.get("deckCount") or 0
        prize_n = len(me.get("prize") or [])
        hand_n = len(me.get("hand") or [])
        pool = deck_n + prize_n + (hand_n if include_hand else 0)
        seen = self._seen_counts(include_hand=not include_hand)
        succ = sum(max(0, self.deck_counts.get(cid, 0) - seen.get(cid, 0))
                   for cid in success_ids)
        return self._hyp_at_least1(pool, succ, n)

    def _attacker_needs_energy(self) -> bool:
        """バトル場のアタッカーが今のエネでは攻撃できず、手札にもエネが無い＝エネ補給が要る。
        進化/たね問わず「払えるワザが無い(=_active_attack_potential 0)」で判定（基本メガにも対応）。"""
        me = self._me()
        if not me:
            return False
        if any(self._is_energy(c.get("id")) for c in (me.get("hand") or [])):
            return False  # 手札にエネあり→直接付けられるので補給サポ不要
        act = (me.get("active") or [None])[0]
        if not act or act.get("id") not in self.plan.attackers:
            return False  # バトル場が攻撃役でない（壁等）なら補給サポより前進等が先
        dmg, _ = self._active_attack_potential()
        return dmg <= 0  # 今のエネで撃てるワザが無い＝補給が要る

    def _attacker_in_play(self) -> bool:
        me = self._me()
        if not me:
            return False
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if sp and sp.get("id") in self.plan.attackers:
                return True
        return False

    def _should_use_lillie(self) -> bool:
        """リーリエの決心: 手札を山に戻して6枚(早期=サイド6なら8枚)引く。
        キー札は温存し、引き直しで純増 or 必要資源(エネ/アタッカー)を高確率で引ける時に使う。"""
        me = self._me()
        hand = (me.get("hand") or []) if me else []
        if not self.deck_counts:  # 構成不明 → 従来の保守的条件
            return not (self._has_key(hand) or len(hand) >= 4)
        blocked = (self._has_key(hand) if self.plan.strict_lillie_guard
                   else self._has_deployable_key(hand))
        if blocked:
            return False  # キーは山に戻さない（既定=この番に展開できるキーのみ／strict=全キー）
        prizes_left = len(me.get("prize") or []) if me else 6
        draw_n = 8 if prizes_left >= 6 else 6
        if len(hand) >= draw_n:
            return False  # 引き直すと純減＝他にやることがある
        if len(hand) <= draw_n - 2:
            return True   # 純増（特に未KO早期の8枚ドロー）
        hand_energy = sum(1 for cd in hand if self._is_energy(cd.get("id")))
        if hand_energy == 0 and self._attacker_in_play():
            if self._p_draw(self._energy_ids, draw_n, include_hand=True) >= 0.55:
                return True  # エネ枯れ→引き直しで高確率にエネを引ける
        if not self._attacker_in_play():
            if self._p_draw(set(self.plan.attackers), draw_n, include_hand=True) >= 0.55:
                return True  # アタッカー不在→高確率に引ける
        return False

    def _should_play_boss(self) -> bool:
        """ボスは『前を倒せない×ベンチにKO可能あり』または『より大きなサイドを取れる』時のみ。"""
        cur = self._cur
        if not cur:
            return False
        dmg, ign = self._active_attack_potential()
        if dmg <= 0:
            return False
        opp = cur["players"][1 - cur["yourIndex"]]
        act = (opp.get("active") or [None])[0]
        if not act:
            return False
        can_ko_active = self._eff_dmg(dmg, ign, act.get("id")) >= (act.get("hp") or 9999)
        active_val = self._prize_value(act.get("id"))
        best_bench = 0
        for sp in opp.get("bench") or []:
            if sp and self._eff_dmg(dmg, ign, sp.get("id")) >= (sp.get("hp") or 9999):
                best_bench = max(best_bench, self._prize_value(sp.get("id")))
        if best_bench == 0:
            return False                       # ベンチにKOできる相手なし → 打たない
        if not can_ko_active:
            return True                        # 前を倒せない → ベンチのKO対象を引っ張る
        return best_bench > active_val         # 前は倒せるが、より大きなサイドを優先

    def _ko_gust_pick(self, sel):
        """相手ポケモン選択: KO可能を最優先 → サイド価値大 → 現HP小 で選ぶ。"""
        cur = self._cur
        if not cur:
            return None
        opp_idx = 1 - cur["yourIndex"]
        opp = cur["players"][opp_idx]
        dmg, ign = self._active_attack_potential()
        cand = []
        for i, op in enumerate(sel.options):
            if op.player_index != opp_idx:
                continue
            spots = (opp.get("active") if op.area == AreaType.ACTIVE else opp.get("bench")) or []
            if op.index is not None and 0 <= op.index < len(spots) and spots[op.index]:
                sp = spots[op.index]
                hp = sp.get("hp", 9999)
                koable = 1 if self._eff_dmg(dmg, ign, sp.get("id")) >= hp else 0
                cand.append((koable, self._prize_value(sp.get("id")), -hp, i))
        if not cand:
            return None
        return max(cand)[3]

    def _take(self, sel, prefer_high: bool, take_max: bool) -> list[int]:
        n = len(sel.options)
        k = sel.max_count if take_max else sel.min_count
        k = max(0, min(k, n))
        if k == 0:
            return []
        keyfn = (self._take_rank if (prefer_high and self.plan.smart_take)
                 else self._opt_value)
        ranked = sorted(range(n), key=lambda i: keyfn(sel.options[i]),
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

    def _has_deployable_key(self, hand) -> bool:
        """この番に実際に使える(展開できる)キー札が手札にあるか。
        ・たね攻撃役: ベンチに空きがあれば出せる
        ・進化攻撃役: 場に進化元のたね攻撃役が居れば進化できる
        詰まったキー(進化元不在の進化先・ベンチ満杯のたね)は対象外＝リーリエで戻してよい。"""
        keys = set(self.plan.key_cards or self.plan.attackers)
        me = self._me()
        if not me:
            return False
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        in_play_basic_attacker = any(
            sp and sp.get("id") in self.plan.attackers
            and (self._cardinfo.get(sp.get("id")) and self._cardinfo[sp.get("id")].is_basic)
            for sp in spots)
        bench = [s for s in (me.get("bench") or []) if s]
        bench_space = len(bench) < (me.get("benchMax") or 5)
        for cd in hand:
            cid = cd.get("id")
            if cid not in keys:
                continue
            info = self._cardinfo.get(cid)
            if not info:
                continue
            if info.is_basic:
                if bench_space:
                    return True
            elif in_play_basic_attacker:
                return True
        return False

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
        # ピーク領域(ポケギア等で山上を見ている)。current["looking"] に実体がある。
        if area == AreaType.LOOKING and self._cur:
            look = self._cur.get("looking") or []
            if 0 <= idx < len(look) and look[idx]:
                return look[idx].get("id")
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
        c = self._cardinfo.get(cid)
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

    def _attack_no_weak(self) -> set:
        if getattr(self, "_atk_no_weak", None) is None:
            self._load_attacks()
        return self._atk_no_weak or set()

    def _load_attacks(self):
        import re
        self._atk_dmg, self._atk_name, self._atk_est = {}, {}, {}
        self._atk_no_weak = set()
        try:
            import sys
            from pathlib import Path
            root = str(Path(__file__).resolve().parents[2])
            if root not in sys.path:
                sys.path.insert(0, root)
            from cg.api import all_attack  # type: ignore
            for a in all_attack():
                base = a.damage or 0
                self._atk_dmg[a.attackId] = base
                self._atk_name.setdefault(a.name, a.attackId)
                # 可変ダメージ推定: 効果文の「N damage」を拾い、"for each" は概算で増やす
                est = base
                if base == 0 and a.text:
                    m = re.search(r"(\d+)\s*damage", a.text)
                    if m and "benched" not in a.text.lower():  # ベンチ限定技は対象外
                        est = int(m.group(1))
                        if "for each" in a.text.lower():
                            est = min(est * 3, 240)
                self._atk_est[a.attackId] = est
                # 弱点/抵抗を無視する技を記録（例: Nebula Beam）
                if a.text and "affected by Weakness" in a.text:
                    self._atk_no_weak.add(a.attackId)
        except Exception:
            pass

    @staticmethod
    def _fallback(sel) -> list[int]:
        n = len(sel.options)
        return list(range(min(max(1, sel.min_count), n)))
