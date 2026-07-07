"""デッキ知識モジュール(Benchmark Phase / Phase6, 2026-07)。

1デッキ=1モジュール。そのデッキに関する知識を両側から参照する:
  - 操縦側: PLAN(DeckPlan) / Bot ……ベンチマーク相手botとして「そのデッキらしく」回す
  - 検収側: IDENTITY ……らしさメトリクス(PLANの仕様書。deck_identity.pyが測定)
  - 対策側: THREAT ……対面した時に参照する脅威プロファイル(ボス枚数・可変ダメ線・急所)。
             現在 deck_bot._opp_boss_remaining / reviewer のアーキタイプ推定に直書きされている
             知識の将来の移設先(TODO)。

設計原則: デッキ固有ロジックはここに、機構はエンジン(bots/deck_bot.py)に汎用ノブとして。
最終形(還元フェーズ): IDENTITYはUniversalBot自動導出の卒業試験スイートになる。
"""
from __future__ import annotations

# 縮退インポート: デッキcsvはローカル研究用で提出tarに含まれない。Kaggle実行環境では
# モジュールを読み飛ばし、deck_registry側がUniversalへフォールバックする(提出プリフライトで
# import時クラッシュを検出した修正。Phase8: 実ラダーとの差=デプロイ事故の根絶)
DECKS = {}
for _name in ("lucario", "alakazam", "dragapult", "archaludon", "grimmsnarl", "kangaskhan"):
    try:
        DECKS[_name] = __import__(f"{__name__}.{_name}", fromlist=[_name])
    except (FileNotFoundError, OSError):
        pass
