"""カードデータ (data/cards.csv) の読み込みユーティリティ。

card_id は cabt のデッキ定義 (deck.csv) や Option.card_id と同じ ID 体系。
PDF からの再生成は scripts/extract_cards.py を参照。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "cards.csv"


@dataclass(frozen=True)
class CardInfo:
    card_id: int
    name: str
    expansion: str
    collection_no: str


@lru_cache(maxsize=None)
def load_cards(csv_path: str | None = None) -> dict[int, CardInfo]:
    """{card_id: CardInfo} を返す（結果はキャッシュ）。"""
    path = Path(csv_path) if csv_path else _DEFAULT_CSV
    cards: dict[int, CardInfo] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cid = int(row["card_id"])
            cards[cid] = CardInfo(
                card_id=cid,
                name=row["name"],
                expansion=row["expansion"],
                collection_no=row["collection_no"],
            )
    return cards


def card_name(card_id: int) -> str:
    """card_id から名前を引く（未知なら '#<id>'）。"""
    info = load_cards().get(card_id)
    return info.name if info else f"#{card_id}"
