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

## 蒸留率スコアボード (2026-07-06 第3弾後。lucarioのみN=50、他はN=20参考値)

| デッキ | Universal | PLAN | Gap |
|---|---|---|---|
| Alakazam | ~80 | 80 | **≈0** |
| Grimmsnarl | 81 | 85 | 4 |
| Dragapult | 78 | 82 | 4 |
| Arch | 79 | 82 | 3 |
| Lucario | **80**(N=50) | 86 | **6**(23→6) |

## 優先キュー

1. **Arch(被弾価値)**: 「自己スケール技持ちの温存」は新汎用ノブ候補=他デッキにも波及見込み
2. 全デッキのN=50再ベースライン(PLAN側もN=50で測り直しGapを確定)
3. Alakazam: 卒業手続き=導出ベース+差分構造への置換(N=50検収)
4. Lucario残差6・Grimmsnarl残差4: N=50確定後に次の抽象化を特定

## 教訓(PLAN執筆・還元作業の一般則)

- **ノブ最小主義**: Universalの素の挙動が正しい部分にPLANで触ると壊れる(dragapult spread / arch 壁・reposition で3回実証)
- **card_valuesはattackers既定95を上書きする罠**: 「土台>支援」を守らないとサーチが勝ち筋を無視する
- **還元は1個ずつ入れて卒業試験で検収**(まとめて入れると悪化の犯人が特定できない)
