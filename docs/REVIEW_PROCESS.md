# レビュー駆動改善プロセス（確立版・2026-07）

Episode 1〜4 と実ラダー分析で確立した「勘で直さない」開発プロセスのテンプレート。
新しい弱点・違和感・勝率低下に対しては、必ずこの順で進める。

## 原則
1. **数字だけ見て直さない**。「○%悪い」は修正対象でなく分解対象。
2. **専用bot/上位者と違う ＝ 悪、ではない**（スタイル差は直さない。genuine gapのみ直す）。
3. **DecisionDiffは原因を探す道具であって、修正対象を決める道具ではない**。
4. **修正は一度に1本**。束ねると何が効いたか分からなくなる。
5. **人間の違和感は最強の信号**（OSレビュー88%一致の裏で28/32局面の穴を人間が発見した実績）。

## 手順テンプレート

### Phase 0: 現象の確定
- 実ラダーなら `ladder_meta.py`（対面別勝敗・Elo帯別）。ローカルなら安定指標(無攻撃率/進化率/ベンチ)。
- 「どの相手に・どれくらい・どんな負け方か」を数字で持つ。

### Phase 1: 敗因の統計分類（DecisionDiffはまだ使わない）
- `ladder_loss_classify.py` 型：無攻撃事故 / 展開負け(0-1) / 競り負け(2-4) / あと一歩(5) / 盤面切れ。
- 勝ち試合との特徴比較（初攻撃T・主役着地T・取得サイド・試合長）。
- **注意: リプレイの action[t] は obs[t-1] への応答**（off-by-one）。ペアリングを間違えると偽の「殴らない」が出る。

### Phase 2: 頻度で優先順位付け → 上位カテゴリだけ深掘り
- Root Cause Matrix: | 分類 | 件数 | DecisionDiff有 | 修正候補 | の表を必ず作る。
- 事故(手札に手段なし)は status/logs/手札で確認してから「運」と確定する（エラー/タイムアウトの反証を含む）。

### Phase 3: 上位カテゴリのみ DecisionDiff / Explain
- `ladder_loss_diff.py` 型：分岐点(T3-8等)の実選択 vs カーネル最善、regret≥40のみ収集。
- 一致率が高い(≈88%)＝判断でなく構造。低い＝判断gap。
- **同一局面比較**が最強の反証装置：「専用/Universalは同じ局面で何を選ぶか」（Recovery142回仮説を21/22一致で反証した型）。

### Phase 4: 人間レビュー
- ビューアHTML（tools/replay_viewer.py）で負け試合を目視。
- 人間の違和感 → **operationalization に注意**（「後続を準備しない」の実体は「置かない(0件)」でなく「付け先(28件)」だった）。
- 違和感は必ず件数測定に落としてから修正判断（逃げ0壁は2/32=低頻度と測ってから後回しにできた）。

### Phase 5: 修正（1本だけ）
- 汎用原則として設計（will_die のハードコードでなく「将来価値の低い投資先を避ける」）。
- 既存Analyzer/既存Gateを使う。新Analyzer追加は原則禁止。
- planノブで既定OFF＝出荷非破壊にして入れる。

### Phase 6: A/B（ローカル）
- **勝率 + 行動メトリクス**（例:「死亡濃厚Attach率 88→60%」）を必ず両方測る。
  行動が変わっていなければ実装ミス、変わって勝率が動かなければ仮説側の問題と切り分けられる。
- ミラー新旧 + 対フィールド。30戦はノイズ過大、100戦以上。
- **ローカルの限界**: ローカルベンチは実ラダーを再現しない（デッキ復元+Universal操縦でも86%勝ててしまう=操縦者gap）。
  ローカル＝「行動が変わったか」の確認器 / 実ラダー＝「強くなったか」の判定器。

### Phase 7: 検証提出（必要時のみ・ユーザ指示必須）
- 目的は順位でなく仮説検証。提出前に git tag（vN-名前）、提出後に submission ID/commit hash/時刻を記録。
- 24-48h後に `ladder_meta.py` で対面別勝率の before/after。改善なしも研究成果。

### Phase 8: 毎提出後の定例——人間レビュー→OSレビュー（必須・正式採用）
- **提出のたびに、人間が3〜5試合リプレイを目視して違和感を挙げる**（replay_viewer HTML）。
- 実績: 人間が3試合で挙げた3違和感のうち2つが全162試合の頻度1位(112件)・2位(15件)だった。
  数試合の目視が全体の頻出問題を引き当てる＝Explain/DecisionDiffと並ぶ最高ROIのレビュー手法。
