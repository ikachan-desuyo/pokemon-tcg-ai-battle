"""input_data/ のカードID一覧 PDF から、カードデータを構造化して書き出す。

PDF は先頭が表形式（Card ID / Card Name / Expansion / Collection No. / Link）、
以降がカード画像ページという構成。表ページのみを解析して
data/cards.csv と data/cards.json を生成する。

使い方:
    pip install pymupdf
    python scripts/extract_cards.py \
        --pdf "input_data/Card_ID List_EN.pdf" \
        --out-dir data

このスクリプトは PDF を読むためだけに pymupdf を必要とする（実行時の bot は不要）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = ["Card ID", "Card Name", "Expansion", "Collection No.", "Link"]
LINK_CELL = "View Image"


def parse_pdf(pdf_path: Path) -> list[dict]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(
            "pymupdf が必要です: pip install pymupdf",
            file=sys.stderr,
        )
        raise

    doc = fitz.open(pdf_path)
    records: list[dict] = []
    for page in doc:
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
        if lines[:5] != HEADER:
            continue  # 画像ページなどはスキップ
        buf: list[str] = []
        for ln in lines[5:]:
            if ln == LINK_CELL:
                records.append(_record_from_buffer(buf))
                buf = []
            else:
                buf.append(ln)
    return records


def _record_from_buffer(buf: list[str]) -> dict:
    """1レコード分のセル列を dict に変換。

    通常: [id, name, expansion, collection_no]
    一部: [id, name, collection_no]（Expansion 欠落カードが8件存在）
    """
    cid = int(buf[0])
    coll = buf[-1]
    if len(buf) >= 4:
        name = " ".join(buf[1:-2])
        expansion = buf[-2]
    else:  # len == 3: expansion 欠落
        name = " ".join(buf[1:-1])
        expansion = ""
    return {
        "card_id": cid,
        "name": name,
        "expansion": expansion,
        "collection_no": coll,
    }


def write_outputs(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "cards.csv"
    json_path = out_dir / "cards.json"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["card_id", "name", "expansion", "collection_no"])
        writer.writeheader()
        writer.writerows(records)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"wrote {len(records)} records -> {csv_path}, {json_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="カードID PDF を構造化データに変換")
    parser.add_argument("--pdf", default=str(ROOT / "input_data" / "Card_ID List_EN.pdf"))
    parser.add_argument("--out-dir", default=str(ROOT / "data"))
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF が見つかりません: {pdf_path}", file=sys.stderr)
        return 1

    records = parse_pdf(pdf_path)
    if not records:
        print("レコードを抽出できませんでした。", file=sys.stderr)
        return 1

    # 整合性チェック: ID は 1..N の連番のはず。
    ids = [r["card_id"] for r in records]
    expected = list(range(min(ids), max(ids) + 1))
    if ids != expected:
        print(f"警告: card_id が連番ではありません (min={min(ids)}, max={max(ids)}, n={len(ids)})")

    write_outputs(records, Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
