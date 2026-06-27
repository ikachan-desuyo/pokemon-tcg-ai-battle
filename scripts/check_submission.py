"""提出前プリフライトチェック（方法A: Kaggle CLI 提出向け）。

順に検証し、1つでも失敗したら非ゼロ終了する:
  1. main.py / cabt_bot の構文チェック (py_compile)
  2. submission.tar.gz をビルド
  3. アーカイブ構造: main.py と deck.csv が**ルート直下**、cg/ が含まれる
  4. deck.csv が合法 (60枚・エンジンの battle_start が通る)
  5. 展開物だけで自己完結に1試合完走（提出物の main.agent を隔離実行）
全て通れば、最後に提出コマンドを表示する。

使い方:
    python scripts/check_submission.py
    python scripts/check_submission.py --deck decks/deck.csv
"""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPETITION = "pokemon-tcg-ai-battle"

_OK = "✅"
_NG = "❌"


def fail(msg: str) -> None:
    print(f"{_NG} {msg}")
    sys.exit(1)


def step(msg: str) -> None:
    print(f"--- {msg}")


def check_compile() -> None:
    step("1) 構文チェック (py_compile)")
    targets = [ROOT / "main.py", *(ROOT / "cabt_bot").rglob("*.py")]
    for f in targets:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            fail(f"構文エラー: {f}\n{e}")
    print(f"{_OK} {len(targets)} ファイル OK")


def build(deck: str, cg: str | None) -> Path:
    step("2) submission.tar.gz をビルド")
    cmd = [sys.executable, str(ROOT / "scripts" / "build_submission.py"), "--deck", deck]
    if cg:
        cmd += ["--cg", cg]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        fail(f"ビルド失敗:\n{r.stderr.strip()}")
    out = ROOT / "submission.tar.gz"
    if not out.exists():
        fail("submission.tar.gz が生成されていません")
    return out


def check_archive(tar_path: Path) -> None:
    step("3) アーカイブ構造")
    with tarfile.open(tar_path) as t:
        names = t.getnames()
    if "main.py" not in names:
        fail("main.py がルート直下にありません（サブフォルダ不可）")
    if "deck.csv" not in names:
        fail("deck.csv がルート直下にありません")
    if not any(n == "cg" or n.startswith("cg/") for n in names):
        fail("cg/（公式エンジン）が含まれていません")
    print(f"{_OK} main.py / deck.csv がルート直下、cg/ 同梱（{len(names)} エントリ）")


def check_deck_legal(deck: str) -> None:
    step("4) デッキ合法性（エンジン検証）")
    if not (ROOT / "cg" / "api.py").exists():
        print("⚠ cg/ がリポジトリ直下に無いため合法性検証をスキップ")
        return
    cards = [int(x) for x in Path(deck).read_text().split()
             if x.strip() and not x.strip().startswith("#")]
    if len(cards) != 60:
        fail(f"デッキ枚数が 60 ではありません（{len(cards)} 枚）")
    sys.path.insert(0, str(ROOT))
    from cg.game import battle_finish, battle_start
    obs, sd = battle_start(cards, cards)
    if obs is None:
        fail(f"エンジンがデッキを拒否（errorType={sd.errorType}）")
    battle_finish()
    print(f"{_OK} 60枚・battle_start 成功（errorType={sd.errorType}）")


def check_isolated_run(tar_path: Path) -> None:
    step("5) 展開物だけで自己完結に1試合")
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tar_path) as t:
            t.extractall(tmp)
        # Kaggle と同様に __file__ 無しで exec して main.py を読み込む
        # （import だと __file__ が定義され、本番固有のバグを見逃すため）。
        runner = (
            "import sys; sys.path.insert(0,'.')\n"
            "from cg.api import to_observation_class\n"
            "from cg.game import battle_start, battle_select, battle_finish\n"
            "ns={}\n"
            "exec(compile(open('main.py').read(),"
            "'/kaggle_simulations/agent/main.py','exec'), ns)\n"
            "agent=ns['agent']\n"
            "deck=[int(x) for x in open('deck.csv').read().split() if x.strip()]\n"
            "obs,sd=battle_start(deck,deck); steps=0\n"
            "while obs is not None and steps<5000:\n"
            "    o=to_observation_class(obs); st=o.current\n"
            "    if st and st.result!=-1:\n"
            "        print('FINISHED',type(ns['BOT']).__name__,'winner',st.result,'turn',st.turn); break\n"
            "    if o.select is None or not o.select.option: break\n"
            "    obs=battle_select(agent(obs)); steps+=1\n"
            "else:\n"
            "    print('NO_RESULT'); sys.exit(2)\n"
            "battle_finish()\n"
        )
        r = subprocess.run([sys.executable, "-c", runner], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode != 0 or "FINISHED" not in r.stdout:
            fail(f"隔離実行に失敗:\n{r.stdout}\n{r.stderr}")
        print(f"{_OK} {r.stdout.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="提出前プリフライト")
    parser.add_argument("--deck", default=str(ROOT / "decks" / "deck.csv"))
    parser.add_argument("--cg", default=None)
    parser.add_argument("--message", "-m", default="v1: Mega Starmie ex + HeuristicBot")
    args = parser.parse_args()

    check_compile()
    tar_path = build(args.deck, args.cg)
    check_archive(tar_path)
    check_deck_legal(args.deck)
    check_isolated_run(tar_path)

    print("\n" + "=" * 56)
    print(f"{_OK} すべて通過。以下のコマンドで提出できます:\n")
    print(f"    kaggle competitions submit {COMPETITION} \\")
    print(f"      -f {tar_path} -m \"{args.message}\"")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
