"""リプレイ登録のフォルダ同期: out/replays/ に置いたJSONをPagesビューアの一覧に反映する。

使い方:
  1. リプレイJSONを out/replays/ に置く(ファイル名がそのまま一覧のラベルになる)。
     - ローカル対戦の記録JSON・Kaggle公式エピソードJSONのどちらも可(ビューアが両対応)
     - 例: out/replays/mirror-0 逆転負け6T.json
  2. python tools/publish_replays.py   ← docs/replays/ へミラー+manifest再生成
  3. コミット&プッシュでPagesに反映

同期規則: out/replays/*.json と docs/replays/ を完全ミラー(削除も反映)。
壊れたJSON・リプレイ形式でない(stepsが無い)ものはスキップして警告。
旧形式(引数でファイル:ラベル指定)も互換: 指定ファイルを out/replays/ にコピーしてから同期する。
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "out" / "replays"
DEST = ROOT / "docs" / "replays"


def valid_replay(p: Path) -> bool:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"  スキップ(JSON不正): {p.name} ({e})")
        return False
    if not isinstance(d, dict) or not d.get("steps"):
        print(f"  スキップ(リプレイ形式でない: stepsなし): {p.name}")
        return False
    return True


def sync():
    SRC.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    srcs = {p.name: p for p in SRC.glob("*.json") if valid_replay(p)}
    # ミラー: 追加/更新
    for name, p in srcs.items():
        dst = DEST / name
        if not dst.exists() or dst.stat().st_size != p.stat().st_size:
            shutil.copy(p, dst)
            print(f"  登録: {name}")
    # ミラー: 削除(manifest以外)
    for old in DEST.glob("*.json"):
        if old.name != "manifest.json" and old.name not in srcs:
            old.unlink()
            print(f"  削除: {old.name}")
    # manifest再生成(新しい順)
    entries = [{"file": n, "label": Path(n).stem}
               for n in sorted(srcs, key=lambda n: srcs[n].stat().st_mtime, reverse=True)]
    json.dump({"replays": entries}, open(DEST / "manifest.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"→ manifest {len(entries)}本。コミット&プッシュでPagesに反映。")


def main(argv):
    # 旧互換: file[:ラベル] 指定はout/replays/へラベル名でコピーしてから同期
    for a in argv:
        if a == "--keep":
            continue
        src, _, label = a.partition(":")
        p = Path(src)
        SRC.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, SRC / f"{(label or p.stem)}.json")
    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
