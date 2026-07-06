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


def _dmg_with_units(cid, e):
    """カードcidがエネ換算e個で払える技の最大ダメージ(汎用)。"""
    import re
    ci = C.get(cid)
    if not ci or e <= 0:
        return 0
    best = 0
    for m in ci.moves:
        if not m.damage:
            continue
        need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
        mt = re.match(r"(\d+)", str(m.damage))
        if mt and need <= e:
            best = max(best, int(mt.group(1)))
    return best


def attack_dmg(spot, cur=None, target_id=None):
    """そのポケモンが現在の付きエネ(イグニは進化ポケ上で無3扱い)で払える技の最大ダメージ。
    cur+target_id指定時はスタジアム軽減(Full Metal Lab: {M}への技-30, 効果無視技は素通し)を適用
    (bot _eff_dmgと同一意味論。人間レビュー20巡目: FML下Jetting=90/Nebula=210の実測)。"""
    import re
    if not spot:
        return 0
    ci = C.get(spot.get("id"))
    if not ci:
        return 0
    fml = False
    if cur is not None and target_id is not None:
        tc = C.get(target_id)
        stad = cur.get("stadium")
        ids = [x.get("id") for x in stad] if isinstance(stad, list) else ([stad.get("id")] if isinstance(stad, dict) else [])
        fml = (1244 in ids and tc is not None and (tc.type or "") == "{M}")
    evolved = not getattr(ci, "is_basic", True)
    e = sum(3 if (ec.get("id") == IGN and evolved) else 1
            for ec in (spot.get("energyCards") or []))
    if e == 0:
        return 0
    best = 0
    for m in ci.moves:
        if not m.damage:
            continue
        need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
        mt = re.match(r"(\d+)", str(m.damage))
        if mt and need <= e:
            dm = int(mt.group(1))
            if fml and not re.search(r"isn[’']t affected", m.effect or ""):
                dm = max(0, dm - 30)
            best = max(best, dm)
    return best


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
    """MissedLethal: 残りサイド1・BossのPLAY選択肢が実在(=サポ権未使用×手札にBoss)・
    今の付きエネ+手貼りで届く技でベンチKO圏、なのにBossを打たなかった。
    選択肢実在確認(4回目の教訓): サポ権使用済みや、勝ち筋のエネ自体がサポ由来(トウコ)で
    1サポ制約と両立不能なケース(lucario-1:T11=H2)を偽陽性にしない。"""
    boss_turns = set()                                  # そのターン中にBossを打った=見逃しでない
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if ch.get("type") == PLAY and ch.get("index") is not None \
                and ch["index"] < len(h) and h[ch["index"]] == BOSS:
            boss_turns.add(cur.get("turn"))
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if len(me.get("prize") or []) != 1 or cur.get("turn") in boss_turns:
            continue
        h = hand_ids(me)
        boss_playable = any(o.get("type") == PLAY and o.get("index") is not None
                            and o["index"] < len(h) and h[o["index"]] == BOSS
                            for o in (sel.get("option") or []))
        if not boss_playable:
            continue
        a = (me.get("active") or [None])[0]
        if not a:
            continue
        ci = C.get(a.get("id"))
        evolved = bool(ci) and not getattr(ci, "is_basic", True)
        e = sum(3 if (ec.get("id") == IGN and evolved) else 1
                for ec in (a.get("energyCards") or []))
        if not cur.get("energyAttached"):
            inc = 0
            for x in h:
                if C.get(x) and not C[x].is_pokemon and "Energy" in (C[x].name or ""):
                    inc = max(inc, 3 if (x == IGN and evolved) else 1)
            e += inc                                    # 手貼り権+手札エネ=貼った後の火力(イグニ×進化=+3)
        dmg = _dmg_with_units(a.get("id"), e)
        oa = (opp.get("active") or [None])[0]
        act_ko = bool(oa) and (oa.get("hp") or 999) <= dmg
        bench_ko = any(b and (b.get("hp") or 999) <= dmg for b in (opp.get("bench") or []))
        if bench_ko and not act_ko:
            sig("MissedLethal|Boss打てたのにベンチ勝ち筋逃し", g["ep"], cur.get("turn"))


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
    lil_turns = set()      # そのターン中にリーリエのPLAY選択肢が実在した(ターン単位評価)
    lil_played = set()     # そのターン中にリーリエを実際に打った(=未使用でない)
    sup_alone = {}         # サポーターを打った瞬間に単騎だったか(自爆コンボ等で後から単騎化した
                           # ケースは「リーリエを打つべきだった」が成立しない=部品を流す)
    for t, ob, act in g["decisions"]:
        cur = ob.get("current")
        sel, ch = chosen(ob, act)
        if not ch or not cur or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h0 = hand_ids(cur["players"][g["my"]])
        if (ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(h0)):
            ci0 = C.get(h0[ch["index"]])
            if ci0 and ci0.stage == "Supporter":
                bench0 = [b for b in (cur["players"][g["my"]].get("bench") or []) if b]
                sup_alone.setdefault(cur.get("turn"), not bench0)
        if any(o.get("type") == PLAY and o.get("index") is not None
               and o["index"] < len(h0) and h0[o["index"]] == LIL
               for o in (sel.get("option") or [])):
            lil_turns.add(cur.get("turn"))
        if (ch.get("type") == PLAY and ch.get("index") is not None
                and ch["index"] < len(h0) and h0[ch["index"]] == LIL):
            lil_played.add(cur.get("turn"))
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
        if turn in lil_played:
            continue                                        # そのターンにリーリエを打っている
        # 「攻撃が致死ならスキップ」は勝ち切れる(このKOで残サイドを取り切る)場合のみ。
        # KOしても勝たなければ単騎リスクは続き、リーリエ(サポ)と攻撃は両立する(lucario-10の教訓)。
        if (attack_dmg(a, cur, oa.get("id")) >= (oa.get("hp") or 999)
                and _pv(oa.get("id")) >= len(me.get("prize") or [])):
            continue
        h = hand_ids(me)
        if any(C.get(x) and C[x].is_pokemon and C[x].is_basic for x in h) or POFFIN_ in h:
            continue                                        # 置けば済む=リーリエ不要
        # リーリエが「そのターン中のどこかで」打てたか(ターン単位評価=選択肢実在の教訓5回目)。
        # 最終MAIN時点だけ見ると、他サポ(ヒルダ等)が先にサポ権を消費したケースを
        # 「打てない(非ブロッキング)」と誤分類する(lucario-10: リーリエ2枚在手でヒルダ2回→敗北)。
        lil_playable = turn in lil_turns
        sel = ob.get("select") or {}
        if not lil_playable:
            lil_playable = any(o.get("type") == PLAY and o.get("index") is not None
                               and o["index"] < len(h) and h[o["index"]] == LIL
                               for o in (sel.get("option") or []))
        lil = ("リーリエ打てたのに未使用" if lil_playable else
               ("リーリエ手札あり(打てない)" if LIL in h else "リーリエなし"))
        if cur.get("supporterPlayed") and sup_alone.get(turn) is False:
            continue    # サポ使用時点ではベンチが居た=単騎は後から(自爆コンボ等)発生。
                        # その時点でリーリエ優先は成立しない(dragapult相手bot: Cursed Bomb)
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


