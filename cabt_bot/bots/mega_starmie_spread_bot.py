"""Mega Starmie ex「スプレッド（ばらまき）」型専用エージェント（meta 準拠の試作）。

勝ち筋: メガスターミーex のジェットブロー(120+ベンチ50)でばらまき、マシマシラ
(Munkidori)の特性アドレナブレイン（悪エネ要）でダメカンを相手に寄せ、ユキメノコ
(Froslass)の自動ダメカンも絡めて多面KO→サイドを取り切る。

MegaStarmieBot を継承し、スプレッド軸の差分のみ上書き:
- 攻撃は「ジェットブロー」を優先（ネビュラビーム単発より、ばらまき＋ダメカン操作）
- エネは「悪→マシマシラ（特性起動）」を最優先、次に水→メガスターミーex
- マシマシラ/ユキメノコ系/ハイパーボールの展開を重視
"""

from __future__ import annotations

from ..enums import AreaType
from ..models import Option
from .heuristic_bot import HeuristicBot  # noqa: F401  (型参照の都合)
from .mega_starmie_bot import MegaStarmieBot, MEGA_STARMIE, WATER

MUNKIDORI = 112   # マシマシラ（特性: 悪エネで自分のダメカンを相手へ移動）
FROSLASS = 104    # ユキメノコ（特性: 毎ターン自動ダメカン）
SNORUNT = 103     # ユキワラシ
DARK = 7          # 基本悪エネルギー（マシマシラ特性用）
HYPER_BALL = 1121

# スプレッド軸での PLAY 優先度（親の値より優先）
_SPREAD_PLAY = {
    MUNKIDORI: 88,    # エンジン本体。たねなので手札から展開（ポフィン不可:HP110）
    HYPER_BALL: 84,   # マシマシラ/メガスターミーexを掘る
    SNORUNT: 76,      # フロスラスライン
}


class MegaStarmieSpreadBot(MegaStarmieBot):
    def __init__(self, go_first: bool = False) -> None:
        super().__init__(go_first=go_first)
        self._jet_ids = None

    # 攻撃はジェットブロー優先（無ければ最大ダメージ）
    def _best_attack(self, idxs, options) -> int:
        idxs = list(idxs)
        jets = [i for i in idxs if options[i].attack_id in self._jetting_ids()]
        if jets:
            return jets[0]
        return max(idxs, key=lambda i: self._dmg(options[i]))

    def _jetting_ids(self):
        if self._jet_ids is None:
            self._jet_ids = set()
            try:
                import sys
                from pathlib import Path
                root = str(Path(__file__).resolve().parents[2])
                if root not in sys.path:
                    sys.path.insert(0, root)
                from cg.api import all_attack  # type: ignore
                self._jet_ids = {a.attackId for a in all_attack()
                                 if a.name == "Jetting Blow"}
            except Exception:
                self._jet_ids = set()
        return self._jet_ids

    # エネ: 悪→マシマシラ（特性起動）最優先、次に 水→メガスターミーex
    def _pick_attach(self, idxs, options, hand, me) -> int:
        best, best_key = idxs[0], (-1, -1, -1, -1)
        for i in idxs:
            op = options[i]
            energy = self._hand_id(hand, op.index)
            target = self._target_id(me, op.in_play_area, op.in_play_index)
            key = (
                1 if (energy == DARK and target == MUNKIDORI) else 0,   # 悪→マシマシラ
                1 if (energy == WATER and target == MEGA_STARMIE) else 0,  # 水→メガ
                1 if target == MEGA_STARMIE else 0,
                1 if op.in_play_area == AreaType.ACTIVE else 0,
            )
            if key > best_key:
                best_key, best = key, i
        return best

    # 展開: スプレッド軸のカードを高評価
    def _play_score(self, cid, hand):
        if cid in _SPREAD_PLAY:
            return _SPREAD_PLAY[cid]
        return super()._play_score(cid, hand)
