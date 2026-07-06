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


def terminal_check(games=3):
    """終局状態の回帰ガード: サイド全取得の勝者(残0枚)が『6枚残り』扱いされる反転バグの再発防止。
    勝者視点の prize_diff >= 敗者視点、かつ prize残0の側は my_prizes==0 であること。"""
    dl = _load("deck")
    n = ok = 0
    for _ in range(games):
        b0 = R.DECK_BOTS["deck"](decklist=dl); b1 = R.DECK_BOTS["deck"](decklist=dl)
        obs, _sd = battle_start(dl, dl); steps = 0; final = None
        while obs is not None and steps < 600:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                final = (obs["current"], st.result); break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0
            ret = (b0 if who == 0 else b1).select(Observation.from_dict(obs)) or [0]
            obs = battle_select(ret); steps += 1
        battle_finish()
        if not final:
            continue
        cur, w = final; n += 1
        b0._cur = cur
        b0._eval_player = w; prw = b0.analyze_prize()
        b0._eval_player = 1 - w; prl = b0.analyze_prize()
        b0._eval_player = None; b0._cur = None
        cond = prw["prize_diff"] >= prl["prize_diff"]
        for pi in (0, 1):
            pz = cur["players"][pi].get("prize")
            if pz is not None and len(pz) == 0:
                b0._cur = cur; b0._eval_player = pi
                cond = cond and (b0.analyze_prize()["my_prizes"] == 0)
                b0._eval_player = None; b0._cur = None
        ok += bool(cond)
    print(f"terminal_check: {ok}/{n} 終局状態が健全")
    if ok < n:
        raise SystemExit(1)


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
    if not ok:
        raise SystemExit(1)
    terminal_check()
    print("all invariants hold")


if __name__ == "__main__":
    main()
