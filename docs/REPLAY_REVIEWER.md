# ReplayReviewer 設計書（Episode 5 前段・設計のみ／実装なし）

## 目的（一文定義）
> **ReplayReviewerの目的は、リプレイから修正案を出すことではない。**
> **リプレイから新しい説明可能な仮説を発見し、既存の推論層で説明できるかを検証することである。**
> **説明できなかったものだけが、新しい推論層の候補となる。**

**ReplayReviewerは「レビューAI」ではなく「観測装置（観測AI）」である。**
```
Replay → Observation → Hypothesis Test → Root Cause
```
これは単なるデバッグツールではなく、**推論アーキテクチャ（Episode 5, 6, 7…）を進化させるための観測装置**であり、
同時に **Episode Generator** でもある——既存推論層の改善だけでなく、
**新しい推論層が必要であることを検出する**のがこの装置のもう一つの役割:
```
実ラダー → 観測 → 仮説棄却(H1〜H5) ─┬─ 既存推論層で説明可能 → 修正候補
                                    └─ Unknown（説明不能）   → 新しいEpisode（新しい推論層）の種
```
＝「新しい機能を思いついたから追加する」のではなく、**説明できない現象が現れたときだけ
アーキテクチャを拡張する**という開発哲学の装置化。

- 人間の代わりに判断しない。**違和感を検出し、最も矛盾のない説明仮説に変換する**のが責務。
- 出力する仮説は憲章§1に従う: Explainできる／他仮説と比較できる／実測で棄却できる。

## 中核の問い：「人間の違和感」をどう機械化するか
人間レビューが見つけた5発見（Towko→イグニ／リーリエEND／Boss勝ち逃し／死にゆくactiveへのエネ／T1壁交代）を分析すると、人間は共通して**「後から見れば無駄・不合理だった行動」**に反応している。
これは機械化できる——**リプレイは未来を全部知っている**。未来を使って「結果的に無駄だった投資・使わなかった権利・逃した勝ち筋」を事実として検出できる（= Hindsight Signal）。
検出はFactのみ（Analyzer原則）。それが「本当に誤りか」は後段の仮説検証が決める。

## レイヤ構成

### Layer 0: Collector（取得・正規化）
- ListEpisodes(submissionId) → kaggleusercontent リプレイ取得（既存 `ladder_meta.py`）。
- 正規化: **off-by-one補正**（action[t]↔obs[t-1]）、自側特定、相手アーキタイプ分類、勝敗・Elo付与。
- 過去の測定事故（off-by-one誤検知・後攻turn-parity）はここで一括して吸収する。

### Layer 1: Signal Detectors（違和感候補の検出＝Factのみ・Opinionなし）
3系統。**検出器は「この事象が起きた」だけを出力し、良し悪しを判断しない。**

**(a) Hindsight検出器**（未来を知る立場からの無駄検出）
3つの抽象カテゴリの下に具体検出器を置く（Episode 5 の Future Value と同型の分類）:
```
Investment（投資）             Opportunity（機会）        Resource（資源）
├── WastedInvestment ★28/32   ├── MissedLethal ★Boss1   ├── DeadEnd（取得カード未使用）
├── DelayedInvestment          ├── UnusedRight ★リーリエ15 ├── Overflow（過剰供給）
├── UnderInvestment            └── MissedTempo ★無攻撃    └── Starvation（枯渇死）
└── OverInvestment ★過積み
```
★=このセッションで実証済みの原型あり。カテゴリが Future Value と揃っているため、
Investment系の発見はそのまま ActionEvaluator の入力仕様になる。

**(b) Cross-policy検出器**（同一局面の別ポリシー比較）
| 検出器 | 事実 |
|---|---|
| KernelDisagree | evaluate_decision の最善と実選択が regret≥θ で乖離 |
| ShadowDisagree | Universal / 専用bot が同一局面で別内容を選択 |

**(c) Statistical検出器**（分布の異常）
| 検出器 | 事実 |
|---|---|
| MatchupOutlier | 対面別勝率の外れ値（例: Lucario 30%） |
| BehaviorSkew | 行動分布の偏り（例: fetch の95%がイグニ） |
| LossShape | 敗因分類の偏り（競り負け型/展開負け型/盤面切れ型） |

### Layer 2: Aggregator（頻度化）→ 出力①頻度ランキング
- シグナルを **パターンキー = 行動タイプ × 文脈 × 違和感の種類**（展開/エネ/サポート/Boss/勝ち筋/テンポ/壁運用＝Phase 8の語彙を再利用）で集約。
- 出力: (パターン, 件数, 代表エピソードID, 対面分布)。

### Layer 3: Hypothesis Generator & Verifier（説明仮説の生成と棄却試験＝本体）
各パターンに**競合仮説の固定セット**を当て、棄却試験を自動実行する。
これは過去に人間+Claudeが手動でやってきた反証プロセスの機械化である:

| 仮説 | 棄却試験 | 実証済みの原型 |
|---|---|---|
| H1 正当（仕様/最適） | 同一局面shadow比較（専用/Universalも同じ選択か） | Recovery142→専用も21/22同じ |
| H2 運/資源（選択肢がなかった） | 手札・盤面・選択肢リストの検証 | 単騎死→置ける札なし |
| H3 測定アーティファクト | off-by-one/turn-parity/集計定義の検査 | 開幕T2→後攻の偶数ターン |
| H4 判断gap | カーネルregret＋DecisionDiff駆動要因が一貫支持 | イグニAttach先9/10収束 |
| H5 構造（デッキ/相性） | 判断一致率が高いのに負けが偏る | Lucario=88%一致でも30% |
| **H6 Unknown（新規パターン）** | 全仮説が棄却された残差 | → **人間送り＝新しい知識の候補** |

