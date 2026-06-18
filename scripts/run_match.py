"""ローカルで2エージェントを対戦させるスクリプト。

使い方:
    python scripts/run_match.py                 # deck.csv 同士で対戦
    python scripts/run_match.py --deck1 decks/deck.csv --deck2 decks/deck.csv

kaggle_environments の "cabt" 環境が利用可能である必要がある
（インストール方法は README 参照）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# プロジェクトルートを import path に追加（agent.py / cabt_bot を解決するため）。
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_deck(path: str | Path) -> list[int]:
    """1行1カードID の CSV を読み込む。空行・#コメントは無視。"""
    deck: list[int] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        deck.append(int(line.split(",")[0]))
    return deck


def main() -> int:
    parser = argparse.ArgumentParser(description="cabt のローカル対戦")
    parser.add_argument("--deck1", default=str(ROOT / "decks" / "deck.csv"))
    parser.add_argument("--deck2", default=str(ROOT / "decks" / "deck.csv"))
    parser.add_argument("--render", action="store_true", help="結果を表示する")
    args = parser.parse_args()

    try:
        from kaggle_environments import make
    except ImportError:
        print(
            "kaggle_environments が見つかりません。\n"
            "  pip install kaggle-environments\n"
            "を実行し、cabt 環境を利用可能にしてください（README 参照）。",
            file=sys.stderr,
        )
        return 1

    from agent import agent

    deck1 = load_deck(args.deck1)
    deck2 = load_deck(args.deck2)

    env = make("cabt", configuration={"decks": [deck1, deck2]})
    env.run([agent, agent])

    if args.render:
        print(env.render(mode="ansi"))

    rewards = [getattr(s, "reward", None) for s in env.state]
    print("rewards:", rewards)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
