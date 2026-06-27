"""Mega Starmie ex デッキ専用エージェント。

理想の処理順をデッキ知識で実装（HeuristicBot を継承して安全性を継承）:
- 後攻を選ぶ（ターン1からネビュラビーム210を狙える）
- リーリエの決心は手札が弱いときだけ（メガスターミーex等のキーを抱えてる時は切らない）
- なかよしポフィン等でベンチ展開を優先（場のポケモン切れ＝即負けを防ぐ）
- エネは進化後の攻撃役へ。イグニッションは進化体メガスターミーexに優先
- 進化はメガスターミーex／バトル場を優先
- 攻撃は最大ダメージ（＝ネビュラビーム210）。これは親 HeuristicBot の挙動

勝ち筋: ヒトデマン→メガスターミーex に進化し、毎ターン「イグニ1枚→ネビュラビーム210」で
KOしてサイドを取り切る。脆さはエースバーン壁＋ポフィンで補う。
"""

from __future__ import annotations

from ..enums import AreaType, OptionType, SelectContext
from ..models import Observation, Option
from .heuristic_bot import HeuristicBot

# Card IDs (data/cards.json と一致)
STARYU = 1030        # ヒトデマン
MEGA_STARMIE = 1031  # メガスターミーex
CINDERACE = 666      # エースバーン
IGNITION = 17        # イグニッションエネルギー（進化体で無3）
WATER = 3            # 基本水エネルギー
LILLIE = 1227        # リーリエの決心（手札全部を山に戻して引き直し）
POFFIN = 1086        # なかよしポフィン（たね2匹ベンチ）
MEGA_SIGNAL = 1145   # メガシンカexサーチ
POKE_PAD = 1152      # 非ルールポケモンサーチ
SAGE = 1189          # セイジ（山から直接進化）
HILDA = 1225         # トウコ（進化ポケ＋エネ）
BOSS = 1182          # ボスの指令

# PLAY 候補のカード優先度（高いほど先に出す）
_PLAY_SCORE = {
    POFFIN: 100,       # ベンチ展開＝最優先
    MEGA_SIGNAL: 80,   # メガスターミーexを手札へ
    POKE_PAD: 75,
    SAGE: 70, HILDA: 70,  # 進化補助サポート
    BOSS: 65,
}


class MegaStarmieBot(HeuristicBot):
    def select(self, obs: Observation) -> list[int]:
        self._cur = obs.current  # 盤面（dict）を退避
        return super().select(obs)

    # --- 後攻を選ぶ ---
    def _yes_no(self, obs: Observation) -> int:
        ctx = obs.select.context
        if isinstance(ctx, SelectContext) and ctx == SelectContext.IS_FIRST:
            for i, op in enumerate(obs.select.options):
                if op.type == OptionType.NO:  # NO = 後攻
                    return i
            return 0
        return super()._yes_no(obs)

    # --- メイン: デッキ知識で具体的な手を選ぶ ---
    def _main(self, options: list[Option]) -> list[int]:
        try:
            r = self._main_smart(options)
            if r is not None:
                return r
        except Exception:
            pass
        return super()._main(options)

    def _main_smart(self, options: list[Option]):
        me = self._me()
        if me is None:
            return None
        hand = me.get("hand") or []
        by: dict = {}
        for i, op in enumerate(options):
            by.setdefault(op.type, []).append(i)

        if OptionType.ABILITY in by:
            return [by[OptionType.ABILITY][0]]
        if OptionType.EVOLVE in by:
            return [self._pick_evolve(by[OptionType.EVOLVE], options, hand)]
        if OptionType.PLAY in by:
            c = self._pick_play(by[OptionType.PLAY], options, hand)
            if c is not None:
                return [c]
            # 良い PLAY が無い（弱手札でないのにリーリエだけ等）→ 次の優先へ
        if OptionType.ATTACH in by:
            return [self._pick_attach(by[OptionType.ATTACH], options, hand, me)]
        if OptionType.ATTACK in by:
            return [max(by[OptionType.ATTACK], key=lambda i: self._dmg_of(options[i]))]
        if OptionType.END in by:
            return [by[OptionType.END][0]]
        return [0]

    # --- 各選択の中身 ---
    def _pick_evolve(self, idxs, options, hand) -> int:
        best, best_key = idxs[0], (-1, -1)
        for i in idxs:
            op = options[i]
            evo = self._hand_id(hand, op.index)
            key = (1 if evo == MEGA_STARMIE else 0,
                   1 if op.in_play_area == AreaType.ACTIVE else 0)
            if key > best_key:
                best_key, best = key, i
        return best

    def _pick_play(self, idxs, options, hand):
        scored = []
        for i in idxs:
            cid = self._hand_id(hand, options[i].index)
            s = self._play_score(cid, hand)
            if s is None:
                continue
            scored.append((s, i))
        if not scored:
            return None
        return max(scored, key=lambda x: x[0])[1]

    def _play_score(self, cid, hand):
        if cid == LILLIE:
            # キーを抱えている / 手札が厚い ときは引き直さない（自滅防止）
            if self._has_key(hand) or len(hand) >= 4:
                return None
            return 30
        return _PLAY_SCORE.get(cid, 50)

    def _pick_attach(self, idxs, options, hand, me) -> int:
        best, best_key = idxs[0], (-1, -1, -1)
        for i in idxs:
            op = options[i]
            energy = self._hand_id(hand, op.index)
            target = self._target_id(me, op.in_play_area, op.in_play_index)
            tgt_mega = 1 if target == MEGA_STARMIE else 0
            key = (
                1 if (energy == IGNITION and tgt_mega) else 0,   # イグニ→進化体最優先
                tgt_mega,                                        # 攻撃役へ
                1 if op.in_play_area == AreaType.ACTIVE else 0,  # バトル場へ
            )
            if key > best_key:
                best_key, best = key, i
        return best

    # --- ヘルパ ---
    def _me(self):
        cur = getattr(self, "_cur", None)
        if not cur:
            return None
        return cur["players"][cur["yourIndex"]]

    @staticmethod
    def _hand_id(hand, idx):
        if idx is None or idx < 0 or idx >= len(hand):
            return None
        return hand[idx].get("id")

    @staticmethod
    def _target_id(me, area, idx):
        if idx is None:
            return None
        spots = me.get("active") if area == AreaType.ACTIVE else me.get("bench")
        spots = spots or []
        if 0 <= idx < len(spots) and spots[idx]:
            return spots[idx].get("id")
        return None

    @staticmethod
    def _has_key(hand) -> bool:
        return any(c.get("id") == MEGA_STARMIE for c in hand)
