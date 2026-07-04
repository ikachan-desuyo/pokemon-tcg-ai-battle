"""登録リプレイを GitHub Pages ビューアに公開する。

usage:
  python tools/publish_replays.py <file.json[:ラベル]> ...   # 既定=総入れ替え
  python tools/publish_replays.py --keep <file.json[:ラベル]> ...  # 既存に追加

docs/replays/ に JSON をコピーし manifest.json を更新する。Pages 側の docs/index.html が
manifest を fetch して「登録済みリプレイ」一覧を表示する(?replay=<file> で直リンク可)。
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs" / "replays"


def main(argv):
    args = [a for a in argv if a != "--keep"]
    keep = "--keep" in argv
    if not args:
        print(__doc__)
        return 1
    DEST.mkdir(exist_ok=True)
    manifest_path = DEST / "manifest.json"
    entries = []
    if keep and manifest_path.exists():
        entries = json.load(open(manifest_path)).get("replays", [])
    else:
        for old in DEST.glob("*.json"):
            if old.name != "manifest.json":
                old.unlink()
    for a in args:
        src, _, label = a.partition(":")
        p = Path(src)
        json.load(open(p))                      # 壊れたJSONを公開しない
        shutil.copy(p, DEST / p.name)
        entries = [e for e in entries if e.get("file") != p.name]
        entries.append({"file": p.name, "label": label or p.stem})
        print(f"登録: {p.name} ({label or p.stem})")
    json.dump({"replays": entries}, open(manifest_path, "w"), ensure_ascii=False, indent=1)
    print(f"→ {manifest_path} ({len(entries)}本)。コミット&プッシュでPagesに反映。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
