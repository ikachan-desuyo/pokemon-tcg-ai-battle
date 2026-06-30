"""ValueModelBot: 学習価値モデル(状態→勝率)を実戦の評価関数に使うbot(depth-1学習評価)。

各MAIN候補手をエンジンのsearch APIでfork→自分の番をrollout方策(既定:専用DeckBot)で
完了させ、ターン終了(相手番/終局)時の盤面を『価値モデル』で採点→最高評価の手を選ぶ。
SearchBot(全playout=10分制限で不採用)と違い、1手先の盤面を価値ネットで即評価＝高速。
LLMの埋め込み理論をポケカに適用したAlphaZero型の価値ネットを、実戦の意思決定に投入する実証。
"""
from __future__ import annotations
import dataclasses, json, math
from ..models import Observation
from ..state_encoder import encode_state  # カード能力ベースの共通エンコーダ
from .search_bot import SearchBot


class ValueModelBot(SearchBot):
    def __init__(self, decklist, model_path="out/value_model.json", rollout_policy=None,
                 move_time_budget: float = 2.5):
        super().__init__(decklist, move_time_budget=move_time_budget, rollout_policy=rollout_policy)
        m = json.load(open(model_path, encoding="utf-8"))
        self.w, self.b, self.mu, self.sd = m["w"], m["b"], m["mu"], m["sd"]

    def _value(self, cur_dict, our_idx) -> float:
        f = encode_state(cur_dict, our_idx)
        z = self.b
        for k in range(len(f)):
            z += self.w[k] * (f[k] - self.mu[k]) / (self.sd[k] or 1e-9)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def _search_main(self, obs_dict):
        from cg.api import search_begin, search_end, search_step
        from cg.api import to_observation_class
        import time
        deadline = time.monotonic() + self.move_time_budget
        o = to_observation_class(obs_dict)
        raw = obs_dict["current"]; our_idx = raw["yourIndex"]
        me = raw["players"][our_idx]; op = raw["players"][1 - our_idx]
        n_opt = len(o.select.option)
        yd, yp = self._determinize_self(me)
        od = self._filler(op["deckCount"]); oh = self._filler(op["handCount"]); opz = self._filler(len(op["prize"]))
        oa = [] if (op["active"] and op["active"][0]) else [self._basics[0]]
        try:
            root = search_begin(o, yd, yp, od, opz, oh, oa, False)
        except Exception:
            return None
        scores = [None] * n_opt
        try:
            for i in range(n_opt):
                if time.monotonic() >= deadline:
                    break
                try:
                    child = search_step(root.searchId, [i])
                except Exception:
                    continue
                scores[i] = self._eval_after_turn(child, our_idx, search_step, deadline)
        finally:
            try: search_end()
            except Exception: pass
        if all(s is None for s in scores):
            return None
        return [max(range(n_opt), key=lambda i: (scores[i] if scores[i] is not None else -1.0))]

    def _eval_after_turn(self, state, our_idx, search_step, deadline) -> float:
        """自分の番を rollout 方策で完了→ターン終了(相手番/終局)時の盤面を価値モデルで採点。"""
        import time
        res = state
        for _ in range(40):
            ob = res.observation; cur = ob.current
            if cur is None:
                break
            if cur.result != -1:
                return 1.0 if cur.result == our_idx else 0.0
            if cur.yourIndex != our_idx:   # 相手の番になった = 自分のターン終了
                break
            if ob.select is None or not ob.select.option or time.monotonic() >= deadline:
                break
            sel = self.policy.select(Observation.from_dict(dataclasses.asdict(ob))) or [0]
            try:
                res = search_step(res.searchId, sel)
            except Exception:
                break
        cur = res.observation.current
        if cur is None:
            return 0.0
        return self._value(dataclasses.asdict(cur), our_idx)
