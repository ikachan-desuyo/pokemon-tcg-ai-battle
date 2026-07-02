"""ReplayReviewer R1: リプレイ観測装置の最小実装（設計: docs/REPLAY_REVIEWER.md）。

R1スコープ = Layer 0(Collector) + Layer 1(検出器5種) + Layer 2(頻度集計)。
受け入れ条件 = 過去に人間が見つけた5件を無人で自動検出できること:
  1. Towko→Ignition取得偏り     (FetchSkew)
  2. リーリエ不使用END           (UnusedSupporterRight)
  3. Boss勝ち逃し               (MissedLethal)
  4. 死にゆくActiveへのAttach    (WastedInvestment: hindsight版=貼った対象が次の相手ターンまでに戦死)
  5. T1壁交代                   (WallRetreat: 逃げ0の壁から交代し同ターン攻撃なし)
検出はFactのみ(良し悪しは判断しない)。仮説検証(H1-H6)はR2。カーネル不使用=高速。
"""
import json, os, sys, pathlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cabt_bot import load_cards
from cabt_bot.enums import SelectType, OptionType

C = load_cards(); nm = lambda i: (C[i].name if i in C else f"#{i}")
SC = pathlib.Path(os.environ.get("REVIEW_SCRATCH",
    "/tmp/claude-0/-mnt-h-work-pokemon-tcg-ai-battle/2f724d4e-1596-4a25-8039-795c317c6f22/scratchpad"))
MAIN = int(SelectType.MAIN)
OT = {int(getattr(OptionType, x)): x for x in dir(OptionType) if x.isupper()}
PLAY = int(OptionType.PLAY); ATTACH = int(OptionType.ATTACH); ATTACK = int(OptionType.ATTACK)
END = int(OptionType.END); RETREAT = int(OptionType.RETREAT)
MEGA, TOUKO, BOSS, IGN, WATER, STARYU = 1031, 1225, 1182, 17, 3, 1030


# ============ Layer 0: Collector ============

MY_TEAM = "1000PARTY"


def load_game(ep):
    """リプレイ正規化: 自側特定・自分の意思決定列 [(step, obs, action)] (off-by-one補正済)。
    自側特定はメタデータ(info.Agents の Name)を優先——デッキ内容による推定はミラー戦で誤認する
    (初実運用で検出したH3バグ: Starmieミラーでは両デッキに1031が居るため常にagent0を自側と誤判定)。"""
    p = SC / "replays" / f"{ep}.json"
    if not p.exists():
        return None
    rj = json.load(open(p))
    my = None
    agents = (rj.get("info") or {}).get("Agents") or []
    for i, a in enumerate(agents):
        if (a.get("Name") or "") == MY_TEAM:
            my = i
            break
    if my is None:                                   # フォールバック(旧方式)
        d0 = rj["steps"][1][0]["action"]
        my = 0 if (d0 and MEGA in d0) else 1
    decisions = []
    for t in range(2, len(rj["steps"]) - 1):
        ob = rj["steps"][t][my].get("observation") or {}
        cur = ob.get("current")
        if not cur:
            continue
        act = rj["steps"][t + 1][my].get("action")   # action[t+1] ↔ obs[t]
        decisions.append((t, ob, act))
    return {"ep": ep, "my": my, "steps": rj["steps"], "decisions": decisions}


def my_view(ob, my):
    cur = ob["current"]
    return cur, cur["players"][my], cur["players"][1 - my]


def chosen(ob, act):
    sel = ob.get("select")
    if not sel or not act or not isinstance(act, list) or act[0] >= len(sel.get("option") or []):
        return None, None
    return sel, sel["option"][act[0]]


def hand_ids(me):
    return [c.get("id") for c in (me.get("hand") or [])]


def attack_dmg(spot):
    e = len(spot.get("energyCards") or []) if spot else 0
    return 210 if e >= 3 else (120 if e >= 1 else 0)


# ============ Layer 1: Detectors (Factのみ) ============

