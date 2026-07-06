"""UniversalBot（Plan AI Episode 4）: デッキ固有の手書き DeckPlan を使わず、
デッキリスト＋カードデータから **最小限の plan（attackers / energy_rules / setup_energy）だけを自動導出**し、
既存の DeckBot エンジン（Analyzer / evaluate_position / Decision Kernel）で回す。

方針(Episode 4 ルール): 新しい Analyzer は作らない。チューニングノブ(boss/recover/wall/spread/reposition…)は
全て OFF のまま。「専用ロジックを書けば勝てる」でなく「Universal が自然に対応できる」ことを目指す。
"""
from __future__ import annotations

import re

from .deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

_SYM = re.compile(r"\{([A-Z])\}|(●)")


def _cost_syms(cost: str | None) -> list[str]:
    """技コスト "{R}{R}●" → ['R','R','C'](●/無色=C)。"""
    if not cost:
        return []
    out = []
    for m in _SYM.finditer(cost):
        out.append("C" if m.group(2) else m.group(1))
    return out


_ABILITY = "[Ability]"
_EST_COUNT = 5      # 可変ダメージの代表個数(手札/ベンチ枚数などの想定値)


def interpret_move(mv) -> dict:
    """Move を総合解釈する（Episode4 の心臓）。damage欄と effect文を統合して
    「攻撃か / 実効ダメージ / コスト記号」を返す。個別if でなく Move全体の解釈能力。
      - "[Ability]" は攻撃でない。
      - damage欄が空でも effect文の「does N damage」「N damage counters ... for each」等からダメージを推定
        ＝可変ダメージ主役(フーディン ハンドパワー / Cruel Arrow 等)を取りこぼさない。
    返り値: {is_attack, est_damage, cost_syms}。"""
    name = mv.name or ""
    if name.startswith(_ABILITY):
        return {"is_attack": False, "est_damage": 0, "cost_syms": [], "partner": None}
    syms = _cost_syms(mv.cost)
    # 相方依存: 「ベンチに X が居ないと何もしない」(例: ソルロック Cosmic Beam→ルナトーン)。
    # ダメージ欄だけ見ると無条件70に見える=ペアの理解が Game Plan に必須(人間レビュー2巡目)。
    partner = None
    if mv.effect:
        m = re.search(r"don[’']t have ([\w\s.'’-]+?) on your Bench, this attack does nothing",
                      mv.effect)
        if m:
            partner = m.group(1).strip()
    est = 0
    if mv.damage:
        m = re.match(r"(\d+)", str(mv.damage))
        if m:
            est = int(m.group(1))
    if est == 0 and mv.effect:                 # damage欄が空 → 効果文から推定
        eff = mv.effect
        m = re.search(r"does (\d+) damage", eff)
        if m:
            est = int(m.group(1))              # 効果文の固定ダメージ(Cruel Arrow=100)
        else:
            m = re.search(r"(\d+) damage counters?.*?for each", eff)
            if m:
                est = int(m.group(1)) * 10 * _EST_COUNT    # counters×10dmg×代表個数(可変)
            elif re.search(r"for each|times the number|damage .*×|×.*damage", eff):
                est = 60                        # 倍率不明の可変=中程度と見なし攻撃役認識
    return {"is_attack": (mv.cost is not None) and est > 0, "est_damage": est,
            "cost_syms": syms, "partner": partner}


def _energy_provides(ci) -> list[str]:
    """エネカードが供給する型記号リスト。Basic {W}→['W']、Ignition {C}{C}{C}→['C','C','C']。
    特殊エネ(無色供給/多色)も type から解釈＝基本エネだけでなく Game Plan のエネ源を正しく捉える。"""
    if not ci or ci.is_pokemon:
        return []
    if "Energy" not in (ci.name or ""):
        return []
    syms = _cost_syms(ci.type or "")           # "{C}{C}{C}"→['C','C','C'], "{W}"→['W']
    if syms:
        return syms
    m = re.search(r"\{([A-Z])\}", ci.name or "")   # fallback: "Basic {W} Energy"
    return [m.group(1)] if m else []


