"""ImitationBot: 1位ブリジュラス(ShumpeiNomura)の行動クローン方策で打つbot。

学習済み方策(out/archaludon_policy.json)で各選択肢を採点し、本人が選びそうな手を選ぶ。
選択肢の解決・特徴量化は学習時(tools/train_policy.py)と同じ cabt_bot.imitation を使うため一致する。
方策が弱い/未対応の選択は安全なフォールバック(個数調整・最大値)で必ず有効手を返す。
"""
from __future__ import annotations
import json, os
from .base import Bot
from ..models import Observation
from ..imitation import resolve, board_ctx, featurize, FEATURE_DIM, policy_scores

try:
    from cg.api import all_attack
    _ATK_DMG = {a.attackId: (getattr(a, "damage", 0) or 0) for a in all_attack()}
except Exception:
    _ATK_DMG = {}


class ImitationBot(Bot):
    def __init__(self, decklist=None, policy_path="out/archaludon_policy.json", attack_bias=0.0):
        self.decklist = decklist
        self.attack_bias = attack_bias   # 学習方策の系統的な過少攻撃を校正するバイアス
        self.params = None
        try:
            m = json.load(open(policy_path, encoding="utf-8"))
            if m.get("feature_dim") == FEATURE_DIM:
                self.params = m
        except Exception:
            self.params = None

    def select(self, obs: Observation) -> list[int]:
        sel = obs.select
        if sel is None or not sel.options:
            return []
        n = len(sel.options)
        lo = max(0, sel.min_count); hi = min(sel.max_count, n)
        cur = obs.current
        if self.params is None or cur is None:
            return self._fallback(sel, lo, hi)
        try:
            me = cur.get("yourIndex", 0)
            ctx = board_ctx(cur, me)
            X = [featurize(ctx, resolve(op.raw, cur, me), _ATK_DMG) for op in sel.options]
            scores = list(policy_scores(X, self.params))
            if self.attack_bias:
                for i, op in enumerate(sel.options):
                    if op.type == 13:               # ATTACK
                        scores[i] += self.attack_bias
        except Exception:
            return self._fallback(sel, lo, hi)
        order = sorted(range(n), key=lambda i: scores[i], reverse=True)
        k = max(lo, 1) if hi >= 1 else lo
        k = min(k, hi) if hi > 0 else lo
        return sorted(order[:k]) if k > 0 else []

    def _fallback(self, sel, lo, hi):
        # NUMBER(個数)は最大、その他は先頭から必要数
        if sel.options and sel.options[0].type == 0:
            best = max(range(len(sel.options)), key=lambda i: sel.options[i].number or 0)
            return [best]
        k = max(lo, 1) if hi >= 1 else lo
        return list(range(min(k, hi))) if hi > 0 else []

    def on_deck_selection(self, obs: Observation):
        return list(self.decklist) if self.decklist else None
