# Kaggle 提出手順（Pokémon TCG AI Battle / Simulation 部門）

提出は **研究の基準点（ベースライン順位）** を取るための実験。研究本体（main）は止めない。

## 方針（重要）
- **不要な「ファイル」を削除するだけ。ファイル内のコードは編集しない。**
  （import文を削る・`__all__`を削る・registryを削る等の**コード編集は不要**。手間とリスクが増えるだけ。）
- 提出デッキは **MegaStarmie**（`decks/deck.csv`）。feature flag は既定 OFF のまま（`use_resolver`/`use_turn_evaluator`/`use_search`、`evaluate_decision`/`evaluate_plan`/`opponent` は全て非接続）。
- 研究コード（Plan AI 等）は提出に入れない。dormant なら同梱されても無害（agent は呼ばない）。

## 手順
```bash
# 0) main がクリーン（全作業コミット済み）であること
git switch main && git status -s        # 空を確認

# 1) 提出ブランチを作成して移行（N は連番: submission-1,2,3,...）
git switch -c submission-N

# 2) 不要“ファイル”のみ削除（コードは触らない）。import依存の無いものだけ:
git rm -r -q --ignore-unmatch tools out docs tests replays
git rm -q --ignore-unmatch plan_*.py episode*.py *_review_summary.md \
  archaludon_*.txt
#   ※ cabt_bot/ パッケージは丸ごと残す（bot削除はimport編集が要るので“やらない”）
#   ※ 研究デッキcsvは import されないので消しても良い（任意）:
#      git rm -q $(git ls-files 'decks/*.csv' | grep -vE 'decks/deck\.csv$')

# 3) パッケージ作成
python scripts/build_submission.py --deck decks/deck.csv --out submission.tar.gz

# 4) プリフライト全検証（構文→ビルド→構造→デッキ60枚合法→展開物だけで1試合完走）
python scripts/check_submission.py --deck decks/deck.csv     # 全✅を確認

# 5) tar.gz を記録してコミット（gitignore対策で -f）
git add -f submission.tar.gz && git add -A
git commit -m "submission-N: <一言>"

# 6) 提出（このブランチ上で。tar.gzはmainには無いので必ずsubmission-N上で実行）
kaggle competitions submit pokemon-tcg-ai-battle \
  -f submission.tar.gz -m "vN: <説明>"

# 7) main に戻って研究再開
git switch main
```

## 注意
- `cg/`（公式エンジン）はリポジトリ直下に必要（コンペからDL・git管理外）。build/check が自動探索。
- `submission.tar.gz` は submission-N に追跡コミットするため、`main` へ戻ると消える。**提出は submission-N 上で行う**。
- 認証: `~/.kaggle/kaggle.json` か環境変数 `KAGGLE_USERNAME`/`KAGGLE_KEY`。
- 1日最大5提出・1試合10分（時間切れ負け）。
- 履歴: submission-1〜5（過去）、submission-6 = OS第1世代ベースライン（2026-07-02）。

## 過去の反省
- v6 では研究bot群まで削除するため deck_registry.py / `__init__.py` の import を編集したが、**それは不要な作業だった**。次回からは上記の「ファイル削除のみ」で行う。
