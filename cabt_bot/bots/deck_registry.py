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
    volatile_energies=(17,),       # イグニはメガ(進化)の場・攻撃できる番のみ付与（浪費防止）
    conserve_volatile=True,        # 今のエネ(ジェットブロー等)でKOできるならイグニ温存
    heal_return_cards=(1229,),     # ミツルは負傷時のみ（無傷使用＝エネ全戻しで有害なため抑止）
    boss_cards=(1182,),            # ボスはKO(サイド)を生む時のみ＋引きずり出し対象もKO優先
    recover_cards=(1097,),         # 夜のタンカは回収価値がある時のみ（無駄打ち防止）
    switch_cards=(1123,),          # ポケモンいれかえは攻撃役を前に出す必要がある時のみ
    smart_take=True,               # ポケギア等のサポ取得を効果×盤面で選ぶ（展開/KO/手札立て直し）
    setup_wall=(666,),             # 先攻T1は攻撃不可→HP160エースバーンを壁に開幕。reposition修正と併せA/B +0.020
    energy_supporters=(1225,),     # トウコ(進化+エネ)。メガが居てエネ切れ＝攻撃不可なら優先＝攻撃を早める
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
    "alakazam": universal_for("alakazam"),   # 1位ログ由来: 超コンボ(フーディン ハンドパワー)
    "froslass": FroslassBot,                 # 1位ログ由来: 水(メガユキメノコex)
    "scrafty": universal_for("scrafty"),     # Control原理: 手札干渉(メガズルズキンex)
}
