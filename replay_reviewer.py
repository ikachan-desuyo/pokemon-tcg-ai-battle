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
    """Mega Starmieの実効火力。イグニは進化ポケ上で無3扱い(枚数だけ数えると
    イグニ1枚のNebula Beam 210圏を120と誤評価→MissedLethal偽陽性: lucario-5:T11)。"""
    if not spot:
        return 0
    ci = C.get(spot.get("id"))
    evolved = bool(ci) and not getattr(ci, "is_basic", True)
    e = 0
    for ec in (spot.get("energyCards") or []):
        e += 3 if (ec.get("id") == IGN and evolved) else 1
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
    **ターン最終MAIN時点**で評価する(ターン途中スナップショットだと「その後リーリエ/ベンチ置きで
    解決したケース」を誤検出する)。手札に生存手段(たね/ポフィン)がある場合も対象外(置けば済む)。"""
    from cabt_bot.state_encoder import line_threat
    LIL, POFFIN_ = 1227, 1086
    last_of_turn = {}
    for t, ob, act in g["decisions"]:
        cur = ob.get("current")
        sel, ch = chosen(ob, act)
        if not ch or not cur or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) in ("ATTACK", "END"):     # ターンを閉じる選択=最終MAIN
            last_of_turn[cur.get("turn")] = ob
    for turn, ob in last_of_turn.items():
        cur, me, opp = my_view(ob, g["my"])
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
            continue
        if attack_dmg(a) >= (oa.get("hp") or 999):
            continue
        h = hand_ids(me)
        if any(C.get(x) and C[x].is_pokemon and C[x].is_basic for x in h) or POFFIN_ in h:
            continue                                        # 置けば済む=リーリエ不要
        # リーリエのPLAY選択肢が実在したか(先攻T1はエンジンがサポ禁止=選択肢が無い→bot誤りでない)
        sel = ob.get("select") or {}
        lil_playable = any(o.get("type") == PLAY and o.get("index") is not None
                           and o["index"] < len(h) and h[o["index"]] == LIL
                           for o in (sel.get("option") or []))
        lil = ("リーリエ打てたのに未使用" if lil_playable else
               ("リーリエ手札あり(打てない)" if LIL in h else "リーリエなし"))
        sup = "サポ権未使用" if not cur.get("supporterPlayed") else "サポ権使用済"
        sig(f"LastStand|単騎×被KO×非致死|{lil}|{sup}", g["ep"], turn)


def _move_partner_req(m):
    """技の効果文から「ベンチに X が居ないと何もしない」の X を抽出。無ければ None。"""
    import re
    mt = re.search(r"don[’']t have ([\w\s.'’-]+?) on your Bench, this attack does nothing",
                   m.effect or "")
    return mt.group(1).strip() if mt else None


def _spread_amount(spot):
    """撒き技のベンチダメージ量(効果文「does N damage to 1 of your opponent's Benched」)。無ければ0。"""
    import re
    ci = C.get((spot or {}).get("id"))
    if not ci:
        return 0
    for m in ci.moves:
        mt = re.search(r"does (\d+) damage to 1 of your opponent[’']s Benched", m.effect or "")
        if mt:
            return int(mt.group(1))
    return 0


def det_dead_move(g, sig):
    """DeadMoveAttack: 条件未成立で「何もしない」技での攻撃(例: ルナトーン不在のCosmic Beam)。
    attackIdと技の対応が取れないため、activeの**全ダメージ技**の条件が未成立の場合のみ発火
    (=どの技を選んでいても0ダメ確定。技が複数あり一部だけ死んでいるケースは発火しない=誤検出ゼロ設計)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) != "ATTACK":
            continue
        a = (me.get("active") or [None])[0]
        ci = C.get((a or {}).get("id"))
        if not ci or not ci.moves:
            continue
        bench_names = {nm(b.get("id")) for b in (me.get("bench") or []) if b}
        dmg_moves = [m for m in ci.moves if m.damage]
        if not dmg_moves:
            continue
        reqs = [_move_partner_req(m) for m in dmg_moves]
        if all(r is not None and r not in bench_names for r in reqs):
            sig(f"DeadMoveAttack|{ci.name}|{reqs[0]}ベンチ不在で0ダメ攻撃", g["ep"], cur.get("turn"))


def det_partner_unbenched(g, sig):
    """PartnerUnbenched: 場のポケモンの技が要求する相方がベンチ不在・手札に相方あり・
    PLAY選択肢実在なのに、出さずにターンを閉じた(ATTACK/END)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        bench = [b for b in (me.get("bench") or []) if b]
        bench_names = {nm(b.get("id")) for b in bench}
        board = [s for s in ([(me.get("active") or [None])[0]] + bench) if s]
        need = set()
        for s in board:
            ci = C.get(s.get("id"))
            for m in (ci.moves if ci else []):
                r = _move_partner_req(m)
                if r and r not in bench_names:
                    need.add(r)
        if not need:
            continue
        h = hand_ids(me)
        for o in (sel.get("option") or []):
            if o.get("type") == PLAY and o.get("index") is not None and o["index"] < len(h):
                ci = C.get(h[o["index"]])
                if ci and ci.name in need:
                    sig(f"PartnerUnbenched|{ci.name}を出さずに手番終了(場に依存技)", g["ep"], cur.get("turn"))
                    break


def det_spread_skew(g, sig):
    """SpreadSkew: 撒き(ベンチ50等)の対象選択で、最大脅威線の進化前(たね×撒き2発以内で狩れる)が
    候補に居たのに、今KOでもない別対象を選んだ。KO圏(撒き>=残HP)選択は正当=発火しない。"""
    from cabt_bot.state_encoder import line_threat
    prev_attack = False
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not sel:
            continue
        if sel.get("type") == MAIN:
            prev_attack = bool(ch) and OT.get(ch.get("type")) == "ATTACK"
            continue
        if not prev_attack:
            continue
        prev_attack = False
        opts = sel.get("option") or []
        if not opts or not all(o.get("playerIndex") == 1 - g["my"] for o in opts):
            continue
        spread = _spread_amount((me.get("active") or [None])[0])
        if spread <= 0:
            continue
        cands = []
        for j, o in enumerate(opts):
            spots = (opp.get("active") if o.get("area") == 4 else opp.get("bench")) or []
            if o.get("index") is not None and 0 <= o["index"] < len(spots) and spots[o["index"]]:
                cands.append((j, spots[o["index"]]))
        if not ch or not cands:
            continue
        pick = next((sp for j, sp in cands if j == act[0]), None)
        if not pick:
            continue
        if spread >= (pick.get("hp") or 9999):
            continue                        # 今KOを取った=正当
        # 最大脅威線の進化前: たね × line_threat が候補全体の最大(=真の主力線) × 撒き2発以内で狩れる。
        # 「候補中のスナイプ可能な最大」だと二番手線(Makuhita等)を主力線と誤認する(QAで検出した誤検出)。
        max_th = max((line_threat(sp.get("id")) or 0) for _, sp in cands)
        best = None
        for j, sp in cands:
            ci = C.get(sp.get("id"))
            th = line_threat(sp.get("id")) or 0
            if (ci and ci.is_pokemon and ci.is_basic and th >= 180 and th >= max_th
                    and 2 * spread >= (sp.get("hp") or 9999)):
                if best is None or th > best[1]:
                    best = (sp, th)
        if best and best[0].get("id") != pick.get("id"):   # 同種個体間の選択は対象外
            sig(f"SpreadSkew|主力線進化前({nm(best[0].get('id'))})を外し{nm(pick.get('id'))}へ撒き",
                g["ep"], cur.get("turn"))


DETECTORS = [det_fetch_skew, det_unused_supporter, det_missed_lethal,
             det_wasted_investment, det_wall_retreat,
             det_valueless_support, det_last_stand,
             det_dead_move, det_partner_unbenched, det_spread_skew]


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
