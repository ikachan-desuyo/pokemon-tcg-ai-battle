"""カードID並びのデッキCSVを、人が読める一覧CSVに変換する（閲覧用）。

入力: decks/foo.csv（カードIDが1行1枚）
出力: decks/foo_view.csv（枚数・カード名・種別・タイプ・HP・ID）

カード名等は公式 input_data/extracted/JP_Card_Data.csv（日本語）から引く。

使い方:
    python scripts/deck_view.py decks/deck.csv decks/megaruka.csv ...
    python scripts/deck_view.py decks/*.csv
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JP_CSV = ROOT / "input_data" / "extracted" / "JP_Card_Data.csv"
EN_CSV = ROOT / "data" / "cards.csv"  # JP データが無い環境向けフォールバック

# data/cards.csv（英語）の stage/type を既存 view と同じ日本語ラベルへ写像
_STAGE_JP = {
    "Basic Pokémon": "ポケモン/たね", "Stage 1 Pokémon": "ポケモン/1進化",
    "Stage 2 Pokémon": "ポケモン/2進化", "Item": "グッズ",
    "Pokémon Tool": "ポケモンのどうぐ", "Supporter": "サポート", "Stadium": "スタジアム",
    "Special Energy": "特殊エネルギー", "Basic Energy": "基本エネルギー",
}
_TYPE_JP = {
    "{G}": "草", "{R}": "炎", "{W}": "水", "{L}": "雷", "{P}": "超",
    "{F}": "闘", "{D}": "悪", "{M}": "鋼", "{C}": "無", "{N}": "竜",
}

COL_ID = "カード ID"
COL_NAME = "カード名"
COL_KIND = "ポケモンの進化の段階/エネルギー・トレーナーズの種類"
COL_TYPE = "タイプ"
COL_HP = "HP"

# 並び順（種別の大分類）。ポケモン→グッズ→道具→サポート→スタジアム→エネルギー
_KIND_RANK = [
    ("たね", 0), ("1進化", 1), ("2進化", 2),  # ポケモン進化段階
    ("グッズ", 5), ("ポケモンのどうぐ", 6), ("サポート", 7), ("スタジアム", 8),
    ("特殊エネルギー", 9), ("基本エネルギー", 10),
]


def _na(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v in ("n/a", "None", "-") else v


def load_index() -> dict[int, dict]:
    idx: dict[int, dict] = {}
    with JP_CSV.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            cid = int(r[COL_ID])
            if cid not in idx:
                idx[cid] = r
    return idx


def load_index_en() -> dict[int, dict]:
    """JP データが無い環境向け: data/cards.csv（英語）から view 用の行を組む。

    カード名は英語のまま。種別・タイプは既存 view と同じ日本語ラベルに揃える。
    """
    idx: dict[int, dict] = {}
    with EN_CSV.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            cid = int(r["card_id"])
            if cid in idx:
                continue
            stage = (r.get("stage") or "").strip()
            kind = _STAGE_JP.get(stage, stage)
            raw_type = (r.get("type") or "").strip()
            # "{C}{C}{C}" のような複数シンボルは各個変換（→「無無無」）
            typ = re.sub(r"\{[A-Z]\}", lambda m: _TYPE_JP.get(m.group(0), m.group(0)), raw_type)
            idx[cid] = {COL_NAME: r.get("name"), COL_KIND: kind, COL_TYPE: typ, COL_HP: r.get("hp")}
    return idx


def kind_rank(kind: str) -> int:
    for key, rank in _KIND_RANK:
        if key in kind:
            return rank
    return 4  # 不明はポケモンとエネの間あたり


def view(deck_csv: Path, idx: dict[int, dict]) -> None:
    ids = [int(x) for x in deck_csv.read_text(encoding="utf-8").split()
           if x.strip() and not x.strip().startswith("#")]
    counts = Counter(ids)
    rows = []
    for cid, n in counts.items():
        r = idx.get(cid, {})
        kind = _na(r.get(COL_KIND))
        rows.append({
            "枚数": n,
            "カード名": _na(r.get(COL_NAME)) or f"#{cid}",
            "種別": kind,
            "タイプ": _na(r.get(COL_TYPE)),
            "HP": _na(r.get(COL_HP)),
            "ID": cid,
        })
    rows.sort(key=lambda x: (kind_rank(x["種別"]), -x["枚数"], x["カード名"]))

    out = deck_csv.with_name(deck_csv.stem + "_view.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["枚数", "カード名", "種別", "タイプ", "HP", "ID"])
        w.writeheader()
        w.writerows(rows)
    total = sum(counts.values())
    print(f"✅ {out.name}  ({len(rows)}種 / 合計{total}枚)")


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("使い方: python scripts/deck_view.py <deck.csv> [...]", file=sys.stderr)
        return 1
    if JP_CSV.exists():
        idx = load_index()
    elif EN_CSV.exists():
        print(f"JPデータ無し → 英語フォールバック ({EN_CSV.name}) を使用", file=sys.stderr)
        idx = load_index_en()
    else:
        print(f"カードデータが見つかりません: {JP_CSV} / {EN_CSV}", file=sys.stderr)
        return 1
    for p in paths:
        if not p.exists() or p.name.endswith("_view.csv"):
            continue
        view(p, idx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
