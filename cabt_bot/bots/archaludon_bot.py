"""Archaludon（ブリジュラスex / 鋼軸）専用 bot。

回し方の方針: ジュラルドン→ブリジュラスex(1進化, HP300)を立てる。
ブリジュラスex の特性「ごうきんビルド」(進化時にトラッシュから基本【鋼】エネを2枚加速)
が火力エンジン。＝先に鋼エネをトラッシュへ置いてから進化すると、メタルディフェンダー
(鋼3=220)を最速で起動できる。

構築(ラダー実#1を再現): たね ジュラルドン×4 / ブリジュラスex×4 / ジーランス×3。
ジーランス(57)特性きおくにもぐる＝進化ポケが進化前のワザを使える＝ブリジュラスexが
ジュラルドンの「ぶちかます(鋼1=30)」を使え、鋼3溜まる前でも毎ターン攻撃でき腐らない。
コンサは カキツバタ(1202,上7枚からポケ+トレーナー) / ポケパッド(1152,ルール無しポケ
サーチ=たね確保でdonk緩和) / リーリエ / ポケギア。妨害に ジャッジマン / ボス。
スタジアム フルメタルラボ(鋼-30)。Cyrano/Hilda/Waitress/Cinderaceは全て劣化のため不採用=A/B。

カスタムロジック: 鋼エネをトラッシュへ送りごうきんビルドを仕込む / active=攻撃役exを
最優先進化 / ベンチ薄時はジュラルドン優先 / activeが攻撃可なら余剰エネは控えにプリチャージ。
"""
from .deck_bot import DeckBot, DeckPlan
from ..enums import AreaType

PLAN = DeckPlan(
    name="Archaludon",
    go_first=True,
    attackers=(190, 169),                 # ブリジュラスex / ジュラルドン
    key_cards=(190, 169),
    preferred_attacks=(),
    energy_rules=((8, 190), (8, 169), (None, 190)),  # 鋼→ブリジュラス/ジュラルドン
    play_priority={169: 84, 190: 86, 57: 85},  # ジュラルドン/ブリジュラスex/ジーランス(engine)
    card_values={190: 100, 57: 84, 169: 80, 8: 84},
    lethal=True,
    est_var_damage=True,
    smart_take=True,
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),          # いれかえは攻撃役を前に出す必要がある時のみ(準備済みアタッカーを下げる無駄打ち防止)
)


METAL = 8        # 基本【鋼】エネルギー
DURALUDON = 169  # ジュラルドン
ARCH_EX = 190    # ブリジュラスex
RELICANTH = 57   # ジーランス(特性きおくにもぐる)
POKE_PAD = 1152  # ポケパッド(ルール無しポケモンをサーチ)
JUDGE = 1213     # ジャッジマン(おたがい手札を山札に戻し4枚引く=手札妨害)
ULTRA_BALL = 1121  # ハイパーボール(手札2枚捨て→ポケモン1枚サーチ)
DRAYTON = 1202     # ドラユキ/カキツバタ(山札上7枚→ポケモン＋トレーナー各1枚)
RAGING_HAMMER = 224  # レイジングハンマー(ジュラルドンのワザ): 80＋自分に乗ったダメージ量


