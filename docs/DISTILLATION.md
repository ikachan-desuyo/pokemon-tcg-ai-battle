# 還元台帳 (Distillation Ledger)

**Phase7 = Knowledge Distillation**: 各デッキ(PLAN)で発見した知識をUniversalBotの
自動導出へ蒸留していくフェーズ。デッキを強くするフェーズではない。

```
Replay → PLAN改善 → Identity向上 → 一般化可能? → Universalへ還元
   ↑                                                    ↓
   └──────── Gapが残る ← Identity再測定(卒業試験) ←──────┘
```

- **蒸留率(Gap)** = PLAN Identity − Universal Identity。「Universalがまだ知らないそのデッキの勝ち方」の量。
- **卒業条件**: Gap≈0 になったら PLANを削除するのではなく `PLAN = dataclasses.replace(infer_plan(deck), **薄い差分)` へ置換する(PLAN botはinfer_planを通らない=単純なノブ削除は機能喪失。alakazamで実証)。
- **測定規約(Benchmark QA)**: 卒業試験は **N≥50**。N=20はIdentityが同一構成でも±10pt以上揺れる(lucario 48〜70%を実測)。IdentityメトリクスもReplayReviewer同様「測定器の品質」を疑う(無意味なP重ね貼りが95%正解に見えたバグを実証済み)。

## 台帳

| 知識 | 発見元 | 還元 | 導出方法(カードテキスト) | 効果 |
|---|---|---|---|---|
| 手札価値管理(conserve_hand) | Alakazam | ✅ | 自技に "for each card in your hand" | alakazam 73→80、**Gap 0=卒業級** |
| 特性燃料エネ規則+燃料ポケ展開優先 | Grimmsnarl/Dragapult | ✅ | 特性に "has any {X} Energy attached" | grimm 69→76(④Adrena 10→35%)、drag 75→78 |
| 「1ターン1回」特性=1体で充足(dup cap) | Lucario | ✅ | "can't use more than 1 … Ability each turn" | ソル/ルナ渋滞防止(単独効果は小) |
| 自己ダメカンスケール技の実数評価 | Arch | ✅ | "more damage for each damage counter on this" | arch 78→79 |
| サーチ/取得の文脈選択(smart_take) | 複数(A/B +0.026〜+0.039) | ✅ | (テキスト不要=恒常ON) | 各デッキ横断 |
| 特性コストの手貼りエネ保護 | Lucario(ルナサイクル) | ✅(エンジン層) | "discard a Basic {X} Energy card from your hand" | 全bot即時有効(ノブ不要) |
| 土台優先展開・エネのアタッカー集中 | Lucario | ✅ | ①エネ規則=主火力50%+の副役のみ ②主線土台card_values≥88+priority加点30 | lucario 63→**80%**(N=50, ③34→77%・⑥→68%)、grimm 76→81%へ波及 |
| 被弾価値(傷んだ砲の温存=退避せず砲化) | Arch | ❌ | 候補: 自己スケール技持ちは退避判断で温存加点 | Gap 3(⑤砲温存 PLAN45% vs Uni20%) |
| 開幕壁の選択(非土台・消耗可) | Lucario/Alakazam | ❌ | 注意: archでは壁ノブが逆効果(H2H33%)=導出は条件付きで | — |
| 竜線card_values(土台>支援) | Dragapult | 部分 | 導出は土台+20加点済みだが手書きに劣る | Gap 4 |
| Grimmsnarl残差(アメ線立ち上げ等) | Grimmsnarl | ❌ | 未特定(もう一段の抽象化候補) | Gap 9 |

## 蒸留率スコアボード (2026-07-06 N=50確定・全10構成500戦)

| デッキ | Universal | PLAN | Gap(確定) |
|---|---|---|---|
| Lucario | 81 | 81 | **0** |
| Grimmsnarl | 86 | 86 | **0** |
| Arch | 82 | 83 | 1 |
| Alakazam | 76 | 78 | 2 |
| Dragapult | 79 | 87 | **8** |

N=20時代のGap(23/9/3/0/4)は測定誤差込みだった。確定値では**4/5デッキでUniversal≒PLAN**。
残る知識保有者はDragapultのみ(③エネ貼り分け 78vs91・①着地 14vs22が内訳)。

## Knowledge Inventory (Universalが今知っていること)

| 知識 | 状態 | 発見元 |
|---|---|---|
| 主火力へのエネ集中(50%規則) | 蒸留済 | Lucario |
| 土台優先展開(card_values≥88+加点30) | 蒸留済 | Lucario/Dragapult |
| 特性燃料エネ+燃料ポケ展開 | 蒸留済 | Grimmsnarl/Dragapult |
| 可変火力手札管理(conserve_hand) | 蒸留済 | Alakazam |
| 「1ターン1回」特性の重複抑制 | 蒸留済 | Lucario |
| 自己ダメカンスケールの実数評価 | 蒸留済 | Arch |
| 特性コストの手貼りエネ保護 | 蒸留済(エンジン層) | Lucario |
| サーチ/取得の文脈選択(smart_take) | 蒸留済 | 複数A/B |
| 目的ゲート群(boss/switch/recover/ケープ/土台+相方加点/lethal/reposition) | 導出済(Phase7以前) | Starmie/共通 |
| 二色コストの貼り分け(ワイルドカード主役規則) | **未蒸留** | Dragapult(Gap8の主因候補) |
| 被弾価値(傷んだ砲の温存) | 未蒸留 | Arch(⑤ 56vs42、Gap寄与~1) |
| 開幕壁の選択 | 未蒸留(条件付き=archで逆効果の前科) | Lucario/Alakazam |

## 優先キュー

1. **Dragapult ③エネ貼り分け(Gap8=最後の大きな知識)**: PLANのワイルドカード規則(None→主役)vs導出の型別規則+(P,Dusknoir)分散の差を蒸留
2. 卒業手続き: Gap≈0の4デッキを `infer_plan(deck)+薄い差分` 形へ置換(N=50検収付き)
3. Arch被弾価値(寄与小と確定したため優先度降格)

## Phase7完了条件(ユーザ定義)

**「すべてのPLANが infer_plan(deck) + ごく薄い差分で表現できること」** = UniversalBotの最初の完成形。

## 教訓(PLAN執筆・還元作業の一般則)

- **ノブ最小主義**: Universalの素の挙動が正しい部分にPLANで触ると壊れる(dragapult spread / arch 壁・reposition で3回実証)
- **card_valuesはattackers既定95を上書きする罠**: 「土台>支援」を守らないとサーチが勝ち筋を無視する
- **還元は1個ずつ入れて卒業試験で検収**(まとめて入れると悪化の犯人が特定できない)
