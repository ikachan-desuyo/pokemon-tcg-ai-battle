"""日本語カード名のデッキ表（1行 = 名前+枚数）を、カードID並びの CSV に変換する。

入力例（decks/foo.txt）:
    メガルカリオ３
    リオル４
    基本闘エネルギー９
出力（decks/foo.csv）: カードIDを1行1枚で60行。

名前→ID は公式 input_data/extracted/JP_Card_Data.csv で照合。
全角数字・全角ピリオド、エネルギーの略記（例「闘エネルギー」「基本闘エネルギー」）も吸収する。
解決できない行は報告し、その場合 CSV は書き出さない。

使い方:
    python scripts/convert_deck.py decks/megaruka.txt [decks/iwapa.txt ...]
    python scripts/convert_deck.py decks/*.txt
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JP_CSV = ROOT / "input_data" / "extracted" / "JP_Card_Data.csv"

# 全角→半角（数字とピリオド）
_Z2H = {ord("０") + i: ord("0") + i for i in range(10)}
_Z2H[ord("．")] = ord(".")

_ENERGY_TYPES = {"草": 1, "炎": 2, "水": 3, "雷": 4, "超": 5, "闘": 6, "悪": 7, "鋼": 8}


def load_name_index() -> dict[str, int]:
    idx: dict[str, int] = {}
    with JP_CSV.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            nm = r["カード名"].strip()
            if nm and nm not in idx:
                idx[nm] = int(r["カード ID"])
    return idx


def resolve(name: str, idx: dict[str, int]) -> tuple[int | None, str]:
    """カード名を ID へ解決。戻り値 (id|None, 実際に一致した名前)。"""
    name = name.strip()
    if name in idx:
        return idx[name], name
    # エネルギー略記の正規化
    if name.endswith("エネルギー"):
        base = name[:-len("エネルギー")]
        # 「基本闘」「闘」→「基本【闘】エネルギー」
        t = base.replace("基本", "")
        if t in _ENERGY_TYPES:
            cand = f"基本【{t}】エネルギー"
            if cand in idx:
                return idx[cand], cand
    # 部分一致（前方一致を優先）
    pref = [k for k in idx if k.startswith(name)]
    if len(pref) == 1:
        return idx[pref[0]], pref[0]
    sub = [k for k in idx if name in k]
    if len(sub) == 1:
        return idx[sub[0]], sub[0]
    return None, name


def convert(txt_path: Path, idx: dict[str, int]) -> bool:
    raw_lines = txt_path.read_text(encoding="utf-8").splitlines()
    deck: list[int] = []
    rows = []
    ng = []
    total = 0
    for ln in raw_lines:
        norm = ln.strip().translate(_Z2H)
        if not norm or norm.startswith("#"):
            continue
        # 末尾数字を枚数として剥がし、名前を解決。名前が数字で終わる場合は
        # 1桁だけ枚数として試す。
        i = len(norm)
        while i > 0 and norm[i - 1].isdigit():
            i -= 1
        digits = norm[i:]
        name = norm[:i].strip()
        if not digits:
            ng.append((ln, "枚数なし"))
            continue
        cnt = int(digits)
        cid, matched = resolve(name, idx)
        if cid is None and len(digits) >= 2:
            # 名前が数字で終わる想定（例 ポケギア3.0）: 末尾1桁だけ枚数に
            name2 = (name + digits[:-1]).strip()
            cnt2 = int(digits[-1])
            cid2, matched2 = resolve(name2, idx)
            if cid2 is not None:
                cid, matched, cnt = cid2, matched2, cnt2
        if cid is None:
            ng.append((ln, f"未解決: '{name}'"))
            continue
        deck += [cid] * cnt
        total += cnt
        rows.append((matched, cid, cnt))

    print(f"\n=== {txt_path.name} ===")
    for matched, cid, cnt in rows:
        print(f"  {matched:18s} id={cid:5d} x{cnt}")
    if ng:
        print("  -- 未解決 --")
        for ln, why in ng:
            print(f"  [NG] {ln.strip()}  ({why})")
    print(f"  合計: {total} 枚")

    if ng or total != 60:
        print(f"  → CSV未出力（未解決 {len(ng)} 件 / 枚数 {total}）。修正後に再実行してください。")
        return False
    out = txt_path.with_suffix(".csv")
    out.write_text("\n".join(map(str, deck)) + "\n", encoding="utf-8")
    print(f"  ✅ 書き出し: {out.name}")
    # 合法性チェック（エンジンがあれば）
    try:
        sys.path.insert(0, str(ROOT))
        from cg.game import battle_finish, battle_start
        obs, sd = battle_start(deck, deck)
        if obs is not None:
            print(f"  ✅ 合法（battle_start errorType={sd.errorType}）")
            battle_finish()
        else:
            print(f"  ⚠ エンジンが拒否: errorType={sd.errorType}")
    except Exception:
        print("  （cg 未配置のため合法性チェックは省略）")
    return True


def main() -> int:
    if not JP_CSV.exists():
        print(f"JP カードデータが見つかりません: {JP_CSV}", file=sys.stderr)
        return 1
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("使い方: python scripts/convert_deck.py <deck.txt> [...]", file=sys.stderr)
        return 1
    idx = load_name_index()
    ok = True
    for p in paths:
        if not p.exists():
            print(f"見つかりません: {p}", file=sys.stderr)
            ok = False
            continue
        ok = convert(p, idx) and ok
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
