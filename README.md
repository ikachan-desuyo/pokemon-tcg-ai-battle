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
scripts/run_match.py  # ローカルで2エージェントを対戦させる
tests/                # パース・合法手のテスト
```

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
