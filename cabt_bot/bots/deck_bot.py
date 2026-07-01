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
from dataclasses import dataclass, field, replace
from math import comb

from .base import Bot
from ..cards import load_cards
from ..enums import AreaType, OptionType, SelectContext, SelectType
from ..models import Observation, Option
from ..state_encoder import line_threat as _line_threat, line_attacker_hp as _line_attacker_hp

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
    spread_attacks: tuple[str, ...] = ()      # ベンチにもダメージを与える技名。KO可能な技が複数ある時、
                                              # 相手バトル場を倒せるならベンチも削れるこの技を優先(次のKOを準備)
    spread_damage: int = 0                    # ベンチ撒きの damage(例:Jetting Blow=50)。ベンチ対象選択で
                                              # 『将来の火力枠を今削り、前に出た時のKO攻撃回数を減らす』予測に使う
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
    setup_attacks: tuple[int, ...] = ()       # 準備技(サーチ/加速)のattackId群(例:コールサイン/あふれるねがい)
    setup_attack_min_damage: int = 0          # 火力技の最大ダメージがこの値未満なら、弱く殴らず準備技を使う
    wide_bench: bool = False                  # 盤面エネ依存火力(メガシンフォニア等)向け: 進化アタッカーが1体立ったら残るたねは進化させずベンチに残し母数にする
    sacrifice_abilities: tuple[int, ...] = () # 自滅特性(例:カースドボム)。ベンチ backup有り＆相手をKOできる時のみ使う
    sacrifice_damage: dict = field(default_factory=dict)  # {特性カードid: 与ダメージ} 自滅特性のKO判定用
    est_var_damage: bool = False              # 可変ダメージ技(base=0)を効果文から推定して評価
    setup_energy: int = 0                     # 主アタッカーが攻撃に必要なエネ数(育成評価器 _eval_setup 用。0=既定3扱い)
    use_resolver: bool = False                # サーチ先(take)を Resolver(Need改善量) で選ぶ(v1限定導入・A/B用)
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
        self._opp_seen = set()      # 相手の場で見えたカードidの累積（相手デッキ判定に使用）
        self._opp_main_line = None  # 相手の最大脅威ライン(line_threat最大)。マッチアップ別処理の起点
        self._resolver_log = []     # Resolver v1 の Explain Log(候補・改善量・採用理由)
        # 専門家ログから学んだ Action Scorer(デッキ非依存) を『どれを選ぶか』に加点(opt-in)。
        # FinalScore = Heuristic + ml_alpha * MLScore。既定オフ(挙動不変)。
        self.action_scorer = None
        self.ml_alpha = 0.0
        # ===== マッチアップ別処理テーブル（DRY: ベース＋相手別差分） =====
        # matchup_signatures: {アーキ名: [そのデッキを示すカードid]} 子クラスで設定。
        # matchup_plans: {アーキ名: {DeckPlanの差分knob}}。ベースと違う部分のみ。残りはベース参照。
        # 全体に効く改善はベース(self._base_plan)のみに入れる。空なら挙動不変(既存bot/提出に無影響)。
        self.matchup_signatures = {}
        self.matchup_plans = {}
        self._base_plan = self.plan
        self._matchup = "__init__"

    # ===== entry =====
    def select(self, obs: Observation) -> list[int]:
        sel = obs.select
        if sel is None or not sel.options:
            return []
        self._cur, self._sel = obs.current, sel
        self._track_opponent()
        self._apply_matchup()
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
            # wide_bench: 進化アタッカーが1体立ったら以降は進化させず、たねをベンチに残す
            # （メガシンフォニア等の“盤面エネ×N”火力の母数を増やす）。
            if not (self.plan.wide_bench and self._evolved_attacker_in_play()):
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
            scored.append((s + self._ml_bonus(options[i]), i))
        return max(scored, key=lambda x: x[0])[1] if scored else None

    def _ml_bonus(self, op: Option) -> float:
        """専門家ログ由来 Action Scorer の加点(デッキ非依存)。action_scorer未設定なら0。"""
        if not self.action_scorer or not self.ml_alpha or not self._cur:
            return 0.0
        try:
            from ..imitation import resolve, board_ctx, featurize_generic, policy_scores
            me = self._cur.get("yourIndex", 0)
            ctx = board_ctx(self._cur, me)
            r = resolve(op.raw, self._cur, me)
            f = featurize_generic(ctx, r)
            return self.ml_alpha * float(policy_scores([f], self.action_scorer)[0])
        except Exception:
            return 0.0

    def _play_score(self, cid, hand):
        if cid == LILLIE:
            return None  # リーリエは展開・進化・エネ付けを終えた後（_main後段）で判断する
        # 回復+エネ手札戻し系(ミツル等): アタッカーが十分ダメージを負っている時のみ。
        # ただし今の技で相手バトル場をKOできる(lethal)なら、回復せず攻撃を優先＝ターンを無駄にしない。
        if cid in self.plan.heal_return_cards:
            if self._active_lethal_now():
                return None
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
        # 火力技がまだ弱い間は、弱く殴らず準備技(サーチ/加速)を使って盤面を育てる
        if self.plan.setup_attacks:
            s = self._setup_attack_choice(idxs, options)
            if s is not None:
                return s
        for nm in self.plan.preferred_attacks:
            aid = self._attack_name_ids().get(nm)
            for i in idxs:
                if aid and options[i].attack_id == aid:
                    return i
        # 非リーサル時の攻撃選択: 多次元評価器(_attack_score = 可変ダメージ＋状態異常＋リソース破壊)で比較。
        return max(idxs, key=lambda i: self._attack_score(options[i]))

    def _setup_attack_choice(self, idxs, options):
        """火力技の最大ダメージが setup_attack_min_damage 未満なら、弱く殴らず準備技(サーチ/加速)を使う。
        ＝進化前で足踏み中はコールサインで掘る／盤面エネが薄い間はあふれるねがいで育てる。"""
        setup_is = [i for i in idxs if options[i].attack_id in self.plan.setup_attacks]
        if not setup_is:
            return None
        best = max((self._dmg(options[i]) for i in idxs
                    if options[i].attack_id not in self.plan.setup_attacks), default=0)
        if best >= self.plan.setup_attack_min_damage:
            return None  # 十分な火力がある→殴る
        return setup_is[0]  # 弱い火力しか無い→準備技で盤面を育てる

    def _lethal_choice(self, idxs, options):
        """相手バトル場を倒せる技があれば選ぶ。倒せる技が複数なら、ベンチも削れる技(spread)を優先し、
        その中で最大ダメージ＝相手バトル場を確実に倒しつつ次のKOも準備する。"""
        hp, weak = self._opp_active_hp_weak()
        if hp is None:
            return None
        my_type = self._my_active_type()
        spread_ids = {self._attack_name_ids().get(n) for n in self.plan.spread_attacks}
        best, best_key = None, None
        for i in idxs:
            base = self._dmg(options[i])
            # 弱点無視の技(例: Nebula Beam)は2倍にしない
            apply_weak = (weak and my_type and weak == my_type
                          and options[i].attack_id not in self._attack_no_weak())
            eff = base * 2 if apply_weak else base
            if eff >= hp:
                # (ベンチも削れるか, 実効ダメージ) で選ぶ＝倒せる技の中でJetting Blow等を優先
                key = (1 if options[i].attack_id in spread_ids else 0, eff)
                if best_key is None or key > best_key:
                    best_key, best = key, i
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
        # 可変ダメージは『現在の盤面』から計算する（期待値でなく実値）。固定技は None → base。
        var = self._var_dmg(op.attack_id, base)
        if var is not None:
            return var
        if base == 0 and self.plan.est_var_damage:
            return self._attack_est().get(op.attack_id, 0)
        return base

    def _atk_texts(self) -> dict:
        if getattr(self, "_atk_text", None) is None:
            self._load_attacks()
        return self._atk_text or {}

    def _var_dmg(self, aid, base):
        """効果文＋現在盤面から可変ダメージを計算（汎用）。『N (more) damage for each X』を、Xの現在数
        （相手手札/自分の手札/自分に乗ったダメカン/相手が取ったサイド/自分のベンチ）で評価する。
        固定技や未対応パターンは None（呼び出し側が base を使う）。全カードに効く共通評価器。"""
        import re
        text = self._atk_texts().get(aid, "")
        cur = self._cur
        if not text or not cur or not cur.get("players"):
            return None
        m = re.search(r"(\d+)\s*(more\s+)?damage\s+for each", text)
        if not m:
            return None
        per = int(m.group(1)); low = text.lower()
        me = cur["players"][cur.get("yourIndex", 0)]
        opp = cur["players"][1 - cur.get("yourIndex", 0)]
        cnt = None
        if "opponent" in low and "hand" in low:
            cnt = len(opp.get("hand") or []) or opp.get("handCount", 0)
        elif "your hand" in low or "in your hand" in low:
            cnt = len(me.get("hand") or [])
        elif "damage counter on this" in low:
            a = (me.get("active") or [None])[0]
            mhp = (a.get("maxHp") or 0) if a else 0; hp = (a.get("hp") or 0) if a else 0
            cnt = max(0, (mhp - hp) // 10) if mhp else 0
        elif "prize" in low and "taken" in low:
            cnt = 6 - (len(opp.get("prize") or []) or 6) if "opponent" in low else 6 - (len(me.get("prize") or []) or 6)
        elif "benched" in low and "your" in low:
            cnt = len([b for b in (me.get("bench") or []) if b])
        if cnt is None:
            return None
        return base + per * cnt   # base=0 なら per×cnt(うらみぶし等)、base有なら加算(レイジング等)

    def _status_value(self, aid) -> int:
        """状態異常の"テンポ価値"。眠り/マヒ=次ターン攻撃不能に近い→加点。攻撃選択の比較にのみ使う。"""
        low = self._atk_texts().get(aid, "").lower()
        if "asleep" in low or "paralyzed" in low:
            return 60
        if "confused" in low:
            return 25
        return 0

    def _disrupt_value(self, aid) -> int:
        """相手リソース破壊の価値（手札/エネ/山札の discard）。Control軸に効く共通次元。"""
        low = self._atk_texts().get(aid, "").lower()
        if "discard" not in low or "opponent" not in low:
            return 0
        v = 0
        if "hand" in low:
            v += 25                              # 手札破壊
        if "energy" in low:
            v += 40                              # エネ破壊(相手の攻撃を止める＝価値大)
        if "deck" in low:
            v += 8                               # 山札削り(緩い)
        return v

    def _eval_attack(self, op) -> dict:
        """攻撃の多次元評価（共通資産・拡張可能）。heuristic選択と将来の探索評価の両方で使う。
        現状: damage(現在盤面) / status(状態異常テンポ) / disrupt(相手リソース破壊)。
        将来: ko_probability / energy_efficiency / prize_trade をこの dict に追加していく。"""
        aid = op.attack_id
        return {
            "damage": self._dmg(op),
            "status": self._status_value(aid),
            "disrupt": self._disrupt_value(aid),
        }

    def _attack_score(self, op) -> int:
        """heuristicの攻撃選択に使うスカラー化（多次元評価の重み付き和）。KOは _lethal_choice が別途最優先。"""
        e = self._eval_attack(op)
        return e["damage"] + e["status"] + e["disrupt"]

    def _analyze_development(self) -> dict:
        """育成の『課題診断』（共通資産）。状態でなく"何が足りないか(ボトルネック)"を複数返す。
        ArchaludonBot._missing_piece を全デッキへ一般化。Ultra Ball/ポフィン/ポケギア等のサーチ先選択・
        Turn Evaluator(攻撃 vs 育成)・探索評価が同じ診断を共有する。Attack Evaluator(技は強いか)とは責務が別。
        返り値: attacker_short(線が場/手札に無い) / evolution_short(進化が必要) / energy_short(主役のエネ不足数)
                / ready(強い攻撃が可能) / priority(不足の優先リスト: attacker>evolve>energy)。
        ※ 複数のボトルネックを返す＝サーチ先の選択肢を潰さない。"""
        out = {"attacker_short": 0, "evolution_short": 0, "energy_short": 0, "ready": False, "priority": []}
        cur = self._cur
        if not cur or not cur.get("players") or not self.plan.attackers:
            return out
        me = cur["players"][cur.get("yourIndex", 0)]
        in_play = [s for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s]
        hand_ids = [c.get("id") for c in (me.get("hand") or [])]
        atk = set(self.plan.attackers)
        evolved_ids = {a for a in atk if not getattr(self._cardinfo.get(a), "is_basic", True)}
        evolved_in_play = [s for s in in_play if s.get("id") in evolved_ids]
        basic_in_play = [s for s in in_play if s.get("id") in atk and s.get("id") not in evolved_ids]
        need = self.plan.setup_energy or 3
        # ① 攻撃役の線が場にも手札にも無い
        if not (any(s.get("id") in atk for s in in_play) or any(h in atk for h in hand_ids)):
            out["attacker_short"] = 1; out["priority"].append("attacker")
        # ② 進化形が要るデッキで、まだ最終形が場に居ない
        if evolved_ids and not evolved_in_play:
            out["evolution_short"] = 1; out["priority"].append("evolve")
        # ③ 主役(進化形優先→前段)のエネ不足
        body = (evolved_in_play or basic_in_play or [None])[0]
        if body:
            short = max(0, need - len(body.get("energyCards") or []))
            out["energy_short"] = short
            if short > 0: out["priority"].append("energy")
        out["ready"] = (not out["attacker_short"]) and (not evolved_ids or bool(evolved_in_play)) and out["energy_short"] == 0
        return out

    def analyze_threat(self) -> dict:
        """相手の脅威診断（情報のみ・スコア無し）。相手が自分の活性をどれだけ削れるか/KOされるか。
        Analyzer層の一部。Turn Evaluator が Attack/Development/Threat/Prize を統合して判断する。"""
        out = {"opp_line_damage": 0, "can_ko_me": False, "my_active_hp": 0, "hits_to_lose": 99}
        cur = self._cur
        if not cur or not cur.get("players"):
            return out
        oi = cur.get("yourIndex", 0)
        me = cur["players"][oi]; opp = cur["players"][1 - oi]
        opp_a = (opp.get("active") or [None])[0]; my_a = (me.get("active") or [None])[0]
        if not opp_a or not my_a:
            return out
        dmg = _line_threat(opp_a.get("id"))              # 相手の進化含む最大火力
        mc = self._cardinfo.get(my_a.get("id")); oc = self._cardinfo.get(opp_a.get("id"))
        if mc and oc and mc.weakness and oc.type == mc.weakness:
            dmg *= 2                                      # 自分の弱点で2倍
        hp = my_a.get("hp", 0)
        out.update(my_active_hp=hp, opp_line_damage=dmg,
                   can_ko_me=(dmg >= hp and hp > 0),
                   hits_to_lose=(((hp + dmg - 1) // dmg) if dmg > 0 else 99))
        return out

    def analyze_prize(self) -> dict:
        """サイドレース診断（情報のみ）。残りサイド差（prize_diff>0 なら自分が先行）。"""
        out = {"my_prizes": 6, "opp_prizes": 6, "prize_diff": 0}
        cur = self._cur
        if not cur or not cur.get("players"):
            return out
        oi = cur.get("yourIndex", 0)
        myp = len(cur["players"][oi].get("prize") or []) or 6
        opz = len(cur["players"][1 - oi].get("prize") or []) or 6
        out.update(my_prizes=myp, opp_prizes=opz, prize_diff=opz - myp)
        return out

    def _need_improvement(self, card_id) -> dict:
        """Action Impact（改善量Analyzer）: このカードを獲得/展開すると Need(analyze_development)を
        どれだけ改善するか"だけ"返す。カード選択はしない（あなたの設計: Need→候補→改善量→決定 を分離）。
        全サーチ札(Ultra Ball/ネスト/ポフィン/夜タンカ)・ドロー・展開・エネ加速が共通で使える。
        返り値: {attacker, evolve, energy} の改善量（Needが大きく、そのカードが該当するほど大きい）。"""
        imp = {"attacker": 0.0, "evolve": 0.0, "energy": 0.0}
        if card_id is None:
            return imp
        need = self._analyze_development()
        atk = set(self.plan.attackers)
        if card_id in atk:
            if getattr(self._cardinfo.get(card_id), "is_basic", True):
                imp["attacker"] = need["attacker_short"] * 60.0    # 攻撃役の線(たね)を確保
                if need["evolution_short"]:
                    imp["evolve"] = 25.0                           # 進化の前提(前段)を確保
            else:
                imp["evolve"] = need["evolution_short"] * 55.0     # 進化形を確保
        if self._is_energy(card_id):
            imp["energy"] = need["energy_short"] * 35.0
        return imp

    def _need_improvement_score(self, card_id) -> float:
        """改善量のスカラー化（決定層/探索が使う。Analyzerは改善量dictを返し、スコア化はここで分離）。"""
        imp = self._need_improvement(card_id)
        return imp["attacker"] + imp["evolve"] + imp["energy"]

    def analyze_recovery(self, card_id) -> dict:
        """復旧/展開の"事実"診断（Analyzer=事実のみ・Opinionを持たない）。カードの価値判断はしない。
        Turn Evaluator が局面ごとに重み付けする。将来 engine状態/エネ源 等の Fact Analyzer をここへ拡張。
        is_attacker / is_evolved_attacker / recovery_possible(進化前が居て最終形が欠けている) /
        bench_thin(ベンチ<3=展開が薄い事実)。"""
        atk = set(self.plan.attackers)
        info = self._cardinfo.get(card_id)
        is_atk = card_id in atk
        is_evo_atk = is_atk and not getattr(info, "is_basic", True)
        need = self._analyze_development()
        cur = self._cur
        me = cur["players"][cur.get("yourIndex", 0)] if (cur and cur.get("players")) else {}
        return {
            "is_attacker": is_atk,
            "is_evolved_attacker": is_evo_atk,
            "recovery_possible": bool(is_evo_atk and need["evolution_short"] and need["attacker_short"] == 0),
            "bench_thin": len([b for b in (me.get("bench") or []) if b]) < 3,
        }

    def analyze_phase(self) -> dict:
        """局面フェーズの事実診断（Fact・Opinion無し）。Turn Evaluator が重み付けに使う。
        opening/midgame/endgame（残りサイド×ターンで判定）＋ prize_race（接戦の終盤=事実）。"""
        out = {"turn": 0, "opening": False, "midgame": True, "endgame": False, "prize_race": False}
        cur = self._cur
        if not cur or not cur.get("players"):
            return out
        oi = cur.get("yourIndex", 0)
        myp = len(cur["players"][oi].get("prize") or []) or 6
        opz = len(cur["players"][1 - oi].get("prize") or []) or 6
        ph = self._game_phase()
        out.update(turn=cur.get("turn", 0), opening=(ph == "early"), endgame=(ph == "late"),
                   midgame=(ph == "mid"), prize_race=(min(myp, opz) <= 3 and abs(myp - opz) <= 1))
        return out

    def evaluate_turn(self) -> dict:
        """Turn Evaluator: Analyzer群(Fact)を統合し、各行動の"機会(Opportunity)"スコアを返す。★Actionは返さない。
        唯一の Opinion 層（Phase補正・Threatの重み等）。Resolver も Search も同じこの評価器を共有する。
        デッキ名・カード名は見ない（Fact経由のみ）＝Universal。feature flag(use_turn_evaluator)で段階導入する。"""
        ph = self.analyze_phase(); th = self.analyze_threat(); dv = self._analyze_development()
        if ph["opening"]:
            w = {"attack": 0.6, "develop": 1.4, "recover": 1.0, "disrupt": 0.8}
        elif ph["endgame"]:
            w = {"attack": 1.3, "develop": 0.6, "recover": 1.1, "disrupt": 0.9}
        else:
            w = {"attack": 1.0, "develop": 1.0, "recover": 1.0, "disrupt": 1.0}
        attack = 100 if dv["ready"] else 25
        develop = 30 + dv["energy_short"] * 15 + dv["evolution_short"] * 30 + dv["attacker_short"] * 45
        recover = 65 if (dv["attacker_short"] or (th["can_ko_me"] and not dv["ready"])) else 10
        disrupt = 25
        return {"attack": round(attack * w["attack"], 1), "develop": round(develop * w["develop"], 1),
                "recover": round(recover * w["recover"], 1), "disrupt": round(disrupt * w["disrupt"], 1)}

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
        # 相手の主力アタッカーの進化前(発展中の脅威)がベンチでKO可能で、前が主力でない(脅威が低い)なら、
        # サイド数が同等でもボスで進化前を狩る＝主力の発展を阻害。ただし前を倒して勝ち切れるなら覆さない。
        me = cur["players"][cur["yourIndex"]]
        my_prizes_left = sum(1 for x in (me.get("prize") or []) if x) or 6
        key_pre_koable = any(
            self._eff_dmg(dmg, ign, sp.get("id")) >= (sp.get("hp") or 9999)
            for sp in self._opp_key_preevo_spots())
        if (key_pre_koable
                and _line_threat(act.get("id")) < (self._opp_main_line or 0)
                and my_prizes_left > active_val):
            return True
        return best_bench > active_val         # 前は倒せるが、より大きなサイドを優先

    def _ko_gust_pick(self, sel):
        """相手ポケモン選択: KO可能を最優先 → サイド価値大 → 現HP小 で選ぶ。"""
        cur = self._cur
        if not cur:
            return None
        opp_idx = 1 - cur["yourIndex"]
        opp = cur["players"][opp_idx]
        dmg, ign = self._active_attack_potential()
        spread = self.plan.spread_damage
        cand = []
        for i, op in enumerate(sel.options):
            if op.player_index != opp_idx:
                continue
            spots = (opp.get("active") if op.area == AreaType.ACTIVE else opp.get("bench")) or []
            if op.index is not None and 0 <= op.index < len(spots) and spots[op.index]:
                sp = spots[op.index]
                cid = sp.get("id")
                hp = sp.get("hp", 9999)
                threat = _line_threat(cid)   # 進化ライン脅威度(例:リオル=メガルカリオ線)
                if spread:
                    cand.append(self._spread_key(sp, cid, hp, threat, spread, dmg) + (i,))
                else:
                    koable = 1 if self._eff_dmg(dmg, ign, cid) >= hp else 0
                    cand.append((koable, self._prize_value(cid), threat, -hp, i))
        if not cand:
            return None
        return max(cand)[-1]

    def _game_phase(self) -> str:
        """序盤/中盤/後半。残りサイドとターンで判定（撒き優先度の切替に使う）。"""
        cur = self._cur
        if not cur:
            return "mid"
        turn = cur.get("turn", 0)
        me = cur["players"][cur["yourIndex"]]; opp = cur["players"][1 - cur["yourIndex"]]
        my_pz = sum(1 for x in (me.get("prize") or []) if x) or 6
        opp_pz = sum(1 for x in (opp.get("prize") or []) if x) or 6
        if turn <= 3 or (my_pz >= 5 and opp_pz >= 5):
            return "early"
        if my_pz <= 2 or opp_pz <= 2:
            return "late"
        return "mid"

    def _spread_key(self, sp, cid, hp, threat, spread, our_dmg):
        """ベンチ撒き(Jetting Blow等)の対象優先度テーブル＝ベース×相手デッキ(self._matchup)×局面。
        ダメージは進化で引き継ぐので『将来この火力枠が前に出た時、今の撒きでKO攻撃回数を減らせるか』を予測する。
          - 序盤: 発展中の主力ライン(進化前=最大脅威の線)を優先的に削り、将来の脅威の芽を先に摘む。
          - 中盤: 将来のKO攻撃回数削減(reduce)を最優先＝前に出てくる火力枠を効率よく軟化。
          - 後半: 撒き＋自火力でKO圏に入る主力を優先＝詰め。
        ＝(局面別のキー, i) を返す。i は呼び出し側で付与。"""
        koable = 1 if spread >= hp else 0            # 撒きだけで今KOできるか(低HPベンチ)
        fhp = _line_attacker_hp(cid)                 # 進化後に前に出てくる火力枠のHP
        maxhp = sp.get("maxHp") or fhp or hp
        cur_dmg = max(0, maxhp - hp) if sp.get("maxHp") else 0
        remaining = max(0, fhp - cur_dmg)            # 火力枠HP - 引き継ぎダメージ
        our = our_dmg if our_dmg > 0 else 210
        rem_after = max(0, remaining - spread)
        reduce = 0                                   # 今の撒きで減る将来のKO攻撃回数(3回→2回等)
        if our > 0 and remaining > 0:
            reduce = (-(-remaining // our)) - (-(-rem_after // our))
        # 相手の火力枠は1回では倒せない→『2回(=2*自火力)で倒せるか』を詰めの判断基準にする(1回狙いは非現実的)。
        two_ko = 1 if (remaining > 0 and rem_after <= 2 * our) else 0
        # 実測で reduce(将来KO削減)＋threat(最大脅威の線に蓄積) が全局面で支配的＝主軸に固定。局面で二次基準を切替。
        phase = self._game_phase()
        pv = self._prize_value(cid)
        if phase == "late":             # 後半=詰め: reduce同点なら『撒き後2回で倒せる』主力を優先
            return (koable, reduce, threat, two_ko, pv, -hp)
        return (koable, reduce, threat, pv, -hp)     # 序盤・中盤: 軟化(将来KO削減＋脅威線に蓄積)

    def _take(self, sel, prefer_high: bool, take_max: bool) -> list[int]:
        n = len(sel.options)
        k = sel.max_count if take_max else sel.min_count
        k = max(0, min(k, n))
        if k == 0:
            return []
        # Resolver v1: 取得(take)は Need改善量 で選ぶ(限定導入・Explain Log付き)。give(discard)は従来通り。
        if prefer_high and self.plan.use_resolver:
            return self._resolve_target(sel, k)
        keyfn = (self._take_rank if (prefer_high and self.plan.smart_take)
                 else self._opt_value)
        ranked = sorted(range(n), key=lambda i: keyfn(sel.options[i]),
                        reverse=prefer_high)
        return sorted(ranked[:k])

    def _resolve_target(self, sel, k) -> list[int]:
        """Resolver v1: 候補(sel.options) × Need改善量(_need_improvement) → 最良k件。カード選択は最後の argmax のみ。
        Explain Log に『候補・改善量・Need・採用』を残す(デバッグ/説明用)。サーチ札共通(候補生成はengineが提供)。"""
        # Resolver = argmax のみ（評価は本来 Turn Evaluator の責務）。Turn Evaluator 実装までの暫定として
        # Need改善量でランクし、同点は静的カード価値(_opt_value=既存の価値判断)でタイブレーク。
        # ※Opinion(価値判断)は Analyzer に持たせない。ここは"決定層"なので暫定的に価値を参照してよい。
        scored = []
        for i in range(len(sel.options)):
            cid = self._opt_card_id(sel.options[i])
            score = (self._need_improvement_score(cid), self._opt_value(sel.options[i]))
            scored.append((score, i, cid))
        scored.sort(key=lambda t: t[0], reverse=True)
        need = self._analyze_development()
        cn = lambda c: (self._cardinfo.get(c).name if self._cardinfo.get(c) else f"#{c}")
        self._resolver_log.append({
            "turn": (self._cur or {}).get("turn"),
            "need": {kk: need[kk] for kk in ("attacker_short", "evolution_short", "energy_short")},
            "candidates": [(cn(c), round(s)) for s, _, c in scored[:5]],
            "chosen": cn(scored[0][2]) if scored else None,
        })
        return sorted(i for _, i, _ in scored[:k])

    def _first_of(self, sel, want_ids) -> int | None:
        for cid in want_ids:
            for i, op in enumerate(sel.options):
                if self._opt_card_id(op) == cid:
                    return i
        return None

    # ===== 相手デッキ検出（マッチアップ別処理の起点） =====
    def _track_opponent(self):
        """相手の場(active/bench)で見えたカードidを累積し、最大脅威ライン(line_threat最大)を更新。
        ＝相手デッキを試合中に判定し、マッチアップ別の処理に切り替えるための観測。"""
        cur = self._cur
        if not cur:
            return
        opp = cur["players"][1 - cur.get("yourIndex", 0)]
        for area in ("active", "bench"):
            for sp in (opp.get(area) or []):
                if sp and sp.get("id") is not None:
                    self._opp_seen.add(sp["id"])
        if self._opp_seen:
            self._opp_main_line = max(_line_threat(c) for c in self._opp_seen)

    def _classify_opponent(self):
        """相手の場で見えたカードからアーキタイプを判別。判別不能ならNone(=ベース処理テーブル)。
        matchup_signatures は『そのデッキを示す代表カードid』。先に定義したものを優先(具体的→一般)。"""
        for arch, sig in self.matchup_signatures.items():
            if any(c in self._opp_seen for c in sig):
                return arch
        return None

    def _apply_matchup(self):
        """検出した相手アーキを self._matchup に保持し、差分テーブルをベースに適用。
        DRY: matchup_plans には差分knobのみ。未定義の処理は self._base_plan(ベース)を参照。
        マッチアップ固有の『ロジック』は各メソッドが self._matchup を見て分岐できる。
        signatures が無い bot は何もしない（既存bot/提出は挙動不変）。"""
        if not self.matchup_signatures:
            return
        arch = self._classify_opponent()
        if arch == self._matchup:
            return
        self._matchup = arch
        ov = self.matchup_plans.get(arch) if self.matchup_plans else None
        self.plan = replace(self._base_plan, **ov) if ov else self._base_plan

    def _opp_key_preevo_spots(self):
        """相手ベンチの『主力アタッカーの進化前』(=倒すと発展を阻害できる)spot。
        最大脅威ラインに属し、まだ最終形でない(line_threat>自身の最大ダメージ=さらに強く進化できる)もの。"""
        cur = self._cur
        ml = self._opp_main_line or 0
        if not cur or ml < 180:
            return []
        opp = cur["players"][1 - cur.get("yourIndex", 0)]
        spots = []
        for sp in (opp.get("bench") or []):
            if not sp:
                continue
            cid = sp.get("id")
            lt = _line_threat(cid)
            if lt >= ml and lt > self._cardinfo_dmg(cid):
                spots.append(sp)
        return spots

    def _cardinfo_dmg(self, cid):
        from ..state_encoder import caps as _caps
        return _caps(cid)["max_dmg"]

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
        self._atk_text = {}
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
                self._atk_text[a.attackId] = a.text or ""
                # 弱点/抵抗を無視する技を記録（例: Nebula Beam）
                if a.text and "affected by Weakness" in a.text:
                    self._atk_no_weak.add(a.attackId)
        except Exception:
            pass

    @staticmethod
    def _fallback(sel) -> list[int]:
        n = len(sel.options)
        return list(range(min(max(1, sel.min_count), n)))
