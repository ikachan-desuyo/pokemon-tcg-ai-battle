"""Rollout-search agent.

At a MAIN decision, it forks each legal option through the engine's search API,
plays the rest of the game out with HeuristicBot as the rollout policy, and picks
the option with the best rollout win rate. Everything else (non-MAIN selections,
errors, missing engine, or running low on the per-move time budget) falls back to
HeuristicBot, so the agent is always safe and never crashes.

Hidden information is determinized each search:
- our deck/prize are inferred from the decklist minus visible cards,
- the opponent's hidden cards are filled with placeholder Basics (they don't act
  during our turn, so their exact identity rarely affects the immediate choice).

The agent operates on the raw obs dict (it needs `search_begin_input`), unlike the
Bot subclasses which take a parsed Observation.
"""

from __future__ import annotations

import dataclasses
import random
import time
from collections import Counter

from ..cards import load_cards
from ..enums import SelectType
from ..models import Observation
from .heuristic_bot import HeuristicBot


class SearchBot:
    def __init__(
        self,
        decklist,
        determinizations: int = 1,
        rollouts: int = 2,
        max_rollout_steps: int = 400,
        move_time_budget: float = 3.0,
        rng_seed: int = 0,
    ) -> None:
        self.deck = [int(x) for x in decklist]
        self.D = determinizations
        self.R = rollouts
        self.max_rollout_steps = max_rollout_steps
        self.move_time_budget = move_time_budget
        self.policy = HeuristicBot()
        self.rng = random.Random(rng_seed)
        try:
            cards = load_cards()
        except Exception:
            cards = {}
        self._basics = [cid for cid, c in cards.items() if c.is_basic][:8] or [1]
        self._enabled = self._probe_engine()

    @staticmethod
    def _probe_engine() -> bool:
        try:
            from cg.api import search_begin  # noqa: F401
            return True
        except Exception:
            return False

    # ----- entry point (raw obs dict) -------------------------------

    def __call__(self, obs_dict: dict) -> list[int]:
        try:
            if not obs_dict.get("select"):
                return []  # deck selection handled by caller
            if self._should_search(obs_dict):
                result = self._search_main(obs_dict)
                if result is not None:
                    return result
        except Exception:
            pass
        return self._policy_select(obs_dict)

    def _policy_select(self, obs_dict: dict) -> list[int]:
        return self.policy.select(Observation.from_dict(obs_dict))

    def _should_search(self, obs_dict: dict) -> bool:
        if not self._enabled:
            return False
        sel = obs_dict.get("select") or {}
        opts = sel.get("option") or []
        return (
            sel.get("type") == int(SelectType.MAIN)
            and len(opts) > 1
            and bool(obs_dict.get("search_begin_input"))
            and obs_dict.get("current") is not None
        )

    # ----- search ---------------------------------------------------

    def _search_main(self, obs_dict: dict):
        from cg.api import search_begin, search_end, search_step, to_observation_class

        deadline = time.monotonic() + self.move_time_budget
        o = to_observation_class(obs_dict)
        raw = obs_dict["current"]
        our_idx = raw["yourIndex"]
        me = raw["players"][our_idx]
        op = raw["players"][1 - our_idx]
        n_opt = len(o.select.option)
        wins = [0] * n_opt
        plays = [0] * n_opt

        for _d in range(self.D):
            if time.monotonic() >= deadline:
                break
            yd, yp = self._determinize_self(me)
            od = self._filler(op["deckCount"])
            oh = self._filler(op["handCount"])
            opz = self._filler(len(op["prize"]))
            oa = [] if (op["active"] and op["active"][0]) else [self._basics[0]]
            try:
                root = search_begin(o, yd, yp, od, opz, oh, oa, False)
            except Exception:
                continue
            try:
                for i in range(n_opt):
                    for _r in range(self.R):
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        try:
                            child = search_step(root.searchId, [i])
                        except Exception:
                            continue
                        wins[i] += self._rollout(child, our_idx, search_step)
                        plays[i] += 1
            except TimeoutError:
                pass
            finally:
                try:
                    search_end()
                except Exception:
                    pass

        if not any(plays):
            return None  # nothing evaluated -> caller falls back to policy
        scores = [(wins[i] / plays[i]) if plays[i] else -1.0 for i in range(n_opt)]
        return [max(range(n_opt), key=lambda i: scores[i])]

    def _rollout(self, state, our_idx, search_step) -> int:
        res = state
        for _ in range(self.max_rollout_steps):
            ob = res.observation
            cur = ob.current
            if cur is not None and cur.result != -1:
                return 1 if cur.result == our_idx else 0
            if ob.select is None or not ob.select.option:
                return 0
            sel = self.policy.select(Observation.from_dict(dataclasses.asdict(ob)))
            if not sel:
                sel = [0]
            try:
                res = search_step(res.searchId, sel)
            except Exception:
                return 0
        return 0

    # ----- determinization ------------------------------------------

    def _determinize_self(self, me: dict):
        rem = Counter(self.deck) - self._known_cards(me)
        pool: list[int] = []
        for cid, n in rem.items():
            pool += [cid] * n
        self.rng.shuffle(pool)
        dc, pc = me["deckCount"], len(me["prize"])
        if len(pool) < dc + pc:  # safety: pad with a basic energy id
            pool += [3] * (dc + pc - len(pool))
        return pool[:dc], pool[dc:dc + pc]

    @staticmethod
    def _known_cards(me: dict) -> Counter:
        c: Counter = Counter()
        for cd in (me.get("hand") or []) + (me.get("discard") or []):
            c[cd["id"]] += 1
        for sp in (me.get("active") or []) + (me.get("bench") or []):
            if not sp:
                continue
            c[sp["id"]] += 1
            for key in ("preEvolution", "energyCards", "tools"):
                for cc in sp.get(key) or []:
                    c[cc["id"]] += 1
        return c

    def _filler(self, n: int) -> list[int]:
        b = self._basics
        return [(b[i % len(b)] if i % 3 == 0 else 3) for i in range(n)]
