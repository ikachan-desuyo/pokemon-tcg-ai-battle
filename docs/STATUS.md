# プロジェクト状況サマリ（別環境からの引き継ぎ用）

最終更新: 2026-06-29 / ブランチ: main

## 目的
Kaggle「Pokémon TCG AI Battle Challenge」で賞金（決勝進出）を狙う。
- エンジン: cabt（`cg/` ＝ctypes でロードするネイティブlib、git管理外）。
- 提出物: `submission.tar.gz`（ルート直下に `main.py` + `deck.csv` + `cg/` ＋ `cabt_bot/` + `data/cards.json`）。
- エージェント API: `agent(obs_dict) -> list[int]`（選択肢インデックスのリスト）。`obs.select` が無い初手はデッキ60枚IDを返す。

## 大会ルール（一次情報の整理 / 2026-06-29 確認）
**2部門制。賞金は Strategy 部門にしか付かない。Simulation は実質「予選＋スコア入力」。**
- **Simulation 部門**: Elo ラダーで自動対戦。**単独賞金なし**。当部門の成績は Strategy 審査の入力の一つ。
- **Strategy 部門**: AIの戦略を**レポート（2,000語以内）**で説明。審査 = ①エージェント安定性 ②デッキ設計の発想 ③シミュレーション成績。**上位8チームが決勝進出**。
- 賞金: 優勝 $50,000 / 準優勝 $30,000 / 8ファイナリストに各 $3,000 分 GCP クレジット。
- 締切: Simulation = エントリ/チームマージ 8/9、最終提出 8/16〜17（以降~2週ラダー収束→ロック）。Strategy レポート = 9/14。
- 主催: The Pokémon Company + 松尾研 + HEROZ（Kaggle / Google・Nvidia 協賛）。

### Simulation 対戦ルール要点
- デッキは提出時固定60枚（約2,000枚プールから、スタンダード準拠）。
- Elo（ガウス分布レーティング）。**1日5提出・直近2提出のみが最終採点対象**。
- 1試合10分/プレイヤー、時間切れ＝負け（→bot速度が品質と同等に重要。SearchBot不採用の根拠）。
- 毎手番、エンジンが**合法手のみ**を提示。先攻T1攻撃不可、後攻はT1から攻撃可。

### 戦略上の含意（厳守）
- 「強さ」だけでは賞金に届かない。**Strategy レポートの質が最終勝敗を分ける**。Simulation 成績はその構成要素。
- 直近2提出のみ採点 → 締切間際の提出枠管理が重要（実験提出で直近枠を汚さない）。

## 現在の到達点（結論）
1. **提出デッキ＝MegaStarmie（`decks/deck.csv`）で確定。** フィールド総当たりで 0.76〜0.80 と圧倒（他候補は 0.31〜0.42）。
   - 理由＝**イグニッションエネルギー1枚＝無3＝ネビュラビーム210（後攻T1起動可）の効率**。他メガは大技に色エネ3-4枚要して遅く再現不可。
   - 自作の新候補 Manectric(メガライボルトex)/Camerupt(メガバクーダex) は大敗→棄却。リスト微調整(v2)も悪化→現行リストは完成度高。
2. **操作（ピロッティング）は「手札でほぼ常に最善」に到達。** 攻撃選択・エネ付け・サポート使用を全カテゴリで意思決定監査済み（非最善ほぼ0）。負け試合の原因は引き(運)とデッキ構造であって操作ミスではない、と確認。
3. **提出bot＝`MegaStarmiePlanBot`（DeckBot + STARMIE_PLAN）。** SearchBot は天井を破れず激遅(18戦888秒＝10分制限リスク)のため不採用。

## アーキテクチャ
- `cabt_bot/bots/deck_bot.py` … 設定駆動の中核エンジン `DeckBot` と `DeckPlan`。フェーズ順 ABILITY > PLAY > EVOLVE > ATTACH > ATTACK > END。
  - `DeckPlan` 主要ノブ: `go_first`, `attackers`, `key_cards`, `preferred_attacks`, `energy_rules`, `lethal`, `smart_gust`, `reposition`, `est_var_damage` 等（各デッキで A/B 検証して採否）。
- `cabt_bot/bots/deck_registry.py` … csv stem → 専用bot対応表（`DECK_BOTS`）と `STARMIE_PLAN`/`SPREAD_PLAN`。
- 各デッキ専用bot: dragapult / iwapa / lopunny(MegaLopunny) / lucario(MegaLucario) / yukinooh(MegaYukinooh)。
- `main.py` … 提出エントリ。`BOT = MegaStarmiePlanBot()`、例外時は HeuristicBot/フォールバックで**絶対に落ちない**。`__file__` 非依存のパス解決。
- データ: `data/cards.json`（実行時に load_cards で使用）。`cg.api.all_attack` も実行時に参照（deck_bot）。

## 提出状況
- 最新提出: Kaggle ref **54157981**（"Mega Starmie ex + tuned DeckBot..."）= minimal bundle 581KB、**PENDING（採点待ち）**。
- 過去最高スコア: 618.3（v2 旧HeuristicBot版）。今回は高速・最善手のDeckBotに刷新。
- ブランチ: `submission-3` に**提出時の実体 `submission.tar.gz` をコミット済み**（提出環境スナップショット）。`submission-1`/`-2` は過去提出。

## ビルド & 提出手順
```bash
# プリフライト（構文/構造/合法性/自己完結1試合）
python scripts/check_submission.py

# minimal bundle は提出毎に手動作成（不要プラットフォームlibを除き libcg.so のみ同梱）。
#   自動化はしない方針（中身が提出毎に変わるため）。

# 提出（kaggle CLI は pyenv 3.12.10 環境、~/.kaggle/access_token を使用）
~/.pyenv/versions/3.12.10/bin/kaggle competitions submit pokemon-tcg-ai-battle \
  -f submission.tar.gz -m "<message>"
# 採点状況確認
~/.pyenv/versions/3.12.10/bin/kaggle competitions submissions pokemon-tcg-ai-battle
```

## 運用ルール（厳守）
- **勝手にコミットしない**（1行メッセージ案を提示し、ユーザーが実行）。コミット末尾に `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- **勝手に Kaggle へ提出しない**（明示指示時のみ）。
- 改善ループ中は確認で止めず自律実行・報告のみ。

## 環境メモ
- プロジェクト実行: pyenv Python 3.10系（エンジン動作確認済み）。kaggle CLI のみ 3.12.10。
- 会話ログ/自動メモリは `~/.claude/projects/.../`（ローカルのみ・git管理外）。本ファイルが git 経由の引き継ぎ用。

## 次にやれること（候補）
- **【最重要・賞金直結】Strategy レポート（≤2,000語）の作成**。審査3観点（安定性/デッキ設計の発想/シミュ成績）を満たす論拠を、本リポジトリの検証結果（フィールド総当たり 0.76〜0.80、A/Bノブ、最善手監査）から構成する。Simulation で強くするだけでは賞金に届かない点に留意。
- 採点スコア確定後、旧618.3との比較で効果検証。
- MegaStarmie の維持・微改善（別archetype再探索は費用対効果低、[memory] 参照）。
- 相性別の細かな調整（reposition/smart_gust 等のデッキ別再検証）。