- **H6は失敗ではない。Episodeを生む種である**（実例: Towko→イグニは当初Unknown→Future Value/Episode 5へ、
  Telepath崩壊はUnknown→Deck Intent/Episode 6候補へ）。H6の蓄積状況がアーキテクチャ拡張の唯一の根拠になる。
- 生き残った仮説＝「最も矛盾のない説明」。複数生存時は併記（断定しない）。
- **カーネルの既知限界を仮説検証に織り込む**: regretの絶対値は信用しない（単一determinization）。
  方向の一貫性（N件中M件が同方向）だけを証拠として扱う。

### Layer 4: Root Cause Matrix Builder → 出力②
各パターンについて自動生成:
`| パターン | 件数 | 代表リプレイ | 採択仮説(Explain) | Universal再現 | regret分布 | DecisionDiff駆動要因 |`

### Layer 5: Prioritizer → 出力③修正優先度
```
Priority A: 頻度高 × 勝敗影響あり（事象の有無での勝率差。※相関である旨を必ず付記＝Override Accuracy 0.67の教訓）
Priority B: 頻度低 × regret高（方向一貫）
Priority C: 1〜2件のみ → 記録のみ（Boss勝ち逃し型）
```

### Layer 6: Responsibility Router → 出力④責務分類
「どう直すか」は出力しない（修正と採用の分離）。**抽象責務 → 具体層**の2段で分類する
（抽象層を持つことで Episode 7 以降に具体層が増えても Router は変わらない）:
```
抽象責務       具体層(現在)                        例
Card       → interpret_move                      30×スケーリング
Deck       → infer_plan / Deck Intent Inference  Telepath主役誤認
Action     → ActionEvaluator(Fetch/Attach FV)    Towko取得・attach先
Policy     → infer_opening / Decision(Gate)      リーリエ・Boss・T1壁
Kernel     → evaluate_decision/evaluate_plan     測定器自体の限界
Unknown(H6)→ Human Queue                         新Episode候補
```

## 人間の位置付け（変更後）: Reviewer から **Teacher** へ
```
AI: 観測 → AI: 頻度化 → AI: 仮説検証 → AI: Matrix/優先度/責務 → Human: H6(Unknown)の確認 + 月次サンプル監査
```
- Phase 8（毎提出後レビュー）は**残す**が、人間の負荷は「Unknownキューの確認」と「Reviewer出力の抜き打ち監査」に縮小。
- 監査が必要な理由: 検出器は自分が符号化した違和感しか見つけられない（カバレッジ限界）。
- **人間＝Teacher**: 人間が新種の違和感を見つけたら、それは**新しい検出器の仕様**としてLayer 1に追加する。
  `Human → Unknown発見 → Detector追加 → ReplayReviewer進化` ——人間の発見が検出器として蓄積され、
  観測装置が成長する構造（UniversalBotの思想と同型）。

## 既存資産とのマッピング（新規実装は薄い接着層のみ）
| Layer | 既存資産（このセッションで実証済み） |
|---|---|
| 0 | ladder_meta.py（取得・アーキ分類・勝敗） |
| 1a | ladder_dev_timing.py（WastedInvestment原型）/ ladder_three_findings.py（UnusedRight/MissedLethal原型） |
| 1b | evaluate_decision＋decision_diff（Kernel）/ episode4_behavior_diff.py（shadow比較） |
| 1c | ladder_loss_classify.py（敗因分類）/ ladder_meta.py（対面別） |
| 3 | 同一局面shadow・単騎死の手札検証・off-by-one検査＝全て既存スクリプトの手順を規則化 |
| 4-6 | 新規（ただし集計とルーティング表のみ＝ロジックは持たない） |

## 設計原則の遵守
- **Explain-first / Measure-first**: 検出はFact、判断は仮説棄却試験の後。
- **新Analyzer原則禁止**: 検出器は既存Analyzer（threat/development/prize）とリプレイの生事実のみを使う。
- **仮説は実装より軽く**: 仮説セットH1-H6は固定データであり、追加・削除がコード変更なしで可能な形にする。
- **修正と採用の分離**: Reviewerの出力は「修正候補ランキング」まで。修正の実装・採用判定は従来サイクル。
- **Reviewer自身も棄却可能**: 各検出器に「過去の既知事例を再発見できるか」の回帰テストを付ける
  （受け入れ試験: 下表の5事例を無人で再発見できること）。

## 受け入れ試験（設計の妥当性検証＝過去の人間発見を無人再現できるか）
| 過去の発見 | 検出経路（設計上） |
|---|---|
| 死にゆくactiveへのエネ(28件) | 1a WastedInvestment → H4(カーネル方向一貫) → Attach FV責務 |
| Towko→イグニ95% | 1c BehaviorSkew → H4/H5比較 → Fetch FV責務 |
| リーリエ不使用END(15件) | 1a UnusedRight → H2で23件棄却(サポ済)→ H4生存 → Decision(Gate)責務 |
| Boss勝ち逃し(1件) | 1a MissedLethal → Priority C(記録のみ) |
| T1壁交代(2件) | 1b ShadowDisagree ＋ 1a TempoStall → H1で中盤5件は正当と分離 → Decision責務 |

## 実装時の段階（将来・優先キュー外）
Phase R1: Layer 0-2（検出と頻度化＝既存スクリプトの統合） → Phase R2: Layer 3（仮説棄却試験の自動化）
→ Phase R3: Layer 4-6（レポート生成）。着手はEpisode 5（②Fetch FV）の後、または次回提出後のレビュー需要時。
