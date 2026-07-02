# Opponent Pilot 設計メモ（実装前の整理・2026-07）

## 背景（実測）
- 実ラダーの MegaLucario/Archaludon に 30%。ローカルで実デッキを復元し UniversalBot に操縦させても、
  提出botが 86%/65% 勝ててしまう。**差の支配項は操縦者（相手botの判断品質）**。
- pilot一致率（相手の実観測に UniversalBot を当てた同一局面一致）: Lucario 41% / Arch 36%。
  序盤は 60%（開幕は型が同じ）、中終盤 ~30%（差はゲームプラン実行にある）。

## 目的
「実ラダーでよく当たる相手」をローカルに再現し、提出Bot改善の判定精度を上げる。
**相手を強くするための模倣は正当**（自分のスタイル模倣が弱くする、という教訓とは別問題。
相手pilotは"正しい"必要はなく"現実的"であればよい）。

## 何を模倣するか（優先順位つき）
1. **トレーナー運用**（最重要と推定）: 実ラダーLucarioは Premium Power Pro / Fighting Gong /
   Dusk Ball / Carmine を使いこなす。UniversalBot は未知トレーナーを generic(40) で雑にプレイ。
   → リプレイから「そのカードを使った局面の特徴」(手番/盤面/手札枚数)を集計し、
     使用条件をルール化 or 使用タイミング分布を再現する。
2. **エネ配分**（Attach先の分布）: 実相手の attach 先(active/bench比率・対象)をターン帯別に集計。
3. **attack選択**: どの技をどの局面で（Lucario系のコンボ判断）。
4. 模倣しないもの: ドロー運・確率(手札は既に本物の分布=デッキ復元済み)。

## どこまで模倣するか（段階）
- **Level 0（現状）**: デッキ復元 + UniversalBot（一致率36-41%）。
- **Level 1（次の一手・軽量）**: OpponentProfile に「トレーナー使用条件」「attach先分布」を
  統計として持たせ、UniversalBot の該当判断だけ profile で上書き（play_priority/energy_rules/
  ノブへの変換）。実装小・検証は一致率の再測定（41→55%+ が目標目安）。
- **Level 2（本格・保留）**: 相手の全MAIN決定の behavior cloning（過去に自分用BCは弱かった実績
  あり＝ただし相手再現用途では「弱い≒本人並みに間違える」も許容される点が異なる）。
- どのLevelでも**検証は同じ**: pilot一致率(ターン帯別) + 提出botの対面勝率が実ラダー(30%)に近づくか。

## UniversalBot との関係（設計上の区別）
- UniversalBot = 「カードデータから正しく打つ」汎用推論器（前向き・演繹）。
- OpponentPilot = 「この相手はこう打つ」再現器（後ろ向き・帰納）。
- 実装は UniversalBot + OpponentProfile 上書き、として共存させる（別botを作らない）。

## OpponentProfile の将来形
```
OpponentProfile
├── deck            (復元60枚・バリアント分布)      ← 済
├── opening         (go_first実測・初期配置傾向)     ← 一部済(planに含む)
├── plan            (Universal推論の主役/setup)      ← 済
├── pilot           (トレーナー使用条件・attach分布) ← Level 1
├── meta            (遭遇率・Elo帯・期間)            ← 済
├── replay          (元エピソードID一覧)             ← rows で追跡可
└── statistics      (対面勝率の履歴=判定器の校正)    ← v7検証で開始
```

## 着手条件
v7 のラダー検証が完了し、次の修正サイクルの判定精度が必要になったとき。
先に Level 1 の一致率改善だけでも、ローカル判定器の価値が大きく上がる見込み。
