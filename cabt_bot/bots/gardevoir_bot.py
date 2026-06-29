"""Mega Gardevoir ex（メガサーナイトex）専用 bot。

汎用 DeckBot の設定(DeckPlan)に加え、メガサーナイト固有の多ターン判断を
オーバーライドで実装したカスタム bot。

ゲームプラン:
- ラルテス→キルリア→(ふしぎなアメ)→メガサーナイトex を立てる。
- メガシンフォニアは「自分の全ポケの超エネ数×50」なので、ベンチを広く保ち
  「あふれるねがい」(山札からベンチ全員に超エネを1枚ずつ)で母数を育ててから、
  倒せる火力になったら撃つ（lethal-aware）。
- キルリア「コールサイン」(3枚サーチ)でメガサーナイト/アメを掘る。
"""
from .deck_bot import DeckBot, DeckPlan

# メガサーナイト関連の attackId
SYMPHONIA = 1079   # メガシンフォニア: 盤面の超エネ数×50
OVERFLOW = 1078    # あふれるねがい: ベンチ全員に超エネ1枚ずつ(加速)
CALL_SIGN = 1076   # キルリア コールサイン: 山札からポケモン3枚サーチ
PSYCHIC_ENERGY = 5  # 基本【超】エネルギー
MEGA = 747         # メガサーナイトex

PLAN = DeckPlan(
    name="MegaGardevoir",
    go_first=True,
    attackers=(747, 746, 745),
    key_cards=(747, 746),
    energy_rules=((5, 747), (None, 747)),
    play_priority={745: 82, 746: 80, 1079: 90},  # ラルトスを厚めにベンチ展開
    card_values={747: 100, 746: 84, 745: 80, 5: 84},
    lethal=True,
    est_var_damage=True,
    smart_take=True,
    boss_cards=(1182,),
    recover_cards=(1097,),
)


class MegaGardevoirBot(DeckBot):
    plan = PLAN

    def _board_psychic(self) -> int:
        """自分の場(active+bench)に付いている【超】エネ総数（メガシンフォニアの母数）。"""
        me = self._me()
        if not me:
            return 0
        n = 0
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if not sp:
                continue
            for e in sp.get("energyCards") or sp.get("energies") or []:
                if (e.get("id") if isinstance(e, dict) else e) == PSYCHIC_ENERGY:
                    n += 1
        return n

    def _has_mega_access(self) -> bool:
        """メガサーナイトを場/手札に持っている（=もう掘らなくてよい）か。"""
        me = self._me()
        if not me:
            return False
        spots = [(me.get("active") or [None])[0]] + list(me.get("bench") or [])
        if any(sp and sp.get("id") == MEGA for sp in spots):
            return True
        return any(c.get("id") == MEGA for c in (me.get("hand") or []))

    def _best_attack(self, idxs, options) -> int:
        idxs = list(idxs)
        ids = {options[i].attack_id: i for i in idxs}

        # --- メガサーナイト稼働中: lethal-aware に「撃つ/母数を増やす」を選ぶ ---
        # 検証結果: この高速メタでは“積み過ぎ”は速度負け→倒せない時の加速は「序盤(母数<2)1回」だけに絞る。
        if SYMPHONIA in ids:
            hp, weak = self._opp_active_hp_weak()
            e = self._board_psychic()
            dmg = e * 50
            mt = self._my_active_type()
            if weak and mt and weak == mt:
                dmg *= 2
            # 倒せるなら即メガシンフォニア
            if hp is not None and dmg >= hp:
                return ids[SYMPHONIA]
            # 倒せない＆母数がまだ薄い(序盤)＆ベンチ有り → 1回だけ加速して立ち上げる
            if OVERFLOW in ids and e < 2:
                me = self._me()
                if me and [s for s in (me.get("bench") or []) if s]:
                    return ids[OVERFLOW]
            # それ以外は今ある母数で殴る（積み過ぎず速度を維持）
            return ids[SYMPHONIA]

        # --- キルリア稼働中: メガサーナイト未確保ならコールサインで掘る ---
        if CALL_SIGN in ids and not self._has_mega_access():
            return ids[CALL_SIGN]

        return super()._best_attack(idxs, options)
