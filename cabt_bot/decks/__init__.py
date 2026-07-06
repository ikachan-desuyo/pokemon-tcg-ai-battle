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

from . import lucario

DECKS = {
    "lucario": lucario,
}
