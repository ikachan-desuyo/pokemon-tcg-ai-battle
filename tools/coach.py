"""ポケカ特化LLMコーチ (Phase 2 / LLM-in-the-loop開発)。

構造化トレース(tools/structured_trace.py)＋ポケカ知識ベースをClaude(claude-opus-4-8)に渡し、
『misplay検出＋構造化された改善提案(どのカードのscore/ゲートをどう変えるか)』を出力させる。
出力はそのまま専用botの改善に使う＝説明可能トレースでゲームAIを自己改善するパイプラインの中核。

実行: python tools/coach.py --me archaludon --opp deck --games 6 --losses-only
  ANTHROPIC_API_KEY があればClaudeを呼ぶ。無ければ組み立てたプロンプトを out/coach_prompt.txt に保存。
"""
import sys, os, json, argparse
sys.path.insert(0, ".")
import importlib.util

# ── ポケカ知識ベース(このレギュ固有・我々が確立した戦略原則) ───────────────
KNOWLEDGE_BASE = """あなたはポケモンカード(cabtエンジン, Simulation部門)に精通した戦略コーチです。
プレイbotの意思決定トレース(JSON)を分析し、misplayの検出と、実装可能な改善提案を出します。

## このレギュ固有の重要ルール
- イグニッションエネルギー: 特殊エネ1枚で無色3。進化ポケモンにのみ有効、番末トラッシュ。MegaStarmieが最大活用し2ターン目に210(Nebula Beam=弱点・効果無視)。
- メガポケモンexはKO時3サイド、通常exは2サイド。弱点は被ダメ2倍。
- 速度が支配的: 2進化デッキは立ち遅れやすい。

## このbotアーキテクチャ(高速ヒューリスティック)で確立した有効原則
1. 目的ゲート: 状況依存札は「目的を達せる時だけ使う」(ボス=KO対象がある時, 夜タンカ=回収対象がある時, いれかえ=攻撃役を前に出す時, ジャッジ=自分が損せず相手の手札が多い時)。
2. 結果志向スコア(depth-1近似): 掘り札は「使った後に何が可能になるか(欠けた重要ピースを取れるか)」で評価。
3. 攻撃はKO最優先→最大ダメージ。可変火力技(例:レイジングハンマー=80+自分の被ダメ)は実ダメージで評価。
4. エンジン札(特性で全体を底上げ)は重複させない。
5. 過剰な温存・掘り札の温存は逆効果(セットアップデッキはパーツを揃える必要がある)。

## トレースの読み方
各decisionのcandidatesは候補手。score=評価値, "却下(None)"相当はゲートで弾かれた, ko=その攻撃で相手バトル場をKO可能, chosen=実際に選んだ手。
『候補生成で出ていない』(払えない技/手札に無い札)と『出ているが評価/ゲートで負けた』を区別すること。

## あなたの出力
負け試合を中心に、明確なmisplayと、その是正のための実装可能な提案を出す。各提案は具体的に:
どのカード/判断を、どの条件で、どう変えるか(スコア/ゲート/結果志向化)。勝率への期待効果と確信度も。"""

OUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "全体所見(1-3文)"},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "対象カード名/判断(例: Ultra Ball, 攻撃選択, ボスの指令)"},
                    "observation": {"type": "string", "description": "トレースで観測したmisplay/非効率(ターン番号等の根拠付き)"},
                    "kind": {"type": "string", "enum": ["gate", "score", "result_oriented", "attack_logic", "deck", "other"]},
                    "change": {"type": "string", "description": "実装する具体的変更(条件・数値含む)"},
                    "rationale": {"type": "string"},
                    "expected_effect": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["target", "observation", "kind", "change", "rationale", "expected_effect", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "proposals"],
    "additionalProperties": False,
}


def build_traces(me, opp, games, losses_only):
    spec = importlib.util.spec_from_file_location("structured_trace", "tools/structured_trace.py")
    st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
    data = st.run(games, me, opp)
    if losses_only:
        data = [g for g in data if g["result"] == "loss"] or data
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default="archaludon"); ap.add_argument("--opp", default="deck")
    ap.add_argument("--games", type=int, default=6); ap.add_argument("--losses-only", action="store_true")
    ap.add_argument("--model", default="claude-opus-4-8")
    a = ap.parse_args()

    traces = build_traces(a.me, a.opp, a.games, a.losses_only)
    user_content = (f"対象bot: {a.me} / 相手: {a.opp}\n"
                    f"以下は{len(traces)}試合分の構造化意思決定トレースです。"
                    f"負け試合を中心にmisplayを検出し、実装可能な改善提案を構造化出力してください。\n\n"
                    f"```json\n{json.dumps(traces, ensure_ascii=False)}\n```")
    os.makedirs("out", exist_ok=True)

    try:
        import anthropic
    except ImportError:
        anthropic = None
    if anthropic is None or not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        path = "out/coach_prompt.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== SYSTEM (knowledge base) ===\n" + KNOWLEDGE_BASE
                    + "\n\n=== USER ===\n" + user_content
                    + "\n\n=== OUTPUT JSON SCHEMA ===\n" + json.dumps(OUT_SCHEMA, ensure_ascii=False, indent=1))
        print(f"[no API] プロンプトを {path} に保存しました（ANTHROPIC_API_KEY設定時はClaudeを呼びます）。")
        print(f"  トレース: {len(traces)}試合 / プロンプト長: {len(user_content)}文字")
        return

    client = anthropic.Anthropic()
    with client.messages.stream(
        model=a.model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": KNOWLEDGE_BASE, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": OUT_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        msg = stream.get_final_message()
    text = next((b.text for b in msg.content if b.type == "text"), "{}")
    result = json.loads(text)
    out = "out/coach_proposals.json"
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== コーチ所見 ===\n{result.get('summary','')}\n")
    for i, p in enumerate(result.get("proposals", []), 1):
        print(f"[{i}] ({p['kind']}/{p['confidence']}) {p['target']}: {p['change']}")
        print(f"     観測: {p['observation']}")
    print(f"\n→ {out} に保存")


if __name__ == "__main__":
    main()