def det_fetch_skew(g, sig):
    """FetchSkew: トウコ(進化+エネの2枚サーチ)使用後、山→手札の取得のうち**エネルギー選択**を
    文脈(1エネ圏か)つきで記録。進化側のfetchは読み飛ばす(エネ選択が観測対象)。"""
    pending = None; seen = set()   # pending=(lethal1e, play_turn)
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        if pending is not None and cur.get("turn", 0) > pending[1] + 1:
            pending = None                                   # 期限切れ(取り逃し安全弁)
        if pending is not None:
            for lg in (ob.get("logs") or []):
                if (lg.get("type") == 6 and lg.get("fromArea") == 1 and lg.get("toArea") == 2
                        and lg.get("playerIndex") == g["my"] and lg.get("serial") is not None
                        and lg.get("serial") not in seen):
                    seen.add(lg["serial"])
                    cid = lg.get("cardId")
                    ci = C.get(cid)
                    if ci and not ci.is_pokemon and "Energy" in (ci.name or ""):
                        ctx = "1エネ圏○" if pending[0] else "1エネ圏×"
                        sig(f"FetchSkew|トウコのエネ選択→{nm(cid)}|{ctx}", g["ep"], cur.get("turn"))
                        pending = None
                        break
                    # ポケモン側のfetchは読み飛ばして走査継続
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(h) and h[ch["index"]] == TOUKO:
            oa = (opp.get("active") or [None])[0]
            pending = (bool(oa) and (oa.get("hp") or 999) <= 120, cur.get("turn", 0))


def det_unused_supporter(g, sig):
    """UnusedSupporterRight: サポ権未使用でEND、かつ手札サポのPLAY選択肢が実在した。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != END or cur.get("supporterPlayed"):
            continue
        h = hand_ids(me)
        emitted = set()   # 同一局面での重複計上を防ぐ(同名2枚→2選択肢など)
        for o in sel["option"]:
            if o.get("type") == PLAY and o.get("index") is not None and o["index"] < len(h):
                ci = C.get(h[o["index"]])
                if ci and ci.stage == "Supporter" and ci.name not in emitted:
                    emitted.add(ci.name)
                    sig(f"UnusedSupporterRight|{ci.name}", g["ep"], cur.get("turn"))


def det_missed_lethal(g, sig):
    """MissedLethal: 残りサイド1・手札にBoss・ベンチにKO圏(現エネの技で)なのにATTACK/ENDで勝たず。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        if len(me.get("prize") or []) != 1 or BOSS not in hand_ids(me):
            continue
        a = (me.get("active") or [None])[0]
        dmg = attack_dmg(a)
        oa = (opp.get("active") or [None])[0]
        act_ko = bool(oa) and (oa.get("hp") or 999) <= dmg
        bench_ko = any(b and (b.get("hp") or 999) <= dmg for b in (opp.get("bench") or []))
        if bench_ko and not act_ko:
            sig("MissedLethal|Boss未使用でベンチ勝ち筋逃し", g["ep"], cur.get("turn"))


def det_wasted_investment(g, sig):
    """WastedInvestment(hindsight): エネをattachした対象が、次の自分の観測までに戦死していた。"""
    pending = []   # (attach時ターン, 対象id, 対象area)
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        # 前回attachの対象の生死を確認(自分の新しい観測ごと)
        if pending:
            board = {s.get("id") for s in ([(me.get("active") or [None])[0]] + list(me.get("bench") or [])) if s}
            disc = [c.get("id") for c in (me.get("discard") or [])]
            still = []
            for turn0, tid, _ in pending:
                if cur.get("turn", 0) > turn0:              # 相手ターンを跨いだ後
                    if tid not in board and tid in disc:
                        sig(f"WastedInvestment|attach対象が戦死|{nm(tid)}", g["ep"], turn0)
                    # 判定済み(生死どちらでも)として除去
                else:
                    still.append((turn0, tid, _))
            pending = still
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") == ATTACH and ch.get("inPlayArea") in (4, 5):
            spots = (me.get("active") if ch["inPlayArea"] == 4 else me.get("bench")) or []
            idx = ch.get("inPlayIndex", 0)
            sp = spots[idx] if 0 <= idx < len(spots) else None
            if sp:
                pending.append((cur.get("turn", 0), sp.get("id"), ch["inPlayArea"]))


