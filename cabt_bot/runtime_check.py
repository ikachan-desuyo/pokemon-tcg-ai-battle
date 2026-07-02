"""Runtime Self Check: 提出環境で推論層が期待通り動作しているかを起動時に自己診断する。

背景: v5〜v7 で JP_Card_Data.csv が提出tarに含まれず、silent fallback({})により
line_threat=0 のまま数提出ぶん実戦を戦っていた(脅威ライン系機能が全て無効)。
「except→空データ→数週間気付かない」を二度と起こさないための Fail Fast 機構。

設計: 推論層ごとの Health Check の registry。Episodeが増えたら層を追加するだけ。
失敗は警告でなく RuntimeError(起動失敗)。Kaggleの検証エピソードが即失敗する＝提出時に発覚する。
"""
from __future__ import annotations


def _check_cards():
    """カードDB(cards.json): 件数と主要カードの実在。"""
    from .cards import load_cards
    C = load_cards()
    assert len(C) > 1000, f"cards.json が不完全(件数{len(C)})"
    assert 1031 in C and C[1031].name, "主要カード(1031 Mega Starmie ex)が引けない"
    assert C[1031].moves, "主要カードの技データが空"


def _check_state_encoder():
    """脅威ライン(line_threat/caps): 空データ・ゼロ値の検出(v5-v7事故の再発防止の本丸)。"""
    from .state_encoder import line_threat, line_attacker_hp, caps
    lt = line_threat(1031)
    assert lt and lt > 0, f"line_threat(1031)={lt} — 脅威ラインデータが空(JP_Card_Data.csv欠落?)"
    assert line_threat(1030) >= lt or line_threat(1030) > 0, "進化ライン(Staryu→Mega)の前方探索が壊れている"
    cp = caps(1031)
    assert cp.get("hp", 0) > 0 and cp.get("max_dmg", 0) > 0, f"caps(1031)が空: {cp}"
    assert line_attacker_hp(1030) > 0, "line_attacker_hp が引けない"


def _check_plan_inference():
    """推論スタック(interpret_move/payability素材): エネ型解釈と技コスト解釈。"""
    from .cards import load_cards
    C = load_cards()
    mv = next((m for m in C[1031].moves if m.cost), None)
    assert mv is not None, "技コストが読めない"
    assert "{" in (mv.cost or "") or "●" in (mv.cost or ""), f"コスト表記が想定外: {mv.cost!r}"


CHECKS = [
    ("cards", _check_cards),
    ("state_encoder", _check_state_encoder),
    ("plan_inference", _check_plan_inference),
]


def run_runtime_checks(strict: bool = True) -> list:
    """全Health Checkを実行。strict=True(既定)なら1つでも失敗で RuntimeError(Fail Fast)。
    返り値: 失敗リスト [(layer, error), ...] (strict=Falseの診断モード用)。"""
    failures = []
    for layer, fn in CHECKS:
        try:
            fn()
        except Exception as e:                  # noqa: BLE001 - 診断目的で全捕捉
            failures.append((layer, repr(e)))
    if failures and strict:
        detail = "; ".join(f"[{l}] {e}" for l, e in failures)
        raise RuntimeError(f"Runtime Self Check 失敗(Fail Fast): {detail}")
    return failures
