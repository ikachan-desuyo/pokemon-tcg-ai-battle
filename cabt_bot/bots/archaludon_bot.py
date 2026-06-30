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

    def _play_score(self, cid, hand):
        # ジーランスは特性(きおくにもぐる)が重複しないため、場に1匹で十分。
        # 既に場に居るなら出さない(2匹目以降はベンチ枠とテンポの無駄＝GPTレビュー指摘)。
        if cid == RELICANTH:
            return None if self._count_in_play(RELICANTH) >= 1 else 87
        # ポケパッド(ルール無しポケサーチ): たね/ジーランスが足りない時のみ価値あり。
        # 盤面が揃っている(場のポケモン4体以上＋ジーランス済)なら温存(無駄なサーチ＝山札を薄くしない)。
        if cid == POKE_PAD:
            me = self._me()
            n = sum(1 for s in [((me or {}).get("active") or [None])[0]] + list((me or {}).get("bench") or []) if s)
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
        # ベンチが薄い時は、唯一のたねであるジュラルドンを最優先で確保・展開する
        # (サーチで進化先を優先して掴み、バックアップを作らず donk 負けするのを防ぐ)。
        if self._opt_card_id(opt) == DURALUDON and self._bench_thin():
            v += 50
        return v

    def _want_metal_in_discard(self) -> bool:
        """ごうきんビルド(進化時にトラッシュから鋼エネ2枚加速)の燃料を仕込むべきか。
        ブリジュラスexが手札にあり(=今/次の番に進化してごうきんビルドが撃てる)、進化先のジュラルドンが
        場におり、鋼エネが3枚以上余る(貼る分2枚を残す)、かつトラッシュの鋼がまだ2枚未満の時だけ捨てる。
        早すぎる仕込みは手貼り用の鋼エネを枯渇させるため、条件を厳しくする。"""
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
