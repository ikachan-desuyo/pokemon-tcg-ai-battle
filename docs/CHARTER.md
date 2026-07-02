# UniversalBot プロジェクト憲章

## 0. このプロジェクトの目的
**目的は専用Botを再現することではない。**
**未知のデッキに対しても、説明可能な推論だけで適切な Game Plan を導ける UniversalBot を構築することである。**

## 1. 推論の原則
AIは構築者の意図を推測しない。AIが行うのは、
**観測された情報を最も矛盾なく説明できる仮説を選択すること**である。
その仮説は以下を条件とする:
- Explain できる
- 他仮説と比較できる
- 実測によって棄却できる

（Deck Intent Inference もこの原則に従う。）

## 2. 開発の原則
新しい問題を発見しても、**現在の改善サイクルは中断しない**。
新しい問題は 分類 → 記録（Known Limitations / Root Cause Matrix）→ 優先度評価 まで行い、
現在のタスクより期待効果が十分高いと証明されない限り、優先順位は変更しない。

## 3. 修正の原則
修正は次の順で行う:
```
人間レビュー → Explain → Root Cause Matrix → DecisionDiff → Kernel
```
Kernel から問題を探すのではなく、**人間が感じた違和感を Explain 可能な形へ変換する**ことを目的とする。

## 4. 採用の原則
**修正と採用は別である。**
- 修正の判定: **行動が期待通り変化したか**（ローカル・行動メトリクス）
- 採用の判定: **実ラダーで勝率が改善したか**（標的対面の勝率・全体順位ではない）

## 5. 仮説の原則
**仮説は実装より軽く、削除しやすく保つ。**
このプロジェクトの強みは仮説を立てることではなく、**仮説を素早く捨てられること**にある。
（反証されてきた仮説の実例: Override71%＝バグ / Plan25%＝アーティファクト / Recovery浪費＝専用も同じ /
ベンチ薄＝リソース不足 / MegaLucario＝判断でなく構造 / 「DBに無いから終了」＝早すぎる断定。
これらを素早く捨てられたからこそ現在の設計がある。）

## 6. 推論スタック
```
Card
  ↓ interpret_move        (Move理解・payability)
  ↓ infer_plan            (Game Plan)
  ↓ infer_opening         (Opening Strategy)
  ↓ infer_trainer_roles   (Trainer役割)
  ↓ ActionEvaluator       (Future Value = Immediate + P(next_turn)×NextTurn − OpportunityCost)
  ↓ Decision
```
Episode 6 では Card より一段上の情報源が加わる:
```
Deck → Deck Intent Inference → infer_plan
```
各 Episode は一貫して「より大きい単位の意味を推論する」方向に進化する
（Ep1=State / Ep2=Card→Move / Ep3=Move→Plan / Ep4=Plan→Opening・Trainer / Ep5=Action→FutureValue / Ep6=Deck→Intent）。