def det_missed_free_advance(g, sig):
    """MissedFreeAdvance: 逃げ0のエネなし壁でEND。退けばベンチの進化アタッカーが前に出て
    今ターン攻撃可能(エネ有 or 手貼り権+手札エネ)だったのに手番を渡した(人間レビュー2巡目②)。
    前進先が負けベイト(KO=相手残サイド充足×確殺圏)なら前進しないのが正当=対象外。"""
    def _pv_m(cid):
        ci0 = C.get(cid)
        low = ((ci0.rule or "") if ci0 else "").lower()
        if "mega" in low and "ex" in low:
            return 3
        return 2 if "ex" in low else 1

    opp_seen = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
                for ec in (sp.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != END:
            continue
        opts = sel.get("option") or []
        if not any(o.get("type") == RETREAT for o in opts):
            continue
        a = (me.get("active") or [None])[0]
        if not a or (a.get("energyCards") or []):
            continue                                    # 前が攻撃準備済みなら対象外
        ci = C.get(a.get("id"))
        if ci and ci.retreat:                           # 逃げコストあり=無料でない
            continue
        import re as _re

        def _esyms(eid):
            ei = C.get(eid)
            if not ei:
                return []
            return (_re.findall(r"\{([A-Z])\}", ei.type or "")
                    or _re.findall(r"\{([A-Z])\}", ei.name or "") or ["C"])

        def _payable(b, extra=None):
            bi2 = C.get(b.get("id"))
            att = []
            for ec in (b.get("energyCards") or []):
                att += _esyms(ec.get("id"))
            if extra is not None:
                att += _esyms(extra)
            for m in bi2.moves:
                if not m.damage:
                    continue
                need = _re.findall(r"\{([A-Z])\}", m.cost or "")
                pool = list(att)
                ok = all((t in pool and (pool.remove(t) or True)) for t in need)
                if ok and len(pool) >= (m.cost or "").count("●"):
                    return True
            return False
        hand_e = [c.get("id") for c in (me.get("hand") or [])
                  if C.get(c.get("id")) and not C[c.get("id")].is_pokemon
                  and "Energy" in (C[c.get("id")].name or "")]
        can_attach = not cur.get("energyAttached")
        for b in (me.get("bench") or []):
            if not b:
                continue
            bi = C.get(b.get("id"))
            if not bi or bi.is_basic or not any(m.damage for m in bi.moves):
                continue
            _op_m = opp.get("prize")
            opp_left_m = len(_op_m) if _op_m is not None else 6
            oa_m = (opp.get("active") or [None])[0]
            if (_pv_m(b.get("id")) >= opp_left_m
                    and (b.get("hp") or 0) <= _incoming_next(b, oa_m, opp_seen, opp.get("handCount"))):
                continue                                # 負けベイト=前進しないのが正当
            # bot側ゲートと同一意味論: 前進した先が実際に攻撃を払える場合のみ「攻撃可」
            # (エネ1枚在中=攻撃可の緩い判定はWallRetreat検出と矛盾する偽陽性源)
            if _payable(b) or (can_attach and any(_payable(b, e) for e in hand_e)):
                sig(f"MissedFreeAdvance|逃げ0壁でEND({nm(b.get('id'))}前進で攻撃可)", g["ep"], cur.get("turn"))
                break


def det_doomed_no_switch(g, sig):
    """DoomedNoSwitch: 前の攻撃役が次の相手ターンKO確定圏 × ベンチに満タンの進化攻撃役 ×
    入れ替えのPLAY選択肢実在 × 前に常設エネ投資なし、なのに入れ替えず手番を閉じた(温存機会の喪失)。
    (人間レビュー2巡目③: 120HPのメガを晒して喪失。イグニ=volatileは投資と数えない)"""
    from cabt_bot.state_encoder import line_threat
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if not a or not oa:
            continue
        from cabt_bot.state_encoder import line_threat as _lt
        if (_lt(a.get("id")) or 0) < 180 and _pv(a.get("id")) < 2:
            continue    # 温存する価値があるのは主役のみ(壁の温存に主役を晒す提案は逆転。bot温存パスと同一意味論)
        # 現実的評価(相手の現エネ+1で払える技)。bot側温存パスと同一意味論
        # (ライン最大基準だとbotが退避しない局面を検出=不整合)
        dmg_in = _incoming_next(a, oa, None, opp.get("handCount"))
        if dmg_in <= 0 or (a.get("hp") or 999) > dmg_in:
            continue                                    # 被KO圏でない
        if any(e.get("id") != IGN for e in (a.get("energyCards") or [])):
            continue                                    # 常設エネ投資あり=退くと損失(温存対象外)
        if cur.get("energyAttached"):
            continue                                    # 手貼り済み=温存の判断窓は閉じた後(交代は攻撃を失う)
        h = me.get("hand") or []
        sw = any(o.get("type") == PLAY and o.get("index") is not None and o["index"] < len(h)
                 and "Switch" in (C.get(h[o["index"]].get("id")).name if C.get(h[o["index"]].get("id")) else "")
                 for o in (sel.get("option") or []))
        if not sw:
            continue
        for b in (me.get("bench") or []):
            if not b:
                continue
            bi = C.get(b.get("id"))
            _op_dns = opp.get("prize")
            opp_left_dns = len(_op_dns) if _op_dns is not None else 6
            bait = (_pv(b.get("id")) >= opp_left_dns
                    and (b.get("hp") or 0) <= _incoming_next(b, oa, None, opp.get("handCount")))
            if (bi and not bait and not bi.is_basic and any(m.damage for m in bi.moves)
                    and (line_threat(b.get("id")) or 0) >= 180
                    and b.get("hp") == b.get("maxHp") and (b.get("hp") or 0) > (a.get("hp") or 0)):
                # 後続候補は主力線(threat>=180)のみ。壁(Cinderace等=Stage2だが主力でない)への
                # 交代提案は誤検出(QA: Staryu×Cinderace 2件)
                sig(f"DoomedNoSwitch|被KO圏の{nm(a.get('id'))}を温存せず(入替可×満タン{nm(b.get('id'))})",
                    g["ep"], cur.get("turn"))
                break


def _pv(cid):
    """KO時に取れるサイド枚数(メガex=3, ex=2, 他=1)。"""
    c = C.get(cid)
    rule = (c.rule or "").lower() if c else ""
    if "mega" in rule and "ex" in rule:
        return 3
    return 2 if "ex" in rule else 1


def det_boss_no_path_gain(g, sig):
    """BossNoPathGain: ボスでベンチ1枚を取っても必要KO回数(残サイド÷主力サイド価値)が減らない
    局面での使用=勝ち筋を早めない1枚取り(人間レビュー4巡目①④: サイド算術。残5でメガ3×2回=残4でも2回)。"""
    import math
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if not (ch.get("type") == PLAY and ch.get("index") is not None
                and ch["index"] < len(h) and h[ch["index"]] == BOSS):
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        # 火力はこのターンの手貼りを含めて評価(botのassume_hand_attachと同じ意味論。
        # arch-17:T11=水を貼って210でex200を引っ張った正当ボスを偽陽性にしない)
        ci = C.get((a or {}).get("id"))
        evolved = bool(ci) and not getattr(ci, "is_basic", True)
        e = sum(3 if (ec.get("id") == IGN and evolved) else 1
                for ec in ((a or {}).get("energyCards") or []))
        if not cur.get("energyAttached"):
            inc = 0
            for x in h:
                if C.get(x) and not C[x].is_pokemon and "Energy" in (C[x].name or ""):
                    inc = max(inc, 3 if (x == IGN and evolved) else 1)
            e += inc                                    # イグニ×進化=+3(botのassume_hand_attachと同義)
        dmg = _dmg_with_units(a.get("id"), e)
        if oa and (oa.get("hp") or 999) <= dmg:
            continue                        # 前を倒せる状況のボスは別判断(より大きなサイド)
        board = [x for x in ([oa] + list(opp.get("bench") or [])) if x]
        main_pv = max((_pv(x.get("id")) for x in board), default=1)
        koable = [x for x in (opp.get("bench") or []) if x and (x.get("hp") or 999) <= dmg]
        if not koable:
            continue
        # ライン否定の例外: KO可能な引っ張り先に「進化線の土台」が居れば、1枚取りでも
        # 相手の主力供給を断つ価値(サイド算術の外)がある=正当(人間レビュー16巡目
        # mirror相手bot T8: Staryu狩り=3体目のMegaを未然に止める)
        if any(C.get(x.get("id")) and getattr(C[x.get("id")], "is_basic", False)
               and _is_base_of_db_line(x.get("id")) for x in koable):
            continue
        best = max(_pv(x.get("id")) for x in koable)
        need = len(me.get("prize") or []) or 6
        # ボス経路のKO回数(引っ張りKO自体を+1) > 直行経路のみ発火。同数なら「今確実にKOできる」
        # ボスが優位(前は1発で倒せない=実ターン数はもっとかかる。arch-17:T11=H1の教訓)。
        if 1 + math.ceil(max(0, need - best) / main_pv) > math.ceil(need / main_pv):
            sig(f"BossNoPathGain|1枚取りが必要KO回数を増やす(残{need}÷主力{main_pv})",
                g["ep"], cur.get("turn"))


def det_volatile_over_permanent(g, sig):
    """VolatileOverPermanent: 基本エネ1枚で最大技が今ターン払える(恒久エネで毎ターン打てる状態が完成)
    のにvolatile(イグニ)をactiveへ貼った=番末に消え次ターン貼り直し(人間レビュー4巡目②③)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != ATTACH or ch.get("inPlayArea") != 4:
            continue
        h = hand_ids(me)
        idx = ch.get("index")
        if idx is None or idx >= len(h) or h[idx] != IGN:
            continue
        a = (me.get("active") or [None])[0]
        if not a:
            continue
        perm = sum(1 for e in (a.get("energyCards") or []) if e.get("id") != IGN)
        if perm + 1 >= 3 and WATER in h:    # Nebula ●●●=3: 水1枚で恒久3枚が完成する状況
            sig("VolatileOverPermanent|基本エネで恒久3枚完成なのにイグニ貼付", g["ep"], cur.get("turn"))


WALLY, CAPE, LILLIE_ = 1229, 1159, 1227


def _incoming(a, oa, opp_owner_hand_count=None):
    """相手activeライン最大火力(弱点込み)=aが次の相手ターンに受けうる最大ダメージ。
    効果文の可変ダメージ(Powerful Hand=手札枚数×等)は実数で補完(bot _incoming_threatと同一意味論)。"""
    import re
    from cabt_bot.state_encoder import line_threat
    if not a or not oa:
        return 0
    t = line_threat(oa.get("id")) or 0
    cc = C.get(a.get("id")); oc = C.get(oa.get("id"))
    if oc and opp_owner_hand_count is not None:
        for m in oc.moves:
            m2 = re.search(r"lace (\d+) damage counters? on your opponent[’\']s Active Pokémon for each card in your hand", m.effect or "")
            if m2:
                t = max(t, 10 * int(m2.group(1)) * (opp_owner_hand_count + 4))
    if cc and oc and cc.weakness and oc.type == cc.weakness:
        t *= 2
    return t


def det_heal_missed(g, sig):
    """HealMissed: activeが重傷(150+)でミツル(回復)がPLAY可能なのに、別のサポを使った
    (かつ現エネで相手activeをKOできない=回復ターンの価値が高い)。(人間レビュー5巡目①)"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if not (ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(h)):
            continue
        played = h[ch["index"]]
        ci = C.get(played)
        if not ci or ci.stage != "Supporter" or played == WALLY:
            continue
        if played in (TOUKO, BOSS):
            continue    # エネ補給サポ=攻撃成立/ボス=サイド獲得(算術ゲート済)。回復との比較はH1
        wally_playable = any(o.get("type") == PLAY and o.get("index") is not None
                             and o["index"] < len(h) and h[o["index"]] == WALLY
                             for o in (sel.get("option") or []))
        if not wally_playable:
            continue
        a = (me.get("active") or [None])[0]
        if not a or (a.get("maxHp") or 0) - (a.get("hp") or 0) < 150:
            continue
        oa = (opp.get("active") or [None])[0]
        if oa and (oa.get("hp") or 999) <= attack_dmg(a, cur, oa.get("id")):
            continue                                    # 今KOできるなら攻撃優先=回復不要
        if (a.get("maxHp") or 0) <= _incoming(a, oa, opp.get("handCount")):
            continue    # 満タンでもワンパン圏=回復は生存反転しない(bot heal句と同一意味論。
                        # alakazam-2 T7: 330 vs Powerful Hand 340で回復無意味=Salvatoreが正)
        sig(f"HealMissed|重傷activeでミツルでなく{ci.name}を使用", g["ep"], cur.get("turn"))


def det_cape_skew(g, sig):
    """CapeSkew: ケープをベンチに貼ったが、activeに貼れば「被KO圏→生存圏」に反転できた。
    (人間レビュー5巡目②: 相手の出しうる最大火力を計算して貼り先を決める)"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if (ch.get("type") != ATTACH or ch.get("index") is None
                or ch["index"] >= len(h) or h[ch["index"]] != CAPE
                or ch.get("inPlayArea") == 4):
            continue                                    # ケープをベンチへ貼った選択のみ対象
        from cabt_bot.state_encoder import line_threat as _lt
        a = (me.get("active") or [None])[0]
        ca = C.get((a or {}).get("id"))
        if (not a or not ca or ca.is_basic or not any(m.damage for m in ca.moves)
                or (_lt(a.get("id")) or 0) < 180):
            continue    # activeが主力線(threat>=180)の進化アタッカーの時のみ
                        # (壁Cinderace=Stage2だが主力でない、へのケープ温存は正当)
        oa = (opp.get("active") or [None])[0]
        th = _incoming(a, oa, opp.get("handCount"))
        hp = a.get("hp") or 0
        if hp <= th < hp + 100:
            sig("CapeSkew|activeに貼れば被KO圏→生存圏だったのにベンチへ", g["ep"], cur.get("turn"))


def det_energy_stuck_no_lillie(g, sig):
    """EnergyStuckNoLillie: 場のアタッカーがエネ不足で最大技を打てず、手札エネ0、
    リーリエがPLAY可能なのに引き直さずターンを閉じた(手札の質より枚数を優先した惰性)。
    (人間レビュー5巡目③⑤: 山にエネが残っているなら掘りに行く)"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        if cur.get("energyAttached"):
            continue    # このターン手貼り済み=ターン開始時に手札エネがあった(「エネ不足×手札エネ0」の
                        # 前提不成立。貼った後の残り手札で判定する順序アーティファクトの偽陽性)
        h = hand_ids(me)
        if any(C.get(x) and not C[x].is_pokemon and "Energy" in (C[x].name or "") for x in h):
            continue                                    # 手札にエネあり=対象外
        lil = any(o.get("type") == PLAY and o.get("index") is not None
                  and o["index"] < len(h) and h[o["index"]] == LILLIE_
                  for o in (sel.get("option") or []))
        if not lil:
            continue
        a = (me.get("active") or [None])[0]
        # 山のエネ枯れ推定(保守的): デッキのエネ最小構成13枚を仮定し、可視エネ(盤面+トラッシュ)を
        # 引いた山残エネで6ドローの命中率を概算。0.55未満ならbotの見送りは正当としてスキップ
        # (bot側はp_drawで正確に判断: lucario-11:T10=0.0, lucario-18:T8=0.54の境界正当見送り)。
        vis_e = sum(len(sp.get("energyCards") or []) for sp in
                    [(me.get("active") or [None])[0]] + list(me.get("bench") or []) if sp)
        vis_e += sum(1 for c in (me.get("discard") or [])
                     if C.get(c.get("id")) and not C[c.get("id")].is_pokemon
                     and "Energy" in (C[c.get("id")].name or ""))
        deck_n = me.get("deckCount") or len(me.get("deck") or []) or 0
        pool = deck_n + len(me.get("prize") or [])   # 未見エネは山+サイドに分散(サイド落ち希釈)
        rem = max(0, 13 - vis_e)
        p_hit = 0.0
        if pool > 0 and rem > 0:
            miss = 1.0
            for k in range(min(6, pool)):
                miss *= max(0, pool - rem - k) / (pool - k)
            p_hit = 1 - miss
        if p_hit < 0.75:
            continue    # 明確に掘れる場合のみ発火(境界はbotのp_draw=0.55判断を信頼)
        # 生きたミツル(active/ベンチいずれかの攻撃役が重傷150+×生存反転可)在手なら、リーリエは
        # 意図的に温存される(流すとミツルを失う=LillieOverLiveHealと表裏)。botの_attacker_damagedは
        # ベンチも見るため検出器も揃える(dragapult-0:T11=ベンチ重傷での正当温存を偽陽性にしない)。
        if WALLY in h and a:
            oa0 = (opp.get("active") or [None])[0]
            hurt = any(sp and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150
                       for sp in [a] + list(me.get("bench") or []))
            if hurt and (a.get("maxHp") or 0) > _incoming(a, oa0, opp.get("handCount")):
                continue
        ci = C.get((a or {}).get("id"))
        if not a or not ci or ci.is_basic or not any(m.damage for m in ci.moves):
            continue                                    # 進化アタッカーが前のケースに限定
        evolved = not ci.is_basic
        e = sum(3 if (ec.get("id") == IGN and evolved) else 1
                for ec in (a.get("energyCards") or []))
        # 「エネ不足」は実カードの最大技コストで判定(3固定だとMega Brave 2エネ270等を誤検出)
        import re as _re2
        need = max((len(_re2.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
                    for m in ci.moves if m.damage), default=0)
        if need == 0 or e >= need or e == 0:
            continue                                    # 最大技可 / 0=別問題(そもそも回っていない)
        sig("EnergyStuckNoLillie|エネ不足×手札エネ0×リーリエ未使用でターン終了", g["ep"], cur.get("turn"))


def _is_base_of_db_line(cid):
    """カードDB上、cidから進化するカードが存在するか(=進化線の土台)。"""
    ci = C.get(cid)
    if not ci:
        return False
    return any(c.previous_stage == ci.name for c in C.values() if c.previous_stage)


def det_setup_skew(g, sig):
    """SetupSkew: 開幕activeに進化線の土台(Makuhita/リオル等)を置いた。単独で殴れる非土台の
    候補(ソルロック等)が手札に居たなら、土台はベンチで育てるべき(人間レビュー6巡目①)。"""
    for t, ob, act in g["decisions"]:
        cur = ob.get("current")
        sel = ob.get("select") or {}
        if not cur or cur.get("turn", 9) > 0 or sel.get("context") != 1 or not act:
            continue
        opts = sel.get("option") or []
        me = cur["players"][g["my"]]
        hand = me.get("hand") or []
        def cid_of(o):
            i = o.get("index")
            return hand[i].get("id") if i is not None and i < len(hand) else None
        ch = opts[act[0]] if act[0] < len(opts) else {}
        chosen_id = cid_of(ch)
        if chosen_id is None or not _is_base_of_db_line(chosen_id):
            continue
        for o in opts:
            oc = cid_of(o)
            ci = C.get(oc) if oc else None
            if (ci and ci.is_pokemon and not _is_base_of_db_line(oc)
                    and any(m.damage for m in ci.moves)):
                sig(f"SetupSkew|開幕activeに土台{nm(chosen_id)}(非土台{nm(oc)}が手札に有)",
                    g["ep"], 0)
                return


def det_dead_evolution_pick(g, sig):
    """DeadEvolutionPick: サーチで進化ポケを取ったが、進化元が場にも手札にも無い=置けない
    (先に土台のたねを取る/置くべき。人間レビュー6巡目③)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel = ob.get("select") or {}
        if cur.get("yourIndex") != g["my"] or sel.get("type") == MAIN or not act:
            continue
        deck = sel.get("deck") or []
        opts = sel.get("option") or []
        if not deck and not (cur.get("looking") or []):
            continue
        names = set()
        for sp in [(me.get("active") or [None])[0]] + list(me.get("bench") or []):
            if sp and C.get(sp.get("id")):
                names.add(C[sp["id"]].name)
        for cd in me.get("hand") or []:
            if C.get(cd.get("id")):
                names.add(C[cd["id"]].name)
        if 1079 in hand_ids(me):
            continue    # ふしぎなアメ在手=進化カードの先取りは計画として正当(H1)
        looking = cur.get("looking") or []
        def card_at(o):
            idx = o.get("index")
            src = deck if o.get("area") == 1 else (looking if o.get("area") == 12 else None)
            if src is None or idx is None or idx >= len(src):
                return None
            return ((src[idx] or {}).get("id") or (src[idx] or {}).get("cardId"))
        cand_ids = {card_at(o) for o in opts} - {None}
        cand_names = {C[c].name for c in cand_ids if C.get(c)}
        for i in act:
            if i >= len(opts):
                continue
            cid = card_at(opts[i])
            ci = C.get(cid)
            # 発火は「同じ候補内に“それ自体が配置可能な”土台が有ったのに進化側を取った」場合のみ
            # (土台候補も死に札(進化元不在の中間進化)なら消去法の取得=正当。dragapult-2:T2)
            base_ok = False
            if ci and ci.previous_stage and ci.previous_stage in cand_names:
                for bc in cand_ids:
                    bci = C.get(bc)
                    if (bci and bci.name == ci.previous_stage
                            and (bci.is_basic or (bci.previous_stage or "") in names)):
                        base_ok = True
                        break
            if (ci and ci.is_pokemon and not ci.is_basic and ci.previous_stage
                    and ci.previous_stage not in names
                    and base_ok):
                sig(f"DeadEvolutionPick|土台{ci.previous_stage}を差し置き進化側{ci.name}を取得",
                    g["ep"], cur.get("turn"))


def det_lillie_over_live_heal(g, sig):
    """LillieOverLiveHeal: 重傷(150+)×生存反転可のミツルが手札にあるのにリーリエで手札を流した
    =今まさに条件成立中の状況札を捨てるリスク(人間レビュー6巡目④: 温存の順序)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        if not (ch.get("type") == PLAY and ch.get("index") is not None
                and ch["index"] < len(h) and h[ch["index"]] == LILLIE_):
            continue
        if WALLY not in h:
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if (a and (a.get("maxHp") or 0) - (a.get("hp") or 0) >= 150
                and (a.get("maxHp") or 0) > _incoming(a, oa, opp.get("handCount"))):
            sig("LillieOverLiveHeal|重傷×反転可のミツルをリーリエで流すリスク", g["ep"], cur.get("turn"))


def det_doomed_no_retreat(g, sig):
    """DoomedNoRetreat: 前の攻撃役(サイド2+)が次ターン被KO確定圏×不利トレード(取れるサイド<
    失うサイド)×RETREAT可×ベンチに攻撃可能な主力後続、なのに残って手番を閉じた(人間レビュー6巡目⑤)。"""
    from cabt_bot.state_encoder import line_threat
    opp_seen = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))
        for sp_o in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp_o:
                opp_seen.add(sp_o.get("id"))
                for ec in (sp_o.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        opts = sel.get("option") or []
        if not any(o.get("type") == RETREAT for o in opts):
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if not a or _pv(a.get("id")) < 2:
            continue
        th = _incoming(a, oa, opp.get("handCount"))
        if th <= 0 or (a.get("hp") or 999) > th:
            continue                                    # 被KO圏でない
        dmg = attack_dmg(a, cur, (oa or {}).get("id"))
        _mp = me.get("prize")
        my_left = len(_mp) if _mp is not None else 6
        if oa and (oa.get("hp") or 999) <= dmg and (_pv(oa.get("id")) >= _pv(a.get("id"))
                                                    or _pv(oa.get("id")) >= my_left):
            continue                                    # 同等以上のトレード or 勝ち切り=残って殴るのは正当
        h = hand_ids(me)
        can_pay = (not cur.get("energyAttached")
                   and any(C.get(x) and not C[x].is_pokemon and "Energy" in (C[x].name or "") for x in h))
        for b in (me.get("bench") or []):
            if not b:
                continue
            bi = C.get(b.get("id"))
            if (bi and not bi.is_basic and (line_threat(b.get("id")) or 0) >= 180
                    and (b.get("hp") or 0) > _incoming_next(b, oa, opp_seen, opp.get("handCount"))
                    and ((b.get("energyCards") or []) or can_pay)):
                sig(f"DoomedNoRetreat|被KO確定×不利トレードで{nm(a.get('id'))}が残留",
                    g["ep"], cur.get("turn"))
                break


def _spot_of(cur, side, o):
    pl = cur["players"][o.get("playerIndex", side)]
    spots = (pl.get("active") if o.get("area") == 4 else pl.get("bench")) or []
    idx = o.get("index")
    return spots[idx] if idx is not None and 0 <= idx < len(spots) else None


def det_gust_target_skew(g, sig):
    """GustTargetSkew: ボス等の引き出し(SWITCH×相手対象)で、KO可能×より高サイドの候補を差し置き
    低価値対象を選んだ(人間レビュー7巡目②: Mega90(3枚KO可)でなくStaryu70)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"]:
            continue
        if (sel or {}).get("context") != 3:
            continue
        opts = sel.get("option") or []
        if not opts or not all(o.get("playerIndex") == 1 - g["my"] for o in opts):
            continue                                    # 相手対象(ボス)のみ。自分側(退避先)は対象外
        a = (me.get("active") or [None])[0]
        # 火力は手貼り込み(botのassume_hand_attachと同義): ボス直後に貼って殴るのが通常の並び
        ci_a = C.get((a or {}).get("id"))
        evolved_a = bool(ci_a) and not getattr(ci_a, "is_basic", True)
        e_a = sum(3 if (ec.get("id") == IGN and evolved_a) else 1
                  for ec in ((a or {}).get("energyCards") or []))
        if not cur.get("energyAttached"):
            h_ = hand_ids(me)
            inc = 0
            for x in h_:
                if C.get(x) and not C[x].is_pokemon and "Energy" in (C[x].name or ""):
                    inc = max(inc, 3 if (x == IGN and evolved_a) else 1)
            e_a += inc
        dmg = _dmg_with_units((a or {}).get("id"), e_a)
        # 相方依存技(Cosmic Beam等)は相方不在なら0=「KOできた」と誤算しない(lucario-3:T4)
        bench_names_ = {nm(b.get("id")) for b in (me.get("bench") or []) if b}
        ci_chk = C.get((a or {}).get("id"))
        if ci_chk and dmg > 0:
            import re as _re3
            ok = 0
            for m in ci_chk.moves:
                if not m.damage:
                    continue
                need = len(_re3.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
                mt = _re3.match(r"(\d+)", str(m.damage))
                if not mt or need > e_a:
                    continue
                req = _move_partner_req(m)
                if req and req not in bench_names_:
                    continue
                ok = max(ok, int(mt.group(1)))
            dmg = ok
        pick = _spot_of(cur, g["my"], ch)
        if not pick:
            continue
        pick_val = (_pv(pick.get("id")) if (pick.get("hp") or 999) <= dmg else 0)
        best = max(((_pv(sp.get("id")) if (sp.get("hp") or 999) <= dmg else 0)
                    for sp in (_spot_of(cur, g["my"], o) for o in opts) if sp), default=0)
        if best > pick_val:
            sig(f"GustTargetSkew|KO可×高サイド候補を差し置き{nm(pick.get('id'))}を引き出し",
                g["ep"], cur.get("turn"))


def det_promotion_skew(g, sig):
    """PromotionSkew: 昇格/退避先(自分の新active)選択で、相手最大火力を耐える攻撃役が居るのに
    1発で落ちる候補や壁を前に出した(人間レビュー7巡目①③: 1ターン耐えればマント/ミツルを引けた)。"""
    from cabt_bot.state_encoder import line_threat
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"]:
            continue
        if (sel or {}).get("context") not in (3, 4):
            continue
        opts = sel.get("option") or []
        if len(opts) < 2 or not all(o.get("playerIndex") == g["my"] for o in opts):
            continue                                    # 自分側の複数候補のみ
        oa = (opp.get("active") or [None])[0]
        pick = _spot_of(cur, g["my"], ch)
        if not pick:
            continue
        def survives(sp):
            return (sp.get("hp") or 0) > _incoming(sp, oa, opp.get("handCount"))
        def is_main(sp):
            return (line_threat(sp.get("id")) or 0) >= 180
        if survives(pick) and is_main(pick):
            continue                                    # 耐える主力を選んだ=正当
        better = any(sp and survives(sp) and is_main(sp)
                     for sp in (_spot_of(cur, g["my"], o) for o in opts))
        if better:
            sig(f"PromotionSkew|耐える主力が居るのに{nm(pick.get('id'))}hp{pick.get('hp')}を前に",
                g["ep"], cur.get("turn"))


def _incoming_next(a, oa, opp_seen=None, opp_owner_hand_count=None):
    """次の相手ターンの現実的な最大被ダメ: 相手activeライン(進化1段含む)の技のうち
    現エネ+1(手貼り)で払える最大(弱点込み)。進化候補は観測済み(opp_seen)に限定。
    opp_owner_hand_count=相手手札枚数(可変ダメージ=Powerful Hand等を実数評価。bot側
    _effect_move_damageと同一意味論)。"""
    import re
    if not a or not oa:
        return 0
    e = len(oa.get("energyCards") or []) + (3 if (opp_seen is not None and IGN in opp_seen) else 1)
    oi = C.get(oa.get("id"))
    moves = list(oi.moves) if oi else []
    for pe in (oa.get("preEvolution") or []):
        pi_ = C.get((pe or {}).get("id"))
        if pi_:
            moves += list(pi_.moves)   # 進化前スタックの技も使える(エンジン実測: Raging Hammer)
    for did, di in C.items():
        if (oi and di.previous_stage == oi.name and di.is_pokemon
                and (opp_seen is None or did in opp_seen)):
            moves += list(di.moves)
    hc = opp_owner_hand_count
    best = 0
    for m in moves:
        need = len(re.findall(r"\{[A-Z]\}", m.cost or "")) + (m.cost or "").count("●")
        if need > e:
            continue
        mt = re.match(r"(\d+)", str(m.damage or ""))
        dm = int(mt.group(1)) if mt else 0
        eff = (m.effect or "")
        if hc is not None:
            m2 = re.search(r"lace (\d+) damage counters? on your opponent[’']s Active Pokémon for each card in your hand", eff)
            if m2:
                dm = max(dm, 10 * int(m2.group(1)) * (hc + 4))
            m2 = re.search(r"does (\d+) (?:more )?damage for each card in your hand", eff)
            if m2:
                dm = max(dm, dm + int(m2.group(1)) * (hc + 4))
        m2 = re.search(r"does (\d+) more damage for each Energy attached to your opponent[’']s Active", eff)
        if m2:
            dm = max(dm, dm + int(m2.group(1)) * len(a.get("energyCards") or []))
        m2 = re.search(r"does (\d+) more damage for each damage counter on this", eff)
        if m2:
            cnt = max(0, ((oa.get("maxHp") or 0) - (oa.get("hp") or 0)) // 10)
            dm = max(dm, dm + int(m2.group(1)) * cnt)
        best = max(best, dm)
    cc = C.get(a.get("id"))
    if cc and oi and cc.weakness and oi.type == cc.weakness:
        best *= 2
    return best


def det_weak_advance(g, sig):
    """WeakAdvance: 壁が相手の次打(現実的評価=現エネ+1で払える技)を耐えるのに、脆いたね
    (エネ付き=将来の進化素材)を前進させた(人間レビュー7巡目①: 20点のためにエネ付きStaryuを晒す)。"""
    opp_seen = set()                                    # 相手の場で観測されたカード(その時点まで)
    prev_retreat = False
    pending = []
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))  # トラッシュ観測はエネのみ(イグニ検出。ポケモンは盤面不在=進化脅威に数えない)
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp and sp.get("id") is not None:
                opp_seen.add(sp["id"])
        sel, ch = chosen(ob, act)
        if not sel or cur.get("yourIndex") != g["my"]:
            continue
        if sel.get("type") == MAIN:
            a = (me.get("active") or [None])[0]
            oa = (opp.get("active") or [None])[0]
            prev_retreat = (bool(ch) and ch.get("type") == RETREAT and a
                            and (a.get("hp") or 0) > _incoming_next(a, oa, opp_seen, opp.get("handCount")))  # 壁は耐えていた
            continue
        if not prev_retreat or sel.get("context") != 3:
            continue
        prev_retreat = False
        opts = sel.get("option") or []
        pick = _spot_of(cur, g["my"], ch) if ch else None
        ci = C.get((pick or {}).get("id"))
        if (pick and ci and ci.is_basic and (pick.get("energyCards") or [])
                and _is_base_of_db_line(pick.get("id"))):
            pending.append((cur.get("turn"), pick.get("id")))
    # 同ターン内にactiveへの進化が続いた前進は「進化プラットフォーム」=正当
    # (arch相手bot: 土台前進→Rare Candy進化→攻撃まで同ターン完走)
    evolve_turns = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if (ch and cur.get("yourIndex") == g["my"] and (sel or {}).get("type") == MAIN
                and ch.get("type") == int(OptionType.EVOLVE) and ch.get("inPlayArea") == 4):
            evolve_turns.add(cur.get("turn"))
    for tn, pid in pending:
        if tn not in evolve_turns:
            sig(f"WeakAdvance|耐える壁を退きエネ付きたね{nm(pid)}を前進", g["ep"], tn)
            return


def det_basic_unbenched(g, sig):
    """BasicUnbenched: 単騎(ベンチ空)なのに、そのターン中に出せたたねポケモンを出さず
    ターンを閉じた(手札シャッフルで流す等=ベンチ切れ負けのリスク。arch-8:T2の教訓)。"""
    playable_turns = {}                                 # turn -> たねPLAY選択肢があった
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if any(b for b in (me.get("bench") or []) if b):
            continue                                    # 単騎の時のみ
        h = hand_ids(me)
        if (ch.get("type") == PLAY and ch.get("index") is not None and ch["index"] < len(h)
                and C.get(h[ch["index"]]) and C[h[ch["index"]]].is_pokemon
                and C[h[ch["index"]]].is_basic):
            playable_turns.pop(cur.get("turn"), None)      # 実際に出した(後で特性等により離れても対象外)
            played_this = playable_turns.setdefault("_played", set())
            played_this.add(cur.get("turn"))
        for o in (sel.get("option") or []):
            if (o.get("type") == PLAY and o.get("index") is not None and o["index"] < len(h)
                    and C.get(h[o["index"]]) and C[h[o["index"]]].is_pokemon
                    and C[h[o["index"]]].is_basic
                    and cur.get("turn") not in playable_turns.get("_played", set())):
                playable_turns[cur.get("turn")] = nm(h[o["index"]])
                break
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        turn = cur.get("turn")
        if turn not in playable_turns:
            continue
        if any(b for b in (me.get("bench") or []) if b):
            continue                                    # 結局出した(解決済み)
        sig(f"BasicUnbenched|単騎なのに出せた{playable_turns[turn]}を出さず手番終了", g["ep"], turn)


def det_evolve_trigger_before_develop(g, sig):
    """EvolveTriggerBeforeDevelop: 進化トリガー特性(『手札から進化した時』=Punk Up等)を持つ進化を、
    同ターンに出せたスタジアム/たねより先に実行(配分先が少ないまま特性を発動=損。grimmsnarl-7:T4)。"""
    import re as _re
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        h = hand_ids(me)
        # 選択=アメ(1079)のPLAY or EVOLVE
        is_candy = (ch.get("type") == PLAY and ch.get("index") is not None
                    and ch["index"] < len(h) and h[ch["index"]] == 1079)
        is_evolve = OT.get(ch.get("type")) == "EVOLVE"
        if not (is_candy or is_evolve):
            continue
        # 手札に進化トリガー特性持ちの進化カードがあるか(=これから出す可能性が高い)
        trigger = any(
            C.get(x) and any(_re.search(r"When you play this Pok\S+mon from your hand to evolve",
                                        m.effect or "") for m in C[x].moves)
            for x in h)
        if not trigger:
            continue
        # 同じMAINの選択肢に「出せたスタジアム/たね」が残っていた
        dev = False
        for o in (sel.get("option") or []):
            if o.get("type") != PLAY or o.get("index") is None or o["index"] >= len(h):
                continue
            ci = C.get(h[o["index"]])
            if ci and (("Stadium" in (ci.stage or "")) or (ci.is_pokemon and ci.is_basic)):
                dev = True
                break
        if dev:
            sig("EvolveTriggerBeforeDevelop|展開(スタジアム/たね)前に進化トリガーを消費", g["ep"], cur.get("turn"))


def det_spread_into_immune(g, sig):
    """SpreadIntoImmune: 撒き(攻撃効果のベンチ選択)の対象に、ベンチ被ダメ無効特性
    (Dragapult exのTera等)持ちを選択=ダメージが完全に無駄(AI自己レビュー: dragapult-3 T9/T11)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"]:
            continue
        if (sel or {}).get("context") != 15:
            continue
        opts = sel.get("option") or []
        if not opts or not all(o.get("playerIndex") == 1 - g["my"] for o in opts):
            continue
        pick = _spot_of(cur, g["my"], ch)
        if not pick or ch.get("area") == 4:
            continue                                    # active対象は無効特性の範囲外
        ci = C.get(pick.get("id"))
        if ci and any("on your Bench, prevent all damage" in (m.effect or "") for m in ci.moves):
            # 他に有効な候補があった場合のみ(全候補が無効なら仕方ない)
            others = [sp for sp in (_spot_of(cur, g["my"], o) for o in opts)
                      if sp and sp is not pick
                      and not (C.get(sp.get("id")) and any("on your Bench, prevent all damage" in (m.effect or "")
                                                           for m in C[sp.get("id")].moves))]
            if others:
                sig(f"SpreadIntoImmune|被ダメ無効の{nm(pick.get('id'))}へ撒き(有効候補あり)", g["ep"], cur.get("turn"))


def det_bench_heal_missed(g, sig):
    """BenchHealMissed: エネ0×重傷150+のベンチ攻撃役(回復の機会損失ゼロ×攻撃と両立)が居て
    ミツルがPLAY可能なのに、別サポを使った/サポ権未使用で手番を閉じた(AI自己レビュー: dragapult-3 T11)。"""
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if OT.get(ch.get("type")) not in ("ATTACK", "END"):
            continue
        if cur.get("supporterPlayed"):
            continue    # サポ権を別用途(ボス=サイド/トウコ=攻撃成立等)に使ったのはH1=対象外
        h = hand_ids(me)
        if WALLY not in h:
            continue
        # 選択肢実在: PLAY Wallyがエンジンの選択肢に無ければ対象外(Wallyの対象=Mega限定=
        # Cinderace等の壁が重傷でも打てない。mirror-6 T7: 手札在中だけ見て発火した偽陽性)
        if not any(o.get("type") == PLAY and o.get("index") is not None
                   and o["index"] < len(h) and h[o["index"]] == WALLY
                   for o in (sel.get("option") or [])):
            continue
        target = any(sp and (sp.get("maxHp") or 0) - (sp.get("hp") or 0) >= 150
                     and not (sp.get("energyCards") or [])
                     and (C.get(sp.get("id")) and not C[sp.get("id")].is_basic)
                     for sp in (me.get("bench") or []))
        if not target:
            continue
        sig("BenchHealMissed|エネ0重傷ベンチ×ミツル在手なのに回復せず", g["ep"], cur.get("turn"))


def det_energy_type_skew(g, sig):
    """EnergyTypeSkew: 同一対象へのエネattachで、選んだエネは最大技の未充足コストを進めないのに、
    手札の別エネなら進められた(例: Phantom Dive={R}{P}にR在中でRを重ね、Pが手札にあった)。
    (人間レビュー10巡目: dragapult相手botのR+R重ねで技が撃てず)"""
    import re as _re

    def _esyms(eid):
        ei = C.get(eid)
        if not ei:
            return []
        return (_re.findall(r"\{([A-Z])\}", ei.type or "")
                or _re.findall(r"\{([A-Z])\}", ei.name or "") or ["C"])

    def _progresses(eid, spot):
        bi = C.get(spot.get("id"))
        if not bi:
            return None
        att = []
        for ec in (spot.get("energyCards") or []):
            att += _esyms(ec.get("id"))
        best = None
        for m in bi.moves:
            mt = _re.match(r"(\d+)", str(m.damage or ""))
            if mt and (best is None or int(mt.group(1)) > best[0]):
                best = (int(mt.group(1)), m.cost or "")
        if not best:
            return None
        need = _re.findall(r"\{([A-Z])\}", best[1])
        pool = list(att)
        remaining = [t for t in need if not (t in pool and (pool.remove(t) or True))]
        any_left = max(0, best[1].count("●") - len(pool))
        mine = _esyms(eid)
        return any(t in remaining for t in mine) or (any_left > 0 and bool(mine))

    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != ATTACH:
            continue
        hand = me.get("hand") or []

        def _hand_id(idx):
            return hand[idx].get("id") if idx is not None and 0 <= idx < len(hand) else None

        def _spot(o):
            spots = (me.get("active") if o.get("inPlayArea") == 4 else me.get("bench")) or []
            i = o.get("inPlayIndex")
            return spots[i] if i is not None and 0 <= i < len(spots) else None

        eid = _hand_id(ch.get("index"))
        spot = _spot(ch)
        if eid is None or spot is None:
            continue
        def _is_energy_card(cid):
            ci = C.get(cid)
            return bool(ci) and "Energy" in (ci.name or "")
        if not _is_energy_card(eid):
            continue  # 道具(ケープ等)のattachは対象外
        prog = _progresses(eid, spot)
        if prog is not False:
            continue  # 進めている/最大技情報なし=対象外
        for o in (sel.get("option") or []):
            if o.get("type") != ATTACH or o is ch:
                continue
            if o.get("inPlayArea") != ch.get("inPlayArea") or o.get("inPlayIndex") != ch.get("inPlayIndex"):
                continue
            alt = _hand_id(o.get("index"))
            if alt is not None and alt != eid and _is_energy_card(alt) and _progresses(alt, spot):
                sig(f"EnergyTypeSkew|未充足を進めないエネ選択({nm(eid)}→{nm(spot.get('id'))}, {nm(alt)}なら前進)",
                    g["ep"], cur.get("turn"))
                return


def det_doomed_game_loss(g, sig):
    """DoomedGameLoss: activeのKO=相手の残りサイド充足(死んだら負け)×次の相手ターンに被KO圏×
    退避手段が実在(入替札のPLAY/逃げ可能+負けない退避先)なのに、殴って勝ち切れないのに殴り/ENDで
    手番を渡した(自己レビュー: arch-7 T17 Mega110=3枚を220の前に残しSwitch未使用で敗北)。"""
    import re as _re

    def _pv(cid):
        # bot側 _prize_value と同一意味論: メガex=3, ex=2, それ以外=1
        ci = C.get(cid)
        low = ((ci.rule or "") if ci else "").lower()
        if "mega" in low and "ex" in low:
            return 3
        return 2 if "ex" in low else 1

    opp_seen = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))  # トラッシュ観測はエネのみ(イグニ検出。ポケモンは盤面不在=進化脅威に数えない)
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
                for ec in (sp.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") not in (ATTACK, END):
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if not a or not oa:
            continue
        _op = opp.get("prize")
        opp_left = len(_op) if _op is not None else 6
        if _pv(a.get("id")) < opp_left:
            continue                                    # 死んでも負けない
        if (a.get("hp") or 0) > _incoming_next(a, oa, opp_seen, opp.get("handCount")):
            continue                                    # 被KO圏でない
        # 殴って勝ち切れるなら残って殴るのが正(自分の残りサイド充足)
        _mp = me.get("prize")
        my_left = len(_mp) if _mp is not None else 6
        if ch.get("type") == ATTACK:
            adv = attack_dmg(a, cur, oa.get("id"))      # 既存: 現エネで払える最大打点(スタジアム込)
            ai = C.get(a.get("id"))
            oi = C.get(oa.get("id"))
            if ai and oi and oi.weakness and ai.type == oi.weakness:
                adv *= 2
            if adv >= (oa.get("hp") or 9999):
                if _pv(oa.get("id")) >= my_left:
                    continue                            # 勝ち切り
                # KOで脅威源が消える(相手ベンチに現エネで攻撃可能な後続なし)なら残って殴るのが正
                def _charged(sp):
                    import re as _re2
                    bi2 = C.get(sp.get("id"))
                    att2 = []
                    for ec in (sp.get("energyCards") or []):
                        ei2 = C.get(ec.get("id"))
                        att2 += (_re2.findall(r"\{([A-Z])\}", (ei2.type or "") if ei2 else "")
                                 or _re2.findall(r"\{([A-Z])\}", (ei2.name or "") if ei2 else "") or ["C"])
                    for m in (bi2.moves if bi2 else []):
                        if not m.damage:
                            continue
                        need2 = _re2.findall(r"\{([A-Z])\}", m.cost or "")
                        pool2 = list(att2)
                        ok2 = all((x in pool2 and (pool2.remove(x) or True)) for x in need2)
                        if ok2 and len(pool2) >= (m.cost or "").count("●"):
                            return True
                    return False
                if not any(sp and _charged(sp) for sp in (opp.get("bench") or [])):
                    continue
        # 退避手段の実在: 入替効果札のPLAY か RETREAT。かつ「負けない/耐える」退避先がベンチに居る
        opts = (sel or {}).get("option") or []
        hand = me.get("hand") or []
        esc = any(o.get("type") == RETREAT for o in opts)
        if not esc:
            for o in opts:
                if o.get("type") != PLAY or o.get("index") is None or o["index"] >= len(hand):
                    continue
                ci = C.get(hand[o["index"]].get("id"))
                if ci and "Switch" in (ci.name or ""):
                    esc = True
                    break
        if not esc:
            continue
        ok_succ = any(sp and (_pv(sp.get("id")) < opp_left
                              or (sp.get("hp") or 0) > _incoming_next(sp, oa, opp_seen, opp.get("handCount")))
                      for sp in (me.get("bench") or []))
        if not ok_succ:
            continue
        sig(f"DoomedGameLoss|死んだら負けのactive放置({nm(a.get('id'))}, 退避可)", g["ep"], cur.get("turn"))
        return


def det_switch_waste(g, sig):
    """SwitchWaste: 入替札(Switch)を使ったのに同ターン攻撃なし、かつ元のactiveは被KO圏でも
    なかった(=退避の正当性なし)。攻撃不可ターンの前進や土台の露出=退避資源の浪費
    (自己レビューarch-5 T1: 先攻T1にSwitchで進化土台Staryuを前進→終盤の退避手段喪失)。"""
    turns = {}
    opp_seen = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
                for ec in (sp.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        tn = cur.get("turn")
        rec = turns.setdefault(tn, {"switch": None, "attacked": False})
        if ch.get("type") == ATTACK:
            rec["attacked"] = True
        if ch.get("type") == PLAY:
            hand = me.get("hand") or []
            idx = ch.get("index")
            cid = hand[idx].get("id") if idx is not None and 0 <= idx < len(hand) else None
            ci = C.get(cid)
            if ci and (ci.name or "") == "Switch":
                a = (me.get("active") or [None])[0]
                oa = (opp.get("active") or [None])[0]
                doomed = (a and oa
                          and (a.get("hp") or 0) <= _incoming_next(a, oa, opp_seen, opp.get("handCount")))
                if not doomed:
                    rec["switch"] = tn
    for tn, rec in turns.items():
        if rec["switch"] is not None and not rec["attacked"]:
            sig("SwitchWaste|入替札使用×攻撃なし×退避正当性なし", g["ep"], tn)
            return


def det_bench_bait_loss(g, sig):
    """BenchBaitLoss: ベンチに「KO=相手残サイド充足(釣られたら負け)」の急所が居て、回復サポで
    圏外にできるのに別のサポ/ENDを選んだ(相手デッキのボス残数推定>=1)。
    (自己レビューgrimmsnarl-6 T11: 傷Mega90放置→T12ボス+Shadow Bulletで敗北)"""
    import re as _re

    def _pv(cid):
        ci = C.get(cid)
        low = ((ci.rule or "") if ci else "").lower()
        if "mega" in low and "ex" in low:
            return 3
        return 2 if "ex" in low else 1

    HEALS = ("Wally's Compassion",)
    opp_seen = set()
    boss_turns = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel_b, ch_b = chosen(ob, act)
        if (ch_b and cur.get("yourIndex") == g["my"] and (sel_b or {}).get("type") == MAIN
                and ch_b.get("type") == PLAY and ch_b.get("index") is not None):
            hb = me.get("hand") or []
            if ch_b["index"] < len(hb):
                cb = C.get(hb[ch_b["index"]].get("id"))
                if cb and "Boss" in (cb.name or ""):
                    boss_turns.add(cur.get("turn"))
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") not in (ATTACK, END, PLAY):
            continue
        if cur.get("turn") in boss_turns:
            continue  # 同ターンにボス使用=サポ権は勝ち筋(KO生成)へ。正当性はBossNoPathGainの管轄
        hand = me.get("hand") or []
        # 選んだ手が回復サポならOK。回復サポのPLAY選択肢が存在することが前提
        opts = (sel or {}).get("option") or []
        heal_ops, chosen_heal = [], False
        for o in opts:
            if o.get("type") != PLAY or o.get("index") is None or o["index"] >= len(hand):
                continue
            ci = C.get(hand[o["index"]].get("id"))
            if ci and (ci.name or "") in HEALS:
                heal_ops.append(o)
                if o is ch:
                    chosen_heal = True
        if not heal_ops or chosen_heal:
            continue
        # 選んだのが別サポ(または攻撃/END)=サポ権を回復以外に使う分岐のみ対象
        if ch.get("type") == PLAY:
            ci = C.get(hand[ch["index"]].get("id")) if ch.get("index") is not None and ch["index"] < len(hand) else None
            if not ci or ci.stage != "Supporter":
                continue
        _op = opp.get("prize")
        opp_left = len(_op) if _op is not None else 6
        # ボス残数推定(アーキタイプ既定2, Arch/Dragapult=3, Alakazam=1) - トラッシュ使用分
        est = 2
        seen = " ".join((C[x].name or "") for x in opp_seen if x in C)
        for key, n in (("Archaludon", 3), ("Dragapult", 3), ("Alakazam", 1)):
            if key in seen:
                est = n
                break
        used = sum(1 for c in (opp.get("discard") or [])
                   if c.get("id") in C and "Boss" in (C[c.get("id")].name or ""))
        if est - used <= 0:
            continue
        oa = (opp.get("active") or [None])[0]
        for sp in (me.get("bench") or []):
            if not sp:
                continue
            th = _incoming_next(sp, oa, opp_seen, opp.get("handCount"))
            if (_pv(sp.get("id")) >= opp_left
                    and (sp.get("hp") or 0) <= th < (sp.get("maxHp") or 0)):
                sig(f"BenchBaitLoss|ボス釣りベイト放置({nm(sp.get('id'))}hp{sp.get('hp')}, 回復サポ在手)",
                    g["ep"], cur.get("turn"))
                return


def det_base_line_sacrifice(g, sig):
    """BaseLineSacrifice: 退却で進化土台(基本ポケ)を前進させ確定死圏に晒した。進化先が手札に
    ありKOも取れない=確定ライン(次ターン進化)を微小ダメージと引き換えに破壊(人間レビュー12巡目
    grimmsnarl-0 T7: 前進Staryu死→線消滅→盤面全滅負け)。壁が耐えない場合でも壁死→強制昇格→
    進化の方が土台を1体分長く守る。"""
    opp_seen = set()
    for gi in range(len(g["decisions"])):
        t, ob, act = g["decisions"][gi]
        cur, me, opp = my_view(ob, g["my"])
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
                for ec in (sp.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))  # トラッシュ観測はエネのみ(イグニ検出。ポケモンは盤面不在=進化脅威に数えない)
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != RETREAT:
            continue
        # 退避が「死んだら負け」(act KO=相手残サイド充足)で、非土台の代替後続がベンチに
        # 居なければ正当な犠牲(mirror-4/arch-8: 唯一の後続が土台=強制)。
        a0 = (me.get("active") or [None])[0]
        oa0 = (opp.get("active") or [None])[0]
        _op0 = opp.get("prize")
        opp_left0 = len(_op0) if _op0 is not None else 6
        if (a0 and oa0 and _pv(a0.get("id")) >= opp_left0
                and (a0.get("hp") or 0) <= _incoming_next(a0, oa0, opp_seen, opp.get("handCount"))):
            def _is_base_alt(sp):
                ci0 = C.get(sp.get("id"))
                return bool(ci0) and getattr(ci0, "is_basic", False) and any(
                    C.get(c.get("id")) and C[c.get("id")].previous_stage == ci0.name
                    for c in (me.get("hand") or []))

            def _is_bait_alt(sp):
                return (_pv(sp.get("id")) >= opp_left0
                        and (sp.get("hp") or 0) <= _incoming_next(sp, oa0, opp_seen, opp.get("handCount")))
            if not any(sp and not _is_base_alt(sp) and not _is_bait_alt(sp)
                       for sp in (me.get("bench") or [])):
                continue    # 非土台かつ非ベイトの代替後続なし=土台の犠牲は強制(最善)
        # 同ターンの次の自分MAIN決定でactiveが誰になったか
        for t2, ob2, act2 in g["decisions"][gi + 1:]:
            cur2, me2, opp2 = my_view(ob2, g["my"])
            if cur2.get("yourIndex") != g["my"] or cur2.get("turn") != cur.get("turn"):
                break
            if ((ob2.get("select") or {}).get("type")) != MAIN:
                continue
            a2 = (me2.get("active") or [None])[0]
            oa2 = (opp2.get("active") or [None])[0]
            if not a2 or not oa2:
                break
            ci = C.get(a2.get("id"))
            if not ci or not getattr(ci, "is_basic", False):
                break
            evo_in_hand = any(C.get(c.get("id")) and C[c.get("id")].previous_stage == ci.name
                              for c in (me2.get("hand") or []))
            dies = (a2.get("hp") or 0) <= _incoming_next(a2, oa2, opp_seen, opp2.get("handCount"))
            kos = attack_dmg(a2) >= (oa2.get("hp") or 9999)
            if evo_in_hand and dies and not kos:
                sig(f"BaseLineSacrifice|進化土台{nm(a2.get('id'))}を確定死圏に前進(進化先在手)",
                    g["ep"], cur.get("turn"))
                return
            break


def det_evolve_into_loss(g, sig):
    """EvolveIntoLoss: activeへの進化で「KO=相手残サイド充足(死んだら負け)」のベイトを作った。
    進化後は現実的脅威(可変ダメ込)で確実にKOされ、進化後の攻撃でも相手activeを取れない=
    負けを1ターン早めるだけ(人間レビュー13巡目 alakazam-0 T7: Staryu70をMega330へ進化し
    Powerful Hand 460の前に差し出して即負け)。"""
    import re as _re

    def _pv(cid):
        ci = C.get(cid)
        low = ((ci.rule or "") if ci else "").lower()
        if "mega" in low and "ex" in low:
            return 3
        return 2 if "ex" in low else 1

    EVOLVE_T = int(OptionType.EVOLVE)
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != EVOLVE_T or ch.get("inPlayArea") != 4:
            continue
        hand = me.get("hand") or []
        idx = ch.get("index")
        evo = hand[idx].get("id") if idx is not None and 0 <= idx < len(hand) else None
        ei = C.get(evo)
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if not ei or not a or not oa:
            continue
        _op = opp.get("prize")
        opp_left = len(_op) if _op is not None else 6
        if _pv(evo) < opp_left or _pv(a.get("id")) >= opp_left:
            continue
        evo_spot = dict(a)
        evo_spot["id"] = evo
        evo_spot["hp"] = evo_spot["maxHp"] = ei.hp or 0
        if (evo_spot["hp"] or 0) > _incoming_next(evo_spot, oa, None, opp.get("handCount")):
            continue                                    # 耐える=ベイトでない
        # 進化後の攻撃(手貼り込み)で相手activeを取れるなら正当
        def _esyms(eid):
            ci2 = C.get(eid)
            if not ci2:
                return []
            return (_re.findall(r"\{([A-Z])\}", ci2.type or "")
                    or _re.findall(r"\{([A-Z])\}", ci2.name or "") or ["C"])
        att = []
        for ec in (a.get("energyCards") or []):
            att += _esyms(ec.get("id"))
        hand_e = [c.get("id") for c in hand
                  if C.get(c.get("id")) and "Energy" in (C[c.get("id")].name or "")]
        extras = [None] + (hand_e if not cur.get("energyAttached") else [])
        best = 0
        for extra in extras:
            pool0 = att + (_esyms(extra) if extra is not None else [])
            for m in ei.moves:
                need = _re.findall(r"\{([A-Z])\}", m.cost or "")
                pool = list(pool0)
                ok = all((x in pool and (pool.remove(x) or True)) for x in need)
                if not ok or len(pool) < (m.cost or "").count("●"):
                    continue
                mt = _re.match(r"(\d+)", str(m.damage or ""))
                if mt:
                    dm = int(mt.group(1))
                    ci_o = C.get(oa.get("id"))
                    if ci_o and ci_o.weakness and ei.type == ci_o.weakness:
                        dm *= 2
                    best = max(best, dm)
        if best >= (oa.get("hp") or 9999):
            continue
        sig(f"EvolveIntoLoss|activeへの進化が負けベイト化({nm(a.get('id'))}→{nm(evo)})",
            g["ep"], cur.get("turn"))
        return


def det_switch_into_loss(g, sig):
    """SwitchIntoLoss: 入替札で「KO=相手残サイド充足(死んだら負け)×確殺圏」の後続を前に出した。
    今のactiveは死んでも負けない(安い犠牲)のに、それを守るために負けベイトを差し出す逆転
    (人間レビュー15巡目 alakazam-3 T9: Staryu70温存のためMega330をPowerful Hand 500の前へ)。"""
    def _pv2(cid):
        ci = C.get(cid)
        low = ((ci.rule or "") if ci else "").lower()
        if "mega" in low and "ex" in low:
            return 3
        return 2 if "ex" in low else 1

    opp_seen = set()
    for t, ob, act in g["decisions"]:
        cur, me, opp = my_view(ob, g["my"])
        for c in (opp.get("discard") or []):
            ci_d = C.get(c.get("id"))
            if ci_d and "Energy" in (ci_d.name or ""):
                opp_seen.add(c.get("id"))
        for sp in [(opp.get("active") or [None])[0]] + list(opp.get("bench") or []):
            if sp:
                opp_seen.add(sp.get("id"))
                for ec in (sp.get("energyCards") or []):
                    opp_seen.add(ec.get("id"))
        sel, ch = chosen(ob, act)
        if not ch or cur.get("yourIndex") != g["my"] or (sel or {}).get("type") != MAIN:
            continue
        if ch.get("type") != PLAY or ch.get("index") is None:
            continue
        hand = me.get("hand") or []
        if ch["index"] >= len(hand):
            continue
        ci = C.get(hand[ch["index"]].get("id"))
        if not ci or (ci.name or "") != "Switch":
            continue
        a = (me.get("active") or [None])[0]
        oa = (opp.get("active") or [None])[0]
        if not a or not oa:
            continue
        _op = opp.get("prize")
        opp_left = len(_op) if _op is not None else 6
        if _pv2(a.get("id")) >= opp_left:
            continue                                    # 今のactiveが既に負け駒=退避は正当(DoomedGameLossの管轄)
        cands = [sp for sp in (me.get("bench") or []) if sp]
        if not cands:
            continue
        all_bait = all(_pv2(sp.get("id")) >= opp_left
                       and (sp.get("hp") or 0) <= _incoming_next(sp, oa, opp_seen, opp.get("handCount"))
                       for sp in cands)
        if all_bait:
            sig(f"SwitchIntoLoss|負けベイトを前に出す入替({nm(a.get('id'))}→全後続が確殺×残サイド充足)",
                g["ep"], cur.get("turn"))
            return


DETECTORS = [det_fetch_skew, det_unused_supporter, det_missed_lethal,
             det_wasted_investment, det_wall_retreat,
             det_valueless_support, det_last_stand,
             det_dead_move, det_partner_unbenched, det_spread_skew,
             det_missed_free_advance, det_doomed_no_switch,
             det_boss_no_path_gain, det_volatile_over_permanent,
             det_heal_missed, det_cape_skew, det_energy_stuck_no_lillie,
             det_setup_skew, det_dead_evolution_pick, det_lillie_over_live_heal,
             det_doomed_no_retreat,
             det_gust_target_skew, det_promotion_skew, det_weak_advance,
             det_basic_unbenched, det_evolve_trigger_before_develop,
             det_spread_into_immune, det_bench_heal_missed, det_energy_type_skew,
             det_doomed_game_loss, det_switch_waste, det_bench_bait_loss,
             det_base_line_sacrifice, det_evolve_into_loss, det_switch_into_loss]


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
