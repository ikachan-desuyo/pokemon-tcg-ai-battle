"""コンペ提出のエントリポイント (cabt / kaggle-environments)。

提出パッケージ (submission.tar.gz) には本ファイル・deck.csv・cg/（公式エンジン）・
cabt_bot/・data/ を同梱する。エンジンは毎手番この `agent(obs_dict)` を呼び、
返り値は選んだ選択肢インデックスのリスト (list[int])。

契約（公式 main.py より）:
- obs.select が None のときは「初期デッキ選択」。60 枚のカードID(list[int]) を返す。
- それ以外は各要素が 0 <= i < len(select.option)、要素数は minCount..maxCount、重複なし。
- エージェントは絶対にクラッシュしてはならない。例外時も必ず合法なフォールバックを返す。
"""

from __future__ import annotations

import os
import sys

# 提出環境でも cabt_bot / data を解決できるよう、自身のディレクトリを import パスに追加。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from cabt_bot import Observation  # noqa: E402
from cabt_bot.bots import Bot, GreedyBot  # noqa: E402

# 使用する戦略。RandomBot() や自作 Bot に差し替え可能。
BOT: Bot = GreedyBot()


def read_deck_csv() -> list[int]:
    """deck.csv（60 枚のカードID）を読む。Kaggle 実行時のパスにも対応。"""
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
    """例外時でも返せる、最低限合法な選択。"""
    try:
        sel = obs_dict.get("select")
        if not sel:
            return read_deck_csv()
        n = len(sel.get("option", []))
        k = max(1, int(sel.get("minCount", 1)))
        k = min(k, n)
        return list(range(k))
    except Exception:
        return [0]


def agent(obs_dict: dict, *_args) -> list[int]:
    """エンジンから呼ばれる関数。常に合法な list[int] を返す。"""
    try:
        obs = Observation.from_dict(obs_dict)

        # 初期デッキ選択フェーズ。
        if obs.select is None:
            deck = BOT.on_deck_selection(obs)
            return deck if deck is not None else read_deck_csv()

        return BOT.select(obs)
    except Exception:
        # どんな失敗でも投了せず合法手を返す。
        return _fallback(obs_dict)