- 違和感→必ず全リプレイ走査で件数化→Root Cause Matrix（正当ケースの除外まで。例: リーリエ38件中23件は
  サポ権使用済みで正当）→ROIで1本だけ修正。
- **レビューシートに「違和感の種類」を必ず記録**: 展開 / エネ / サポート / Boss / 勝ち筋 / テンポ / 壁運用。
  提出をまたいで蓄積し「エネ関係の違和感が毎回出ている」等の長期傾向を Root Cause Matrix と突き合わせる。

### 検証提出の採用基準（対面別勝率重視）
- 修正が特定対面を狙ったものなら、**判定は全体勝率・順位でなく標的対面の勝率**で行う。
  例: Lucario 30%→38% / Arch 30%→37% なら、全体勝率がほぼ不変でも採用してよい。
- 逆に全体勝率が微増でも標的対面が不変なら、修正は「効いていない」と判定する。

## 設計原則の追記（2026-07）
- **Future Value はAttach（どこへ貼る）だけでなくFetch（何を取る）にもある**。
  取得選択は「カード名の固定優先(card_values)」でなく「候補ごとの将来価値を計算して最大を取る」形に
  する（例: 今120で倒せる→水（ベンチ50+イグニ温存+次ターン継続）/ 210で2枚取りできる→イグニでよい）。
  ハードコード（水優先）にしない。

### Future Value の一般形（Episode 5 の基盤・実装は凍結中）
評価しているのは「エネ」でなく**リソース投資先の将来価値**。1つの抽象層として持つ。
**期待値と実現可能性を分離する**（確率重み付け・最終形）:
```
FutureValue = ImmediateValue
            + P(next_turn) × NextTurnValue
            − OpportunityCost
```
「210点出せる」だけでは高評価になってしまう——**そこへ到達できる確率**を掛けて初めて期待値になる
（例: Ignition→Nebula 210 は強いが、死にゆくactiveの上では P(next_turn) が低い）。
適用先（同じ式で書ける）: Attach(どこへ貼る) / Fetch(何を取る) / Support(今サポを切るか) /
Boss(今使うか) / Bench(今埋める価値) / Evolution(今進化させる価値)。
interpret_move / infer_plan / infer_opening / infer_trainer_roles と並ぶ**汎用推論層**として設計する。
P(next_turn) は新Analyzer不要——既存の analyze_threat(can_ko_me/hits_to_lose) がそのまま確率の素材になる。

**評価単位は「カード」でなく「行動(Action)」**: Attach Water / Attach Ignition / Fetch Water /
Play Boss / Play Lillie / Bench Staryu ——これら全てが Action であり、同じ式で採点する:
`ActionScore = ImmediateValue + P(next_turn) × NextTurnValue − OpportunityCost`
Attach Logic / Fetch Logic / Support Logic を別々に持つ必要はない——全部「次の1アクションの評価」。
Episode 5 の中心概念 = **ActionEvaluator**。

### アーキテクチャの階層（Episode 1〜5 で構築した推論スタック）
```
Card → interpret_move(Move理解・payability)
     → infer_plan(Game Plan)
     → infer_opening(Opening Strategy)
     → infer_trainer_roles(Trainer役割)
     → FutureValue(ActionEvaluator)   ← Episode 5
     → Decision
```
各Episodeは「暗黙知を明示的な推論へ置き換える作業」だった。採用判定は常に実ラダー(対面別勝率)。

### レビューの順番（確定・従来から反転）
```
人間レビュー → Explain → Root Cause Matrix → DecisionDiff → Kernel
```
DecisionDiff/Kernelは「どこを調べるか」を教えるが、「違和感」の発見は人間が圧倒的に速い。
Kernel起点だった従来の順番をこの形に改める。

### v7型の検証提出 判定ルーブリック
- **採用**: 標的対面が両方 30→36%以上。
- **保留**: 片方のみ改善（例 Lucario 30→40 / Arch 30→29）→ 改善しなかった側の原因を調べる。
- **巻き戻し**: 両方不変/悪化 → 「行動は改善したが勝率に寄与せず」の知見として保存し次へ。

## 過去の実績（このプロセスが防いだ誤修正）
- Override 71% → 評価器バグだった / Plan 25% → 検出アーティファクト / Recovery 142回 → 専用も同じ
- ベンチ薄い → リソース不足(運) / Attach差53% → 半分は仕様 / 開幕T2 → 後攻アーティファクト
- 初攻撃T遅い → off-by-one誤検知 / 単騎死 → 置ける札なし(運) + Cinderace=Stage2の発見
