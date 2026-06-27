"""Submission entry point for the cabt (Pokémon TCG AI Battle) environment.

The engine calls `agent(obs_dict)` each turn; it must return a list of chosen
option indices. When `obs.select` is None it is the initial deck selection and
the agent returns 60 card IDs. The agent never raises: on any failure it returns
a legal fallback.
"""

from __future__ import annotations

import os
import sys

# Kaggle は main.py を exec() で読み込むため __file__ が無い場合がある。
# 依存せずに、想定されるエージェントディレクトリを import パスへ追加する。
_CANDIDATES = []
try:
    _CANDIDATES.append(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass
_CANDIDATES += ["/kaggle_simulations/agent", os.getcwd()]
for _p in _CANDIDATES:
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)
_HERE = _CANDIDATES[0]

from cabt_bot import Observation
from cabt_bot.bots import HeuristicBot, SearchBot


def read_deck_csv() -> list[int]:
    path = "deck.csv"
    if not os.path.exists(path):
        kaggle_path = "/kaggle_simulations/agent/deck.csv"
        path = kaggle_path if os.path.exists(kaggle_path) else os.path.join(_HERE, "deck.csv")
    deck: list[int] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f.read().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            deck.append(int(line.split(",")[0]))
            if len(deck) == 60:
                break
    return deck


def _load_decklist() -> list[int]:
    try:
        return read_deck_csv()
    except Exception:
        return []


# SearchBot は cg(エンジン)があれば先読み探索、無ければ内部で HeuristicBot に委譲。
# 生 obs_dict を取り、常に合法手を返す。
try:
    BOT = SearchBot(_load_decklist())
except Exception:
    BOT = HeuristicBot()


def _fallback(obs_dict: dict) -> list[int]:
    try:
        sel = obs_dict.get("select")
        if not sel:
            return read_deck_csv()
        n = len(sel.get("option", []))
        return list(range(min(max(1, int(sel.get("minCount", 1))), n)))
    except Exception:
        return [0]


def agent(obs_dict: dict, *_args) -> list[int]:
    try:
        if not obs_dict.get("select"):
            return read_deck_csv()  # initial deck selection
        if isinstance(BOT, SearchBot):
            return BOT(obs_dict)
        return BOT.select(Observation.from_dict(obs_dict))
    except Exception:
        return _fallback(obs_dict)
