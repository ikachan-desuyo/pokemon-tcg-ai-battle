# pokemon-tcg-ai-battle

[cabt](https://matsuoinstitute.github.io/cabt/api.html)（Kaggle Environments 上の
ポケモンカードゲーム対戦環境）向け AI 対戦エージェントのベースコード。

## 仕組み

cabt 環境は各手番でエージェントに **observation (dict)** を渡し、エージェントは
`observation["select"]["option"]`（選択肢のリスト）から選んだ**インデックスの
リスト (`list[int]`)** を返す。選ぶ個数は `minCount`〜`maxCount` の範囲。

```python
from kaggle_environments import make
env = make("cabt", configuration={"decks": [deck, deck]})
env.run([agent, agent])
```

このリポジトリでは、素の dict を型付きの `Observation` に変換し、
`Bot` クラスに思考を委譲する構成にしている。

## ディレクトリ構成

```
agent.py              # Kaggle エントリポイント（agent(obs_dict) -> list[int]）
cabt_bot/
  enums.py            # SelectType / OptionType / AreaType などの列挙型
  models.py           # Observation / SelectData / Option / Card のデータクラス
  bots/
    base.py           # Bot 基底クラス（select() を実装する）
    random_bot.py     # ランダムに合法手を選ぶベースライン
    greedy_bot.py     # OptionType ベースの簡易ヒューリスティック
decks/deck.csv        # 60 枚のカードIDデッキ定義（要差し替え）
data/cards.csv        # カードID一覧（id/name/expansion/collection_no）1267件
data/cards.json       # 同上の JSON 版
scripts/extract_cards.py  # input_data/ の PDF からカードデータを再生成
scripts/run_match.py  # ローカルで2エージェントを対戦させる
tests/                # パース・合法手のテスト
```

## カードデータ

`data/cards.csv` / `data/cards.json` に全 1267 枚のカード情報を収録。
`card_id` は deck.csv や `Option.card_id` と同じ ID 体系。

```python
from cabt_bot import load_cards, card_name
cards = load_cards()        # {card_id: CardInfo}
card_name(40)               # -> "Greninja ex"
```

再生成（`input_data/` の PDF が必要）:

```bash
pip install pymupdf
python scripts/extract_cards.py
```

> 注: 元 PDF で Expansion 列が欠落しているカードが 8 件あり、その `expansion` は空文字。

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> **cabt 環境について**: `make("cabt", ...)` を使うには cabt 環境本体が
> `kaggle_environments` に登録されている必要がある。配布形態（pip パッケージ /
> Kaggle ノートブック上の追加登録など）は公式ドキュメント・コンペページの
> 案内に従って導入すること。

## 使い方

### テスト（環境不要）

```bash
python -m pytest          # または: python tests/test_observation.py
```

### ローカル対戦

```bash
python scripts/run_match.py --render
```

### 戦略の差し替え

`agent.py` の `BOT = GreedyBot()` を別の `Bot` 実装に変えるだけ。
独自ロジックは `cabt_bot/bots/base.py` の `Bot` を継承して `select()` を実装する：

```python
from cabt_bot.bots import Bot
from cabt_bot.models import Observation

class MyBot(Bot):
    def select(self, obs: Observation) -> list[int]:
        # obs.options を見て、選んだインデックスのリストを返す
        ...
```

## メモ / TODO

- `AreaType` / `SpecialConditionType` の数値は公式ドキュメントに明記がなく**暫定値**。
  実エンジンの値が判明したら `cabt_bot/enums.py` を修正する。
- `Observation.search_begin_input`（探索開始時の相手デッキ予想）への本格対応は
  `Bot.on_search_begin()` を実装して行う。
- `decks/deck.csv` はプレースホルダ。`all_card_data()` で取得した実カードIDに置き換える。
