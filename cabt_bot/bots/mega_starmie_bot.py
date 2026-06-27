"""Mega Starmie ex デッキ専用エージェント（フルスクラッチ）。

先に定めた「理想の処理順」を忠実に実装する。HeuristicBot は継承しない。

勝ち筋: ヒトデマン→メガスターミーex に進化し、毎ターン「イグニ1枚(=無3)→
ネビュラビーム210」でKOしてサイドを取り切る。脆さはエースバーン壁＋ポフィンで補う。

処理順（毎ターン、MAIN のたびに最優先フェーズを1つ実行）:
  ① 特性（無料の価値）
  ② サーチ/サポート/展開 (PLAY): ポフィンでベンチ→必要パーツ確保→進化補助サポート
     ・リーリエの決心はキーを抱える/手札が厚い時は切らない（自滅防止）
  ③ 進化: ヒトデマン→メガスターミーex（バトル場優先）
  ④ エネ加速: 進化後の攻撃役へ。イグニッションは進化体メガスターミーex最優先
  ⑤ 攻撃: 最大ダメージ（=ネビュラビーム210）。展開を終えてから

先攻/後攻:
  ・IS_FIRST は後攻を選ぶ（後攻はターン1から攻撃でき、即ネビュラビーム210を狙える）
  ・後攻T1は上記順で攻撃まで到達。先攻T1は engine が攻撃を出さないので自然にセットアップ止まり。
"""

from __future__ import annotations

from .base import Bot
from ..cards import load_cards
from ..enums import AreaType, OptionType, SelectContext, SelectType
from ..models import Observation, Option

# --- Card IDs (data/cards.json と一致) ---
STARYU = 1030          # ヒトデマン (basic)
MEGA_STARMIE = 1031    # メガスターミーex (1進化, 攻撃役)
CINDERACE = 666        # エースバーン (設置壁)
IGNITION = 17          # イグニッションエネルギー（進化体で無3）
WATER = 3              # 基本水エネルギー
POFFIN = 1086          # なかよしポフィン（たね2匹ベンチ）
MEGA_SIGNAL = 1145     # メガシンカexサーチ
POKE_PAD = 1152        # 非ルールポケモンサーチ
SAGE = 1189            # セイジ（山から直接進化）
HILDA = 1225           # トウコ（進化ポケ＋エネ）
BOSS = 1182            # ボスの指令
LILLIE = 1227          # リーリエの決心（手札全部を山に戻して引き直し）
SWITCH = 1123          # ポケモンいれかえ
NIGHT_STRETCHER = 1097  # 夜のタンカ
HEROS_CAPE = 1159      # ヒーローマント (ACE SPEC, +100HP)
MITSURU = 1229         # ミツルの思いやり（メガ回復＋エネ手札戻し）

# PLAY するカードの優先度（高いほど先に出す）
_PLAY_SCORE = {
    POFFIN: 100,        # ベンチ展開＝最優先（事故負け防止）
    MEGA_SIGNAL: 86, POKE_PAD: 82,  # 必要パーツのサーチ
    STARYU: 80,         # たねをベンチに（展開）
    SAGE: 74, HILDA: 72,  # 進化補助
    SWITCH: 64,         # 位置調整（エネを払わずに前後入替）
    BOSS: 62,           # 引きずり出し（攻撃前）
    NIGHT_STRETCHER: 50,
    MITSURU: 45,        # 回復（エネ戻りデメリットあり）
}

# カード選択（サーチで取る/捨てる）の価値
_VALUE = {
    MEGA_STARMIE: 100, IGNITION: 92, STARYU: 84, CINDERACE: 78, WATER: 64,
    POFFIN: 58, MEGA_SIGNAL: 56, BOSS: 55, HILDA: 52, SAGE: 52,
    POKE_PAD: 50, SWITCH: 48, NIGHT_STRETCHER: 46, HEROS_CAPE: 44, MITSURU: 40,
    LILLIE: 34,
}
_DEFAULT_VALUE = 42

# サーチで「最大数を取りに行く」と得な文脈
_TAKE_CONTEXTS = {
    SelectContext.TO_HAND, SelectContext.TO_FIELD, SelectContext.TO_ACTIVE,
    SelectContext.TO_BENCH, SelectContext.SETUP_ACTIVE_POKEMON,
    SelectContext.SETUP_BENCH_POKEMON, SelectContext.EVOLVES_FROM,
    SelectContext.EVOLVES_TO, SelectContext.TO_HAND_ENERGY,
    SelectContext.HEAL, SelectContext.REMOVE_DAMAGE_COUNTER,
}
# 「手放す」文脈（最小数・低価値から）
_GIVE_CONTEXTS = {
    SelectContext.DISCARD, SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
    SelectContext.TO_PRIZE, SelectContext.DISCARD_ENERGY,
    SelectContext.DISCARD_ENERGY_CARD, SelectContext.DISCARD_TOOL_CARD,
    SelectContext.DISCARD_CARD_OR_ATTACHED_CARD, SelectContext.TO_DECK_ENERGY,
    SelectContext.DEVOLVE,
}


