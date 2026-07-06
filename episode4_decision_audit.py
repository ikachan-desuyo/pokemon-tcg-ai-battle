"""Episode 4: Infer→Decision 接続の Explain 監査（Attach Timing 中心）。

Infer Score(理解)は高いのに勝率が低い＝Decision(運用)が弱い、との仮説を検証する。
UniversalBot の実戦で Game Plan(主役/主技/setup_energy) が Attach/Attack にどう反映されているかを追う:
  ① Attach は主役ライン(plan.attackers)へ向いているか / 主役(active)を育てているか
  ② 主役が active で setup_energy 以上のエネを持つ("準備完了")のに ATTACK せず END＝テンポ失敗
"""
import sys, os
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class
from cabt_bot import Observation, load_cards
from cabt_bot.bots import deck_registry as R
from cabt_bot.bots.universal_bot import UniversalBot, infer_plan
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
MAIN = int(SelectType.MAIN); ATTACH = int(OptionType.ATTACH); ATTACK = int(OptionType.ATTACK); END = int(OptionType.END)


def load(p):
    return [int(x) for x in open(f"decks/{p}.csv").read().split() if x.strip()]


def target_of(ch, me):
    area = ch.get("inPlayArea"); idx = ch.get("inPlayIndex", 0)
    if area == 4:
        act = me.get("active") or [None]; return act[0] if act else None
    if area == 5:
        b = me.get("bench") or []; return b[idx] if idx < len(b) else None
    return None


def main(deck="deck", spec_key=None, games=12):
    spec_key = spec_key or deck
    dl = load(deck); plan = infer_plan(dl)
    atk_set = set(plan.attackers or ()); main_atk = (plan.key_cards or (None,))[0]
    setup = plan.setup_energy or 3
    print(f"=== Attach Timing 監査: {deck} (主役={nm(main_atk)}, setup_energy={setup}) ===")
    st_atk_on_line = 0; st_atk_off = 0; st_atk_active_main = 0
    ready_no_attack = 0; ready_total = 0; attacks = 0
    examples = []
    for g in range(games):
        u = UniversalBot(decklist=dl); opp = R.DECK_BOTS[spec_key](decklist=dl)
        obs, _ = battle_start(dl, dl); steps = 0
        while obs is not None and steps < 400:
            st = to_observation_class(obs).current
            if st and st.result != -1:
                break
            if not (obs.get("select") and obs["select"].get("option")):
                break
            who = st.yourIndex if st else 0; sel = obs["select"]
            if who == 0 and sel.get("type") == MAIN:
                cur = obs["current"]; me = cur["players"][0]
                act = (me.get("active") or [None])[0]
                # 準備完了(主役activeがsetup以上)なのにATTACKせずEND=テンポ失敗を検出
                if act and act.get("id") in atk_set and len(act.get("energyCards") or []) >= setup:
                    has_atk = any(o.get("type") == ATTACK for o in sel["option"])
                    if has_atk:
                        ready_total += 1
                ret = u.select(Observation.from_dict(obs)) or [0]
                ch = sel["option"][ret[0]] if ret and ret[0] < len(sel["option"]) else None
                if ch:
                    if ch.get("type") == ATTACH:
                        tgt = target_of(ch, me)
                        tid = tgt.get("id") if tgt else None
                        if tid in atk_set:
                            st_atk_on_line += 1
                            if ch.get("inPlayArea") == 4 and tid == main_atk:
                                st_atk_active_main += 1
                        else:
                            st_atk_off += 1
                            if len(examples) < 8:
                                examples.append(f"T{st.turn} ATTACH→{nm(tid)}(主役ライン外) active={nm(act['id']) if act else None}")
                    elif ch.get("type") == ATTACK:
                        attacks += 1
                    elif ch.get("type") == END:
                        if act and act.get("id") in atk_set and len(act.get("energyCards") or []) >= setup \
                                and any(o.get("type") == ATTACK for o in sel["option"]):
                            ready_no_attack += 1
                            if len(examples) < 8:
                                examples.append(f"T{st.turn} 準備完了({nm(act['id'])} {len(act.get('energyCards') or [])}エネ)なのにEND=殴らず")
                obs = battle_select(ret); steps += 1; continue
            ret = u.select(Observation.from_dict(obs)) if who == 0 else opp.select(Observation.from_dict(obs))
            obs = battle_select(ret or [0]); steps += 1
        battle_finish()

    tot_at = st_atk_on_line + st_atk_off
    print(f"\n① Attach 先: 主役ライン {st_atk_on_line}/{tot_at} ({100*st_atk_on_line//max(1,tot_at)}%)  うち主役active {st_atk_active_main}  / ライン外 {st_atk_off}")
    print(f"② 準備完了で殴らずEND: {ready_no_attack} 回 / 準備完了局面 {ready_total} (ATTACK総数 {attacks})")
    print(f"--- Explain 例 ---")
    for e in examples:
        print(f"  {e}")


if __name__ == "__main__":
    main()
