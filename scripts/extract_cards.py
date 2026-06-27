"""公式カードデータ (EN_Card_Data.csv) を構造化して data/ に書き出す。

EN_Card_Data.csv は「1カード × ワザ毎に1行」の形式（ワザ3つなら3行）。
これを card_id 単位に集約し、HP・タイプ・弱点・にげる・ワザ一覧を持つ
リッチな data/cards.json と、検索しやすいフラットな data/cards.csv を生成する。

使い方:
    python scripts/extract_cards.py \
        --csv "input_data/extracted/EN_Card_Data.csv" \
        --out-dir data

入力 CSV はコンペ配布物（input_data/ 配下・git 管理外）。
出力は公開可能なカード事実（名前/HP/ワザ等）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# EN_Card_Data.csv のヘッダ名
COL_ID = "Card ID"
COL_NAME = "Card Name"
COL_EXPANSION = "Expansion"
COL_COLLECTION = "Collection No."
COL_STAGE = "Stage (Pokémon)/Type (Energy and Trainer)"
COL_RULE = "Rule"
COL_CATEGORY = "Category"
COL_PREV = "Previous stage"
COL_HP = "HP"
COL_TYPE = "Type"
COL_WEAKNESS = "Weakness"
COL_RESISTANCE = "Resistance (Type)"
COL_RETREAT = "Retreat"
COL_MOVE = "Move Name"
COL_COST = "Cost"
COL_DAMAGE = "Damage"
COL_EFFECT = "Effect Explanation"

_NA = {"n/a", "", "None", "-"}


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v in _NA else v


def _to_int(v: str | None) -> int | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def parse_csv(csv_path: Path) -> list[dict]:
    """card_id 単位に集約したカード一覧を返す（card_id 昇順）。"""
    cards: dict[int, dict] = {}
    order: list[int] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cid = _to_int(row.get(COL_ID))
            if cid is None:
                continue
            if cid not in cards:
                cards[cid] = {
                    "card_id": cid,
                    "name": _clean(row.get(COL_NAME)) or "",
                    "expansion": _clean(row.get(COL_EXPANSION)) or "",
                    "collection_no": _clean(row.get(COL_COLLECTION)) or "",
                    "stage": _clean(row.get(COL_STAGE)),
                    "rule": _clean(row.get(COL_RULE)),
                    "category": _clean(row.get(COL_CATEGORY)),
                    "previous_stage": _clean(row.get(COL_PREV)),
                    "hp": _to_int(row.get(COL_HP)),
                    "type": _clean(row.get(COL_TYPE)),
                    "weakness": _clean(row.get(COL_WEAKNESS)),
                    "resistance": _clean(row.get(COL_RESISTANCE)),
                    "retreat": _to_int(row.get(COL_RETREAT)),
                    "moves": [],
                }
                order.append(cid)
            move_name = _clean(row.get(COL_MOVE))
            if move_name:
                cards[cid]["moves"].append({
                    "name": move_name,
                    "cost": _clean(row.get(COL_COST)),
                    "damage": _clean(row.get(COL_DAMAGE)),
                    "effect": _clean(row.get(COL_EFFECT)),
                })
    return [cards[i] for i in sorted(order)]


def write_outputs(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "cards.json"
    csv_path = out_dir / "cards.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    # フラット版（ワザは件数のみ）。検索・概観用。
    flat_fields = [
        "card_id", "name", "expansion", "collection_no",
        "stage", "category", "hp", "type", "weakness", "retreat", "move_count",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=flat_fields)
        w.writeheader()
        for r in records:
            w.writerow({
                **{k: r.get(k, "") if r.get(k) is not None else "" for k in flat_fields if k != "move_count"},
                "move_count": len(r["moves"]),
            })

    print(f"wrote {len(records)} cards -> {json_path}, {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="公式カードデータ CSV を構造化")
    parser.add_argument(
        "--csv",
        default=str(ROOT / "input_data" / "extracted" / "EN_Card_Data.csv"),
    )
    parser.add_argument("--out-dir", default=str(ROOT / "data"))
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"カードデータ CSV が見つかりません: {csv_path}", file=sys.stderr)
        print("コンペ配布の EN_Card_Data.csv のパスを --csv で指定してください。", file=sys.stderr)
        return 1

    records = parse_csv(csv_path)
    if not records:
        print("レコードを抽出できませんでした。", file=sys.stderr)
        return 1

    ids = [r["card_id"] for r in records]
    expected = list(range(min(ids), max(ids) + 1))
    if ids != expected:
        print(f"警告: card_id が連番ではありません (min={min(ids)}, max={max(ids)}, n={len(ids)})")

    write_outputs(records, Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
