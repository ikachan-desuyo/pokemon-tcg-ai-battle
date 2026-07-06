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
    POFFIN: 100, RARE_CANDY: 60, MEGA_SIGNAL: 84, HYPER_BALL: 82, POKE_PAD: 78,
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
    hp_boost_tools: dict = field(default_factory=dict)  # HP増加ツール{id:+HP}(例:ケープ100)。activeの被KO圏→生存圏の反転を最優先
    heal_return_cards: tuple[int, ...] = ()   # 回復+エネ手札戻し系(例:ミツル)。アタッカーが十分ダメージ時のみ使用
    boss_cards: tuple[int, ...] = ()          # 引きずり出し系(例:ボスの指令)。KO(サイド)を生む時のみ使用
    recover_cards: tuple[int, ...] = ()       # トラッシュ回収系(例:夜のタンカ)。回収価値がある時のみ使用
    switch_cards: tuple[int, ...] = ()        # 入替系(例:ポケモンいれかえ)。攻撃役を前に出す必要がある時のみ使用
    evolve_supporters: tuple[int, ...] = ()   # 進化加速サポ(例:セイジ)。場に山札から進化できるポケモンが居る時のみ
                                              # =前提条件Gateファミリ(boss/recover/switchと同じ責務)。QA: 無価値セイジ11件の修正
    smart_take: bool = False                  # サーチ/ポケギア取得時、状況依存サポを今役立つ時だけ優先
    strict_lillie_guard: bool = False         # True=手札にキーがあれば常にリーリエ抑制(コンボ系向け)。既定はこの番に展開できるキーのみ抑制
    setup_wall: tuple[int, ...] = ()          # 開幕バトル場に優先したい高HP壁(例:エースバーン)。先攻はT1攻撃不可なので壁を前に
    energy_supporters: tuple[int, ...] = ()   # エネ補給サポ(例:トウコ)。進化アタッカーが居てエネ切れ＝攻撃不可の時に優先して打つ
    eager_reposition: bool = False            # 壁→攻撃役の前進を「エネ付けの前」に行い、手札のエネ(イグニ等)で前進後に殴る
    avoid_overstack: bool = False             # 最大技コストを満たした対象への追加エネを後回し=後継(ベンチ)を並行育成。既定OFF(出荷非破壊)
    setup_attacks: tuple[int, ...] = ()       # 準備技(サーチ/加速)のattackId群(例:コールサイン/あふれるねがい)
    setup_attack_min_damage: int = 0          # 火力技の最大ダメージがこの値未満なら、弱く殴らず準備技を使う
    wide_bench: bool = False                  # 盤面エネ依存火力(メガシンフォニア等)向け: 進化アタッカーが1体立ったら残るたねは進化させずベンチに残し母数にする
    sacrifice_abilities: tuple[int, ...] = () # 自滅特性(例:カースドボム)。ベンチ backup有り＆相手をKOできる時のみ使う
    sacrifice_damage: dict = field(default_factory=dict)  # {特性カードid: 与ダメージ} 自滅特性のKO判定用
    est_var_damage: bool = False              # 可変ダメージ技(base=0)を効果文から推定して評価
    setup_energy: int = 0                     # 主アタッカーが攻撃に必要なエネ数(育成評価器 _eval_setup 用。0=既定3扱い)
    use_resolver: bool = False                # サーチ先(take)を Resolver(Need改善量) で選ぶ(v1限定導入・A/B用)
    use_turn_evaluator: bool = False          # 「攻撃 vs 育成」の1判断のみ Turn Evaluator に委譲(限定接続・A/B用)
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
        self._attach_turn = None    # 手貼りを行ったターン(assume_hand_attach の判定に使用)
        self._opp_ene_mark = None   # (turn, 相手の場のエネ総数)。手札エネ推論の基準点
        self._opp_no_attach_streak = 0  # 相手が手貼りせず終えた連続ターン数(≥1で手札エネ薄の示唆)
        self._opp_seen = set()      # 相手の場で見えたカードidの累積（相手デッキ判定に使用）
        self._opp_main_line = None  # 相手の最大脅威ライン(line_threat最大)。マッチアップ別処理の起点
        self._resolver_log = []     # Resolver v1 の Explain Log(候補・改善量・採用理由)
        self._turn_eval_log = []    # Turn Evaluator接続の Explain Log(攻撃 vs 育成の Opportunity・採用)
        self._eval_player = None    # Analyzer/評価器の視点を固定(Search中はroot視点)。Noneなら現手番(cur.yourIndex)
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
                ev = self._pick_evolve(g[OptionType.EVOLVE], options, hand)
                if ev is not None:
                    return [ev]
        # （任意）エネ付けの前に壁を退いて攻撃役を前に出すと今ターン殴れるなら退く。
        # イグニはベンチに付けられないため、前進後に手札のイグニ→ネビュラを成立させる。
        if (self.plan.reposition and self.plan.eager_reposition
                and OptionType.RETREAT in g and self._should_reposition_eager(me, hand)):
            return [g[OptionType.RETREAT][0]]
        # 死亡確定×不利トレードの前逃げ(人間レビュー6巡目⑤): 前の攻撃役(サイド2+)が次ターン被KO
        # 確定圏で、残って殴っても取れるサイド<失うサイド、かつベンチの主力後続が今ターン攻撃可能なら
        # 手貼り前に退く(前の付きエネはどうせ失われる=退却コストは実質ゼロ。退いた後に後続へ貼る)。
        # ※普遍原則のためrepositionフラグ非依存(UniversalBotにも適用)。
        if OptionType.RETREAT in g and self._should_retreat_doomed(me, hand):
            return [g[OptionType.RETREAT][0]]
        if OptionType.ATTACH in g:
            a = self._pick_attach(g[OptionType.ATTACH], options, hand, me)
            if a is not None:
                self._attach_turn = (self._cur or {}).get("turn")
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
            idxs = g[OptionType.ATTACK]
            # 相方不在で「何もしない」技しか無ければ空撃ちせずEND(DeadMoveAttackの修正)。
            live = [i for i in idxs
                    if not self._dead_by_partner(self._atk_texts().get(options[i].attack_id, ""))]
            if not live and OptionType.END in g:
                return [g[OptionType.END][0]]
            if live:
                idxs = live
            # 砲装填ガード: 非KOチップが相手のダメカン×N技(Raging Hammer等)を自分の致死圏まで
            # 装填する攻撃は撃たない(人間レビュー20巡目 arch T9: Jetting90でArch100→10残し
            # →RH 280→370に装填→Mega330一撃死=敗着。撃たなければ280<330で生存だった)
            safe = self._filter_gun_loading(idxs, options)
            if not safe and OptionType.END in g:
                return [g[OptionType.END][0]]
            if safe:
                idxs = safe
            # Turn Evaluator 限定接続: 「攻撃 vs 育成」の1判断のみ委譲(flag)。リーサルは必ず攻撃。
            if self.plan.use_turn_evaluator and OptionType.END in g:
                lethal = self._lethal_choice(idxs, options) if self.plan.lethal else None
                if lethal is None:
                    ev = self.evaluate_turn(attack_candidates=[self._eval_attack(options[i]) for i in idxs])
                    a_op, d_op = ev["attack"]["score"], ev["develop"]["score"]
                    chosen = "develop(skip)" if d_op > a_op * 1.3 else "attack"
                    self._turn_eval_log.append({"turn": (self._cur or {}).get("turn"), "phase": ev["phase"],
                                                "attack": a_op, "develop": d_op, "chosen": chosen})
                    if chosen == "develop(skip)":
                        return [g[OptionType.END][0]]  # この番は殴らず育成優先(盤面は既に展開済)
            return [self._best_attack(idxs, options)]
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
        # 単騎の緊急展開: ベンチが空なら手札のたねを最優先で置く(ベンチ切れ負け防止の普遍原則。
        # QA: 相手archbotがRelicanth在手のままJudgeで流して単騎敗北リスク)。
        ci0 = self._cardinfo.get(cid)
        if ci0 and ci0.is_pokemon and ci0.is_basic:
            me0 = self._me()
            if me0 is not None and not any(b for b in (me0.get("bench") or []) if b):
                return 96
        if cid == LILLIE:
            # 緊急時(単騎×被KO圏×手札に生存手段なし)は最優先=他サポ(ヒルダ83等)にサポ権を
            # 先に消費させない(人間レビュー8巡目: 単騎でリーリエ2枚を持ちながらヒルダ2回で敗北。
            # 山にたね/ポフィン7枚=引ければ生存できた)。通常時は従来通り_main後段で判断。
            if self._lillie_emergency():
                return 95
            # エネ掘り(勝ち筋直結)も_play_scoreに昇格: 手札エネ0×攻撃役が技を払えない×p_draw高
            # の時、軽微ヒール(50)等がサポ権を先に消費するのを防ぐ(人間レビュー18巡目 mirror T11:
            # 相手Mega残20=エネ1枚で即勝ちの局面でWally50が先取り→勝利がT13に遅延)
            if self._lillie_energy_dig():
                return 70
            return None
        # 回復+エネ手札戻し系(ミツル等): アタッカーが十分ダメージを負っている時のみ。
        # ただし今の技で相手バトル場をKOできる(lethal)なら、回復せず攻撃を優先＝ターンを無駄にしない。
        if cid in self.plan.heal_return_cards:
            # ベンチのボス釣りベイト(KO=相手残サイド充足=負け)を回復で圏外へ。相手デッキの
            # ボス残数推定>=1なら「ベンチ=安全」は成立しない(自己レビューgrimmsnarl-6 T11:
            # 傷Mega90を放置しサポ権をSalvatoreへ→T12ボス+Shadow Bulletで敗北)。
            me_b = self._me() or {}
            pr_b = self.analyze_prize()
            opp_left_b = pr_b.get("opp_prizes") or 6
            # activeの生存が負けを防ぐ回復も90: 「死んだら負け(相手残充足) or 単騎(=盤面全滅)」
            # × 被KO圏 × 回復で生存反転。Boss62等のサイド獲得サポより優先(人間レビュー23巡目
            # lucario T9敗着: 単騎Mega60でBoss62がWally60を2点差で先取り→+3取るも次ターン全滅)
            act_b = (me_b.get("active") or [None])[0]
            if act_b is not None:
                alone_b = not any(x for x in (me_b.get("bench") or []) if x)
                th_a = self._incoming_next_turn(act_b)
                if ((self._prize_value(act_b.get("id")) >= opp_left_b or alone_b)
                        and (act_b.get("hp") or 0) <= th_a < (act_b.get("maxHp") or 0)):
                    if not (self._attack_prizes_now() >= (pr_b.get("my_prizes") or 6)):
                        return 90
            if self._opp_boss_remaining() > 0:
                for sp in me_b.get("bench") or []:
                    if not sp:
                        continue
                    th_b = self._incoming_next_turn(sp)
                    if (self._prize_value(sp.get("id")) >= opp_left_b
                            and (sp.get("hp") or 0) <= th_b < (sp.get("maxHp") or 0)):
                        # 今殴って自分が勝ち切れるなら攻撃優先
                        oa_b = ((cur := self._cur or {}).get("players", [{}, {}])[1 - cur.get("yourIndex", 0)].get("active") or [None])[0]
                        if not (oa_b and self._active_lethal_now()
                                and self._prize_value(oa_b.get("id")) >= (pr_b.get("my_prizes") or 6)):
                            return 90
            # ベンチの重傷攻撃役(エネ0=エネ戻し損失ゼロ)の回復は攻撃と両立する=lethalでも打つ
            # (AI自己レビュー: dragapult-3 T11 ベンチMega30を放置→翌ターン多面KO負けの修正)。
            me_h = self._me() or {}
            for sp in me_h.get("bench") or []:
                if (sp and sp.get("id") in self.plan.attackers
                        and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150
                        and not (sp.get("energyCards") or [])):
                    return 60
            if self._active_lethal_now():
                return None
            # 重傷(150+)なら進化加速サポ(セイジ58)より優先(人間レビュー5巡目①: HP120のactiveを
            # 放置して3体目のメガを立てるより回復)。ボス(62=サイド獲得)は上のまま。
            # ただし回復が生存反転になる場合のみ(満タンでも相手最大火力のワンパン圏なら回復は無意味
            # =テンポ損。回帰でarch77→68を検出した過剰発火の修正)。
            if self._attacker_damaged(150):
                me2 = self._me()
                act2 = ((me2 or {}).get("active") or [None])[0]
                if act2 and (act2.get("maxHp") or 0) > self._incoming_threat(act2):
                    return 60
                # ベンチの重傷攻撃役が撒き(相手のJetting50等)圏内なら回復価値あり
                # (人間レビュー7巡目④: ベンチMega50を放置して撒きで喪失)。
                for sp in (me2 or {}).get("bench") or []:
                    if (sp and sp.get("id") in self.plan.attackers
                            and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150
                            and (sp.get("hp") or 999) <= 50):
                        return 60
                return None
            return 50 if self._attacker_damaged() else None
        # エネ補給サポ(トウコ等): 進化アタッカーが居て攻撃できない(エネ切れ)なら優先＝攻撃を早める
        if cid in self.plan.energy_supporters and self._attacker_needs_energy():
            return 83
        # 引きずり出し系(ボス等): KO(サイド獲得)を生む時のみ。勝ち切れる(取れるサイド>=残り)なら最優先
        if cid in self.plan.boss_cards:
            if not self._should_play_boss():
                return None
            # 勝ち切りボスは緊急リーリエ(95)より上=「今勝てる」は生存準備に優先
            # (人間レビュー23巡目 grimmsnarl T11: 残1でboss+Jetting=勝ちなのに同点95の
            #  緊急リーリエが先取りしBossごと手札を流した)
            return 96 if self._boss_wins_game() else 62
        # 回収系(夜のタンカ等): トラッシュに回収価値がある時のみ（無駄打ち防止）
        if cid in self.plan.recover_cards:
            return 50 if self._has_recover_target() else None
        # 入替系(ポケモンいれかえ等): 攻撃役を前に出す必要がある時のみ
        if cid in self.plan.switch_cards:
            return 64 if self._should_switch() else None
        # 進化加速サポ(セイジ等): 場に山札から進化できるポケモンが居る時のみ(前提条件Gate)。
        # 対象ゼロでの使用はサポ権の浪費(QAゲート: 無価値セイジ11件/30試合)。
        if cid in self.plan.evolve_supporters:
            return 58 if self._has_evolution_target() else None
        if cid in self.plan.play_priority:
            return self.plan.play_priority[cid]
        if ci0 and not ci0.is_pokemon and "Stadium" in (ci0.stage or ""):
            return 75    # スタジアムは展開初手級(アメ60/進化より先。Punk Up等の進化トリガーの下地)
        if cid in self.plan.attackers:   # 進化前/アタッカーをベンチに置くのは重要
            return 80
        if ci0 and ci0.is_pokemon and ci0.is_basic:
            return 65    # 非アタッカーのたね(特性要員等)もアメ(60)/進化トリガーより先に展開
        return _GENERIC_PLAY.get(cid, 40)

    def _pick_evolve(self, idxs, options, hand) -> int:
        best, best_key = None, None
        for i in idxs:
            op = options[i]
            evo = self._hand_id(hand, op.index)
            key = (0 if self._evolve_creates_loss_bait(evo, op) else 1,  # 負けベイト化する進化を避ける
                   1 if evo in self.plan.attackers else 0,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if best_key is None or key > best_key:
                best_key, best = key, i
        if best_key is not None and best_key[0] == 0:
            return None                        # 全候補が負けベイト=進化しない方が良い
        return best

    def _evolve_creates_loss_bait(self, evo_id, op) -> bool:
        """この進化が「KO=相手の残サイド充足(死んだら負け)」のactiveベイトを作るか。
        進化後が現実的脅威(可変ダメ込)で確実にKOされ、かつ進化後の攻撃でも相手activeを
        取れない(脅威を消せない)なら、activeへの進化は負けを1ターン早めるだけ
        (人間レビュー13巡目 alakazam-0 T7: Staryu70(死1枚)をMega330(死3枚)へ進化し
        Powerful Hand 440の前に差し出して即負け。進化しなければ継続していた)。"""
        if op.in_play_area != AreaType.ACTIVE:
            return False
        info = self._cardinfo.get(evo_id)
        if not info:
            return False
        cur = self._cur or {}
        me = self._me() or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        oa = (opp.get("active") or [None])[0]
        act = (me.get("active") or [None])[0]
        if not oa or not act:
            return False
        pr = self.analyze_prize()
        opp_left = pr.get("opp_prizes") or 6
        if self._prize_value(evo_id) < opp_left:
            return False                       # 死んでも負けない
        if self._prize_value(act.get("id")) >= opp_left:
            return False                       # 進化前から既にベイト=進化で悪化しない
        # 進化後の被KO(現実的評価): 進化後スポット想定でmaxHp vs 脅威
        evo_spot = dict(act)
        evo_spot["id"] = evo_id
        evo_spot["hp"] = evo_spot["maxHp"] = info.hp or (act.get("maxHp") or 0)
        if (evo_spot["hp"] or 0) > self._incoming_next_turn(evo_spot):
            return False                       # 耐える=ベイトでない
        # 進化後の攻撃(手貼り込み)で相手activeを取れるなら脅威側が消える=正当
        import re
        att = []
        for ec in (act.get("energyCards") or []):
            att += self._energy_provides_syms(ec.get("id"))
        hand_e = [c.get("id") for c in (me.get("hand") or []) if self._is_energy(c.get("id"))]
        best_dmg = 0
        for extra in [None] + (hand_e if not cur.get("energyAttached") else []):
            pool0 = att + (self._energy_provides_syms(extra) if extra is not None else [])
            for m in info.moves:
                need = re.findall(r"\{([A-Z])\}", m.cost or "")
                pool = list(pool0)
                ok = all((t in pool and (pool.remove(t) or True)) for t in need)
                if not ok or len(pool) < (m.cost or "").count("●"):
                    continue
                mt = re.match(r"(\d+)", str(m.damage or ""))
                if mt:
                    best_dmg = max(best_dmg, self._eff_dmg(int(mt.group(1)), False, oa.get("id")))
        return best_dmg < (oa.get("hp") or 9999)

    def _pick_attach(self, idxs, options, hand, me):
        # HPブーストツール(ケープ等): activeを「被KO圏→生存圏」に反転できるなら最優先で前に貼る。
        # avoid_overstackは死亡濃厚activeへの投資を避けるが、ケープは死亡条件そのものを変えるため
        # エネと同じ扱いにしない(人間レビュー5巡目②: 相手の最大火力を計算して貼り先を決める)。
        for i in idxs:
            op = options[i]
            tool = self._hand_id(hand, op.index)
            boost = (self.plan.hp_boost_tools or {}).get(tool)
            if not boost or op.in_play_area != AreaType.ACTIVE:
                continue
            act = (me.get("active") or [None])[0]
            if not act or act.get("id") not in self.plan.attackers:
                continue
            th = max(self._incoming_threat(act), self._incoming_next_turn(act))
            hp = act.get("hp") or 0
            if hp <= th < hp + boost:
                return i
        # 勝ちエネ最優先: このエネをactiveに貼ると攻撃(スプラッシュKO込み)で残りサイドを
        # 取り切れるなら、rule順位に関係なくそれを貼る(人間レビュー21巡目 mirror T11:
        # W→Jetting+スプラッシュ50=ベンチMega20 KO=勝ちなのにrule上位のイグニを貼り
        # Jetting不能→退却→勝利がT15に遅延)
        pr_w = self.analyze_prize()
        my_left_w = pr_w.get("my_prizes") or 6
        win_opts = []
        for i in idxs:
            op = options[i]
            if op.in_play_area != AreaType.ACTIVE:
                continue
            energy = self._hand_id(hand, op.index)
            if not self._is_energy(energy):
                continue
            if self._attack_prizes_now(extra_energy_id=energy) >= my_left_w:
                win_opts.append((1 if energy in self.plan.volatile_energies else 0, i))
        if win_opts:
            return min(win_opts)[1]    # 勝ちエネ複数なら非揮発(基本エネ)優先=イグニ温存
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
                # 手札の基本エネ1枚で最大技が今ターン払える(恒久エネ完成=毎ターン打てる状態)なら
                # イグニは温存(番末に消えて次ターン貼り直しになる。人間レビュー4巡目②③:
                # 水2枚+手札水でイグニを貼った局面の修正)。
                if self._basic_attach_suffices(me, op, hand):
                    continue
            spots_k = (me.get("active") if op.in_play_area == AreaType.ACTIVE else me.get("bench")) or []
            sp_k = (spots_k[op.in_play_index]
                    if op.in_play_index is not None and 0 <= op.in_play_index < len(spots_k) else None)
            comp = self._completes_cost(energy, target, sp_k)
            # 規則(plan)適合を最上位に、その中でコスト充足を優先。compを全体最優先にすると
            # 脇役の1エネ技「完成」(comp=2)が計画の主役育成(水→メガ, rule>0)を上書きして
            # WallRetreat再発(QA 2件)。逆にruleを最上位にすると同一対象のR+R重ね(rule大)が
            # P充足(rule小)に勝つ(人間レビュー10巡目)。→「rule有無」→「充足」→「rule順位」。
            # 先攻T1(攻撃不可)×activeが次ターン確殺圏なら、activeへの貼りは失われる
            # =ベンチの同候補を優先(人間レビュー17巡目 lucario-2 T1: Cosmic Beam 70が
            # Staryu 70にちょうど致死なのにactiveへ貼りT2に喪失→回収に夜のタンカ1枚を費消)
            act_doomed_t1 = 0
            if op.in_play_area == AreaType.ACTIVE:
                cur_k = self._cur or {}
                if (cur_k.get("turn") == 1 and cur_k.get("yourIndex") == cur_k.get("firstPlayer")):
                    act_k = (me.get("active") or [None])[0]
                    if act_k and (act_k.get("hp") or 0) <= self._incoming_next_turn(act_k):
                        act_doomed_t1 = 1
            key = (1 if rule > 0 else 0,
                   comp,
                   rule,
                   1 if target in self.plan.attackers else 0,
                   0 if act_doomed_t1 else 1,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if self.plan.avoid_overstack:
                # 将来価値の低い投資先を後回し(汎用原則: エネは死ぬ前に価値を生む場所へ)。
                #   ①飽和(最大技コスト充足済) ②死亡濃厚なactive(既存Analyzer can_ko_me)かつ
                #     このattachが今ターンより強い技を解放しない(解放するなら注いで良い=Ignition→Nebula等)。
                # 全員低価値なら従来通り付ける。実ラダー監査: 32敗中28局面が"死にゆくactiveへのエネ注ぎ"。
                key = (0 if self._low_future_value(target, me, op, energy) else 1,) + key
            if key > best_key:
                best_key, best = key, i
        return best  # None なら良い付け先なし → 付けずに次フェーズへ

    def _energy_provides_syms(self, eid):
        """エネカードが供給する型記号(基本エネ={X}1個, volatile(イグニ)=C3, その他type欄から)。"""
        import re
        ci = self._cardinfo.get(eid)
        if not ci:
            return []
        syms = re.findall(r"\{([A-Z])\}", ci.type or "") or re.findall(r"\{([A-Z])\}", ci.name or "")
        if syms:
            return syms
        return ["C", "C", "C"] if eid in self.plan.volatile_energies else ["C"]

    def _completes_cost(self, energy_id, target_id, sp) -> int:
        """このエネが対象の最大ダメージ技の未充足コストを進めるか(1/0)。
        2色コスト(Phantom Dive={R}{P}等)で同型の重ね貼り(R+R)を防ぐ
        (人間レビュー10巡目: dragapult相手botがP在手でRを重ねて技が撃てず)。"""
        import re
        info = self._cardinfo.get(target_id)
        if not info or not sp:
            return 0
        att = []
        for ec in (sp.get("energyCards") or []):
            att += self._energy_provides_syms(ec.get("id"))
        best = None
        for m in info.moves:
            if not m.damage:
                continue
            mt = re.match(r"(\d+)", str(m.damage))
            if mt and (best is None or int(mt.group(1)) > best[0]):
                best = (int(mt.group(1)), m.cost or "")
        if not best:
            return 0
        need_spec = re.findall(r"\{([A-Z])\}", best[1])
        n_any = best[1].count("●")
        pool = list(att)
        remaining = []
        for t in need_spec:
            if t in pool:
                pool.remove(t)
            else:
                remaining.append(t)
        any_left = max(0, n_any - len(pool))
        # energy_id=None は「追加なしで既に最大技が払えるか」の問い(前進ゲート①)
        mine = self._energy_provides_syms(energy_id) if energy_id is not None else []
        if energy_id is not None:
            progresses = any(t in remaining for t in mine) or (any_left > 0 and bool(mine))
            if not progresses:
                return 0
        # この1枚で最大技が完成する(=今すぐ/次の攻撃が立つ)なら最上位
        m2 = list(mine)
        rem2 = []
        for t in remaining:
            if t in m2:
                m2.remove(t)
            else:
                rem2.append(t)
        left2 = max(0, any_left - len(m2))
        if not rem2 and left2 == 0:
            return 2
        return 1 if energy_id is not None else 0

    def _attack_prizes_now(self, extra_energy_id=None) -> int:
        """このターンの攻撃(手貼り込み)で取れるサイドの最大(相手active KO + スプラッシュKO)。
        wins_now判定はactive KOだけでなくスプラッシュの1枚も数える(人間レビュー19巡目
        alakazam T13: 残1でJettingスプラッシュ50=Abra50 KO=勝利を見ずに退避した)。"""
        import re
        cur = self._cur or {}
        me = self._me() or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        oa = (opp.get("active") or [None])[0]
        act = (me.get("active") or [None])[0]
        if not act or not oa:
            return 0
        info = self._cardinfo.get(act.get("id"))
        if not info:
            return 0
        att = []
        for ec in (act.get("energyCards") or []):
            att += self._energy_provides_syms(ec.get("id"))
        if extra_energy_id is not None:
            pools = [att + self._energy_provides_syms(extra_energy_id)]
        else:
            pools = [list(att)]
            if not cur.get("energyAttached"):
                for c in (me.get("hand") or []):
                    if self._is_energy(c.get("id")):
                        pools.append(att + self._energy_provides_syms(c.get("id")))
        best_total = 0
        for m in info.moves:
            mt = re.match(r"(\d+)", str(m.damage or ""))
            if not mt:
                continue
            need = re.findall(r"\{([A-Z])\}", m.cost or "")
            n_any = (m.cost or "").count("●")
            payable = False
            for pool0 in pools:
                pool = list(pool0)
                if all((t in pool and (pool.remove(t) or True)) for t in need) and len(pool) >= n_any:
                    payable = True
                    break
            if not payable:
                continue
            total = 0
            if self._eff_dmg(int(mt.group(1)), False, oa.get("id")) >= (oa.get("hp") or 9999):
                total += self._prize_value(oa.get("id"))
            sp_mt = re.search(r"does (\d+) damage to 1 of your opponent[’']s Benched", m.effect or "")
            spread = int(sp_mt.group(1)) if sp_mt else 0
            if spread:
                bs = 0
                for sp in opp.get("bench") or []:
                    if (sp and not self._bench_damage_immune(sp.get("id"))
                            and (sp.get("hp") or 9999) <= spread):
                        bs = max(bs, self._prize_value(sp.get("id")))
                total += bs
            best_total = max(best_total, total)
        return best_total

    def _opp_bench_charged(self) -> bool:
        """相手ベンチに現在の付きエネで攻撃を払える後続が居るか。居なければ相手activeの
        KOで脅威は一旦消える(=死んだら負けでも残ってKOする価値がある)。"""
        cur = self._cur or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        return any(sp and self._move_payable(sp) for sp in opp.get("bench") or [])

    def _is_loss_bait(self, sp) -> bool:
        """このスポットを前に出すと「KO=相手の残サイド充足(死んだら負け)×確殺圏」になるか。
        今KOを取れる(脅威側が消える)なら免除。全前進経路(switch/reposition/eager/昇格/進化)の
        共通判定(人間レビュー15巡目: ゲートごとの個別実装が相互作用の残差を生んだ)。"""
        if not sp:
            return False
        pr = self.analyze_prize()
        opp_left = pr.get("opp_prizes") or 6
        if self._prize_value(sp.get("id")) < opp_left:
            return False
        if (sp.get("hp") or 0) > self._incoming_next_turn(sp):
            return False
        return not self._spot_kos_opp_active(sp)

    def _spot_kos_opp_active(self, sp) -> bool:
        """このスポットが(前に出れば)現在の付きエネで相手activeをKOできるか。"""
        import re
        cur = self._cur or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        oa = (opp.get("active") or [None])[0]
        info = self._cardinfo.get(sp.get("id")) if sp else None
        if not oa or not info:
            return False
        att = []
        for ec in (sp.get("energyCards") or []):
            att += self._energy_provides_syms(ec.get("id"))
        best = 0
        for m in info.moves:
            need = re.findall(r"\{([A-Z])\}", m.cost or "")
            pool = list(att)
            ok = True
            for t in need:
                if t in pool:
                    pool.remove(t)
                else:
                    ok = False
                    break
            if not ok or len(pool) < (m.cost or "").count("●"):
                continue
            mt = re.match(r"(\d+)", str(m.damage or ""))
            if mt:
                best = max(best, self._eff_dmg(int(mt.group(1)), False, oa.get("id")))
        return best >= (oa.get("hp") or 9999)

    def _move_payable(self, sp, extra_energy_id=None) -> bool:
        """このスポットが(任意でextraを1枚貼れば)いずれかの攻撃を払えるか。
        前進ゲート用: 「最大技の完成」でなく「殴れるか」(安い技でも前進の価値はある)。"""
        import re
        info = self._cardinfo.get(sp.get("id")) if sp else None
        if not info:
            return False
        att = []
        for ec in (sp.get("energyCards") or []):
            att += self._energy_provides_syms(ec.get("id"))
        if extra_energy_id is not None:
            att += self._energy_provides_syms(extra_energy_id)
        for m in info.moves:
            if not m.damage:
                continue
            need = re.findall(r"\{([A-Z])\}", m.cost or "")
            n_any = (m.cost or "").count("●")
            pool = list(att)
            ok = True
            for t in need:
                if t in pool:
                    pool.remove(t)
                else:
                    ok = False
                    break
            if ok and len(pool) >= n_any:
                return True
        return False

    def _basic_attach_suffices(self, me, op, hand) -> bool:
        """volatile(イグニ等)でなく手札の基本エネ1枚で、attach対象の最大コスト技が今ターン払えるか。
        払えるなら恒久エネの方が価値が高い(番末に消えず、次ターン以降も貼り直しなしで技が打てる)。"""
        import re
        target = self._target_id(me, op.in_play_area, op.in_play_index)
        info = self._cardinfo.get(target)
        if not info:
            return False
        spots = (me.get("active") if op.in_play_area == AreaType.ACTIVE else me.get("bench")) or []
        sp = (spots[op.in_play_index]
              if op.in_play_index is not None and 0 <= op.in_play_index < len(spots) else None)
        if not sp:
            return False
        perm = sum(1 for e in (sp.get("energyCards") or [])
                   if e.get("id") not in self.plan.volatile_energies)
        need = max((len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
                    for m in info.moves if m.damage), default=0)
        if need == 0 or perm + 1 < need:
            return False
        return any(self._is_energy(c.get("id"))
                   and c.get("id") not in self.plan.volatile_energies
                   and self._energy_rule_rank(c.get("id"), target) > 0
                   for c in (hand or []))

    def _low_future_value(self, target_id, me, op, energy_id) -> bool:
        """エネ投資先の将来価値が低いか(avoid_overstackの一般化)。
        ①飽和 ②死亡濃厚active(can_ko_me=既存Analyzer。Boss/ケープ/回復の不確実性があるため
          "確定"でなく相手現ライン火力ベースの高確率判定) かつ 今ターンより強い技を解放しない。
        例外=解放する場合(Ignition{C}{C}{C}でNebula解放等)は「死ぬ前に価値を生む」ので注いで良い。"""
        if self._is_saturated(target_id, me, op):
            return True
        if op.in_play_area != AreaType.ACTIVE:
            return False
        th = self.analyze_threat()
        if not th.get("can_ko_me"):
            return False
        # このattachで「今払えないより強い技」が払えるようになるか(コスト数ベース)
        spots = me.get("active") or []
        idx = op.in_play_index
        sp = spots[idx] if (idx is not None and 0 <= idx < len(spots)) else None
        if sp is None:
            return True
        cur_e = len(sp.get("energyCards") or [])
        e_info = self._cardinfo.get(energy_id)
        provides = max(1, (e_info.type or "").count("{")) if e_info else 1   # Ignition {C}{C}{C}=3
        info = self._cardinfo.get(target_id)
        best_now = 0; best_unlocked = 0
        for mv in (info.moves if info else ()):  # noqa
            if (mv.name or "").startswith("[Ability]") or mv.cost is None:
                continue
            cost = mv.cost.count("{") + mv.cost.count("●")
            try:
                dmg = int(str(mv.damage or "0").rstrip("+×x"))
            except ValueError:
                dmg = 0
            if cost <= cur_e:
                best_now = max(best_now, dmg)
            elif cost <= cur_e + provides:
                best_unlocked = max(best_unlocked, dmg)
        return best_unlocked <= best_now      # 解放なし=死にゆくactiveへの注ぎ=低価値

    def _is_saturated(self, target_id, me, op) -> bool:
        """対象が最大技コストぶんのエネを既に持つか(avoid_overstack用)。技情報が無ければ False。"""
        info = self._cardinfo.get(target_id)
        if not info or not info.moves:
            return False
        need = 0
        for mv in info.moves:
            if (mv.name or "").startswith("[Ability]") or mv.cost is None:
                continue
            need = max(need, mv.cost.count("{") + mv.cost.count("●"))
        if need <= 0:
            return False
        spots = (me.get("active") if op.in_play_area == AreaType.ACTIVE else me.get("bench")) or []
        idx = op.in_play_index
        sp = spots[idx] if (idx is not None and 0 <= idx < len(spots)) else None
        return sp is not None and len(sp.get("energyCards") or []) >= need

    def _energy_rule_rank(self, energy, target) -> int:
        # energy_rules の上にあるものほど高ランク
        rules = self.plan.energy_rules
        for k, (eid, tid) in enumerate(rules):
            if (eid is None or energy == eid) and target == tid:
                return len(rules) - k
        return 0

    # ===== 攻撃 =====
    def _filter_gun_loading(self, idxs, options):
        """「この攻撃で相手のダメカン×N技が自分のactiveの致死圏に入る(攻撃前は圏外)」
        非KO攻撃を除外して返す。KOする攻撃・非装填攻撃はそのまま。"""
        import re
        cur = self._cur or {}
        me = self._me() or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        oa = (opp.get("active") or [None])[0]
        act = (me.get("active") or [None])[0]
        if not oa or not act or self._prize_value(act.get("id")) < 2:
            return idxs
        # 相手active(進化前スタック込み)のダメカン×N技で、次ターン払えるもの
        oi = self._cardinfo.get(oa.get("id"))
        moves = list(oi.moves) if oi else []
        for pe in (oa.get("preEvolution") or []):
            pi_ = self._cardinfo.get((pe or {}).get("id"))
            if pi_:
                moves += list(pi_.moves)
        oe = len(oa.get("energyCards") or []) + 1
        gun = None
        for m in moves:
            mt = re.search(r"does (\d+) more damage for each damage counter on this", m.effect or "")
            if not mt:
                continue
            need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
            if need > oe:
                continue
            base_m = re.match(r"(\d+)", str(m.damage or ""))
            gun = (int(base_m.group(1)) if base_m else 0, int(mt.group(1)))
        if gun is None:
            return idxs
        base, per = gun
        hp_o = oa.get("hp") or 0
        max_o = oa.get("maxHp") or 0
        act_hp = act.get("hp") or 0
        pre_th = base + per * max(0, (max_o - hp_o) // 10)
        if pre_th >= act_hp:
            return idxs                    # 既に圏内=装填の概念なし(退避系ゲートの領分)
        out = []
        for i in idxs:
            dmg = self._dmg(options[i]) or 0
            eff = self._eff_dmg(dmg, False, oa.get("id"))
            if eff >= hp_o:
                out.append(i)              # KO=装填ごと除去
                continue
            post_th = base + per * max(0, (max_o - (hp_o - eff)) // 10)
            if post_th < act_hp:
                out.append(i)              # 撃っても圏外のまま
        return out

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

    def _dead_by_partner(self, effect_text: str) -> bool:
        """技の効果文が要求する相方(『ベンチに X が居ないと何もしない』)が自ベンチ不在＝技が死んでいるか。
        例: ソルロック Cosmic Beam はルナトーン不在だと0ダメ(人間レビュー2巡目で発覚した理解漏れ)。"""
        import re
        m = re.search(r"don[’']t have ([\w\s.'’-]+?) on your Bench, this attack does nothing",
                      effect_text or "")
        if not m:
            return False
        need = m.group(1).strip()
        cur = self._cur
        if not cur:
            return True
        me = cur["players"][self._me_index()]
        for b in (me.get("bench") or []):
            if b:
                ci = self._cardinfo.get(b.get("id"))
                if ci and ci.name == need:
                    return False
        return True

    def _dmg(self, op: Option) -> int:
        if op.attack_id is None:
            return 0
        if self._dead_by_partner(self._atk_texts().get(op.attack_id, "")):
            return 0                                   # 条件未成立=この技は何もしない
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

    def _me_index(self) -> int:
        """Analyzer/評価器の"自分"の視点。Search中は root視点(self._eval_player)に固定、通常は現手番。
        ＝ENDで手番が相手に移った状態でも root視点で評価できる(視点フリップバグの修正)。"""
        if self._eval_player is not None:
            return self._eval_player
        return (self._cur or {}).get("yourIndex", 0)

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
        me = cur["players"][self._me_index()]
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
        # ③ 主役(進化形優先→前段)のエネ不足。※攻撃役が場に無い時は0(不足なし)でなく need(満額不足)。
        #   0にすると「エネを乗せる攻撃役が居ない」状態が「エネ充足」と誤読され、ENDが好調に見えるバグになる。
        body = (evolved_in_play or basic_in_play or [None])[0]
        if body:
            short = max(0, need - len(body.get("energyCards") or []))
        else:
            short = need
        out["energy_short"] = short
        if short > 0:
            out["priority"].append("energy")
        out["ready"] = (not out["attacker_short"]) and (not evolved_ids or bool(evolved_in_play)) and out["energy_short"] == 0
        return out

    def analyze_threat(self) -> dict:
        """相手の脅威診断（情報のみ・スコア無し）。相手が自分の活性をどれだけ削れるか/KOされるか。
        Analyzer層の一部。Turn Evaluator が Attack/Development/Threat/Prize を統合して判断する。"""
        out = {"opp_line_damage": 0, "can_ko_me": False, "my_active_hp": 0, "hits_to_lose": 99}
        cur = self._cur
        if not cur or not cur.get("players"):
            return out
        oi = self._me_index()
        me = cur["players"][oi]; opp = cur["players"][1 - oi]
        opp_a = (opp.get("active") or [None])[0]; my_a = (me.get("active") or [None])[0]
        if not opp_a or not my_a:
            return out
        dmg = _line_threat(opp_a.get("id"))              # 相手の進化含む最大火力
        mc = self._cardinfo.get(my_a.get("id")); oc = self._cardinfo.get(opp_a.get("id"))
        # 効果文の可変ダメージ(Powerful Hand=手札枚数×等)はline_threat(静的)に乗らない=実数で補完
        for m in (oc.moves if oc else []):
            dmg = max(dmg, self._effect_move_damage(m, my_a, opp_a))
        if mc and oc and mc.weakness and oc.type == mc.weakness:
            dmg *= 2                                      # 自分の弱点で2倍
        # 現実的次ターン評価(進化1段・可変ダメ・ベンチ装填銃・進化前スタック込み)とのmax。
        # activeのKadabra(30)しか見ずベンチのAlakazam PH 360を見落とし、can_ko_me偽陰性で
        # 死にゆくactiveへエネ投資(人間レビュー20巡目 alakazam T11)
        dmg = max(dmg, self._incoming_next_turn(my_a))
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
        oi = self._me_index()
        # ※ `len(...) or 6` は禁物: サイドを全取得した勝者(残0枚)が「6枚残り」扱いになり
        #   勝った終局ほど評価が悪化する反転バグになる(実測: 勝者視点-22 vs 敗者視点+244)。
        _mp = cur["players"][oi].get("prize")
        _op = cur["players"][1 - oi].get("prize")
        myp = len(_mp) if _mp is not None else 6
        opz = len(_op) if _op is not None else 6
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
        me = cur["players"][self._me_index()] if (cur and cur.get("players")) else {}
        return {
            "is_attacker": is_atk,
            "is_evolved_attacker": is_evo_atk,
            "recovery_possible": bool(is_evo_atk and need["evolution_short"] and need["attacker_short"] == 0),
            "bench_thin": len([b for b in (me.get("bench") or []) if b]) < 3,
        }

    def analyze_phase(self) -> dict:
        """局面の"事実(features)"のみ返す（Fact）。opening/mid/end の判定はしない＝それはOpinion(Turn Evaluatorの責務)。
        turn / 残りサイド / 攻撃役数 / 進化済み攻撃役数 / 盤面エネ数。"""
        out = {"turn": 0, "my_prizes": 6, "opp_prizes": 6, "my_attackers": 0, "my_evolved": 0,
               "opp_evolved": 0, "my_energy": 0, "opp_energy": 0}
        cur = self._cur
        if not cur or not cur.get("players"):
            return out
        oi = self._me_index(); me = cur["players"][oi]; opp = cur["players"][1 - oi]
        atk = set(self.plan.attackers)
        ma = mevo = me_e = 0
        for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if not s:
                continue
            me_e += len(s.get("energyCards") or [])
            if s.get("id") in atk:
                ma += 1
                if not getattr(self._cardinfo.get(s.get("id")), "is_basic", True):
                    mevo += 1
        oevo = oe = 0
        for s in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if not s:
                continue
            oe += len(s.get("energyCards") or [])
            if not getattr(self._cardinfo.get(s.get("id")), "is_basic", True):
                oevo += 1
        _mp = me.get("prize"); _op = opp.get("prize")   # 残0枚を6扱いにしない(analyze_prizeと同じ反転バグ回避)
        out.update(turn=cur.get("turn", 0), my_prizes=(len(_mp) if _mp is not None else 6),
                   opp_prizes=(len(_op) if _op is not None else 6), my_attackers=ma, my_evolved=mevo,
                   opp_evolved=oevo, my_energy=me_e, opp_energy=oe)
        return out

    def check_invariants(self) -> list:
        """Analyzer同士の整合性(Invariant)を自己検知する。事実層が"ルール違反"を自分で見つける。
        レビューで人間が気づく前に、Analyzerが矛盾した事実を返したら即検出する
        （例: 攻撃役が場に無いのに energy_short=0 ＝今回のバグ）。返り値=違反メッセージのリスト(空=健全)。
        提出botを壊さないため assert で落とさず違反を返す（テスト/デバッグ側が判定）。"""
        v = []
        dv = self._analyze_development(); th = self.analyze_threat()
        pr = self.analyze_prize(); ph = self.analyze_phase()
        need = self.plan.setup_energy or 3
        # --- Development ---
        if not (0 <= dv["energy_short"] <= need):
            v.append(f"energy_short={dv['energy_short']} が範囲[0,{need}]外")
        if dv["ready"] and dv["attacker_short"]:
            v.append("ready=True なのに attacker_short>0（攻撃役なしでready）")
        if dv["ready"] and dv["energy_short"]:
            v.append(f"ready=True なのに energy_short={dv['energy_short']}")
        if dv["ready"] and dv["evolution_short"]:
            v.append("ready=True なのに evolution_short>0")
        # 今回のバグ: 攻撃役が場に無いのに energy_short=0（"エネ充足"と誤読）
        cur = self._cur
        if cur and cur.get("players") and self.plan.attackers:
            me = cur["players"][self._me_index()]
            in_play = [s for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s]
            if not any(s.get("id") in set(self.plan.attackers) for s in in_play) and dv["energy_short"] == 0:
                v.append("攻撃役が場に無いのに energy_short=0（=今回修正したバグの再発）")
        # --- Threat ---
        if th["can_ko_me"] and th["hits_to_lose"] != 1:
            v.append(f"can_ko_me=True なのに hits_to_lose={th['hits_to_lose']}(≠1)")
        if (not th["can_ko_me"]) and th["opp_line_damage"] > 0 and th["my_active_hp"] > 0 and th["hits_to_lose"] < 2:
            v.append(f"can_ko_me=False なのに hits_to_lose={th['hits_to_lose']}(<2)")
        if th["hits_to_lose"] < 1:
            v.append(f"hits_to_lose={th['hits_to_lose']} <1")
        # --- Prize ---
        if pr["prize_diff"] != pr["opp_prizes"] - pr["my_prizes"]:
            v.append("prize_diff が opp_prizes-my_prizes と不一致")
        # --- Phase ---
        if ph["my_evolved"] > ph["my_attackers"]:
            v.append(f"my_evolved={ph['my_evolved']} > my_attackers={ph['my_attackers']}")
        return v

    def evaluate_position(self) -> float:
        """状態評価器(State→スカラー): 今の盤面の良さ。Analyzer(Development/Threat/Prize)を統合。
        Resolver/Search/Explain が共有する共通の"局面価値"。デッキ名・カード名は見ない＝Universal。
        育成進捗＋攻撃準備＋実効耐久(被KO)＋サイド差 で構成。将来 Tempo 等を加える。"""
        dv = self._analyze_development(); th = self.analyze_threat(); pr = self.analyze_prize()
        need = self.plan.setup_energy or 3
        score = pr["prize_diff"] * 40.0                                   # サイド先行=+ (KO=離散イベントなので階段でよい)
        # 攻撃準備は連続値(エネ進捗)で。+100の二値階段を避けSearchを滑らかに。readyは小ボーナスのみ。
        ep = max(0.0, min(1.0, (need - dv["energy_short"]) / need)) if need else 0.0
        score += ep * 80.0 + (20.0 if dv["ready"] else 0.0)
        score -= dv["evolution_short"] * 25 + dv["attacker_short"] * 40   # 育成不足=-
        # 脅威は連続な hits_to_lose 主体に(can_ko_meの-50二値は撤廃)。耐えるほど+。
        score += min(th["hits_to_lose"], 6) * 14
        return round(score, 1)

    def evaluate_decision(self, obs_dict, first_idx, root_player, seed=0):
        """OSカーネル: 初手(first_idx=Decisionの最初の選択)を実行し、以降ヒューリスティックで root_player の
        ターンを終端まで"完成"させ、root視点で局面評価して TurnResult{position, decision} を返す。
        全候補(END含む)が同じ経路を通る＝ENDを特別扱いしない。視点はroot固定(フリップバグ回避)。
        Search/Resolver/Plan がこのAPIを共有する共通カーネル。"""
        import dataclasses as _dc, random
        from collections import Counter as _C
        from cg.api import search_begin, search_step, search_end, to_observation_class
        raw = obs_dict.get("current")
        if not raw or self.deck_counts is None:
            return None
        o = to_observation_class(obs_dict); oi = raw["yourIndex"]
        me = raw["players"][oi]; op = raw["players"][1 - oi]
        rem = _C(self.deck_counts) - _C([c["id"] for c in (me.get("hand") or []) + (me.get("discard") or [])])
        for sp in (me.get("active") or []) + (me.get("bench") or []):
            if sp:
                rem[sp["id"]] -= 1
                for k in ("preEvolution", "energyCards", "tools"):
                    for cc in sp.get(k) or []:
                        rem[cc["id"]] -= 1
        pool = []
        for cid, n in rem.items():
            pool += [cid] * max(0, n)
        random.Random(seed).shuffle(pool)
        dc = me["deckCount"]; pc = len(me["prize"])
        if len(pool) < dc + pc:
            pool += [3] * (dc + pc - len(pool))
        fil = lambda n: [(8 if i % 3 == 0 else 3) for i in range(n)]
        oa = [] if (op["active"] and op["active"][0]) else [8]
        saved_cur = self._cur
        # rollout中の self.select は _opp_seen/_matchup/plan を書き換える(マッチアップ検出)。
        # 決定化された仮想の相手カードで汚染すると実戦の判断が狂うため、丸ごと退避→復元する。
        saved_opp_seen = set(self._opp_seen); saved_matchup = self._matchup; saved_plan = self.plan
        try:
            state = search_begin(o, pool[:dc], pool[dc:dc + pc], fil(op["deckCount"]),
                                 fil(len(op["prize"])), fil(op["handCount"]), oa, False)
        except Exception:
            return None
        pos = None
        try:
            state = search_step(state.searchId, [first_idx])       # Decisionの最初の選択
            for _ in range(40):                                    # 以降ヒューリスティックで自ターン完成
                ob = state.observation; c = ob.current
                if c is None or c.result != -1:
                    break
                if c.yourIndex != root_player:                     # 自ターン終了＝Decision Complete
                    break
                if ob.select is None or not ob.select.option:
                    break
                sel = self.select(Observation.from_dict(_dc.asdict(ob))) or [0]
                state = search_step(state.searchId, sel)
            fc = state.observation.current
            comp = None
            if fc is not None:
                self._cur = _dc.asdict(fc); self._eval_player = root_player   # root視点で最終局面を評価
                pos = self.evaluate_position()
                pr = self.analyze_prize(); th = self.analyze_threat(); dv = self._analyze_development()
                comp = {"prize": pr["prize_diff"], "hits_to_lose": min(th["hits_to_lose"], 6),
                        "energy_short": dv["energy_short"], "evolution_short": dv["evolution_short"],
                        "ready": int(dv["ready"])}
        finally:
            self._eval_player = None
            self._cur = saved_cur
            self._opp_seen = saved_opp_seen; self._matchup = saved_matchup; self.plan = saved_plan
            try:
                search_end()
            except Exception:
                pass
        return {"position": pos, "decision": first_idx, "comp": comp} if pos is not None else None

    def evaluate_plan(self, obs_dict, first_idx, root_player, horizon=3, seeds=(7, 17, 29),
                      record_chain=False, opponent=None, opp_decklist=None):
        """Plan AI (Episode 1): 初手(first_idx)を実行し、root_player の複数ターン先(horizon)まで
        自己trajectoryを延長して"各自ターン終端の position 軌跡"を返す。
        設計(明示): 相手ターンは最小行動(END/強制先頭)で通す=相手の攻めは入れず、まず
          「自分の複数ターン育成計画」の良さを測る(相手の本格rolloutは Episode 2)。相手の脅威は
          静的な analyze_threat 経由で position に反映される。
        未来ドローのノイズは複数determinization(seeds)平均で低減。各自ターン終端で check_invariants を
        回し「でたらめな未来でない」ことをOSが自己検知(Plan健全性)。
        返り値: {terminal, trajectory:[t1..tH](seed平均), n_seeds, invariant_violations}。"""
        import dataclasses as _dc, random
        from collections import Counter as _C
        from cg.api import search_begin, search_step, search_end, to_observation_class
        from cabt_bot.enums import OptionType as _OT
        _END = int(_OT.END)
        _ACT = {int(_OT.PLAY): "PLAY", int(_OT.EVOLVE): "EVOLVE", int(_OT.ATTACH): "ATTACH",
                int(_OT.ATTACK): "ATTACK", int(_OT.ABILITY): "ABILITY"}   # Decision Chain記録対象
        raw = obs_dict.get("current")
        if not raw or self.deck_counts is None:
            return None
        o = to_observation_class(obs_dict); oi = raw["yourIndex"]
        if oi != root_player:
            return None
        me = raw["players"][oi]; op = raw["players"][1 - oi]
        base_rem = _C(self.deck_counts) - _C([c["id"] for c in (me.get("hand") or []) + (me.get("discard") or [])])
        for sp in (me.get("active") or []) + (me.get("bench") or []):
            if sp:
                base_rem[sp["id"]] -= 1
                for k in ("preEvolution", "energyCards", "tools"):
                    for cc in sp.get(k) or []:
                        base_rem[cc["id"]] -= 1
        fil = lambda n: [(8 if i % 3 == 0 else 3) for i in range(n)]
        dc = me["deckCount"]; pc = len(me["prize"])

        def opp_min(ob):                                   # 相手は最小行動: 可能ならEND、強制選択は先頭
            for i, o_ in enumerate(ob.select.option):
                if getattr(o_, "type", None) == _END:
                    return [i]
            return [0]

        saved_cur = self._cur
        # evaluate_decision と同じ状態リーク対策(rollout中のselectによる _opp_seen/_matchup/plan 汚染を復元)
        saved_opp_seen = set(self._opp_seen); saved_matchup = self._matchup; saved_plan = self.plan
        trajectories = []; viol_total = 0; seed_terminal_comps = []; chain = []; cap_chain = []
        init_caps = None
        if record_chain:                                   # 決定"前"の能力集合(既存能力は新規獲得に数えない)
            self._cur = raw; self._eval_player = root_player
            dv0 = self._analyze_development(); ph0 = self.analyze_phase()
            init_caps = {"attacker": ph0["my_attackers"] >= 1, "evolved": ph0["my_evolved"] >= 1,
                         "energy": dv0["energy_short"] == 0 and ph0["my_attackers"] >= 1, "ready": bool(dv0["ready"])}
            self._eval_player = None; self._cur = saved_cur
        try:
            for seed in seeds:
                pool = []
                for cid, n in _C(base_rem).items():
                    pool += [cid] * max(0, n)
                random.Random(seed).shuffle(pool)
                if len(pool) < dc + pc:
                    pool += [3] * (dc + pc - len(pool))
                oa = [] if (op["active"] and op["active"][0]) else [8]
                # 相手の隠し札(山/サイド/手札): opp_decklist があれば既知デッキで determinize、無ければ filler
                if opp_decklist:
                    orem = _C(opp_decklist) - _C([c["id"] for c in (op.get("discard") or [])])
                    for sp in (op.get("active") or []) + (op.get("bench") or []):
                        if sp:
                            orem[sp["id"]] -= 1
                            for k in ("preEvolution", "energyCards", "tools"):
                                for cc in sp.get(k) or []:
                                    orem[cc["id"]] -= 1
                    opool = []
                    for cid, n in orem.items():
                        opool += [cid] * max(0, n)
                    random.Random(seed + 1).shuffle(opool)
                    odc = op["deckCount"]; opc = len(op["prize"]); ohc = op["handCount"]
                    if len(opool) < odc + opc + ohc:
                        opool += [3] * (odc + opc + ohc - len(opool))
                    o_deck = opool[:odc]; o_prize = opool[odc:odc + opc]; o_hand = opool[odc + opc:odc + opc + ohc]
                else:
                    o_deck = fil(op["deckCount"]); o_prize = fil(len(op["prize"])); o_hand = fil(op["handCount"])
                try:
                    state = search_begin(o, pool[:dc], pool[dc:dc + pc], o_deck, o_prize, o_hand, oa, False)
                except Exception:
                    continue
                traj = []; turns_done = 0; pending = [first_idx]; last_comp = None; prev_ms = None
                rec = record_chain and len(seeds) > 0 and seed == seeds[0]
                cap_prev = dict(init_caps) if (rec and init_caps) else None; attacked = False
                for _ in range(400):
                    ob = state.observation; c = ob.current
                    if c is None or c.result != -1:
                        break
                    if ob.select is None or not ob.select.option:
                        break
                    if c.yourIndex == root_player:
                        sel = pending if pending else (self.select(Observation.from_dict(_dc.asdict(ob))) or [0])
                        pending = None
                        if rec:                            # Decision Chain: root行動をカード名付きで記録
                            _si = sel[0] if sel else 0
                            if 0 <= _si < len(ob.select.option):
                                _opt = ob.select.option[_si]; _t = getattr(_opt, "type", None)
                                if _t in _ACT:
                                    _idx = getattr(_opt, "index", None)
                                    _hd = _dc.asdict(ob)["current"]["players"][root_player].get("hand") or []
                                    _cid = _hd[_idx]["id"] if (_idx is not None and 0 <= _idx < len(_hd)) else None
                                    _nm = self._cardinfo.get(_cid).name if _cid in self._cardinfo else ""
                                    chain.append(f"{_ACT[_t]}{(' '+_nm) if _nm else ''}")
                                    if _t == int(_OT.ATTACK):
                                        attacked = True
                        state = search_step(state.searchId, sel)
                        nc = state.observation.current
                        if nc is None:
                            break
                        ended = (nc.result != -1) or (nc.yourIndex != root_player)
                        if ended:                          # 自ターン終端(またはゲーム終了)=軌跡を1点記録
                            self._cur = _dc.asdict(nc); self._eval_player = root_player
                            traj.append(self.evaluate_position())
                            viol_total += len(self.check_invariants())
                            pr = self.analyze_prize(); th = self.analyze_threat()
                            dv = self._analyze_development(); ph = self.analyze_phase()
                            last_comp = {"prize_diff": pr["prize_diff"], "hits_to_lose": min(th["hits_to_lose"], 6),
                                         "energy_short": dv["energy_short"], "evolution_short": dv["evolution_short"],
                                         "ready": int(dv["ready"]), "attackers": ph["my_attackers"],
                                         "evolved": ph["my_evolved"], "energy": ph["my_energy"], "result": nc.result}
                            if rec:                        # マイルストーン: 決定が生んだ未来の状態変化
                                if prev_ms is not None:
                                    if prev_ms["evolution_short"] and not last_comp["evolution_short"]:
                                        chain.append("★線完成")
                                    if last_comp["prize_diff"] > prev_ms["prize_diff"]:
                                        chain.append(f"★サイド+{last_comp['prize_diff']-prev_ms['prize_diff']}")
                                    if last_comp["ready"] and not prev_ms["ready"]:
                                        chain.append("★攻撃準備")
                                if last_comp["result"] != -1:
                                    chain.append("★決着")
                                # Capability Chain(抽象・デッキ非依存): 決定が新規獲得した能力を依存順で
                                if cap_prev is not None:
                                    curr = {"attacker": last_comp["attackers"] >= 1,
                                            "evolved": last_comp["evolved"] >= 1,
                                            "energy": last_comp["energy_short"] == 0 and last_comp["attackers"] >= 1,
                                            "ready": last_comp["ready"] == 1}
                                    if curr["attacker"] and not cap_prev["attacker"]:
                                        cap_chain.append("攻撃役Exists")
                                    if curr["energy"] and not cap_prev["energy"]:
                                        cap_chain.append("エネReady")
                                    if curr["evolved"] and not cap_prev["evolved"]:
                                        cap_chain.append("進化Attacker")
                                    if curr["ready"] and not cap_prev["ready"]:
                                        cap_chain.append("攻撃Possible")
                                    if attacked:
                                        cap_chain.append("Attack")
                                    _pd = prev_ms["prize_diff"] if prev_ms else 0
                                    if last_comp["prize_diff"] > _pd:
                                        cap_chain.append(f"Prize+{last_comp['prize_diff']-_pd}")
                                    if last_comp["result"] != -1:
                                        cap_chain.append("Win" if last_comp["result"] == root_player else "Loss")
                                    cap_prev = curr
                                attacked = False
                                prev_ms = last_comp
                                chain.append(f"‖T+{turns_done+1}")
                            turns_done += 1
                            if nc.result != -1 or turns_done >= horizon:
                                break
                    else:                                  # 相手手番: opponent(薄い方策)が居ればそれ、無ければ最小行動
                        osel = (opponent.act(ob) if opponent is not None else opp_min(ob)) or [0]
                        state = search_step(state.searchId, osel)
                if traj:
                    trajectories.append(traj)
                    if last_comp is not None:
                        seed_terminal_comps.append(last_comp)
        finally:
            self._eval_player = None
            self._cur = saved_cur
            self._opp_seen = saved_opp_seen; self._matchup = saved_matchup; self.plan = saved_plan
            try:
                search_end()
            except Exception:
                pass
        if not trajectories:
            return None
        H = max(len(t) for t in trajectories)
        avg = [round(sum(t[i] for t in trajectories if len(t) > i) /
                     max(1, sum(1 for t in trajectories if len(t) > i)), 1) for i in range(H)]
        tcomp = None
        if seed_terminal_comps:                            # 終端事実(seed平均)=Plan Explain用
            keys = seed_terminal_comps[0].keys()
            tcomp = {k: round(sum(sc[k] for sc in seed_terminal_comps) / len(seed_terminal_comps), 1) for k in keys}
        return {"terminal": avg[-1], "trajectory": avg, "n_seeds": len(trajectories),
                "invariant_violations": viol_total, "terminal_comp": tcomp,
                "chain": chain, "cap_chain": cap_chain}

    @staticmethod
    def decision_diff(search_tr, heur_tr) -> dict:
        """DecisionDiff: Search と Heuristic の TurnResult の Component 差分(なぜ差がついたかの内訳)。
        position_delta と、prize/threat(hits_to_lose)/development(energy/evolution/ready) の各deltaを返す。"""
        if not search_tr or not heur_tr or not search_tr.get("comp") or not heur_tr.get("comp"):
            return {}
        s, h = search_tr["comp"], heur_tr["comp"]
        return {
            "position_delta": round(search_tr["position"] - heur_tr["position"], 1),
            "prize_delta": s["prize"] - h["prize"],
            "threat_delta": s["hits_to_lose"] - h["hits_to_lose"],
            "development_delta": (h["energy_short"] - s["energy_short"]) + (h["evolution_short"] - s["evolution_short"]) * 2 + (s["ready"] - h["ready"]) * 3,
        }

    def _estimate_phase(self, ph, dv) -> str:
        """フェーズ推定(Opinion・Turn Evaluator内)。事実(サイド/ターン/成熟度)から opening/mid/end を判断。"""
        if min(ph["my_prizes"], ph["opp_prizes"]) <= 2:
            return "end"
        # 盤面が未成熟(進化攻撃役が立っていない/攻撃役が薄い) かつ 序盤ターン → opening
        if ph["my_evolved"] == 0 and ph["turn"] <= 5 and not dv["ready"]:
            return "opening"
        return "mid"

    def evaluate_turn(self, attack_candidates=None) -> dict:
        """Turn Evaluator（唯一のOpinion層）: Analyzer群(Fact)を統合し、各行動の"機会(Opportunity)"スコアと
        ★その内訳(Explain)を返す。Actionは返さない。phase推定・Phase補正・各軸の重みはここだけ。
        Attack Opportunity は Attack Analyzer 候補集合(attack_candidates=[{damage,status,disrupt},...])の最良で評価。
        デッキ名・カード名は見ない＝Universal。Resolver も Search もこの評価器を共有する。"""
        ph = self.analyze_phase(); th = self.analyze_threat(); dv = self._analyze_development()
        phase = self._estimate_phase(ph, dv)
        W = {"opening": {"attack": 0.6, "develop": 1.4, "recover": 1.0, "disrupt": 0.8},
             "mid":     {"attack": 1.0, "develop": 1.0, "recover": 1.0, "disrupt": 1.0},
             "end":     {"attack": 1.3, "develop": 0.6, "recover": 1.1, "disrupt": 1.0}}[phase]
        if attack_candidates:
            atk_base = max((c.get("damage", 0) + c.get("status", 0) + c.get("disrupt", 0)) for c in attack_candidates)
        else:
            atk_base = 100 if dv["ready"] else 25
        dev_parts = {"attacker": dv["attacker_short"] * 45, "evolve": dv["evolution_short"] * 30,
                     "energy": dv["energy_short"] * 15}
        dev_base = 30 + sum(dev_parts.values())
        rec_base = 65 if (dv["attacker_short"] or (th["can_ko_me"] and not dv["ready"])) else 10
        dis_base = 25
        def opp(base, key, parts=None):
            e = {"score": round(base * W[key], 1), "base": round(base, 1), "phase_w": W[key]}
            if parts:
                e["parts"] = parts
            return e
        return {"phase": phase,
                "attack": opp(atk_base, "attack"),
                "develop": opp(dev_base, "develop", dev_parts),
                "recover": opp(rec_base, "recover"),
                "disrupt": opp(dis_base, "disrupt")}

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
            # 開幕active: 進化する土台(例:Makuhita/リオル)はベンチで育て、単独で殴れる
            # アタッカー(例:ソルロック)を前に(人間レビュー6巡目①: 手札順の先頭ではなく効果で選ぶ)。
            best_i, best_key = None, (-1, -1, -1)
            for i, op in enumerate(sel.options):
                cid = self._opt_card_id(op)
                if cid is None:
                    continue
                info = self._cardinfo.get(cid)
                if not info or not info.is_pokemon:
                    continue
                dmg = max((int(m.damage) for m in info.moves
                           if m.damage and str(m.damage).isdigit()), default=0)
                # 「土台を前に晒さない」を最優先(攻撃不能な非土台を前に置く方が、主力土台を
                # 晒すよりまし=arch: Relicanth前>Duraludon前)。次いでアタッカー・火力。
                key = (0 if self._is_evolving_base(cid) else 1,
                       1 if cid in self.plan.attackers else 0,
                       dmg)
                if key > best_key:
                    best_key, best_i = key, i
            if best_i is not None:
                return [best_i]
        # 回復(ミツル等)の対象選択: 最も重傷の攻撃役を回復(人間レビュー7巡目④)。
        cc = getattr(sel, "context_card", None)
        if cc is not None and getattr(cc, "card_id", None) in self.plan.heal_return_cards:
            best_i, best_key_h = None, (-1, -1)
            pr_h = self.analyze_prize()
            opp_left_h = pr_h.get("opp_prizes") or 6
            for i, op in enumerate(sel.options):
                me2 = self._me() or {}
                spots = (me2.get("active") if op.area == AreaType.ACTIVE else me2.get("bench")) or []
                sp = (spots[op.index] if op.index is not None and 0 <= op.index < len(spots) else None)
                if not sp:
                    continue
                d = (sp.get("maxHp") or 0) - (sp.get("hp") or 0)
                if sp.get("id") in self.plan.attackers:
                    d += 40                               # 攻撃役を優先
                # 負けベイト除去を最優先: 「KO=相手残サイド充足×確殺圏×回復で圏外化」の個体
                # (人間レビュー22巡目 arch T17: ダメージ量タイブレークが同点でactiveを選び、
                #  ベンチのボス釣り即負けベイトを残した)
                th_h = self._incoming_next_turn(sp)
                bait = (1 if (self._prize_value(sp.get("id")) >= opp_left_h
                              and (sp.get("hp") or 0) <= th_h < (sp.get("maxHp") or 0)) else 0)
                if (bait, d) > best_key_h:
                    best_key_h, best_i = (bait, d), i
            if best_i is not None:
                return [best_i]
        # 昇格/退避先(自分の新しいバトル場)選択: 相手の最大火力を1発耐える攻撃役を優先
        # (人間レビュー7巡目③: HP230のメガが居るのに壁や瀕死メガを前に出していた)。
        if (isinstance(ctx, SelectContext) and ctx in (SelectContext.TO_ACTIVE, SelectContext.SWITCH)
                and sel.options and all(getattr(o, "player_index", None) == (self._cur or {}).get("yourIndex")
                                        for o in sel.options)):
            best_i, best_key = None, None
            for i, op in enumerate(sel.options):
                me2 = self._me() or {}
                spots = (me2.get("active") if op.area == AreaType.ACTIVE else me2.get("bench")) or []
                sp = (spots[op.index] if op.index is not None and 0 <= op.index < len(spots) else None)
                if not sp:
                    continue
                th = self._incoming_threat(sp)
                pr = self.analyze_prize()
                loses_game = (self._prize_value(sp.get("id")) >= (pr.get("opp_prizes") or 6)
                              and (sp.get("hp") or 0) <= th)
                if loses_game and self._spot_kos_opp_active(sp):
                    loses_game = False   # 前に出て今KOできるなら脅威側が消える(ベイト扱いしない)
                info_p = self._cardinfo.get(sp.get("id"))
                base_sac = (info_p is not None and info_p.is_basic
                            and self._is_evolving_base(sp.get("id"))
                            and (sp.get("hp") or 0) <= th)
                key = (0 if loses_game else 1,                      # 次打KO=負け確定の昇格先を避ける
                       1 if (sp.get("hp") or 0) > th else 0,        # 1発耐える
                       0 if base_sac else 1,                        # 確定死圏の進化土台を避ける(線の保護)
                       # 全候補が土台犠牲なら線価値の低い方を犠牲に(主力線=Grimm180の土台でなく
                       # 弱線=Froslass60の土台を差し出す。人間レビュー21巡目 grimmsnarl相手bot T10)
                       -(_line_threat(sp.get("id")) or 0) if base_sac else 0,
                       1 if sp.get("id") in self.plan.attackers else 0,
                       len(sp.get("energyCards") or []),
                       sp.get("hp") or 0)
                if best_key is None or key > best_key:
                    best_key, best_i = key, i
            if best_i is not None:
                return [best_i]
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
                and not (act.get("energyCards") or [])):
            if any((d.get("id") or 99) < 10 for d in discard):  # 基本エネ(小ID)
                return True
        return False

    def _should_switch(self) -> bool:
        """入替系: ①バトル場が攻撃役でなくベンチに攻撃役が居る(前進) ②前の攻撃役が被KO確定圏で
        ベンチに満タンの進化攻撃役が居る(温存=退けて守る)。②は常設エネ投資なし×このターン攻撃を
        失わない(手貼り権+手札エネ)場合のみ(人間レビュー3巡目③: 120HPのメガを晒して喪失の修正)。"""
        me = self._me()
        if not me or not self.plan.attackers:
            return False
        act = (me.get("active") or [None])[0]
        if not act:
            return False
        cur = self._cur or {}
        # 敗北回避オーバーライド: このactiveのKO=相手の残りサイド充足(死んだら負け)なら、
        # エネ投資もこのターンの攻撃テンポも無関係(負ければ全て無価値)。「今殴れば自分が
        # 勝ち切れる」場合だけ殴る。壁(非攻撃役)にも適用。(自己レビュー: arch-7 T17
        # Mega110=3枚を220の前に残して敗北。Switch→ケープCinderace260なら拒否できた)
        pr = self.analyze_prize()
        opp_left = pr.get("opp_prizes") or 6
        if (self._prize_value(act.get("id")) >= opp_left
                and (act.get("hp") or 0) <= self._incoming_next_turn(act)):
            dmg, ign = self._active_attack_potential(assume_hand_attach=True)
            opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
            oa = (opp.get("active") or [None])[0]
            ko_now = (oa and dmg > 0
                      and self._eff_dmg(dmg, ign, oa.get("id")) >= (oa.get("hp") or 9999))
            wins_now = self._attack_prizes_now() >= (pr.get("my_prizes") or 6)
            if ko_now and self._post_ko_threat(act) < (act.get("hp") or 0):
                wins_now = True    # KOで脅威が消える(KO後の残存脅威<自HP)=残って殴る
            if not wins_now:
                for sp in me.get("bench") or []:
                    if not sp:
                        continue
                    if (self._prize_value(sp.get("id")) < opp_left
                            or (sp.get("hp") or 0) > self._incoming_next_turn(sp)):
                        return True   # 死んでも負けない/次打(現実的評価)を耐える退避先がある
        if act.get("id") in self.plan.attackers or (_line_threat(act.get("id")) or 0) >= 180:
            # 温存パス: 次の相手ターンにKO確定圏(現実的評価=相手の現エネ+1で払える技)なら、
            # 対象はplan.attackersまたはライン180+の主役級(planに列挙されない主役=Hariyama等を
            # 取りこぼさない。検出器と同一意味論)。
            # 満タンの後続に交代して前を守る。ライン最大(潜在)基準だと過剰退避になり
            # SwitchWaste(検出器=現実的評価)と不整合(QA lucario相手bot T12)。
            if (act.get("hp") or 0) > self._incoming_next_turn(act):
                return False
            # ※Switch札はエネを付けたまま交代する(退却と違い投資は失われない)ため
            # 「常設エネ投資あり」でブロックしない(人間レビュー19巡目 arch T11: W1枚を理由に
            # 温存拒否→330の体から同じNebulaを撃てたのに110のMegaで殴って3枚献上=敗着)
            # このターンの攻撃を失わないこと。前が攻撃可能なら、交代後も攻撃できる(手貼り権+手札エネ)
            # 時のみ。前がどうせ攻撃不可(エネ0×手札エネ0等)なら失う攻撃が無い=温存だけで交代してよい
            # (QA: 手札エネ0の被KO圏放置4件の修正)。
            dmg, _ = self._active_attack_potential(assume_hand_attach=True)
            if dmg > 0 and (cur.get("energyAttached") or not any(
                    self._is_energy(c.get("id")) for c in (me.get("hand") or []))):
                return False
            for sp in me.get("bench") or []:
                if not sp or sp.get("id") not in self.plan.attackers:
                    continue
                info = self._cardinfo.get(sp.get("id"))
                if not (info and not info.is_basic and sp.get("hp") == sp.get("maxHp")
                        and (sp.get("hp") or 0) > (act.get("hp") or 0)):
                    continue
                # 後続が負けベイト化するなら温存しない(1枚の犠牲を守るために3枚の敗着を
                # 前に出す逆転を防ぐ。alakazam-3 T9: Powerful Hand 500の前へMega330)
                if self._is_loss_bait(sp):
                    continue
                return True
            return False
        # 前進パス: retreat版(_should_reposition)と同じ検証に委譲=先攻T1ガード+
        # 「前進先が今ターン実際に殴れる」を要求(自己レビューarch-5 T1: 攻撃不可ターンに
        # Switchを消費して進化土台を前進=退避資源の浪費+土台の露出)。
        # 無料退却(逃げ0)で同じ前進ができるならSwitch札は温存(人間レビュー18巡目 dragapult T3:
        # Cinderace逃げ0なのにSwitch消費=終盤の退避切符を無償の手段があるのに浪費)
        info_a = self._cardinfo.get(act.get("id"))
        if info_a is not None and int(info_a.retreat or 0) == 0:
            return False
        return self._should_reposition(me)

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
        # 先攻T1は攻撃不可＝前進は主役を無駄に晒すだけ(eager版と同じガード。QA: WallRetreat 2件の修正)
        cur = self._cur or {}
        if cur.get("turn") == 1 and cur.get("yourIndex") == cur.get("firstPlayer"):
            return False
        act = me.get("active") or []
        if not act or not act[0]:
            return False
        if act[0].get("id") in self.plan.attackers:
            cur_r = self._cur or {}
            act_can = self._move_payable(act[0]) or (not cur_r.get("energyAttached") and any(
                self._is_energy(c.get("id")) and self._move_payable(act[0], c.get("id"))
                for c in (me.get("hand") or [])))
            if act_can:
                return False  # 既に「攻撃できる」攻撃役が前(名目だけの攻撃役=払えないなら前進検討)
        for sp in me.get("bench") or []:
            if not sp or sp.get("id") not in self.plan.attackers:
                continue
            # 「エネ有」の旧判定は存在しないフィールド("energies")で常に偽=経路全体が休眠していた。
            # 正しくは「前進すれば殴れる」(既に払える or 手貼りで完成)。
            hand_e = [c.get("id") for c in (me.get("hand") or []) if self._is_energy(c.get("id"))]
            payable = (self._move_payable(sp)
                       or (not (self._cur or {}).get("energyAttached")
                           and any(self._move_payable(sp, e) for e in hand_e)))
            if not payable:
                continue
            if self._is_loss_bait(sp):
                continue                   # 前進先が負けベイト(死=相手残充足×確殺)なら出さない
            info = self._cardinfo.get(sp.get("id"))
            if info and info.is_basic:
                # 脆いたね(将来の進化素材)は前に晒さない: 壁が相手の次打(現実的評価=現エネ+1で
                # 払える技)を耐えるなら壁のまま(人間レビュー7巡目①: 20点のためエネ付きStaryu喪失)。
                if (act[0].get("hp") or 0) > self._incoming_next_turn(act[0]):
                    continue
                # 進化土台は壁が死ぬ場合でも前に出さない: 壁死→強制昇格→次ターン進化の方が
                # 土台を1体分長く守る(壁の体が攻撃1回分を吸収する)。前進は20点と引き換えに
                # 確定ライン(進化先在手)を破壊し盤面全滅へ(人間レビュー12巡目 grimmsnarl-0 T7:
                # Salvatore+Mega在手×Staryu W付きで前進→T8死→T9線なし→全滅負け)。
                if self._is_evolving_base(sp.get("id")):
                    continue
            return True  # 攻撃役がベンチに居る(進化済 or 壁が持たない場合のみたね)
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
        if not act:
            return False
        not_attached = not cur.get("energyAttached")
        if act.get("id") in self.plan.attackers:
            # 前が攻撃役でも「今ターン攻撃できない」(払えず手貼りでも立たない)なら前進検討を継続
            # (人間レビュー18巡目 alakazam相手bot T4: e0のDunsparce=名目攻撃役が前で、
            #  e1で払えるKadabraがベンチに居るのにEND)
            act_can = self._move_payable(act) or (not_attached and any(
                self._is_energy(c.get("id")) and self._move_payable(act, c.get("id"))
                for c in (hand or [])))
            if act_can:
                return False
        have_energy = any(self._is_energy(c.get("id")) for c in (hand or []))
        for sp in me.get("bench") or []:
            if not sp or sp.get("id") not in self.plan.attackers:
                continue
            info = self._cardinfo.get(sp.get("id"))
            if info and info.is_basic:
                continue
            if self._is_loss_bait(sp):
                continue                   # 前進先が負けベイトなら出さない(eager版)
            if self._move_payable(sp):
                return True  # 既にいずれかの技が払える=前進すれば殴れる
            # ②は「そのエネを貼ればいずれかの技が立つ」場合のみ(イグニ=C3なら3エネ技成立。
            # 基本1枚で3エネ技は立たない=前進しても殴れずWallRetreat。QA再発2件の修正)。
            # かつエネ規則がその攻撃役に付くこと(規則がベンチの主役を指すと、前進後の
            # attachがベンチへ流れて攻撃不発=退却権の浪費。自己レビューalakazam-2 T11/13)
            if not_attached:
                act_sp = (me.get("active") or [None])[0]
                others = [t for t in [act_sp] + list(me.get("bench") or []) if t and t is not sp]
                for c in (hand or []):
                    cid = c.get("id")
                    if not self._is_energy(cid) or not self._move_payable(sp, cid):
                        continue
                    # エネが実際にspへ流れるか: rule順位がより高く未充足の付け先が盤上に居れば
                    # attachはそちらへ行く=前進しても殴れない(alakazam-2 T11の退却権浪費)。
                    r = self._energy_rule_rank(cid, sp.get("id"))
                    if any(self._energy_rule_rank(cid, t.get("id")) > r
                           and self._completes_cost(cid, t.get("id"), t) > 0
                           for t in others):
                        continue
                    return True
        return False

    def _active_attack_potential(self, assume_hand_attach: bool = False):
        """現バトル場アタッカーの (払えるワザの最大ダメージ, 弱点無視か)。攻撃不可なら(0,False)。

        assume_hand_attach=True は「このターンまだ手貼りしておらず手札にエネがあるなら、
        貼った後の火力」で評価する(MAIN処理順はPLAY→ATTACHなのでサポ判断は常に手貼り前)。
        ボスゲートとガスト対象選択の判断ペアのみ使用。_active_lethal_now/補給サポ判定は
        「今付いているエネだけ」の意味論なのでデフォルト(False)のまま。"""
        import re
        cur = self._cur
        if not cur:
            return 0, False
        me = cur["players"][cur["yourIndex"]]
        act = (me.get("active") or [None])[0]
        if not act:
            return 0, False
        # プランのattackers限定にしない=実カードの技で評価(AI自己レビュー: Cinderaceの
        # Turbo Flare 50を火力0扱いし、残1でボス→ベンチKO=勝ちの局面を見逃して敗北)
        info = self._cardinfo.get(act.get("id"))
        if not info:
            return 0, False
        # 実効エネ数: イグニ等の volatile エネは進化ポケ上で無3として数える
        evolved = not info.is_basic
        e = 0
        for ec in act.get("energyCards") or []:
            e += 3 if (ec.get("id") in self.plan.volatile_energies and evolved) else 1
        if assume_hand_attach and cur.get("turn") != self._attach_turn:
            inc = 0
            for c in me.get("hand") or []:
                hid = c.get("id")
                if self._is_energy(hid):
                    inc = max(inc, 3 if (hid in self.plan.volatile_energies and evolved) else 1)
            e += inc
        if e <= 0:
            return 0, False
        best, ign = 0, False
        for m in info.moves:
            if not m.damage:
                continue
            if self._dead_by_partner(m.effect or ""):
                continue                       # 相方不在で「何もしない」技は火力に数えない
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
        """対象(target_id)へ与える実効ダメージ（弱点2倍・スタジアム軽減を考慮。
        効果無視技(ign=Nebula等)は据置）。"""
        my_type = self._my_active_type()
        c = self._cardinfo.get(target_id)
        weak = c.weakness if c else None
        out = base * 2 if (weak and my_type and weak == my_type and not ign) else base
        # Full Metal Lab: {M}ポケモンへの技ダメージ-30(エンジン実測: FML下のJetting=90/Nebula=210
        # =効果無視技は素通し。人間レビュー20巡目: Jetting120≥100の偽リーサル予測でRH砲を装填し敗着)
        if not ign and out > 0 and c and (c.type or "") == "{M}":
            stad = (self._cur or {}).get("stadium")
            ids = [x.get("id") for x in stad] if isinstance(stad, list) else ([stad.get("id")] if isinstance(stad, dict) else [])
            if 1244 in ids:
                out = max(0, out - 30)
        return out

    def _should_retreat_doomed(self, me, hand) -> bool:
        """死亡確定×不利トレードの前逃げ判定。①前が攻撃役×サイド2+ ②被KO確定圏 ③残って殴っても
        取れるサイド<失うサイド(有利トレードなら残って殴る) ④ベンチの主力後続が今ターン攻撃可能。"""
        if not me:
            return False
        cur = self._cur or {}
        act = (me.get("active") or [None])[0]
        if not act:
            return False
        pv = self._prize_value(act.get("id"))
        pr = self.analyze_prize()
        opp_left = pr.get("opp_prizes") or 6
        death_loses = pv >= opp_left           # このactiveのKO=相手の残りサイド充足=負け確定
        if act.get("id") not in self.plan.attackers and not death_loses:
            return False
        if pv < 2 and not death_loses:
            return False
        th = max(self._incoming_threat(act), self._incoming_next_turn(act))
        if th <= 0 or (act.get("hp") or 999) > th:
            return False                       # 被KO圏でない(ライン最大と現実評価の高い方)
        # 残って殴った場合のトレード: 相手activeをKOでき、その価値が自分の損失以上なら残る
        dmg, ign = self._active_attack_potential(assume_hand_attach=True)
        opp = cur["players"][1 - cur["yourIndex"]]
        oa = (opp.get("active") or [None])[0]
        if (oa and dmg > 0 and self._eff_dmg(dmg, ign, oa.get("id")) >= (oa.get("hp") or 9999)):
            if death_loses:
                # 死んだら負け: 「今殴れば勝ち切れる(スプラッシュKO込み)」or「KOで脅威が
                # 消える(KO後の残存脅威<自HP)」なら残って殴る(16巡目/19巡目/23巡目)
                if self._attack_prizes_now() >= (pr.get("my_prizes") or 6):
                    return False
                if self._post_ko_threat(act) < (act.get("hp") or 0):
                    return False
            elif (self._prize_value(oa.get("id")) >= pv
                  or self._post_ko_threat(act) < (act.get("hp") or 0)):
                return False                   # 有利トレード or KO後は残存脅威なし=受け入れて殴る
        if death_loses:
            # 敗北回避: 後続の攻撃可否は問わない(負ければ攻撃テンポも無価値)。
            # 「死んでも負けない or 次打を耐える」後続が居れば退く。
            for sp in me.get("bench") or []:
                if not sp:
                    continue
                if (self._prize_value(sp.get("id")) < opp_left
                        or (sp.get("hp") or 0) > self._incoming_next_turn(sp)):
                    return True
            return False
        # ベンチの主力後続が今ターン攻撃できるか(エネ有 or 手貼り権+手札エネ)
        not_attached = not cur.get("energyAttached")
        have_energy = any(self._is_energy(c.get("id")) for c in (hand or []))
        for sp in me.get("bench") or []:
            if not sp or sp.get("id") not in self.plan.attackers:
                continue
            info = self._cardinfo.get(sp.get("id"))
            if not info or info.is_basic:
                continue
            if (sp.get("hp") or 0) <= self._incoming_next_turn(sp):
                continue        # 後続も即死圏(現実的評価=可変ダメ込み)なら退却は損失だけ
                                # (19巡目 alakazam T9: PH420圏の後続を旧line評価で安全と誤認しW2枚を燃やした)
            if (sp.get("energyCards") or []) or (not_attached and have_energy):
                return True
        return False

    def _is_evolving_base(self, cid) -> bool:
        """このデッキ内に cid から進化するカードがあるか(=進化線の土台。開幕はベンチで育てる)。"""
        info = self._cardinfo.get(cid)
        if not info:
            return False
        for did in (self.deck_counts or {}):
            d = self._cardinfo.get(did)
            if d and d.previous_stage and d.previous_stage == info.name:
                return True
        return False

    def _bench_damage_immune(self, cid) -> bool:
        """ベンチに居る限りワザのダメージを防ぐ特性(Dragapult exのTera等)を持つか。"""
        info = self._cardinfo.get(cid)
        for m in (info.moves if info else []):
            if "on your Bench, prevent all damage" in (m.effect or ""):
                return True
        return False

    def _effect_move_damage(self, m, my_spot, attacker_spot=None) -> int:
        """damage欄が空/固定の技でも、効果文の可変ダメージを「見えている実数」で評価する。
        Powerful Hand(ダメカン2×相手手札枚数=公開情報)で330のMegaが一撃圏なのに
        20点扱い→3枚献上ベイトを前に出して敗北(自己レビュー alakazam-9 T7)。
        次の相手ターン想定なので手札は+1(ドロー分)。"""
        import re
        eff = (m.effect or "")
        cur = self._cur or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        hc = opp.get("handCount")
        if hc is None:
            h = opp.get("hand")
            hc = len(h) if isinstance(h, list) else 0
        hc += 4    # 次の相手ターンの手札成長projection。+1(素引きのみ)だとAlakazam等の
                   # ドローエンジン(実測+5/ターン)を~100点過小評価し、生存圏の誤認で
                   # 退却先を焼く(19巡目 alakazam T9: 330>320判定→実際は420で死亡)
        base = 0
        mt = re.match(r"(\d+)", str(m.damage or ""))
        if mt:
            base = int(mt.group(1))
        dmg = 0
        mt = re.search(r"lace (\d+) damage counters? on your opponent[’']s Active Pokémon for each card in your hand", eff)
        if mt:
            dmg = max(dmg, 10 * int(mt.group(1)) * hc)
        mt = re.search(r"does (\d+) (?:more )?damage for each card in your hand", eff)
        if mt:
            dmg = max(dmg, base + int(mt.group(1)) * hc)
        mt = re.search(r"does (\d+) more damage for each Energy attached to your opponent[’']s Active", eff)
        if mt and my_spot is not None:
            dmg = max(dmg, base + int(mt.group(1)) * len(my_spot.get("energyCards") or []))
        mt = re.search(r"does (\d+) more damage for each damage counter on this", eff)
        if mt and attacker_spot is not None:
            cnt = max(0, ((attacker_spot.get("maxHp") or 0) - (attacker_spot.get("hp") or 0)) // 10)
            dmg = max(dmg, base + int(mt.group(1)) * cnt)
        return dmg

    def _incoming_next_turn(self, my_spot) -> int:
        """次の相手ターンの現実的な最大被ダメ(弱点込み): 相手activeライン(進化1段含む)の技のうち
        「現エネ+手貼り1枚(イグニ観測済みなら+3)」で払える最大。ライン最大(line_threat)より現実的
        (人間レビュー7巡目①: エネ0のStaryu相手に210を恐れて壁を退いていた)。"""
        import re
        cur = self._cur
        if not cur or not my_spot:
            return 0
        opp = cur["players"][1 - cur["yourIndex"]]
        oa = (opp.get("active") or [None])[0]
        if not oa:
            return 0
        e = len(oa.get("energyCards") or []) + (3 if any(
            v in self._opp_seen for v in (17,)) else 1)
        oi = self._cardinfo.get(oa.get("id"))
        moves = list(oi.moves) if oi else []
        # 進化前スタックの技も使える(エンジン実測: Archaludon exがDuraludonのRaging Hammer
        # =80+ダメカン×10で満タンMega330を一撃。人間レビュー19巡目 arch T18)
        for pe in (oa.get("preEvolution") or []):
            pi_ = self._cardinfo.get((pe or {}).get("id"))
            if pi_:
                moves += list(pi_.moves)
        for did, di in self._cardinfo.items():
            # 進化1段先の技も想定。ただし相手の場で観測済みのカードのみ(DB全体を見ると
            # 相手デッキに無い別進化形の技を拾い過大評価する)。
            if (oi and di.previous_stage == oi.name and di.is_pokemon
                    and did in self._opp_seen):
                moves += list(di.moves)
        best = 0
        for m in moves:
            need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
            if need > e:
                continue
            mt = re.match(r"(\d+)", str(m.damage or ""))
            dm = int(mt.group(1)) if mt else 0
            dm = max(dm, self._effect_move_damage(m, my_spot, oa))
            best = max(best, dm)
        # ベンチの装填済み銃: 現エネで即払える技を持つベンチは昇格1手で届く(相手はKO後の
        # 昇格/入替で前に出せる)。攻撃者自身のダメカン×N技(Raging Hammer)は瀕死ほど強い
        for sp in opp.get("bench") or []:
            if not sp:
                continue
            si_ = self._cardinfo.get(sp.get("id"))
            if not si_:
                continue
            b_moves = list(si_.moves)
            for pe in (sp.get("preEvolution") or []):
                pi_ = self._cardinfo.get((pe or {}).get("id"))
                if pi_:
                    b_moves += list(pi_.moves)
            be = len(sp.get("energyCards") or [])
            for m in b_moves:
                need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
                if need > be:
                    continue
                mt = re.match(r"(\d+)", str(m.damage or ""))
                dm = int(mt.group(1)) if mt else 0
                dm = max(dm, self._effect_move_damage(m, my_spot, sp))
                best = max(best, dm)
        cc = self._cardinfo.get(my_spot.get("id"))
        if cc and oi and cc.weakness and oi.type == cc.weakness:
            best *= 2
        return best

    def _post_ko_threat(self, my_spot) -> int:
        """相手activeをKOした後の残存脅威: 相手ベンチの装填済み銃(現エネで即払える技)の
        現実的最大ダメージ。ダメカン×N技(Raging Hammer)は昇格時点のダメカンで実数評価
        されるため、瀕死のactiveをKOすれば装填銃でも火力が消えることがある
        (人間レビュー23巡目 arch-4 T7: Arch ex 40hpをKO→昇格Duraludonは80点=Mega330に無害)。"""
        import re
        cur = self._cur
        if not cur or not my_spot:
            return 0
        opp = cur["players"][1 - cur["yourIndex"]]
        best = 0
        cc = self._cardinfo.get(my_spot.get("id"))
        for sp in opp.get("bench") or []:
            if not sp:
                continue
            si_ = self._cardinfo.get(sp.get("id"))
            if not si_:
                continue
            b_moves = list(si_.moves)
            for pe in (sp.get("preEvolution") or []):
                pi_ = self._cardinfo.get((pe or {}).get("id"))
                if pi_:
                    b_moves += list(pi_.moves)
            # 昇格後は手貼り1枚(イグニ観測済みなら+3)も想定
            be = len(sp.get("energyCards") or []) + (3 if any(
                v in self._opp_seen for v in (17,)) else 1)
            for m in b_moves:
                need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
                if need > be:
                    continue
                mt = re.match(r"(\d+)", str(m.damage or ""))
                dm = int(mt.group(1)) if mt else 0
                dm = max(dm, self._effect_move_damage(m, my_spot, sp))
                if cc and cc.weakness and si_.type == cc.weakness:
                    dm *= 2
                best = max(best, dm)
        return best

    def _incoming_threat(self, my_spot) -> int:
        """相手バトル場ラインの最大火力(弱点込み)=このポケモンが次の相手ターンに受けうる最大ダメージ。"""
        cur = self._cur
        if not cur or not my_spot:
            return 0
        opp = cur["players"][1 - cur["yourIndex"]]
        oa = (opp.get("active") or [None])[0]
        if not oa:
            return 0
        t = _line_threat(oa.get("id")) or 0
        oc = self._cardinfo.get(oa.get("id"))
        # 効果文の可変ダメージ(手札枚数×等)はline_threat(静的)に乗らない=実数で補完
        moves = list(oc.moves) if oc else []
        for did, di in self._cardinfo.items():
            if oc and di.previous_stage == oc.name and di.is_pokemon and did in self._opp_seen:
                moves += list(di.moves)
        for m in moves:
            t = max(t, self._effect_move_damage(m, my_spot, oa))
        cc = self._cardinfo.get(my_spot.get("id"))
        if cc and oc and cc.weakness and oc.type == cc.weakness:
            t *= 2
        return t

    def _opp_boss_remaining(self) -> int:
        """相手のボス(引きずり出し)残数推定。見えたカードからアーキタイプを推定し、
        既知構築のボス枚数(既定2)から相手トラッシュで見えた使用分を引く。
        =「ベンチは安全地帯ではない」をデッキ推定から定量化(人間レビュー項目A③)。"""
        cur = self._cur or {}
        opp = cur.get("players", [{}, {}])[1 - cur.get("yourIndex", 0)]
        est = 2
        seen = " ".join((self._cardinfo.get(x).name or "") for x in self._opp_seen if x in self._cardinfo)
        for key, n in (("Archaludon", 3), ("Dragapult", 3), ("Alakazam", 1)):
            if key in seen:
                est = n
                break
        used = sum(1 for c in (opp.get("discard") or [])
                   if "Boss" in ((self._cardinfo.get(c.get("id")).name or "")
                                 if c.get("id") in self._cardinfo else ""))
        return max(0, est - used)

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

    def _deck_likely_has(self, cid) -> bool:
        """カードcidが山に残っている見込み(デッキ構成枚数 - 可視枚数 > 0)。"""
        total = (self.deck_counts or {}).get(cid, 0)
        if total <= 0:
            return False
        me = self._me() or {}
        vis = sum(1 for c in (me.get("hand") or []) if c.get("id") == cid)
        vis += sum(1 for c in (me.get("discard") or []) if c.get("id") == cid)
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if sp and sp.get("id") == cid:
                vis += 1
        return total - vis > 0

    def _has_evolution_target(self) -> bool:
        """場に『山札から進化できるポケモン』が居るか(セイジ等 進化加速サポの前提条件)。
        ＝場のポケモン名を進化前(previous_stage)に持つカードがデッキに存在する。"""
        me = self._me()
        if not me or not self.deck_counts:
            return False
        # 進化させる価値のある対象のみ数える: activeへの進化が負けベイトを作る(死1枚を
        # 死3枚に変える)なら、その対象は「進化すべきでない」=Salvatoreを打つ理由にならない
        # (人間レビュー23巡目 alakazam T9敗着: 唯一の対象=active Staryuで、進化後Mega330が
        #  PH540圏×残3=Salvatore経路がEvolveIntoLossゲートを素通り)
        act0 = (me.get("active") or [None])[0]
        spots = [sp for sp in ([act0] + list(me.get("bench") or [])) if sp]
        name2spot = {}
        for sp in spots:
            info_s = self._cardinfo.get(sp.get("id"))
            if info_s:
                name2spot.setdefault(info_s.name, []).append(sp)
        for cid, n in self.deck_counts.items():
            info = self._cardinfo.get(cid)
            if not (info and info.previous_stage in name2spot
                    and self._deck_likely_has(cid)):
                continue
            for sp in name2spot[info.previous_stage]:
                if sp is act0:
                    class _Op:  # activeへの進化のみベイト判定(ベンチ進化は常に価値あり)
                        in_play_area = AreaType.ACTIVE
                    if self._evolve_creates_loss_bait(cid, _Op()):
                        continue
                return True
        return False

    def _lillie_emergency(self) -> bool:
        """緊急時Gate: 単騎 × 被KO圏 × 現手札に生存手段なし(たねポケ/ポフィン無し)
        → 引き直しが唯一の生存線(条件は意図的に限定=乱発防止)。"""
        me = self._me()
        if not me or any(b for b in (me.get("bench") or []) if b):
            return False
        th = self.analyze_threat()
        if not th.get("can_ko_me"):
            # 可変ダメージ技(手札×20のPowerful Hand等)はline_threat=0に静落ちして
            # can_ko_meが偽陰性になる→単騎では脅威扱い(alakazam-0 T5=ベンチアウト負けの真因)
            opp0 = self._cur["players"][1 - self._cur["yourIndex"]]
            oa0 = (opp0.get("active") or [None])[0]
            oi0 = self._cardinfo.get((oa0 or {}).get("id"))
            if not (oi0 and any("for each" in (m.effect or "") for m in oi0.moves)):
                return False
        hand = me.get("hand") or []
        has_basic = any(
            (c.get("id") in self._cardinfo and self._cardinfo[c.get("id")].is_pokemon
             and self._cardinfo[c.get("id")].is_basic) for c in hand)
        has_poffin = any(c.get("id") == POFFIN for c in hand)
        if has_basic or has_poffin:
            return False
        # 生きたミツル(回復で被KO圏→生存圏に反転)も生存手段=緊急でない。回復を優先し
        # リーリエで流さない(QA: 単騎重傷でミツルを差し置きリーリエ2件の修正)。
        # ただし相手activeに可変ダメージ技(手札×20のPowerful Hand等)があると静的threatは
        # 過小評価=「回復で安全」は幻想→リーリエ(たね掘り=構造解)を優先
        # (AI自己レビュー: alakazam-0 T5 ボス2枚取り→T6単騎ベンチアウト負け)。
        if any(c.get("id") in self.plan.heal_return_cards for c in hand):
            act = (me.get("active") or [None])[0]
            opp0 = self._cur["players"][1 - self._cur["yourIndex"]]
            oa0 = (opp0.get("active") or [None])[0]
            oi0 = self._cardinfo.get((oa0 or {}).get("id"))
            variable = any("for each" in (m.effect or "") for m in (oi0.moves if oi0 else []))
            # 譲る条件はWally自身の発火条件(重傷150+)と揃える: 150未満だとWallyは打たれず
            # 「どちらも発火しない=サポ権未使用」の隙間に落ちる(人間レビュー18巡目 lucario-5 T7:
            # 単騎×被KO×ダメージ130でリーリエもWallyも不発)
            if (not variable and act
                    and (act.get("maxHp") or 0) - (act.get("hp") or 0) >= 150
                    and (act.get("maxHp") or 0) > self._incoming_threat(act)):
                return False
        return True

    def _lillie_energy_dig(self) -> bool:
        """エネ掘りリーリエの成立条件(手札エネ0×場の攻撃役が最大技/どの技も払えない×p_draw>=0.55)。
        _should_use_lillieのエネ掘り条項と同一意味論(こちらは_play_scoreの優先度付けに使う)。"""
        me = self._me()
        if not me or not self.deck_counts:
            return False
        hand = me.get("hand") or []
        if any(self._is_energy(cd.get("id")) for cd in hand):
            return False
        # 生きた状況札(Wally等)の温存: 重傷×反転可のヒール条件が成立しているなら回復が先
        # (エネ掘り70が正当なヒール60を先取りした60戦退行: mirror-4 T9/mirror-6 T7)
        if any(c.get("id") in self.plan.heal_return_cards for c in hand):
            act_h = (me.get("active") or [None])[0]
            if (self._attacker_damaged(150) and act_h
                    and (act_h.get("maxHp") or 0) > self._incoming_threat(act_h)):
                return False
            for sp in me.get("bench") or []:
                if (sp and sp.get("id") in self.plan.attackers
                        and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150
                        and not (sp.get("energyCards") or [])):
                    return False
        prizes_left = len(me.get("prize") or [])
        draw_n = 8 if prizes_left >= 6 else 6
        act0 = (me.get("active") or [None])[0]
        if act0 and act0.get("id") in self.plan.attackers:
            dmg_now, _ = self._active_attack_potential()
            info0 = self._cardinfo.get(act0.get("id"))
            import re as _re
            full = 0
            for m in (info0.moves if info0 else []):
                mt = _re.match(r"(\d+)", m.damage or "")
                if mt:
                    full = max(full, int(mt.group(1)))
            if dmg_now < full and self._p_draw(self._energy_ids, draw_n, include_hand=True) >= 0.55:
                return True
        for sp in [act0] + list(me.get("bench") or []):
            if (sp and sp.get("id") in self.plan.attackers
                    and not self._move_payable(sp)
                    and self._p_draw(self._energy_ids, draw_n, include_hand=True) >= 0.55):
                return True
        return False

    def _should_use_lillie(self) -> bool:
        """リーリエの決心: 手札を山に戻して6枚(早期=サイド6なら8枚)引く。
        キー札は温存し、引き直しで純増 or 必要資源(エネ/アタッカー)を高確率で引ける時に使う。"""
        me = self._me()
        hand = (me.get("hand") or []) if me else []
        if self._lillie_emergency():
            return True
        if not self.deck_counts:  # 構成不明 → 従来の保守的条件
            return not (self._has_key(hand) or len(hand) >= 4)
        prizes_left = len(me.get("prize") or []) if me else 6
        draw_n = 8 if prizes_left >= 6 else 6
        # 生きた状況札の温存(人間レビュー6巡目④): 重傷×生存反転のミツル等、今まさに条件が成立
        # している状況札を引き直しで流さない(リーリエは温存し、状況札を先に消化する)。
        if any(c.get("id") in self.plan.heal_return_cards for c in hand):
            act_h = ((me or {}).get("active") or [None])[0]
            if (self._attacker_damaged(150) and act_h
                    and (act_h.get("maxHp") or 0) > self._incoming_threat(act_h)):
                return False
        # 主力線dig(人間レビュー6巡目②): 主力ライン(key_cards[0]の線)が場に1体も無く、手札からも
        # 立てられないなら、リーリエで土台(たね)を掘りに行く(死に手札=ハリテヤマ2枚等より質を優先)。
        main0 = (self.plan.key_cards or (None,))[0]
        if main0 is not None and me:
            chain = {main0}
            cur_i = self._cardinfo.get(main0)
            name2id = {self._cardinfo[i].name: i for i in (self.deck_counts or {}) if i in self._cardinfo}
            while cur_i and cur_i.previous_stage in name2id:
                pid = name2id[cur_i.previous_stage]
                if pid in chain:
                    break
                chain.add(pid); cur_i = self._cardinfo.get(pid)
            board_ids = {sp.get("id") for sp in
                         [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp}
            hand_ids_ = {c.get("id") for c in hand}
            bases = {i for i in chain
                     if self._cardinfo.get(i) and self._cardinfo[i].is_basic}
            if (not (chain & board_ids) and not (bases & hand_ids_)
                    and self._p_draw(bases, draw_n, include_hand=True) >= 0.3):
                return True
        # エネ掘り(人間レビュー5巡目③⑤): 場のアタッカーがエネ不足で最大技を打てず手札エネ0なら、
        # 手札の枚数(純増減)やキー温存より質を優先して引き直す(キーは山に戻るだけで失われない。
        # 山のエネ残量は_p_drawが考慮。「手札は多いが死んでいる」状態こそ引き直しの価値がある)。
        if me and not any(self._is_energy(cd.get("id")) for cd in hand):
            act0 = (me.get("active") or [None])[0]
            if act0 and act0.get("id") in self.plan.attackers:
                dmg_now, _ = self._active_attack_potential()
                info0 = self._cardinfo.get(act0.get("id"))
                import re as _re
                full = 0
                for m in (info0.moves if info0 else []):
                    mt = _re.match(r"(\d+)", m.damage or "")
                    if mt:
                        full = max(full, int(mt.group(1)))
                if dmg_now < full and self._p_draw(self._energy_ids, draw_n, include_hand=True) >= 0.55:
                    return True
            # activeが攻撃役でなくても、場の攻撃役のどれかが1technique も払えない(エネ枯れ)なら掘る
            # (人間レビュー15巡目 grimmsnarl相手bot: 手札9枚全部死に札×ベンチGrimmsnarl e1で
            #  Shadow Bullet不能を放置=「手札の枚数より質」の原則がactive限定だった)。
            for sp in [act0] + list(me.get("bench") or []):
                if (sp and sp.get("id") in self.plan.attackers
                        and not self._move_payable(sp)
                        and self._p_draw(self._energy_ids, draw_n, include_hand=True) >= 0.55):
                    return True
        blocked = (self._has_key(hand) if self.plan.strict_lillie_guard
                   else self._has_deployable_key(hand))
        if blocked:
            return False  # キーは山に戻さない（既定=この番に展開できるキーのみ／strict=全キー）
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

    def _boss_wins_game(self) -> bool:
        """ボスで引き出せるベンチKOのサイドが残り必要数以上=このボスで勝ち切れるか。"""
        cur = self._cur
        if not cur:
            return False
        dmg, ign = self._active_attack_potential(assume_hand_attach=True)
        if dmg <= 0:
            return False
        me = cur["players"][cur["yourIndex"]]
        opp = cur["players"][1 - cur["yourIndex"]]
        need = len(me.get("prize") or []) or 6
        best = 0
        for sp in opp.get("bench") or []:
            if sp and self._eff_dmg(dmg, ign, sp.get("id")) >= (sp.get("hp") or 9999):
                best = max(best, self._prize_value(sp.get("id")))
        return best >= need

    def _should_play_boss(self) -> bool:
        """ボスは『前を倒せない×ベンチにKO可能あり』または『より大きなサイドを取れる』時のみ。"""
        cur = self._cur
        if not cur:
            return False
        dmg, ign = self._active_attack_potential(assume_hand_attach=True)
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
            # 勝ち筋チェック(人間レビュー4巡目①④): ボス経路のKO回数(引っ張りKO自体+1)が
            # 直行経路より「増える」場合のみ温存し主力へ蓄積(例: 残5・メガ3=直行2回 vs ボス1+2=3回)。
            # 同数なら打つ=引っ張った相手は今確実にKOできるが、前は1発で倒せない(arch-17の教訓)。
            import math
            me2 = cur["players"][cur["yourIndex"]]
            need = len(me2.get("prize") or []) or 6
            board = [x for x in ([act] + list(opp.get("bench") or [])) if x]
            main_pv = max((self._prize_value(x.get("id")) for x in board), default=1)
            if 1 + math.ceil(max(0, need - best_bench) / main_pv) > math.ceil(need / main_pv):
                return False
            return True                        # 前を倒せない×勝ち筋を遅らせない → 引っ張る
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
        dmg, ign = self._active_attack_potential(assume_hand_attach=True)
        # 撒きキー(_spread_key)は攻撃効果のベンチ選択(DAMAGE)のみ。ボス等の引き出し(SWITCH)は
        # KO×サイド価値で選ぶ(人間レビュー7巡目②: ボスでMega90(3枚KO)でなくStaryu70(snipe)を
        # 引いた謎行動=撒きロジックの誤用)。
        spread = (self.plan.spread_damage
                  if getattr(sel, "context", None) == SelectContext.DAMAGE else 0)
        if getattr(sel, "context", None) == SelectContext.DAMAGE and not spread:
            # plan未設定(UniversalBot)は攻撃者の効果文から撒き量を導出。導出できないと
            # 本体火力でKO判定してしまい30点撒きでMega(倒せない)を選ぶ(QA: grimmsnarl相手bot)。
            import re as _re
            me_ = cur["players"][cur["yourIndex"]]
            a_ = (me_.get("active") or [None])[0]
            info_ = self._cardinfo.get((a_ or {}).get("id"))
            for m in (info_.moves if info_ else []):
                mt = _re.search(r"does (\d+) damage to 1 of your opponent[’']s Benched", m.effect or "")
                if mt:
                    spread = int(mt.group(1))
                    break
        cand = []
        pre = []
        for i, op in enumerate(sel.options):
            if op.player_index != opp_idx:
                continue
            spots = (opp.get("active") if op.area == AreaType.ACTIVE else opp.get("bench")) or []
            if op.index is not None and 0 <= op.index < len(spots) and spots[op.index]:
                sp = spots[op.index]
                cid = sp.get("id")
                if spread and op.area != AreaType.ACTIVE and self._bench_damage_immune(cid):
                    continue
                th0 = _line_threat(cid) or 0
                if self._line_has_variable_damage(cid):
                    th0 = max(th0, 400)
                pre.append((i, op, sp, cid, th0))
        cand_max_th = max((t for *_, t in pre), default=0)
        for i, op, sp, cid, th0 in pre:
            if True:
                hp = sp.get("hp", 9999)
                threat = th0                 # 進化ライン脅威度(例:リオル=メガルカリオ線)
                if spread:
                    cand.append(self._spread_key(sp, cid, hp, threat, spread, dmg, cand_max_th) + (i,))
                else:
                    koable = 1 if self._eff_dmg(dmg, ign, cid) >= hp else 0
                    # 同点(同KO/同サイド)ならエネ投資が多い個体を釣る=投資破壊+進化して戻るのを防ぐ
                    # (人間レビュー18巡目 dragapult T5: Dreepy-e0を釣りe1が生存→Drakloakに進化)
                    e_inv = len(sp.get("energyCards") or [])
                    cand.append((koable, self._prize_value(cid), threat, e_inv, -hp, i))
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

    def _line_has_variable_damage(self, cid) -> bool:
        """この線(進化2段まで)に効果文可変ダメージ(手札枚数×等)の技があるか。
        Powerful Hand等はdamage欄が空でline_threat(静的)に乗らない=Abra線が
        Dunsparce線(90)より低脅威と誤評価される(人間レビュー17巡目 alakazam-0 T5/T7:
        スプラッシュ同時KOの標的にAbraでなくDunsparce10/エネ無しAbraを選択)。"""
        import re
        if not hasattr(self, "_varline_cache"):
            self._varline_cache = {}
        if cid in self._varline_cache:
            return self._varline_cache[cid]
        cur_i = self._cardinfo.get(cid)
        out = False
        if cur_i:
            stage1 = [di for di in self._cardinfo.values()
                      if di.previous_stage == cur_i.name and di.is_pokemon]
            stage2 = [dj for dj in self._cardinfo.values()
                      for di in stage1 if dj.previous_stage == di.name and dj.is_pokemon]
            for c in [cur_i] + stage1 + stage2:
                for m in c.moves:
                    if re.search(r"for each card in your hand", m.effect or ""):
                        out = True
        self._varline_cache[cid] = out
        return out

    def _spread_key(self, sp, cid, hp, threat, spread, our_dmg, cand_max_th=None):
        """ベンチ撒き(Jetting Blow等)の対象優先度テーブル＝ベース×相手デッキ(self._matchup)×局面。
        ダメージは進化で引き継ぐので『将来この火力枠が前に出た時、今の撒きでKO攻撃回数を減らせるか』を予測する。
          - 序盤: 発展中の主力ライン(進化前=最大脅威の線)を優先的に削り、将来の脅威の芽を先に摘む。
          - 中盤: 将来のKO攻撃回数削減(reduce)を最優先＝前に出てくる火力枠を効率よく軟化。
          - 後半: 撒き＋自火力でKO圏に入る主力を優先＝詰め。
        ＝(局面別のキー, i) を返す。i は呼び出し側で付与。"""
        koable = 1 if spread >= hp else 0            # 撒きだけで今KOできるか(低HPベンチ)
        fhp = _line_attacker_hp(cid)                 # 進化後に前に出てくる火力枠のHP
        # 進化前スナイプ: 最大脅威線の進化前(たね)を撒き2発以内で狩れるなら、進化される前に芽を摘む
        # のが reduce(将来KO回数削減)より優先(人間レビュー2巡目: リオル80を外しMakuhita/Hariyamaへ
        # 撒いた6局面の修正)。同点時は従来キーで決まる。
        ci = self._cardinfo.get(cid)
        if self._line_has_variable_damage(cid):
            threat = max(threat, 400)            # 可変ダメ線(Powerful Hand等)=実質最大脅威
        # スナイプ閾値は「現存候補中の最大脅威線」(歴史的_opp_main_lineだと既に全滅した線=
        # 例: 死んだLucario線270が、現役のMakuhita線210のスナイプを永遠に抑制する)
        top_th = cand_max_th if cand_max_th is not None else (self._opp_main_line or 0)
        snipe = 1 if (ci and ci.is_basic and threat >= 180
                      and threat >= top_th
                      and 2 * spread >= hp and fhp > hp) else 0
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
        e_inv = len(sp.get("energyCards") or [])     # エネ投資破壊の価値(同点タイブレーク)
        if phase == "late":             # 後半=詰め: reduce同点なら『撒き後2回で倒せる』主力を優先
            return (koable, snipe, reduce, threat, two_ko, pv, e_inv, -hp)
        return (koable, snipe, reduce, threat, pv, e_inv, -hp)  # 序盤・中盤: スナイプ>軟化(将来KO削減+脅威線蓄積)

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
                    for ec in (sp.get("energyCards") or []):
                        if ec.get("id") is not None:
                            self._opp_seen.add(ec["id"])
        # トラッシュの「エネルギーのみ」観測(公開情報)。イグニ等の揮発エネは相手ターン内で
        # 「貼る→番末に消える」ため盤面には一度も見えない=トラッシュを見ないと脅威(+3エネ)を
        # 永遠に過小評価する(人間レビュー13巡目 mirror-9 T11: 相手イグニ使用済みなのに
        # Nebula 210圏を120と評価し死んだら負けのMega210を放置)。
        # ※ポケモンは対象外: トラッシュの進化ポケは盤面に居ない=進化脅威に数えると
        #   過剰逃避の連鎖(60戦でWallRetreat等10件の退行を実測)。
        for c in (opp.get("discard") or []):
            cid = c.get("id")
            if cid is not None and self._is_energy(cid):
                self._opp_seen.add(cid)
        if self._opp_seen:
            self._opp_main_line = max(_line_threat(c) for c in self._opp_seen)
        # 相手手札エネ推論(人間レビュー5巡目④・Fact収集): 手貼りは1ターン1回なので、相手が
        # 場のエネ総数を増やさずターンを終え続ける=手札にエネが無い可能性が高い。
        # 手札全入れ替え(リーリエ等)の観測は困難なため連続ターン数のみ保持(判断材料。消費者は未接続)。
        tot = sum(len(sp.get("energyCards") or [])
                  for area in ("active", "bench") for sp in (opp.get(area) or []) if sp)
        t = cur.get("turn", 0)
        if self._opp_ene_mark is not None and t > self._opp_ene_mark[0]:
            if tot <= self._opp_ene_mark[1]:
                self._opp_no_attach_streak += 1
            else:
                self._opp_no_attach_streak = 0
        if self._opp_ene_mark is None or t != self._opp_ene_mark[0]:
            self._opp_ene_mark = (t, tot)
        else:
            self._opp_ene_mark = (t, max(tot, self._opp_ene_mark[1]))

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
        # spread型デッキの文脈評価: 相手バトル場が1エネ技(Jetting等)圏内なら、基本エネ(1エネ技+撒き)を
        # volatile(イグニ=大技単発)より優先(人間レビュー3巡目①: FetchSkew|1エネ圏○ 52件/60戦の修正。
        # 「前を倒せる+ベンチ50」>「前を倒せるだけ」の比較)。
        if (self.plan.spread_damage and self._is_energy(cid)
                and cid not in self.plan.volatile_energies
                and self._opp_active_in_cheap_range()):
            return 92
        # 死んだ進化カードの抑制(人間レビュー6巡目③): 進化元が場にも手札にも居ない進化ポケは
        # 持ってきても置けない=価値を大きく下げる(土台のたねを先に取るべき)。
        # ※取得ゾーン(山/公開/トラッシュ)のみ。場に居るポケモン(昇格/対象選択)へ適用すると
        #   全候補が30に潰れて先頭選びに退化する(人間レビュー7巡目で発覚したバグ)。
        c = self._cardinfo.get(cid)
        if (c and c.is_pokemon and not c.is_basic and c.previous_stage
                and op.area in (AreaType.DECK, AreaType.LOOKING, AreaType.DISCARD)
                and not any(cd.get("id") == RARE_CANDY for cd in (self._me() or {}).get("hand") or [])):
            me = self._me() or {}
            names = set()
            for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
                if sp:
                    ci2 = self._cardinfo.get(sp.get("id"))
                    if ci2:
                        names.add(ci2.name)
            for cd in me.get("hand") or []:
                ci2 = self._cardinfo.get(cd.get("id"))
                if ci2:
                    names.add(ci2.name)
            if c.previous_stage not in names:
                return 30
        if cid in self.plan.card_values:
            return self.plan.card_values[cid]
        if cid in self.plan.attackers:
            return 95
        if c and c.hp is not None:
            return 80 if (c.rule and "ex" in (c.rule or "").lower()) else 60
        return 42

    def _opp_active_in_cheap_range(self) -> bool:
        """相手バトル場が撒き技(1エネ技=Jetting等)のダメージ圏内か。エネfetch選択の文脈評価用。"""
        cur = self._cur
        if not cur:
            return False
        opp = cur["players"][1 - cur["yourIndex"]]
        oa = (opp.get("active") or [None])[0]
        if not oa:
            return False
        dmg = 0
        for nm_ in self.plan.spread_attacks:
            aid = self._attack_name_ids().get(nm_)
            if aid is not None:
                dmg = max(dmg, self._attack_table().get(aid, 0))
        return dmg > 0 and (oa.get("hp") or 999) <= dmg

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
