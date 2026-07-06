"""デッキ(csv stem) → 専用 bot の対応表。総当たり評価ループで使う。

各デッキに専用 bot を割り当てる。Starmie 系は DeckBot プランをここで定義。
"""
from __future__ import annotations

from .deck_bot import DeckBot, DeckPlan
from .archaludon_bot import ArchaludonBot
from .imitation_bot import ImitationBot
from .dragapult_bot import DragapultBot
from .gardevoir_bot import MegaGardevoirBot
from .iwapa_bot import IwapaBot
from .lopunny_bot import MegaLopunnyBot
from .lucario_bot import MegaLucarioBot
from .yukinooh_bot import MegaYukinoohBot
from .alakazam_bot import AlakazamBot
from .froslass_bot import FroslassBot
from .scrafty_bot import ScraftyBot
from .universal_bot import universal_for


def _deck_bot(deck_key: str) -> type:
    """cabt_bot/decks/<deck_key>.py のPLAN版botを引数なし生成可能な形で返す(Benchmark Phase)。"""
    from ..decks import DECKS
    mod = DECKS[deck_key]
    path = mod.DECK_CSV

    class _PlanDeckBot(mod.Bot):
        def __init__(self, decklist=None, plan=None) -> None:
            if decklist is None:
                from pathlib import Path
                decklist = [int(x) for x in (Path(__file__).resolve().parents[2] / path).read_text().split() if x.strip()]
            super().__init__(decklist=decklist, plan=plan)

    _PlanDeckBot.__name__ = f"Plan_{deck_key}"
    return _PlanDeckBot

# Mega Starmie（Nebula 主軸）
STARMIE_PLAN = DeckPlan(
    name="MegaStarmie",
    go_first=True,
    attackers=(1031, 1030),               # メガスターミーex / ヒトデマン
    key_cards=(1031, 1030),
    preferred_attacks=("Nebula Beam", "Jetting Blow"),
    spread_attacks=("Jetting Blow",),  # 120でバトル場を倒せるなら、ベンチ50も入るJetting Blowを優先(次のKO準備)
    spread_damage=50,                  # Jetting Blowのベンチ50。将来前に出る火力枠を先読みで削り、KO攻撃回数を減らす
    energy_rules=((17, 1031), (3, 1031)),  # イグニ→メガ, 水→メガ
    play_priority={1030: 80, 666: 60},
    card_values={1031: 100, 17: 90, 1030: 84},
    lethal=True,
    reposition=True,               # 壁(エースバーン)を無料retreatで退かし、ベンチのメガを前に出して殴る（A/B +0.022）
    eager_reposition=True,         # エネ付け前に退く=イグニ(volatileでベンチに貼らない)を前進後に貼って殴る。
                                   # 後段repositionは「ベンチにエネ有」を要求するためイグニ主体では構造的に発火不能
                                   # (人間レビュー3巡目②: 逃げ0壁でENDの真因)
    volatile_energies=(17,),       # イグニはメガ(進化)の場・攻撃できる番のみ付与（浪費防止）
    conserve_volatile=True,        # 今のエネ(ジェットブロー等)でKOできるならイグニ温存
    hp_boost_tools={1159: 100},    # ヒーローマント+100。activeの被KO圏→生存圏の反転を最優先(相手最大火力を計算)
    heal_return_cards=(1229,),     # ミツルは負傷時のみ（無傷使用＝エネ全戻しで有害なため抑止）
    boss_cards=(1182,),            # ボスはKO(サイド)を生む時のみ＋引きずり出し対象もKO優先
    recover_cards=(1097,),         # 夜のタンカは回収価値がある時のみ（無駄打ち防止）
    switch_cards=(1123,),          # ポケモンいれかえは攻撃役を前に出す必要がある時のみ
    smart_take=True,               # ポケギア等のサポ取得を効果×盤面で選ぶ（展開/KO/手札立て直し）
    setup_wall=(666,),             # 先攻T1は攻撃不可→HP160エースバーンを壁に開幕。reposition修正と併せA/B +0.020
    energy_supporters=(1225,),     # トウコ(進化+エネ)。メガが居てエネ切れ＝攻撃不可なら優先＝攻撃を早める
    evolve_supporters=(1189,),     # セイジ(山札から進化)。場に進化対象が居る時のみ=前提条件Gate(無価値使用の防止)
    avoid_overstack=True,          # v7: エネ将来価値原則(飽和or死亡濃厚(can_ko_me)かつ技解放なしの対象へ注がない。
                                   #     Ignition→Nebula解放は例外)。実ラダー32敗中28局面の"死にゆくactiveへの注ぎ"対策。
                                   #     ローカル5環境で悪化なし・死亡濃厚Attach率88→59-63%。最終判定=実ラダー(v7検証提出)
)
# Mega Starmie（spread 主軸）
SPREAD_PLAN = DeckPlan(
    name="MegaStarmieSpread",
    go_first=True,
    attackers=(1031, 112),
    key_cards=(1031, 112),
    preferred_attacks=("Jetting Blow",),
    energy_rules=((7, 112), (3, 1031)),    # 悪→マシマシラ, 水→メガ
    play_priority={112: 84, 103: 76, 1030: 78},
    card_values={1031: 100, 112: 85, 104: 70},
    lethal=True,
    smart_gust=True,   # A/B(80戦) +0.027
    reposition=True,   # A/B(80戦) +0.069
    boss_cards=(1182,),            # ボスはKO時のみ
    recover_cards=(1097,),         # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),          # いれかえは攻撃役を前に出す時のみ
    smart_take=True,               # ポケギアの取得を効果×盤面で選ぶ（共通ノブ A/B +0.024）
)


