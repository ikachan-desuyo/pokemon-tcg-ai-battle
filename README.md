# pokemon-tcg-ai-battle

Kaggle コンペ **[Pokémon TCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)**
（cabt エンジン / Simulation 部門）向け AI 対戦エージェント。

> **目的は専用Botを再現することではない。**
> **未知のデッキに対しても、説明可能な推論だけで適切な Game Plan を導ける UniversalBot を構築することである。**
> （プロジェクト憲章: [docs/CHARTER.md](docs/CHARTER.md) / 開発プロセス: [docs/REVIEW_PROCESS.md](docs/REVIEW_PROCESS.md)）

## コンペ概要

- **Simulation 部門**: エージェント同士の Elo ラダー。1試合10分、時間切れは負け。1日最大5提出。
- **Strategy 部門**: 戦略・デッキ設計を 2,000 語以内のレポートで説明。
- 配布カードプール（約2,000枚 / 我々の `data/` は1267枚）から **60枚デッキ**を構築。
- 対戦は **cabt エンジン**（ネイティブ lib + `cg/` Python ラッパ）上で実行。

## 仕組み

エンジンは各手番でエージェントに **observation (dict)** を渡し、エージェントは
`obs["select"]["option"]`（選択肢）から選んだ**インデックスのリスト (`list[int]`)** を返す。
個数は `minCount`〜`maxCount`、重複なし。`obs.select` が `None` のときは
**初期デッキ選択**で 60 枚のカードIDを返す。

エージェントは**絶対にクラッシュしてはならない**（[main.py](main.py) は例外時も合法手を返す）。

## ディレクトリ構成

```
main.py               # 提出エントリポイント agent(obs_dict)->list[int]（堅牢・フォールバック付き）
cabt_bot/
  enums.py            # 公式 cg/api.py に一致する列挙型（SelectType/OptionType/AreaType/EnergyType/...）
  models.py           # Observation / SelectData / Option / Card のデータクラス（エンジン非依存）
  cards.py            # カードデータ(data/cards.json)ローダー（HP/タイプ/ワザ等）
  arena.py            # 公式エンジン直叩きのローカル対戦アリーナ
  bots/
    base.py           # Bot 基底クラス（select() を実装）
    random_bot.py     # ランダムに合法手を選ぶベースライン
    heuristic_bot.py  # 展開→最後に攻撃するルールベース実戦エージェント
decks/
  deck.csv            # 自分のデッキ（メガスターミーex・検証済み）
  sample_deck.csv     # 公式サンプルの合法デッキ（動作確認用）
data/cards.json       # 全1267カードのリッチデータ（id/name/hp/type/weakness/retreat/moves）
data/cards.csv        # フラット概観版
scripts/
  extract_cards.py    # 公式 EN_Card_Data.csv からカードデータを再生成
  run_match.py        # ローカル対戦（1試合 / 勝率集計）
  build_submission.py # submission.tar.gz を作成
tests/                # パース・列挙・カード・エントリポイントのテスト
cg/                   # 公式エンジン（コンペ配布物・再配布不可・git 管理外）
input_data/           # 配布 zip/PDF/CSV の展開先（git 管理外）
```

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# コンペ配布物を input_data/ に置いて展開後、エンジンをリポジトリ直下へコピー
cp -r input_data/extracted/sample_submission/sample_submission/cg ./cg
```

> `cg/`（ネイティブエンジン）と `input_data/`（配布データ）は **git 管理外**。
> 各自 Kaggle のコンペページから入手する。

## 使い方

### テスト（エンジン不要）

```bash
python tests/test_observation.py      # または: python -m pytest
```

### ローカル対戦（エンジン必要 / `cg/` 配置済み）

```bash
python scripts/run_match.py                 # サンプルデッキ同士で1試合
python scripts/run_match.py --games 50       # 50試合の勝率集計
python scripts/run_match.py --deck0 decks/a.csv --deck1 decks/b.csv
```

### 提出パッケージ作成

```bash
python scripts/build_submission.py --deck decks/deck.csv
# -> submission.tar.gz（main.py / deck.csv / cg/ / cabt_bot/ / data/）
```

### 戦略の差し替え

[main.py](main.py) の `BOT = HeuristicBot()` を変えるだけ。独自ロジックは
`Bot` を継承して `select()` を実装する：

```python
from cabt_bot.bots import Bot
from cabt_bot.models import Observation

class MyBot(Bot):
    def select(self, obs: Observation) -> list[int]:
        # obs.options を見て、選んだインデックスのリストを返す
        ...
```

## カードデータ

```python
from cabt_bot import load_cards, card_name
cards = load_cards()        # {card_id: CardInfo}
cards[30].hp                # 270
cards[30].moves             # (Move(name='Hot Magma', cost='{R}●', damage='70', ...), ...)
card_name(40)               # "Greninja ex"
```

再生成（公式 `EN_Card_Data.csv` が必要）:

```bash
python scripts/extract_cards.py --csv input_data/extracted/EN_Card_Data.csv
```

## 次のステップ

- デッキ最適化ツール: `cabt_bot/arena.run_series` で候補デッキの勝率を測り、
  山登り / 遺伝的アルゴリズムで改良する（評価用の強い固定エージェントが前提）。
- `HeuristicBot` を超える思考ルーチン（探索 `search_*` API の活用など）。
