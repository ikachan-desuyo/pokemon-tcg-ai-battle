"""Analyzer Invariant Test — 事実層(Analyzer)同士の整合性を全局面で検証する。

OSの検査能力を"レビュー頼み"から"自動検知"へ引き上げる。今回発見した
「攻撃役が場に無いのに energy_short=0（エネ充足と誤読）」のようなルール違反を、
Analyzerが自分で(check_invariants)検知し、テストが全局面で0件を保証する。

不変条件（DeckBot.check_invariants が判定）:
  Development: energy_short∈[0,need] / ready⟹attacker_short=0 & energy_short=0 & evolution_short=0
               / 攻撃役が場に無い⟹energy_short>0
  Threat     : can_ko_me⟹hits_to_lose=1 / ¬can_ko_me&被弾&HP>0⟹hits_to_lose≥2 / hits_to_lose≥1
  Prize      : prize_diff = opp_prizes - my_prizes
  Phase      : my_evolved ≤ my_attackers
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation
from cabt_bot.bots import deck_registry as R
from cabt_bot.enums import SelectType

MAIN = int(SelectType.MAIN)


def _load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def run(bot_key, deck_file, opp_key="deck", opp_deck="deck", games=6, max_steps=1500):
    """1デッキを複数試合走らせ、root手番の全MAIN局面で check_invariants を集計。"""
    me_deck = _load(deck_file); op_deck = _load(opp_deck)
    checked = 0; violations = []
    for g in range(games):
        bot = R.DECK_BOTS[bot_key](decklist=me_deck)
        opp = R.DECK_BOTS[opp_key](decklist=op_deck) if bot_key != opp_key else R.DECK_BOTS[opp_key]()
        obs, _ = battle_start(me_deck, op_deck); steps = 0
        while obs is not None and steps < max_steps:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0
            if who == 0:
                # root手番: Analyzerを現局面に固定して整合性を検査
                bot.select(Observation.from_dict(obs))          # _cur を現局面にセット
                if obs["select"].get("type") == MAIN:
                    vs = bot.check_invariants()
                    checked += 1
                    if vs:
                        violations.append((g, st.turn if st else "?", vs))
                ret = bot.select(Observation.from_dict(obs))
            else:
                ret = opp.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()
    return checked, violations


def main():
    # 攻撃形の異なる複数デッキで検査（Basic/進化/2進化）
    cases = [
        ("archaludon", "archaludon_real"),
        ("deck", "deck"),
        ("dragapult", "dragapult"),
        ("lightning", "lightning"),
    ]
    total_checked = 0; total_viol = 0; ok = True
    for bot_key, deck_file in cases:
        if bot_key not in R.DECK_BOTS or not os.path.exists(f"decks/{deck_file}.csv"):
            print(f"SKIP {bot_key}/{deck_file} (未登録)"); continue
        checked, violations = run(bot_key, deck_file)
        total_checked += checked; total_viol += len(violations)
        if violations:
            ok = False
            print(f"FAIL {bot_key}: {len(violations)}件の違反 / {checked}局面")
            for g, t, vs in violations[:5]:
                for msg in vs:
                    print(f"    game{g} T{t}: {msg}")
        else:
            print(f"PASS {bot_key}: 0違反 / {checked}局面")
    print(f"--- 合計 {total_checked}局面を検査, 違反 {total_viol}件 ---")
    if ok:
        print("all invariants hold")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
