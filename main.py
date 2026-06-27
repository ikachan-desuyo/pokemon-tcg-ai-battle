"""Submission entry point for the cabt (Pokémon TCG AI Battle) environment.

The engine calls `agent(obs_dict)` each turn; it must return a list of chosen
option indices. When `obs.select` is None it is the initial deck selection and
the agent returns 60 card IDs. The agent never raises: on any failure it returns
a legal fallback.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from cabt_bot import Observation
from cabt_bot.bots import Bot, HeuristicBot, RandomBot

try:
    BOT: Bot = HeuristicBot()
except Exception:
    BOT = RandomBot()


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
        obs = Observation.from_dict(obs_dict)
        if obs.select is None:
            deck = BOT.on_deck_selection(obs)
            return deck if deck is not None else read_deck_csv()
        return BOT.select(obs)
    except Exception:
        return _fallback(obs_dict)
