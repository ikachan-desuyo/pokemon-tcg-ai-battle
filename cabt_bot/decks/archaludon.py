"""Archaludon ex デッキ知識(実ラダー2番目の出血対面: Judge/Carmine型)。

勝ち筋: ジュラルドン→ブリジュラスex(300)。Assemble Alloy(進化時に基本鋼を2枚まで加速)で
即Metal Defender 220。ジーランス(Memory Dive)が居れば進化後もRaging Hammer
(80+自分のダメカン×10)を使える=**傷んだブリジュラスほど砲になる**(被弾が価値)。
Full Metal Labで{M}への被ダメ-30、Judge×4の手札妨害でテンポを取る。
"""
from __future__ import annotations

from collections import defaultdict

from ..bots.deck_bot import DeckBot, DeckPlan
from ..cards import load_cards

DECK_CSV = "decks/ladder_archaludon.csv"

DURALUDON, ARCH, RELICANTH = 169, 190, 57
METAL = 8
CAPE, BOSS, SWITCH, NIGHT_STRETCHER, FML = 1159, 1182, 1123, 1097, 1244
LINE = (DURALUDON, ARCH)

# ==== 操縦側: PLAN ====
PLAN = DeckPlan(
    name="LadderArchaludon",
    go_first=True,
    attackers=(ARCH, DURALUDON),
    key_cards=(ARCH, DURALUDON),
    preferred_attacks=(),                  # 既定=最大ダメージ(RHはest_var_damageで実数比較)
    energy_rules=((METAL, ARCH), (METAL, DURALUDON)),
    play_priority={DURALUDON: 86, RELICANTH: 82},
    card_values={ARCH: 100, DURALUDON: 90, RELICANTH: 84},
    lethal=True,
    est_var_damage=True,                   # Raging Hammer=80+自分ダメカン×10の実数評価
    hp_boost_tools={CAPE: 100},
    boss_cards=(BOSS,),
    recover_cards=(NIGHT_STRETCHER,),
    switch_cards=(SWITCH,),
    smart_take=True,
    dup_play_caps={RELICANTH: 2},          # Memory Dive要員+ボス釣り対策の予備
)


class Bot(DeckBot):
    plan = PLAN


# ==== 対策側: 脅威プロファイル ====
THREAT = {
    "boss_count": 3,
    "max_line_damage": 220,                # MD220。RHは80+ダメカン×10(Cape込み瀕死で最大400級)
    "self_scaling": {ARCH: (80, 10), DURALUDON: (80, 10)},  # RH=(基礎, ダメカン単価)
    "requires": {("RagingHammer",): RELICANTH},  # 進化後RHはMemory Dive(ジーランス)前提
    "bases": (DURALUDON,),
    "hand_disruption": 4,                  # Judge×4(手札を4枚に流される=抱え込み無効)
    "stadium": FML,                        # {M}への技ダメ-30(効果無視技は素通し)
}


# ==== 検収側: IDENTITY ====
def identity_metrics(games, C=None, NAME=None):
    """Archaludonらしさ: ①ブリジュラスT5着地 ②攻撃機会 ③エネは鋼線へ ④ジーランス確保
    (Memory Dive=RHの前提) ⑤傷んだ砲の温存(ダメージ150+のArch線がベンチに存在) ⑥FML展開。"""
    C = C or load_cards()
    NAME = NAME or {cid: c.name for cid, c in C.items()}
    m = defaultdict(lambda: [0, 0])

    def _my(cur):
        return cur["players"][cur["yourIndex"]]

    def _in_play(me):
        return [sp for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp]

    for g in games:
        arch_turn = None
        reli_by4 = False
        gun_preserved = False
        late_turns = fml_turns = 0
        for o, sel in g["rows"]:
            cur = o["current"]
            tn = cur.get("turn")
            me = _my(cur)
            s = o.get("select") or {}
            opts = s.get("option") or []
            ch = opts[sel[0]] if sel and sel[0] < len(opts) else {}
            ids_play = [sp.get("id") for sp in _in_play(me)]
            if arch_turn is None and ARCH in ids_play:
                arch_turn = tn
            if tn <= 4 and RELICANTH in ids_play:
                reli_by4 = True
            # ⑤ 傷んだ砲: ダメージ150+(RH230+)のArch線がベンチに温存されている
            for sp in (me.get("bench") or []):
                if sp and sp.get("id") in LINE and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150:
                    gun_preserved = True
            if s.get("type") != 0:
                continue
            # ⑥ FML: T5以降の自ターンでスタジアムがFML
            if tn >= 5:
                late_turns += 1
                stad = cur.get("stadium")
                sids = [x.get("id") for x in stad] if isinstance(stad, list) else (
                    [stad.get("id")] if isinstance(stad, dict) else [])
                if FML in sids:
                    fml_turns += 1
            hand = me.get("hand") or []
            atk_opt = any(op.get("type") == 13 for op in opts)
            if atk_opt and ch.get("type") in (13, 14):
                m["②攻撃機会を逃さない"][1] += 1
                if ch.get("type") == 13:
                    m["②攻撃機会を逃さない"][0] += 1
            if ch.get("type") == 8 and ch.get("index") is not None and ch["index"] < len(hand):
                cid = hand[ch["index"]].get("id")
                ci = C.get(cid)
                if ci and "Energy" in (ci.name or ""):
                    m["③エネは鋼線へ"][1] += 1
                    area = ch.get("inPlayArea")
                    idx = ch.get("inPlayIndex")
                    spots = (me.get("active") if area == 4 else me.get("bench")) or []
                    tgt = spots[idx] if idx is not None and 0 <= idx < len(spots) else None
                    if tgt and tgt.get("id") in LINE:
                        m["③エネは鋼線へ"][0] += 1
        m["①ブリジュラスT5までに着地"][1] += 1
        if arch_turn is not None and arch_turn <= 5:
            m["①ブリジュラスT5までに着地"][0] += 1
        m["④ジーランスT4までに確保"][1] += 1
        if reli_by4:
            m["④ジーランスT4までに確保"][0] += 1
        m["⑤傷んだ砲の温存(150+)"][1] += 1
        if gun_preserved:
            m["⑤傷んだ砲の温存(150+)"][0] += 1
        if late_turns:
            m["⑥FML展開(T5+)"][1] += late_turns
            m["⑥FML展開(T5+)"][0] += fml_turns
    return m