def infer_trainer_roles(ids, cards):
    """Trainerの役割推定(認識のみ)。※カードDBはトレーナー効果文を持たない(rule=None)ため名前ベース。
    「認識」と「使用タイミング」を分離: タイミングは既存の Decision Gate に接続する(ユーザ方針)——
    boss→『KOを生む時のみ』/ recover→『回収価値がある時のみ』/ switch→『攻撃役を前に出す時のみ』。
    ＝GateをONにすることでサポ枠の浪費(Boss早撃ち等)を抑え、Drawサポが自然に回るようにする。"""
    boss, recover, switch = [], [], []
    for i in ids:
        ci = cards.get(i)
        if not ci or ci.is_pokemon or "Energy" in (ci.name or ""):
            continue
        n = ci.name or ""
        if "Boss" in n:
            boss.append(i)
        elif any(k in n for k in ("Stretcher", "Rescue")):
            recover.append(i)
        elif "Switch" in n:
            switch.append(i)
    return tuple(boss), tuple(recover), tuple(switch)


def infer_opening(main_ids, cards) -> dict:
    """Opening Strategy 層（Game Plan → 開幕戦略）。go_first を planの直属性でなくここから導出する
    (将来、相手デッキを見たマッチアップ判断へ拡張するための薄い抽象・ユーザ指示)。
    原則: 進化デッキ=先攻(T1攻撃不可でも土台を先に築くテンポ優先) / 全たねアグロ=後攻(先に殴れる)。
    専用bot群(Mega/Archaludon=先攻, Lightning=後攻)と同じ判断を汎用原則で再現する。"""
    main0 = main_ids[0] if main_ids else None
    ci = cards.get(main0) if main0 else None
    evolved_main = bool(ci) and not getattr(ci, "is_basic", True)
    return {"go_first": evolved_main}