class MegaStarmieBot(Bot):
    def __init__(self, go_first: bool = False) -> None:
        self.go_first = go_first
        try:
            self._cards = load_cards()
        except Exception:
            self._cards = {}
        self._attack_dmg: dict[int, int] | None = None
        self._cur = None
        self._sel = None

    # ===== entry =====
    def select(self, obs: Observation) -> list[int]:
        sel = obs.select
        if sel is None or not sel.options:
            return []
        self._cur = obs.current
        self._sel = sel
        try:
            t = sel.type
            if t == SelectType.MAIN:
                return self._main(sel.options)
            if t == SelectType.ATTACK:
                return [self._best_attack(range(len(sel.options)), sel.options)]
            if t == SelectType.YES_NO:
                return [self._yes_no(sel)]
            if t == SelectType.COUNT:
                return [max(range(len(sel.options)),
                            key=lambda i: sel.options[i].number or 0)]
            if t in (SelectType.CARD, SelectType.ATTACHED_CARD,
                     SelectType.CARD_OR_ATTACHED_CARD, SelectType.ENERGY):
                return self._cards(sel)
            # EVOLVE / SKILL / SPECIAL_CONDITION 等
            return self._take(sel, prefer_high=True, take_max=False)
        except Exception:
            return self._legal_fallback(sel)

    # ===== MAIN: 処理順 =====
    def _main(self, options: list[Option]) -> list[int]:
        me = self._me()
        hand = (me.get("hand") or []) if me else []
        g: dict = {}
        for i, op in enumerate(options):
            g.setdefault(op.type, []).append(i)

        # ① 特性
        if OptionType.ABILITY in g:
            return [g[OptionType.ABILITY][0]]
        # ② サーチ/サポート/展開
        if OptionType.PLAY in g:
            c = self._pick_play(g[OptionType.PLAY], options, hand)
            if c is not None:
                return [c]
        # ③ 進化
        if OptionType.EVOLVE in g:
            return [self._pick_evolve(g[OptionType.EVOLVE], options, hand)]
        # ④ エネ加速
        if OptionType.ATTACH in g:
            return [self._pick_attach(g[OptionType.ATTACH], options, hand, me)]
        # ⑤ 攻撃（最大ダメージ＝ネビュラビーム210）
        if OptionType.ATTACK in g:
            return [self._best_attack(g[OptionType.ATTACK], options)]
        # 位置調整(RETREAT)は基本避ける → END 優先
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
        if not scored:
            return None
        return max(scored, key=lambda x: x[0])[1]

    def _play_score(self, cid, hand):
        if cid == LILLIE:
            # キー(メガスターミーex/ヒトデマン)を抱える or 手札が厚い時は切らない
            if self._has_key(hand) or len(hand) >= 4:
                return None
            return 28
        return _PLAY_SCORE.get(cid, 40)

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

    # ===== 攻撃 =====
    def _best_attack(self, idxs, options) -> int:
        return max(idxs, key=lambda i: self._dmg(options[i]))

    def _dmg(self, op: Option) -> int:
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

    # ===== YesNo =====
    def _yes_no(self, sel) -> int:
        ctx = sel.context
        want_yes = True
        if isinstance(ctx, SelectContext):
            if ctx == SelectContext.IS_FIRST:
                want_yes = self.go_first
            elif ctx == SelectContext.MORE_DEVOLVE:
                want_yes = False
        target = OptionType.YES if want_yes else OptionType.NO
        for i, op in enumerate(sel.options):
            if op.type == target:
                return i
        return 0

    # ===== カード選択（サーチ/捨て） =====
    def _cards(self, sel) -> list[int]:
        ctx = sel.context
        # セットアップのバトル場はエースバーン壁を優先、無ければヒトデマン
        if isinstance(ctx, SelectContext) and ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            pref = self._first_of(sel, [CINDERACE, STARYU])
            if pref is not None:
                return [pref]
        give = isinstance(ctx, SelectContext) and ctx in _GIVE_CONTEXTS
        take = isinstance(ctx, SelectContext) and ctx in _TAKE_CONTEXTS
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
        ranked = sorted(range(n),
                        key=lambda i: self._opt_value(sel.options[i]),
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
        return any(c.get("id") in (MEGA_STARMIE, STARYU) for c in hand)

    def _opt_card_id(self, op: Option):
        """選択肢が指すカードIDを最善努力で解決。"""
        if op.card_id is not None:
            return op.card_id
        me = self._me()
        area, idx = op.area, op.index
        if idx is None:
            return None
        # 山札サーチ: select.deck から
        if self._sel is not None and self._sel.deck and area == AreaType.DECK:
            if 0 <= idx < len(self._sel.deck):
                return self._sel.deck[idx].card_id
        if me is None:
            return None
        zone = {
            AreaType.HAND: me.get("hand"),
            AreaType.ACTIVE: me.get("active"),
            AreaType.BENCH: me.get("bench"),
            AreaType.DISCARD: me.get("discard"),
        }.get(area)
        if zone and 0 <= idx < len(zone) and zone[idx]:
            return zone[idx].get("id")
        return None

    def _opt_value(self, op: Option) -> int:
        cid = self._opt_card_id(op)
        if cid is None:
            return _DEFAULT_VALUE
        return _VALUE.get(cid, _DEFAULT_VALUE)

    @staticmethod
    def _legal_fallback(sel) -> list[int]:
        n = len(sel.options)
        k = min(max(1, sel.min_count), n)
        return list(range(k))
