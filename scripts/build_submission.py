"""提出用 submission.tar.gz を作成する。

同梱物:
    main.py            エントリポイント
    deck.csv           60 枚デッキ
    cg/                公式エンジン（コンペ配布物・git 管理外）
    cabt_bot/          bot ロジック
    data/cards.json    カードデータ（任意・戦略で使う場合）

cg/ は再配布不可のため、コンペからダウンロードした実体を --cg で指定するか、
リポジトリ直下に cg/ を置いておくこと（既定で探索する）。

使い方:
    python scripts/build_submission.py \
        --deck decks/deck.csv \
        --cg input_data/extracted/sample_submission/sample_submission/cg \
        --out submission.tar.gz
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CG_CANDIDATES = [
    ROOT / "cg",
    ROOT / "input_data" / "extracted" / "sample_submission" / "sample_submission" / "cg",
]


def find_cg(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if (p / "api.py").exists() else None
    for c in _CG_CANDIDATES:
        if (c / "api.py").exists():
            return c
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="提出パッケージを作成")
    parser.add_argument("--deck", default=str(ROOT / "decks" / "deck.csv"))
    parser.add_argument("--cg", default=None, help="公式エンジン cg/ のパス")
    parser.add_argument("--out", default=str(ROOT / "submission.tar.gz"))
    parser.add_argument("--no-cg", action="store_true", help="cg/ を含めない（動作確認用）")
    args = parser.parse_args()

    deck = Path(args.deck)
    if not deck.exists():
        print(f"deck が見つかりません: {deck}", file=sys.stderr)
        return 1

    # deck の枚数チェック。
    n = sum(1 for ln in deck.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#"))
    if n != 60:
        print(f"警告: デッキ枚数が 60 ではありません ({n} 枚)")

    cg = None
    if not args.no_cg:
        cg = find_cg(args.cg)
        if cg is None:
            print(
                "エンジン cg/ が見つかりません。--cg でパス指定するか、--no-cg で省略してください。",
                file=sys.stderr,
            )
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "submission"
        stage.mkdir()
        shutil.copy2(ROOT / "main.py", stage / "main.py")
        shutil.copy2(deck, stage / "deck.csv")
        shutil.copytree(ROOT / "cabt_bot", stage / "cabt_bot",
                        ignore=shutil.ignore_patterns("__pycache__"))
        data_dir = ROOT / "data"
        if data_dir.exists():
            shutil.copytree(data_dir, stage / "data")
        if cg is not None:
            shutil.copytree(cg, stage / "cg", ignore=shutil.ignore_patterns("__pycache__"))

        out = Path(args.out)
        with tarfile.open(out, "w:gz") as tar:
            # アーカイブ直下に main.py 等が並ぶように arcname を調整。
            for item in sorted(stage.iterdir()):
                tar.add(item, arcname=item.name)

    print(f"作成しました: {out}")
    print("  含: main.py, deck.csv, cabt_bot/, data/" + ("," + " cg/" if cg else " (cg/ なし)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
