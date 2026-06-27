"""カードデータ (data/cards.json) の読み込みユーティリティ。

card_id は cabt のデッキ定義 (deck.csv) や Option.cardId と同じ ID 体系。
データは公式 EN_Card_Data.csv から scripts/extract_cards.py で生成する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DEFAULT_JSON = Path(__file__).resolve().parent.parent / "data" / "cards.json"


@dataclass(frozen=True)
class Move:
    name: str
    cost: str | None = None      # 例 "{R}{R}●"（● は無色）
    damage: str | None = None    # 例 "140"（"140+" 等の表記もありうるため文字列）
    effect: str | None = None


@dataclass(frozen=True)
class CardInfo:
    card_id: int
    name: str
    expansion: str = ""
    collection_no: str = ""
    stage: str | None = None          # 例 "Basic Pokémon" / "Stage 1 Pokémon" / "Item"
    rule: str | None = None           # 例 "Pokémon ex"
    category: str | None = None
    previous_stage: str | None = None
    hp: int | None = None
    type: str | None = None           # 例 "{R}"
    weakness: str | None = None
    resistance: str | None = None
    retreat: int | None = None
    moves: tuple[Move, ...] = field(default_factory=tuple)

    @property
    def is_pokemon(self) -> bool:
        return self.hp is not None

    @property
    def is_basic(self) -> bool:
        return bool(self.stage) and self.stage.startswith("Basic") and self.is_pokemon


@lru_cache(maxsize=None)
def load_cards(json_path: str | None = None) -> dict[int, CardInfo]:
    """{card_id: CardInfo} を返す（結果はキャッシュ）。"""
    path = Path(json_path) if json_path else _DEFAULT_JSON
    raw = json.loads(path.read_text(encoding="utf-8"))
    cards: dict[int, CardInfo] = {}
    for r in raw:
        moves = tuple(
            Move(
                name=m["name"],
                cost=m.get("cost"),
                damage=m.get("damage"),
                effect=m.get("effect"),
            )
            for m in r.get("moves", [])
        )
        cards[r["card_id"]] = CardInfo(
            card_id=r["card_id"],
            name=r.get("name", ""),
            expansion=r.get("expansion", ""),
            collection_no=r.get("collection_no", ""),
            stage=r.get("stage"),
            rule=r.get("rule"),
            category=r.get("category"),
            previous_stage=r.get("previous_stage"),
            hp=r.get("hp"),
            type=r.get("type"),
            weakness=r.get("weakness"),
            resistance=r.get("resistance"),
            retreat=r.get("retreat"),
            moves=moves,
        )
    return cards


def card_name(card_id: int) -> str:
    """card_id から名前を引く（未知なら '#<id>'）。"""
    info = load_cards().get(card_id)
    return info.name if info else f"#{card_id}"
