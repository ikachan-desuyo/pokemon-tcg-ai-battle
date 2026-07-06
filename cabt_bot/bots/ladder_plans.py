"""(移設済み) ベンチマーク用デッキ知識は cabt_bot/decks/ に移動しました。

1デッキ=1モジュール(PLAN/Bot/IDENTITY/THREAT)構成。対戦相手のデッキに応じた
処理(対策側参照)を将来入れるため、デッキ固有知識をデッキ単位で分離する
(ユーザ設計 2026-07-06)。互換のため旧名を再輸出。
"""
from ..decks.lucario import PLAN as LADDER_LUCARIO_PLAN  # noqa: F401
from ..decks.lucario import Bot as LadderLucarioBot  # noqa: F401
