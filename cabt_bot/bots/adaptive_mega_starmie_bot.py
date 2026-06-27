"""相手デッキを判定し、マッチアップ別の方針に切り替える MegaStarmie エージェント。

MegaStarmieBot（理想形）を継承し、相手の見せたカードからアーキタイプを推定して
プロファイル（先攻可否・攻撃方針・ボス優先対象）を切り替える。判定不能なら理想形。
"""

from __future__ import annotations

from ..enums import AreaType, SelectContext
from ..meta import DEFAULT_PROFILE, identify, profile_for
from .mega_starmie_bot import MegaStarmieBot


class AdaptiveMegaStarmieBot(MegaStarmieBot):
    def __init__(self, go_first: bool = False) -> None:
        super().__init__(go_first=go_first)
        self._seen: set[int] = set()
        self._arch: str | None = None
        self._profile = dict(DEFAULT_PROFILE)
        self._jet_ids = None

    @property
    def archetype(self) -> str | None:
        return self._arch

    def select(self, obs):
        self._observe(obs)
        return super().select(obs)

    # --- 相手カードの観測と判定 ---
    def _observe(self, obs) -> None:
        cur = obs.current
        if not cur:
            return
        opp_idx = 1 - cur["yourIndex"]
        opp = cur["players"][opp_idx]
        for sp in (opp.get("active") or []) + (opp.get("bench") or []):
            if not sp:
                continue
            self._seen.add(sp.get("id"))
            for k in ("preEvolution", "energyCards", "tools"):
                for cc in sp.get(k) or []:
                    self._seen.add(cc.get("id"))
        for cd in opp.get("discard") or []:
            self._seen.add(cd.get("id"))
        for lg in (obs.logs or []):
            if lg.get("playerIndex") == opp_idx and lg.get("cardId"):
                self._seen.add(lg.get("cardId"))
        self._seen.discard(None)
        arch = identify(self._seen)
        if arch != self._arch:
            self._arch = arch
            self._profile = profile_for(arch)

    # --- 先攻/後攻はプロファイル準拠 ---
    def _yes_no(self, sel) -> int:
        ctx = sel.context
        if isinstance(ctx, SelectContext) and ctx == SelectContext.IS_FIRST:
            self.go_first = bool(self._profile.get("go_first", False))
        return super()._yes_no(sel)

    # --- 攻撃方針（nebula=最大火力 / spread=ジェットブロー） ---
    def _best_attack(self, idxs, options) -> int:
        idxs = list(idxs)
        if self._profile.get("attack_mode") == "spread":
            jets = [i for i in idxs if options[i].attack_id in self._jetting_ids()]
            if jets:
                return jets[0]
        return super()._best_attack(idxs, options)

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
                self._jet_ids = {a.attackId for a in all_attack() if a.name == "Jetting Blow"}
            except Exception:
                self._jet_ids = set()
        return self._jet_ids

    # --- ボス等の「相手を選ぶ」選択は gust_targets を優先 ---
    def _cards(self, sel) -> list[int]:
        targets = self._profile.get("gust_targets") or []
        if targets:
            pick = self._opponent_target_choice(sel, targets)
            if pick is not None:
                return [pick]
        return super()._cards(sel)

    def _opponent_target_choice(self, sel, targets):
        cur = self._cur
        if not cur:
            return None
        opp_idx = 1 - cur["yourIndex"]
        opp = cur["players"][opp_idx]
        cand = []
        for i, op in enumerate(sel.options):
            if op.player_index == opp_idx:
                cand.append((i, self._zone_card(opp, op.area, op.index)))
        if not cand:
            return None
        for t in targets:
            for i, cid in cand:
                if cid == t:
                    return i
        return None  # 相手対象だが優先対象なし → 通常ロジックに委譲

    @staticmethod
    def _zone_card(player, area, idx):
        if idx is None:
            return None
        spots = {
            AreaType.ACTIVE: player.get("active"),
            AreaType.BENCH: player.get("bench"),
            AreaType.DISCARD: player.get("discard"),
        }.get(area)
        spots = spots or []
        if 0 <= idx < len(spots) and spots[idx]:
            return spots[idx].get("id")
        return None
