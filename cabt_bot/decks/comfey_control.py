"""Comfey/Shaymin/Yveltalコントロール(実ラダー上位、episode 84552024 から採取 2026-07-08)。
上位1043点grimmに2勝1敗した実在コントロールデッキ。PLANはノブ最小主義(Universal infer)。
主役=Comfey(70)×4+Yveltal×2。Boss4/Xerosic4/Acerola4/Colress4/Crushing Hammer4の妨害山。
既知: Comfeyのpayability=Telepathエネ意味論の誤爆歴あり(meta_decks_audit)。要実測。"""
from __future__ import annotations

import dataclasses as _dc
from pathlib import Path as _P

from ..bots.deck_bot import DeckBot
from ..bots.universal_bot import infer_plan as _infer

DECK_CSV = "decks/comfey_control.csv"

_deck = [int(x) for x in (_P(__file__).resolve().parents[2] / DECK_CSV).read_text().split() if x.strip()]
PLAN = _dc.replace(_infer(_deck), name="ComfeyControl",
                   attackers=(164, 689, 343))  # infer漏れ: Yveltal(110)を主砲に追加


class Bot(DeckBot):
    plan = PLAN


THREAT = {"boss_count": 4, "max_line_damage": 110, "spread": 0, "bases": (164, 689, 343), "hand_disruption": 4}
