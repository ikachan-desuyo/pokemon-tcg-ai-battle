"""相手デッキ（アーキタイプ）判定と、マッチアップ別の基本方針。

相手が見せたカード（盤面・ログで判明したカードID）を signature と突き合わせて
アーキタイプを推定し、それに応じた戦略プロファイルを返す。判定不能なら None。

戦略プロファイルの knob（メガスターミー Nebula 軸を前提）:
- go_first: 先攻するか
- attack_mode: "nebula"(最大火力で確実KO) / "spread"(ジェットブローでばらまき)
- gust_targets: ボスの指令等で優先的に引きずり出す相手カードID（脅威/エンジンを除去）
"""

from __future__ import annotations

# --- 代表的な強いデッキの目印（signature）カードID ---
ARCHETYPES: dict[str, set[int]] = {
    "Dragapult":         {121, 119, 120, 133, 132, 112},  # ドラパルトex/ドラメシヤ/ドロンチ/ヨノワール/サマヨール/マシマシラ
    "MegaLopunny":       {849, 758, 66},                   # メガミミロップex/ミミロル/ノココッチ
    "MegaLucario":       {678, 333, 676, 675, 673, 674},  # メガルカリオex/リオル/ソルロック/ルナトーン/マクノシタ/ハリテヤマ
    "MegaYukinooh":      {723, 722, 721},                  # メガユキノオーex/ユキカブリ/カイオーガ
    "Iwapa":             {345, 344, 970, 112},             # イワパレス/イシズマイ/キチキギス/マシマシラ
    "MegaStarmieSpread": {1031, 112, 104, 103},            # メガスターミーex+マシマシラ+ユキメノコ+ユキワラシ
    "MegaStarmie":       {1031, 1030, 666, 17},            # メガスターミーex/ヒトデマン/エースバーン/イグニ
}

# 一意性の強い目印（1枚見えれば確定に近い）
_UNIQUE_HINT: dict[int, str] = {
    121: "Dragapult", 849: "MegaLopunny",
    678: "MegaLucario", 723: "MegaYukinooh", 345: "Iwapa", 344: "Iwapa",
    104: "MegaStarmieSpread", 103: "MegaStarmieSpread",
}

# マッチアップ別プロファイル
#
# 注意: 手作りのボス優先対象(gust_targets)は A/B 検証で「既定の価値ベース狙撃」より
# 劣ることが多かった（2026-06-28 計測: 4/5 マッチアップで悪化）。そのため現状は
# 「検証で有効だったものだけ」を残し、他は既定挙動(gust_targets=[])にしている。
# 新しい調整を入れるときは必ず A/B で勝率改善を確認してから有効化すること。
DEFAULT_PROFILE = {"go_first": False, "attack_mode": "nebula", "gust_targets": []}
PROFILES: dict[str, dict] = {
    "Dragapult":    {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "MegaLopunny":  {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "MegaLucario":  {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "MegaYukinooh": {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "Iwapa":        {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "MegaStarmieSpread": {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
    "MegaStarmie":  {"go_first": False, "attack_mode": "nebula", "gust_targets": []},
}
# 現状どのプロファイルも DEFAULT 相当（検証で勝率を上げられた調整が無いため）。
# 枠組み（識別→切替）は完成しており、A/B で有効と確認できた調整をここに足していく。


def identify(seen_ids: set[int]) -> str | None:
    """観測した相手カードID集合からアーキタイプを推定。不明なら None。"""
    if not seen_ids:
        return None
    # 一意目印が見えていれば優先
    for cid, name in _UNIQUE_HINT.items():
        if cid in seen_ids:
            # MegaStarmie 系の Nebula/Spread 取り違え回避: spread 目印を優先
            if name == "MegaStarmieSpread" or cid not in (1031,):
                return name
    # signature の一致数で採点
    best, best_score = None, 0
    for name, sig in ARCHETYPES.items():
        score = len(seen_ids & sig)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else None


def profile_for(name: str | None) -> dict:
    return PROFILES.get(name, DEFAULT_PROFILE)