class ArchaludonBot(DeckBot):
    plan = PLAN

    ATTACK_COST = 3  # メタルディフェンダー(鋼鋼鋼)

    @staticmethod
    def _metal_on(spot) -> int:
        if not spot:
            return 0
        e = spot.get("energyCards") or spot.get("energies") or []
        return sum(1 for x in e if (x.get("id") if isinstance(x, dict) else x) == METAL)

    def _pick_attach(self, idxs, options, hand, me):
        # active が既に攻撃可能(鋼3個)なら、余剰の鋼エネはベンチの攻撃役に貼って次の番に備える。
        # (active への重ね貼りは無駄。ベンチ育成でKO後の再加速を速める)
        # ※被ダメしたactiveはレイジングハンマー(80+被ダメ)の最高火力役なので、エネは奪わない。
        active = (me.get("active") or [None])[0]
        if active and self._metal_on(active) >= self.ATTACK_COST:
            cand = []
            for i in idxs:
                op = options[i]
                if op.in_play_area == AreaType.ACTIVE:
                    continue
                if self._hand_id(hand, op.index) != METAL:
                    continue
                tid = self._target_id(me, op.in_play_area, op.in_play_index)
                if tid in (ARCH_EX, DURALUDON):
                    spot = self._target_spot(me, op.in_play_area, op.in_play_index)
                    cand.append((self._metal_on(spot), i))  # 鋼が少ない控えを優先育成
            if cand:
                cand.sort()
                return cand[0][1]
        return super()._pick_attach(idxs, options, hand, me)

    def _target_spot(self, me, area, index):
        if area == AreaType.ACTIVE:
            return (me.get("active") or [None])[0]
        bench = me.get("bench") or []
        return bench[index] if 0 <= index < len(bench) else None

    def _pick_evolve(self, idxs, options, hand) -> int:
        """active のジュラルドンは攻撃役 Archaludon ex(190) に進化させ、エネを攻撃役に残す。
        非ex(170, 自由入替の補助)が active に乗って攻撃役のexがベンチでE0放置されるのを防ぐ。"""
        best, best_key = idxs[0], None
        for i in idxs:
            op = options[i]
            evo = self._hand_id(hand, op.index)
            is_active = 1 if op.in_play_area == AreaType.ACTIVE else 0
            is_ex = 1 if evo == ARCH_EX else 0
            key = (is_active, is_ex, self.plan.card_values.get(evo, 0))
            if best_key is None or key > best_key:
                best_key, best = key, i
        return best

    def _count_in_play(self, cid: int) -> int:
        me = self._me()
        if not me:
            return 0
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        return sum(1 for s in spots if s and s.get("id") == cid)

    def _missing_piece(self) -> tuple[int, str]:
        """サーチで今得られると価値が高い『欠けているピース』の(評価値, 理由)を返す(depth-1近似)。
        ＝『使った後に何が可能になるか』で札を評価する(GPTレビュー: 結果志向＋Explainability)。"""
        me = self._me() or {}
        hand = me.get("hand") or []
        has_ex = self._count_in_play(ARCH_EX) >= 1 or any(c.get("id") == ARCH_EX for c in hand)
        dura = self._count_in_play(DURALUDON) + sum(1 for c in hand if c.get("id") == DURALUDON)
        has_reli = self._count_in_play(RELICANTH) >= 1 or any(c.get("id") == RELICANTH for c in hand)
        n = sum(1 for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s)
        if dura == 0 and not has_ex:
            return 120, "進化線が皆無→たね確保が最優先"
        if not has_ex and dura >= 1:
            return 115, "攻撃役ブリジュラスex未所持→exを確保し進化→Metal Defenderへ"
        if not has_reli:
            return 95, "ジーランス未所持→レイジング/Hammer Inのエンジン確保"
        if n < 3:
            return 75, "ベンチが薄い→バックアップ確保"
        return 40, "主要ピースは揃っている→低価値"

    def _missing_piece_value(self) -> int:
        return self._missing_piece()[0]

    def explain_play(self, cid: int) -> str:
        """そのカードを今プレイする評価の『理由』を返す(Explainability用)。"""
        if cid in (ULTRA_BALL, DRAYTON):
            v, why = self._missing_piece()
            return f"結果志向:{why}"
        if cid == RELICANTH:
            return "場に既にジーランス→重複は無価値" if self._count_in_play(RELICANTH) >= 1 else "エンジン(きおくにもぐる)を設置"
        if cid == JUDGE:
            return "手札妨害(自分が損せず相手の手札が多い時のみ)"
        if cid == POKE_PAD:
            return "ルール無しポケサーチ(盤面が揃えば温存)"
        return ""

    def _play_score(self, cid, hand):
        # ハイパボ(ポケモンサーチ): 静的でなく『何を持ってこられるか』で評価(結果志向=depth-1)。
        # 欠けている重要ピース(攻撃役/たね/ジーランス)を取れる時ほど高く、揃っていれば低い。
        # ※加点中心(基準82を下回らない)で、揃っている時の過度な温存=テンポ損を避ける。
        if cid == ULTRA_BALL:
            return max(82, self._missing_piece_value())
        # ドラユキ(ポケモン＋トレーナーを各1枚): 同じく結果志向。欠けた重要ピースを取れる時ほど
        # 高評価。トレーナーも取れるため底値は高め(純アド)＝GPT指摘『盤面で価値が変わる』に対応。
        if cid == DRAYTON:
            return max(40, self._missing_piece_value())
        # ジャッジマン(手札妨害): 自分の手札が多い時に使うと自分の手札も捨てる損。
        # 自分の手札が少なく(プレイ後に山札に戻る枚数<=4で実質減らない=4枚引き直し)、
        # かつ相手の手札が多い(妨害価値あり)時だけ使う＝「目的のために使う」。
        if cid == JUDGE:
            me = self._me() or {}
            cur = self._cur or {}
            opp = (cur.get("players") or [None, None])[1 - cur.get("yourIndex", 0)] if cur else {}
            my_after = len(me.get("hand") or []) - 1   # ジャッジ自身を除いた戻り枚数
            opp_hand = len((opp or {}).get("hand") or [])
            return 60 if (my_after <= 4 and opp_hand >= 5) else None
        # ジーランスは特性(きおくにもぐる)が重複しないため、場に1匹で十分。
        # 既に場に居るなら出さない(2匹目以降はベンチ枠とテンポの無駄＝GPTレビュー指摘)。
        if cid == RELICANTH:
            return None if self._count_in_play(RELICANTH) >= 1 else 87
        # ポケパッド(ルール無しポケサーチ): 盤面が揃っている(場4体以上＋ジーランス済)なら
        # 温存(無駄なサーチで山札を薄くしない)。結果志向の細分化はA/Bで悪化のため二値ゲートを採用。
        if cid == POKE_PAD:
            me = self._me() or {}
            n = sum(1 for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s)
            setup_done = n >= 4 and self._count_in_play(RELICANTH) >= 1
            return None if setup_done else super()._play_score(cid, hand)
        return super()._play_score(cid, hand)

    def _my_active_spot(self):
        cur = self._cur
        if not cur:
            return None
        act = cur["players"][cur["yourIndex"]].get("active") or []
        return act[0] if act and act[0] else None

    def _dmg(self, op):
        # ジーランス(きおくにもぐる)でブリジュラスexが使える「レイジングハンマー」は、
        # 基底80＋自分に乗ったダメージ量。HP300のexが削れるほど高火力(削れていればメタル
        # ディフェンダー220を上回り、HP50まで削れれば330=メガスターミーをワンパン)。
        # 基底値(80)のままだと常にメタルディフェンダーが選ばれてしまうため正しく計算する。
        if op.attack_id == RAGING_HAMMER:
            sp = self._my_active_spot()
            if sp:
                taken = (sp.get("maxHp") or 0) - (sp.get("hp") or 0)
                return 80 + max(0, taken)
            return 80
        return super()._dmg(op)

    def _bench_thin(self) -> bool:
        """場のポケモン総数が1以下＝バックアップが無く donk 負けの危険がある状態。"""
        me = self._me()
        if not me:
            return False
        n = sum(1 for s in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if s)
        return n <= 1

    def _opt_value(self, opt) -> float:
        v = super()._opt_value(opt)
        cid = self._opt_card_id(opt)
        me = self._me() or {}
        hand = me.get("hand") or []
        has_ex = self._count_in_play(ARCH_EX) >= 1 or any(c.get("id") == ARCH_EX for c in hand)
        dura_avail = self._count_in_play(DURALUDON) + sum(1 for c in hand if c.get("id") == DURALUDON)
        # 攻撃役(ブリジュラスex)が場にも手札にも無く、進化元のジュラルドンは居る
        # → 進化先を最優先でサーチ(復旧プラン: たねを並べても攻撃役にならないと勝てない)。
        if cid == ARCH_EX and not has_ex and dura_avail >= 1:
            v += 60
        # ベンチが薄く、ジュラルドンがまだ2体未満の時だけ、たねを確保(donk/展開不足を防ぐ)。
        # 既に2体あるなら3体目より進化先や他パーツを優先(GAME2の事故=3体目を掴む を是正)。
        elif cid == DURALUDON and self._bench_thin() and dura_avail < 2:
            v += 50
        return v

    def _want_metal_in_discard(self) -> bool:
        """ごうきんビルド(進化時にトラッシュから鋼エネ2枚加速)の燃料を仕込むべきか。
        ブリジュラスexが手札にあり(=今/次の番に進化してごうきんビルドが撃てる)、進化先のジュラルドンが
        場におり、鋼エネが3枚以上余る(貼る分2枚を残す)、かつトラッシュの鋼がまだ2枚未満の時だけ捨てる。
        ※条件を緩めて捨てすぎると手貼り用の鋼が枯れ、鋼3(Metal Defender)到達率が下がる(A/B確認済)。"""
        me = self._me()
        if not me:
            return False
        ex_in_hand = any(c.get("id") == ARCH_EX for c in (me.get("hand") or []))
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        has_target = any(sp and sp.get("id") == DURALUDON for sp in spots)
        if not (ex_in_hand and has_target):
            return False
        hand_metal = sum(1 for c in (me.get("hand") or []) if c.get("id") == METAL)
        disc_metal = sum(1 for c in (me.get("discard") or []) if c.get("id") == METAL)
        return hand_metal >= 3 and disc_metal < 2

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
