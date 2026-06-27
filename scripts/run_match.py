"""ローカルで2エージェントを対戦させる（公式エンジン直叩き）。

使い方:
    python scripts/run_match.py                      # サンプルデッキ同士で1試合
    python scripts/run_match.py --games 50           # 50 試合の勝率集計
    python scripts/run_match.py --deck0 decks/a.csv --deck1 decks/b.csv

前提: リポジトリ直下に公式エンジン cg/ があること（git 管理外）。
    cp -r input_data/extracted/sample_submission/sample_submission/cg ./cg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_deck(path: str | Path) -> list[int]:
    deck: list[int] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        deck.append(int(line.split(",")[0]))
    return deck


def main() -> int:
    default_deck = ROOT / "decks" / "sample_deck.csv"
    parser = argparse.ArgumentParser(description="cabt のローカル対戦")
    parser.add_argument("--deck0", default=str(default_deck))
    parser.add_argument("--deck1", default=str(default_deck))
    parser.add_argument("--games", type=int, default=1, help="試合数（>1 で勝率集計）")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if not (ROOT / "cg" / "api.py").exists():
        print(
            "エンジン cg/ が見つかりません。リポジトリ直下に配置してください:\n"
            "  cp -r input_data/extracted/sample_submission/sample_submission/cg ./cg",
            file=sys.stderr,
        )
        return 1

    from cabt_bot.arena import run_match, run_series
    from main import agent

    deck0 = load_deck(args.deck0)
    deck1 = load_deck(args.deck1)
    for name, d in (("deck0", deck0), ("deck1", deck1)):
        if len(d) != 60:
            print(f"警告: {name} の枚数が 60 ではありません ({len(d)} 枚)")

    if args.games <= 1:
        r = run_match(agent, agent, deck0, deck1)
        print(f"winner={r.winner} (0/1, draw=2, unresolved=-1)  turns={r.turns}  steps={r.steps}")
    else:
        stats = run_series(agent, agent, deck0, deck1, games=args.games, seed=args.seed)
        print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