class MegaStarmiePlanBot(DeckBot):
    plan = STARMIE_PLAN


class MegaStarmieSpreadPlanBot(DeckBot):
    plan = SPREAD_PLAN


# Lightning（弱点デッキ: 水のMegaStarmie exを雷2倍でOHKOする天敵候補。全アタッカーBasic＝速い）
LIGHTNING_PLAN = DeckPlan(
    name="Lightning",
    attackers=(957, 328, 953),             # ミライドンex / ピカチュウex / サンダー(全てたね)
    key_cards=(957, 328),
    energy_rules=((4, 957), (4, 328), (4, 953)),  # 基本雷→各アタッカー
    play_priority={957: 90, 328: 84, 953: 78},
    card_values={957: 100, 328: 90, 953: 80, 4: 85},
    lethal=True,                           # 雷技はMega ex(水)を弱点2倍でOHKO＝KO最優先
    boss_cards=(1182,),                    # ボスはKO時のみ
    recover_cards=(1097,),                 # 夜タンカは回収価値がある時のみ
    switch_cards=(1123,),                  # いれかえは攻撃役を前に出す時のみ
    smart_take=True,
)


class LightningPlanBot(DeckBot):
    plan = LIGHTNING_PLAN


# csv stem -> bot class（引数なしで生成できる）
DECK_BOTS: dict[str, type] = {
    "lightning": LightningPlanBot,
    "deck": MegaStarmiePlanBot,
    "mega_spread": MegaStarmieSpreadPlanBot,
    "dragapult": DragapultBot,
    "lopunny": MegaLopunnyBot,
    "megaruka": MegaLucarioBot,
    "iwapa": IwapaBot,
    "sample_deck": MegaYukinoohBot,
    "gardevoir": MegaGardevoirBot,
    "archaludon": ArchaludonBot,
    "archaludon_il": ImitationBot,
    # コンボ/Control系は config bot が壊れていた(無攻撃100%/82%)ため UniversalBot に置換(Benchmark Health回収)。
    # 旧 AlakazamBot/ScraftyBot はクラスとして残置(比較用)。
    "alakazam": _deck_bot("alakazam"),       # 1位ログ由来: 超コンボ(PH)。Benchmark PhaseでPLAN版へ
    "froslass": FroslassBot,                 # 1位ログ由来: 水(メガユキメノコex)
    "scrafty": universal_for("scrafty"),     # Control原理: 手札干渉(メガズルズキンex)
    # 実ラダー復元ベンチ(2026-07): 1000PARTYの実対戦相手の最頻デッキをUniversalBotで操縦。
    # ローカル旧ベンチ(megaruka 87%/archaludon 70%勝ち)が実ラダー(同アーキ30%)を再現できない問題への回答。
    # Benchmark Phase(2026-07-06): 相手をPLAN版(cabt_bot/decks/=デッキ知識モジュール)へ強化。
    # Identity(らしさ)とH2H(対Universal同デッキ)で検収済み。Universal版はuniversal_forで残置(A/B用)。
    "ladder_lucario": _deck_bot("lucario"),                  # 実メタ最多(33戦)のMega Lucario ex
    "ladder_archaludon": _deck_bot("archaludon"),            # 実ラダーのArchaludon(Judge/Carmine型)
    "dragapult": _deck_bot("dragapult"),                     # ドラパルトex(ダメカン撒き)
    "grimmsnarl": _deck_bot("grimmsnarl"),                   # マリィのオーロンゲex(悪コントロール)
}
