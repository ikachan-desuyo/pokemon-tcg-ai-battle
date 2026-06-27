"""観測 (Observation) を表す型付きデータクラス群。

Kaggle Environments から渡される `obs_dict` は素の dict なので、
`Observation.from_dict(obs_dict)` で型付きオブジェクトへ変換して扱う。
未知のキーは無視し、欠損キーは None / デフォルトで埋めるため、
エンジンが項目を増減しても壊れにくいようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import OptionType, SelectContext, SelectType


def _enum_or_none(enum_cls, value):
    if value is None:
        return None
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        return value  # 未知の値はそのまま保持


@dataclass
class Card:
    """カード1枚。エンジンの Card 構造の薄いラッパ。"""

    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def card_id(self) -> int | None:
        return self.raw.get("cardId", self.raw.get("id"))

    @property
    def serial(self) -> int | None:
        return self.raw.get("serial")

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Card | None":
        if d is None:
            return None
        return cls(raw=d)


@dataclass
class Option:
    """1つの選択肢。`type` がどんな行動かを表し、残りは付随パラメータ。"""

    type: OptionType | int | None
    number: int | None = None
    area: int | None = None
    index: int | None = None
    player_index: int | None = None
    tool_index: int | None = None
    energy_index: int | None = None
    count: int | None = None
    in_play_area: int | None = None
    in_play_index: int | None = None
    attack_id: int | None = None
    card_id: int | None = None
    serial: int | None = None
    special_condition_type: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Option":
        return cls(
            type=_enum_or_none(OptionType, d.get("type")),
            number=d.get("number"),
            area=d.get("area"),
            index=d.get("index"),
            player_index=d.get("playerIndex"),
            tool_index=d.get("toolIndex"),
            energy_index=d.get("energyIndex"),
            count=d.get("count"),
            in_play_area=d.get("inPlayArea"),
            in_play_index=d.get("inPlayIndex"),
            attack_id=d.get("attackId"),
            card_id=d.get("cardId"),
            serial=d.get("serial"),
            special_condition_type=d.get("specialConditionType"),
            raw=d,
        )


@dataclass
class SelectData:
    """今このターン、何をどれだけ選ばせたいか。"""

    type: SelectType | int | None
    options: list[Option] = field(default_factory=list)
    min_count: int = 1
    max_count: int = 1
    remain_damage_counter: int | None = None
    remain_energy_cost: int | None = None
    context: Any = None
    context_card: Card | None = None
    effect: Card | None = None
    deck: list[Card] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SelectData | None":
        if d is None:
            return None
        options = [Option.from_dict(o) for o in d.get("option", []) or []]
        deck = d.get("deck")
        return cls(
            type=_enum_or_none(SelectType, d.get("type")),
            options=options,
            min_count=d.get("minCount", 1),
            max_count=d.get("maxCount", 1),
            remain_damage_counter=d.get("remainDamageCounter"),
            remain_energy_cost=d.get("remainEnergyCost"),
            context=_enum_or_none(SelectContext, d.get("context")),
            context_card=Card.from_dict(d.get("contextCard")),
            effect=Card.from_dict(d.get("effect")),
            deck=[Card.from_dict(c) for c in deck] if deck else None,
            raw=d,
        )


@dataclass
class Observation:
    """エンジンから渡される1観測。`select` があれば選択を返す番。"""

    select: SelectData | None
    logs: list[dict[str, Any]] = field(default_factory=list)
    current: dict[str, Any] | None = None  # State (生 dict のまま保持)
    search_begin_input: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Observation":
        return cls(
            select=SelectData.from_dict(d.get("select")),
            logs=d.get("logs", []) or [],
            current=d.get("current"),
            search_begin_input=d.get("search_begin_input"),
            raw=d,
        )

    @property
    def options(self) -> list[Option]:
        return self.select.options if self.select else []