def det_wall_retreat(g, sig):
    """WallRetreat: 逃げ0(None含む)のactiveからRETREATし、同ターンに攻撃しなかった。"""
    for i, (t, ob, act) in enumerate(g["decisions"]):
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != RETREAT:
            continue
        a = (me.get("active") or [None])[0]
        if not a:
            continue
        rc = C.get(a.get("id")).retreat if a.get("id") in C else None
        if rc not in (None, 0):
            continue
        turn = cur.get("turn")
        attacked = False
        for t2, ob2, act2 in g["decisions"][i + 1:]:
            cur2 = ob2.get("current")
            if not cur2 or cur2.get("turn") != turn or cur2.get("yourIndex") != g["my"]:
                break
            _, ch2 = chosen(ob2, act2)
            if ch2 and ch2.get("type") == ATTACK:
                attacked = True
                break
        if not attacked:
            sig(f"WallRetreat|逃げ0壁から交代し攻撃なし|{nm(a.get('id'))}", g["ep"], turn)


def det_valueless_support(g, sig):
    """ValuelessSupportPlay: 効果対象が存在しないサポートでサポ権を消費(Fact)。
    現デッキの具体例: Salvatore(1189=山札から進化)を、進化可能なポケモン(Staryu1030)が場に居ない時に使用。
    (v8 ep83382354 T4 の人間発見: Mega単騎でセイジ→対象ゼロ→サポ権だけ消えた)"""
    SAL = 1189
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        idx = ch.get("index")
        if ch.get("type") != PLAY or idx is None or idx >= len(h) or h[idx] != SAL:
            continue
        inplay = {s.get("id") for s in ([(me.get("active") or [None])[0]] + list(me.get("bench") or [])) if s}
        if STARYU not in inplay:
            sig("ValuelessSupportPlay|Salvatore(進化対象なし)", g["ep"], cur.get("turn"))


def det_last_stand(g, sig):
    """LastStand: 確定敗北圏(ベンチ空×被KO圏×今ターン非致死)での資源運用をFactとして記録。
    人間が1試合で気付く「詰み回避を探すべき局面」——リーリエ(引き直し=ベンチ札を探す唯一の生存線)の
    扱いと、サポ権を何に使ったかを観測する。"""
    from cabt_bot.state_encoder import line_threat
    LIL = 1227
    seen_turn = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        turn = cur.get("turn")
        if turn in seen_turn:
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        bench = [b for b in (me.get("bench") or []) if b]
        if bench or not a or not oa:
            continue
        dmg_in = line_threat(oa.get("id")) or 0
        cc = C.get(a.get("id")); oc = C.get(oa.get("id"))
        if cc and oc and cc.weakness and oc.type == cc.weakness:
            dmg_in *= 2
        if (a.get("hp") or 999) > dmg_in:
            continue                                        # 被KO圏でない
        my_dmg = attack_dmg(a)
        if my_dmg >= (oa.get("hp") or 999):
            continue                                        # 今ターン倒せるなら詰みでない
        seen_turn.add(turn)
        h = hand_ids(me)
        lil = "リーリエ手札あり" if LIL in h else "リーリエなし"
        sup = "サポ権未使用" if not cur.get("supporterPlayed") else "サポ権使用済"
        sig(f"LastStand|単騎×被KO×非致死|{lil}|{sup}", g["ep"], turn)


DETECTORS = [det_fetch_skew, det_unused_supporter, det_missed_lethal,
             det_wasted_investment, det_wall_retreat,
             det_valueless_support, det_last_stand]


# ============ Layer 2: Aggregator ============

def review(episodes):
    counts = Counter(); reps = defaultdict(list)

    def sig(key, ep, turn):
        counts[key] += 1
        if len(reps[key]) < 3:
            reps[key].append(f"ep{ep}:T{turn}")
    n = 0
    for ep in episodes:
        g = load_game(ep)
        if not g:
            continue
        n += 1
        for det in DETECTORS:
            det(g, sig)
    return n, counts, reps


def main():
    rows = json.load(open(SC / "ladder_rows.json"))
    episodes = [r["ep"] for r in rows]
    n, counts, reps = review(episodes)
    print(f"=== ReplayReviewer R1: {n}試合を観測 ===")
    print(f"\n{'シグナル(頻度順)':<52}{'件数':>5}  代表")
    for key, c in counts.most_common(24):
        print(f"{key:<52}{c:>5}  {','.join(reps[key])}")


if __name__ == "__main__":
    main()
