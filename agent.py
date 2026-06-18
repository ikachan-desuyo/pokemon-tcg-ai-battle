"""Kaggle Environments 用エントリポイント。

cabt 環境はこのファイルの `agent` 関数を呼び出す。
    from kaggle_environments import make
    env = make("cabt", configuration={"decks": [deck, deck]})
    env.run([agent, agent])

`agent(obs_dict)` は選んだ選択肢インデックスのリスト (list[int]) を返す。
中身は cabt_bot.Bot 実装に委譲しているので、ここを差し替えれば
別の思考ルーチンに切り替えられる。
"""

from __future__ import annotations

from typing import Any

from cabt_bot import Observation
from cabt_bot.bots import Bot, GreedyBot

# ここを RandomBot() / 自作 Bot に変えるだけで戦略を切り替えられる。
BOT: Bot = GreedyBot()


def agent(obs_dict: dict[str, Any], *_args: Any) -> list[int]:
    """Kaggle から呼ばれる関数。選択肢インデックスのリストを返す。

    第2引数 (configuration) は cabt では使わないので無視する。
    """
    obs = Observation.from_dict(obs_dict)

    # 探索開始フェーズ（相手デッキ予想）への対応。未対応なら None でスキップ。
    if obs.search_begin_input is not None:
        result = BOT.on_search_begin(obs)
        if result is not None:
            return result  # type: ignore[return-value]

    if obs.select is None:
        return []
    return BOT.select(obs)