def infer_plan(decklist) -> DeckPlan:
    """デッキリストから最小 plan を推論（デッキ非依存）。attackers / energy_rules / setup_energy / lethal。"""
    C = load_cards()
    ids = list(dict.fromkeys(int(x) for x in decklist))
    pokes = [i for i in ids if C.get(i) and C[i].is_pokemon]

    # デッキが供給できるエネ型(payability判定用)。技の特定型シンボルが供給不能なら
    # その技は"このデッキでは撃てない"＝攻撃役と数えない。
    #   例: Relicanth Razor Fin {F}● は鋼単デッキでは原理的に不払い→攻撃役でなくエンジン役
    #   (damage>0だけで攻撃役認定すると、撃てないポケモンを開幕activeに置いて詰む)
    provided = set()
    for i in ids:
        provided.update(_energy_provides(C.get(i)))

    def payable(im):
        return all(t in provided for t in im["cost_syms"] if t != "C")

    def moves_of(i):
        return [interpret_move(mv) for mv in C[i].moves]

    def usable_attacks(i):
        return [im for im in moves_of(i) if im["is_attack"] and payable(im)]

    def maxdmg(i):
        return max((im["est_damage"] for im in usable_attacks(i)), default=0)

    def best_attack(i):
        atks = usable_attacks(i)
        return max(atks, key=lambda im: im["est_damage"]) if atks else None

    damaging = [i for i in pokes if usable_attacks(i)]
    # 進化線(previous_stage 名で辿る)を含めて attacker 役を集める＝前段のたねも役に含める
    name2id = {C[i].name: i for i in pokes}

    def line(i):
        chain = [i]; cur = C[i]
        seen = {i}
        while cur and cur.previous_stage and cur.previous_stage in name2id:
            pid = name2id[cur.previous_stage]
            if pid in seen:
                break
            chain.append(pid); seen.add(pid); cur = C[pid]
        return chain

    attackers = set()
    for i in damaging:
        attackers.update(line(i))

    # ===== Game Plan 推論層: main attack → 必要エネ → energy_rules / setup_energy =====
    energy_cards = {i: _energy_provides(C.get(i)) for i in ids}   # id → 供給型(特殊エネ含む)
    energy_cards = {i: p for i, p in energy_cards.items() if p}

    def basic_of(t):
        return (next((e for e, p in energy_cards.items() if p == [t]), None)
                or next((e for e, p in energy_cards.items() if t in p), None))

    main = sorted(damaging, key=maxdmg, reverse=True)   # main attack = 最大火力(ゲームプランの中心)
    setup = 0; rules = []

    def assign(atk, primary):
        """主技コストから energy_rules を派生。特殊エネ(無色供給)も使う。"""
        ba = best_attack(atk)
        if not ba:
            return
        syms = ba["cost_syms"]; used = set()
        for t in [x for x in syms if x != "C"]:          # 特定型 → 基本エネ
            e = basic_of(t)
            if e is not None and e not in used:
                rules.append((e, atk)); used.add(e)
        if "C" in syms and primary:                      # 無色枠 → 基本エネ優先
            # 特殊エネ(Ignition等 volatile)は番末トラッシュ等の特別扱いが要り、ノブOFFのUniversalには不利。
            # 基本エネで払えるなら基本を使う(信頼性優先)。基本が無い時のみ特殊エネにフォールバック。
            fb = next((e for e, p in energy_cards.items() if len(p) == 1 and e not in used), None)
            if fb is None:
                fb = next((e for e, p in energy_cards.items() if e not in used), None)
            if fb is not None:
                rules.append((fb, atk)); used.add(fb)

    if main:
        b0 = best_attack(main[0])
        if b0:
            setup = len(b0["cost_syms"])                 # setup = 主役の主技コスト(最初に使う技)
        assign(main[0], primary=True)
        # Phase7蒸留(Lucario Gap23): エネ規則は主火力の50%以上の副役のみ。三次アタッカー
        # (例: Solrock 70 vs ML 270)へ規則を張るとエネが分散し主線が立たない(③エネ配分34-49%の主因)
        for atk in main[1:3]:
            if maxdmg(atk) >= maxdmg(main[0]) * 0.5:
                assign(atk, primary=False)
    rules = list(dict.fromkeys(rules))

    # card_values / play_priority を火力から自動導出（デッキ固有チューニングでなくカードデータ由来）
    #   主役ほど高価値=守る/出す。専用botの手書き値を、火力という普遍指標で代替する。
    # 主役(main[0])の前段(土台)集合。火力ゼロでもゲームプランの土台＝早く置きたい。
    main_line = set()
    if main:
        cur = C.get(main[0])
        while cur and cur.previous_stage and cur.previous_stage in name2id:
            pid = name2id[cur.previous_stage]
            if pid in main_line:
                break
            main_line.add(pid); cur = C.get(pid)
    # 相方依存(ペア)土台: 攻撃役の技が要求する相方(例: ソルロック→ルナトーン)。
    # 相方が居ないと技が「何もしない」＝火力ゼロの土台と同じ扱いで早く置く(人間レビュー2巡目)。
    partners = set()
    for i in attackers:
        for im in moves_of(i):
            p = im.get("partner")
            if p and p in name2id:
                partners.add(name2id[p])
    # play_priority = 火力ベース + 加点(前段=土台 +20 / ペア相方 +15)。固定値でなく加点＝大量タイを避ける。
    card_values = {}
    play_priority = {}
    for i in attackers | partners:
        d = maxdmg(i)
        card_values[i] = min(100, 50 + d // 3)
        base = 50 + min(40, d // 5)                    # 火力ベース(0火力=50, 高火力ほど高い)
        play_priority[i] = (base + (30 if i in main_line else 0)
                            + (15 if i in partners else 0))
        # Phase7蒸留(土台>支援, dragapult/lucarioで実証): 主線土台は火力ゼロでも勝ち筋の入口。
        # 火力由来値だと土台(Riolu60)が支援(Solrock73)を下回り、サーチが勝ち筋を無視する
        if i in main_line:
            card_values[i] = max(card_values[i], 88)
    for e in energy_cards:
        card_values.setdefault(e, 82)                  # エネは温存価値やや高め

    # ===== Phase7(Knowledge Distillation): Benchmark Phaseの5デッキPLANから抽出した一般則を
    # カードテキストから自動導出する(デッキ固有ロジックをUniversalへ還元) =====
    import re as _re
    # ① conserve_hand: 手札枚数スケール技(Powerful Hand等)を自分が使える=手札1枚に打点価値
    conserve_hand = any(
        _re.search(r"for each card in your hand", mv.effect or "")
        for i in attackers for mv in C[i].moves if mv.damage or (mv.effect or ""))
    # ② est_var_damage: 自分のダメカン数スケール技(Raging Hammer等)=可変打点の実数評価
    est_var = any(
        _re.search(r"more damage for each damage counter on this", mv.effect or "")
        for i in attackers for mv in C[i].moves)
    # ③ dup_play_caps: 「1ターンに1回まで」のグローバル制限特性(ルナサイクル等)は1体で充足
    dup_caps = {}
    for i in pokes:
        ab_text = " ".join((mv.effect or "") for mv in C[i].moves
                           if (mv.name or "").startswith("[Ability]"))
        if _re.search(r"can[’']t use more than 1 .* Ability each turn", ab_text):
            dup_caps[i] = 1
    # ④ 特性燃料エネ規則: 「{X}エネが付いていれば」型の特性(Adrena-Brain等)へ該当エネを供給
    fuel_rules = []
    fuel_pokes = set()
    for i in pokes:
        ab_text = " ".join((mv.effect or "") for mv in C[i].moves
                           if (mv.name or "").startswith("[Ability]"))
        m_f = _re.search(r"has any \{([A-Z])\} Energy attached", ab_text)
        if m_f:
            e = basic_of(m_f.group(1))
            if e is not None:
                fuel_rules.append((e, i))
                fuel_pokes.add(i)
    rules = rules + [r for r in fuel_rules if r not in rules]
    # 特性燃料ポケ(Adrena-Brain等)は展開してエネを供給する価値がある(Phase7:
    # grimmsnarl④Adrena起動10%=マシマシラが展開されずD燃料規則が死ぬ、の還元)
    for i in fuel_pokes:
        play_priority[i] = max(play_priority.get(i, 0), 78)
        card_values.setdefault(i, 72)

    opening = infer_opening(main, C)
    boss, recover, switch = infer_trainer_roles(ids, C)
    # HPブーストツール(名前ベース認識。ケープ=+100)。activeの被KO圏→生存圏の反転を最優先
    hp_tools = {i: 100 for i in ids
                if C.get(i) and not C[i].is_pokemon and "Cape" in (C[i].name or "")}
    return DeckPlan(
        name="Universal",
        go_first=opening["go_first"],
        boss_cards=boss,               # 認識=名前ベース / タイミング=既存Gate(KOを生む時のみ)
        recover_cards=recover,         # 同(回収価値がある時のみ)
        switch_cards=switch,           # 同(攻撃役を前に出す時のみ)
        attackers=tuple(attackers),
        key_cards=tuple(main[:2]),
        energy_rules=tuple(dict.fromkeys(rules)),
        lethal=True,                       # KOできる技を優先(デッキ非依存の普遍原則)
        hp_boost_tools=hp_tools,           # ケープ等: 被KO圏→生存圏の反転を最優先
        avoid_overstack=True,              # 飽和対象への追加エネを後回し=後継を並行育成(Attach監査49%=過積みの修正)
        reposition=True,                   # 壁→攻撃役の前進(未設定=壁でENDしMissedFreeAdvance。QA alakazam T4)
        eager_reposition=True,             # エネ付け前判定版(ゲートは「殴れる」検証済のみ通す)
        setup_energy=setup or 0,
        card_values=card_values,
        play_priority=play_priority,
        # Phase7還元(カードテキスト由来の一般則。Benchmark Phaseの5デッキPLANから抽出):
        conserve_hand=conserve_hand,       # 手札スケール技デッキ=手札の切り売り防止
        est_var_damage=est_var,            # 自己ダメカンスケール技=可変打点の実数評価
        dup_play_caps=dup_caps,            # 1ターン1回のグローバル特性=1体で充足
        smart_take=True,                   # サーチ/ポケギア取得の文脈選択(複数デッキでA/B正: +0.026〜+0.039)
    )


class UniversalBot(DeckBot):
    """デッキ固有 plan を持たず、デッキリストから自動導出した最小 plan で既存エンジンを回す。"""
    def __init__(self, decklist=None, plan: DeckPlan | None = None) -> None:
        if plan is None and decklist is not None:
            plan = infer_plan(decklist)
        super().__init__(plan=plan, decklist=decklist)


def universal_for(deck_stem: str) -> type:
    """decks/<stem>.csv を既定デッキとする UniversalBot サブクラスを作る（deck_registry 用・引数なし生成可）。
    複雑archetype(コンボ/Control)で壊れていた config bot をベンチ相手として置換する(Benchmark Health回収)。"""
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "decks" / f"{deck_stem}.csv"

    class _UniversalDeckBot(UniversalBot):
        def __init__(self, decklist=None, plan: DeckPlan | None = None) -> None:
            if decklist is None:
                decklist = [int(x) for x in path.read_text().split() if x.strip()]
            super().__init__(decklist=decklist, plan=plan)

    _UniversalDeckBot.__name__ = f"Universal_{deck_stem}"
    return _UniversalDeckBot
