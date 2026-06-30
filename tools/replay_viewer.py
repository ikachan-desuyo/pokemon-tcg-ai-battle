"""Kaggle cabtエピソードのリプレイ(JSON)を、ローカルで開ける自己完結HTMLビジュアライザに変換する。

各stepの全盤面(current)とイベント(logs)をカード名/技名/エリア名に解決して埋め込み、
ブラウザ上で『盤面(両者のバトル場・ベンチ・エネ・HP・状態)＋イベントログ』をステップ再生できる。
依存なし(単一HTML)。実行:
  python tools/replay_viewer.py input_data/submission_replay/82775814.json
  → out/replay_82775814.html を生成（ブラウザで開く）
"""
import sys, os, json, csv, re, argparse
sys.path.insert(0, ".")
from cabt_bot import load_cards
from cabt_bot.enums import AreaType, LogType, EnergyType

C = load_cards()
_JP_CSV = "input_data/extracted/JP_Card_Data.csv"

# 日本語カード名 + 技名(ワザ名)を JP_Card_Data.csv から読む（英語名でなく日本語で表示する）
NAME = {cid: (getattr(c, "name", None) or f"#{cid}") for cid, c in C.items()}
_JP_ATK_BY_DMG = {}   # (cardId, damage) -> 日本語ワザ名
try:
    for r in csv.DictReader(open(_JP_CSV, encoding="utf-8")):
        cid = int(r["カード ID"]); nm = (r.get("カード名") or "").strip()
        if nm:
            NAME[cid] = nm
        wn = (r.get("ワザ名") or "").strip()
        if wn and wn != "n/a":
            m = re.match(r"(\d+)", (r.get("ダメージ") or "").strip())
            dmg = int(m.group(1)) if m else 0
            _JP_ATK_BY_DMG[(cid, dmg)] = wn
except Exception:
    pass

# attackId -> ダメージ（ログの attackId を (cardId,damage) 経由で日本語ワザ名に橋渡し）
_ATK_DMG = {}
_ATK_EN = {}
try:
    from cg.api import all_attack
    for a in all_attack():
        _ATK_DMG[a.attackId] = getattr(a, "damage", 0) or 0
        _ATK_EN[a.attackId] = a.name
except Exception:
    pass

# エネルギータイプの日本語表記
_ETYPE_JP = {0: "無", 1: "草", 2: "炎", 3: "水", 4: "雷", 5: "超",
             6: "闘", 7: "悪", 8: "鋼", 9: "竜", 10: "虹", 11: "悪超"}
_AREA_JP = {1: "山札", 2: "手札", 3: "トラッシュ", 4: "バトル場", 5: "ベンチ", 6: "サイド",
            7: "スタジアム", 8: "エネルギー", 9: "どうぐ", 10: "進化前", 11: "プレイヤー", 12: "確認中"}
AREA = {int(a): _AREA_JP.get(int(a), a.name) for a in AreaType}
ETYPE = {int(e): _ETYPE_JP.get(int(e), e.name) for e in EnergyType}


def cname(cid):
    return NAME.get(cid, f"#{cid}")


def aname(card_id, attack_id):
    """ログの (cardId, attackId) を日本語ワザ名に。突合不能なら英語名→技#id。"""
    jp = _JP_ATK_BY_DMG.get((card_id, _ATK_DMG.get(attack_id)))
    return jp or _ATK_EN.get(attack_id) or f"技#{attack_id}"


def _spot(s):
    if not s:
        return None
    ec = s.get("energyCards") or []
    return {
        "name": cname(s["id"]), "id": s["id"],
        "hp": s.get("hp"), "maxHp": s.get("maxHp"),
        "energy": [cname(e.get("id") if isinstance(e, dict) else e) for e in ec],
        "etypes": [ETYPE.get(t, str(t)) for t in (s.get("energies") or [])],
        "tools": [cname(t.get("id") if isinstance(t, dict) else t) for t in (s.get("tools") or [])],
    }


def _stadium_name(s):
    if not s:
        return None
    if isinstance(s, list):
        s = s[0] if s else None
    if isinstance(s, dict):
        s = s.get("id")
    return cname(s) if s is not None else None


def _player(p):
    hand = p.get("hand") or []
    return {
        "prize": len(p.get("prize") or []),
        "hand": p.get("handCount", len(hand)),
        "handCards": [cname(c.get("id") if isinstance(c, dict) else c) for c in hand],
        "deck": p.get("deckCount"),
        "discard": len(p.get("discard") or []),
        "active": _spot((p.get("active") or [None])[0]),
        "bench": [_spot(b) for b in (p.get("bench") or []) if b],
        "status": [k for k in ("poisoned", "burned", "asleep", "paralyzed", "confused") if p.get(k)],
    }


def _fmt_log(lg):
    t = lg.get("type"); pi = lg.get("playerIndex"); who = f"P{pi}"

    def cn(k):
        return cname(lg[k]) if lg.get(k) is not None else "?"

    if t == LogType.TURN_START:
        return ("turn", f"▶ {who} ターン開始")
    if t == LogType.TURN_END:
        return ("turn", f"■ {who} ターン終了")
    if t == LogType.SHUFFLE:
        return ("misc", f"{who} 山札シャッフル")
    if t == LogType.HAS_BASIC_POKEMON:
        return ("misc", f"{who} たねポケモン確認")
    if t == LogType.DRAW:
        return ("draw", f"{who} ドロー: {cn('cardId')}")
    if t == LogType.DRAW_REVERSE:
        return ("draw", f"{who} ドロー(非公開)")
    if t == LogType.MOVE_CARD:
        return ("move", f"{who} {cn('cardId')}: {AREA.get(lg.get('fromArea'),'?')}→{AREA.get(lg.get('toArea'),'?')}")
    if t == LogType.MOVE_CARD_REVERSE:
        return ("move", f"{who} 移動(非公開): {AREA.get(lg.get('fromArea'),'?')}→{AREA.get(lg.get('toArea'),'?')}")
    if t == LogType.SWITCH:
        return ("move", f"{who} 入替: {cname(lg.get('cardIdActive'))} ⇄ {cname(lg.get('cardIdBench'))}")
    if t == LogType.CHANGE:
        return ("move", f"{who} バトル場交代: {cn('cardId')}")
    if t == LogType.PLAY:
        return ("play", f"{who} 使用: {cn('cardId')}")
    if t == LogType.ATTACH:
        return ("attach", f"{who} エネ付与: {cn('cardId')} → {cname(lg.get('cardIdTarget'))}")
    if t == LogType.EVOLVE:
        return ("evolve", f"{who} 進化: {cname(lg.get('cardIdTarget'))} → {cn('cardId')}")
    if t == LogType.DEVOLVE:
        return ("evolve", f"{who} 退化: {cn('cardId')}")
    if t == LogType.MOVE_ATTACHED:
        return ("attach", f"{who} 付帯カード移動: {cn('cardId')}")
    if t == LogType.ATTACK:
        return ("attack", f"⚔ {who} 攻撃: {cname(lg.get('cardId'))} 〔{aname(lg.get('cardId'), lg.get('attackId'))}〕")
    if t == LogType.HP_CHANGE:
        v = lg.get("value") or 0
        if v < 0:
            return ("dmg", f"   💥 {cname(lg.get('cardId'))} に {-v} ダメージ")
        return ("heal", f"   ✚ {cname(lg.get('cardId'))} HP +{v}")
    if t in (LogType.POISONED, LogType.BURNED, LogType.ASLEEP, LogType.PARALYZED, LogType.CONFUSED):
        return ("status", f"{who} 状態異常: {LogType(t).name}")
    if t == LogType.COIN:
        return ("misc", f"{who} コイン")
    if t == LogType.RESULT:
        return ("result", f"★ 結果確定")
    return ("misc", f"{who} [{LogType(t).name if t in LogType._value2member_map_ else t}]")


def _collapse(logs):
    """連続する同一イベント(例: 相手の7枚ドロー, サイド6枚セット)を『×N』に集約して冗長表示を防ぐ。"""
    out = []
    for k, t in logs:
        if out and out[-1][0] == k and out[-1][1] == t:
            out[-1][2] += 1
        else:
            out.append([k, t, 1])
    return [[k, (f"{t} ×{n}" if n > 1 else t)] for k, t, n in out]


def build(replay_path):
    d = json.load(open(replay_path, encoding="utf-8"))
    steps = d["steps"]
    agents = d.get("info", {}).get("Agents", [])
    names = [a.get("Name", f"P{i}") for i, a in enumerate(agents)] or ["P0", "P1"]
    raw = []
    last_cur = None
    last_act = 0
    prev_logs = None
    hand_cards = [[], []]   # 各プレイヤーの最後に判明した手札(本人ACTIVE時に更新)。常時表示用。
    seen_events = set()     # 表示済みの実イベント(serialで一意特定)。視点違いの再掲を除去。
    for st in steps:
        # status=="ACTIVE" のエージェントが行動者。その視点(本人手札可視・逐次更新)を盤面/ログ/手番に採用。
        # ＝P0もP1も自分の手番中は1手ずつ進行し、相手の手番中は潰さず本人視点で詳細表示できる。
        if len(st) > 1 and st[1].get("status") == "ACTIVE" and st[0].get("status") != "ACTIVE":
            act_idx = 1
        elif st[0].get("status") == "ACTIVE":
            act_idx = 0
        else:
            act_idx = last_act
        act_changed = (act_idx != last_act)
        last_act = act_idx
        obs = st[act_idx]["observation"]
        cur = obs.get("current") or last_cur
        if obs.get("current"):
            last_cur = obs["current"]
            # 行動中プレイヤーの手札(自視点で中身が見える)を記録＝以後その手札を常時表示。
            me = obs["current"]["players"][act_idx]
            hand_cards[act_idx] = [cname(c.get("id") if isinstance(c, dict) else c)
                                   for c in (me.get("hand") or [])]
        raw_logs = obs.get("logs") or []
        # 行動権が移った最初の観測には『前プレイヤーのターン』がバックログとして乗る(既に表示済み)。
        # 自分の最後の「ターン開始」以降だけ残す。無ければ(=自分のターンが未開始)バックログ全捨て。
        if act_changed:
            starts = [j for j, lg in enumerate(raw_logs)
                      if lg.get("type") == int(LogType.TURN_START) and lg.get("playerIndex") == act_idx]
            raw_logs = raw_logs[starts[-1]:] if starts else []
        # さらに、serialで一意に特定できる実イベントはグローバルに重複排除(同一イベントは1度だけ)。
        # ＝視点違いの再掲(バックログ)を確実に除去。serialの無いマーカー/非公開はそのまま。
        kept = []
        for lg in raw_logs:
            sig = None
            if lg.get("serial") is not None:
                sig = (lg.get("type"), lg.get("playerIndex"), lg.get("serial"),
                       lg.get("serialTarget"), lg.get("fromArea"), lg.get("toArea"))
            elif lg.get("serialActive") is not None:
                sig = (lg.get("type"), lg.get("serialActive"), lg.get("serialBench"))
            if sig is not None:
                if sig in seen_events:
                    continue
                seen_events.add(sig)
            kept.append(lg)
        raw_logs = kept
        logs = [] if raw_logs == prev_logs else [_fmt_log(lg) for lg in raw_logs]
        prev_logs = raw_logs
        view = None
        if cur:
            # players は絶対index([0]=P0,[1]=P1)。両者の手札を常時表示(各自の最後に判明した手札)。
            # 枚数バッジも表示中の手札に合わせて整合させる。
            pv = [_player(cur["players"][0]), _player(cur["players"][1])]
            for pi in (0, 1):
                if hand_cards[pi]:
                    pv[pi]["handCards"] = hand_cards[pi]
                    pv[pi]["hand"] = len(hand_cards[pi])
            view = {
                "turn": cur.get("turn"),
                "active_player": cur.get("yourIndex", act_idx),
                "result": cur.get("result"),
                "stadium": _stadium_name(cur.get("stadium")),
                "players": pv,
            }
        raw.append((view, logs))
    # 盤面(view)が同一の連続stepは1フレームに統合し、その間のイベントログをまとめる
    # ＝『次へ』で必ず盤面が動くようにする（サブ決定だけで盤面不変のstepを畳む）。
    out_steps = []
    for view, logs in raw:
        key = json.dumps(view, ensure_ascii=False, sort_keys=True) if view else None
        if out_steps and out_steps[-1]["_key"] == key:
            out_steps[-1]["logs"].extend(logs)
        else:
            out_steps.append({"_key": key, "view": view, "logs": list(logs)})
    for n, f in enumerate(out_steps):
        f.pop("_key"); f["i"] = n
        f["logs"] = _collapse(f["logs"])
    rewards = d.get("rewards") or []
    winner = None
    if len(rewards) == 2 and rewards[0] != rewards[1]:
        winner = 0 if rewards[0] > rewards[1] else 1
    return {"names": names, "episode": d.get("info", {}).get("EpisodeId"),
            "rewards": rewards, "winner": winner, "steps": out_steps}


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>cabt リプレイ — {title}</title>
<style>
:root{{--bg:#0f1420;--panel:#1a2233;--line:#2c3a55;--me:#1e3a5f;--opp:#5f1e2e;--txt:#dde6f5;--dim:#8aa0c0;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--txt);font:13px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}}
header{{padding:10px 16px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
header b{{font-size:15px}} .dim{{color:var(--dim)}}
#wrap{{display:grid;grid-template-columns:1fr 320px;gap:0;height:calc(100vh - 52px)}}
#board{{padding:14px;overflow:auto}} #side{{border-left:1px solid var(--line);background:var(--panel);padding:12px;overflow:auto}}
.side-half{{padding:10px;border-radius:10px;margin-bottom:10px}}
.half-opp{{background:linear-gradient(180deg,#2a1620,#1a2233)}} .half-me{{background:linear-gradient(180deg,#16202a,#1a2233)}}
.phead{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.phead .nm{{font-weight:700}} .badge{{display:inline-block;background:#0c1322;border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin-left:6px}}
.prizes{{color:#ffcf5c}}
.row{{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}}
.slot{{width:128px;background:#0e1626;border:1px solid var(--line);border-radius:9px;padding:7px}}
.slot.active{{border-color:#ffcf5c;box-shadow:0 0 0 1px #ffcf5c55}}
.slot .cn{{font-weight:700;font-size:12px;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.hpbar{{height:6px;background:#33202a;border-radius:4px;overflow:hidden;margin:3px 0}}
.hpbar>i{{display:block;height:100%;background:linear-gradient(90deg,#36d07a,#9fe860)}}
.hpbar.low>i{{background:linear-gradient(90deg,#e85f5f,#f2a14e)}}
.meta{{font-size:11px;color:var(--dim)}} .ene{{color:#7fd0ff}} .tool{{color:#d79bff}}
.lab{{font-size:11px;color:var(--dim);margin:4px 0 6px;text-transform:uppercase;letter-spacing:.05em}}
.empty{{color:#54627d;font-style:italic;padding:6px}}
.hand{{display:flex;gap:5px;flex-wrap:wrap;margin-top:2px}}
.chip{{background:#10203a;border:1px solid #2c3a55;border-radius:6px;padding:3px 8px;font-size:11px;white-space:nowrap}}
.chip.back{{background:#241622;border-color:#4a2a38;color:#a07585}}
#turnbar{{margin:6px 0 12px;padding:8px 12px;border-radius:8px;background:#0c1322;border:1px solid var(--line)}}
#turnbar .who{{font-weight:700}}
.logitem{{padding:2px 6px;border-left:3px solid var(--line);margin:2px 0;border-radius:0 4px 4px 0;white-space:pre-wrap}}
.l-attack{{border-color:#ff7a59;color:#ffd2c4}} .l-dmg{{border-color:#ff5f5f;color:#ff9c9c}} .l-evolve{{border-color:#9fe860}}
.l-play{{border-color:#7fd0ff}} .l-attach{{border-color:#7fd0ff;color:#bfe6ff}} .l-turn{{border-color:#ffcf5c;color:#ffe6a0;font-weight:700}}
.l-result{{border-color:#ffcf5c;color:#ffcf5c;font-weight:700}} .l-heal{{border-color:#36d07a;color:#9fe8b8}} .l-draw,.l-move,.l-misc,.l-status{{color:var(--dim)}}
#ctrl{{display:flex;gap:8px;align-items:center;flex:1}} #slider{{flex:1}}
button{{background:#243049;color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:6px 12px;cursor:pointer;font-size:13px}}
button:hover{{background:#2e3c5a}} kbd{{background:#0c1322;border:1px solid var(--line);border-radius:4px;padding:0 5px}}
</style></head><body>
<header>
  <b>cabt リプレイ</b><span class="dim">ep {episode}</span><span id="outcome"></span>
  <div id="ctrl">
    <button id="prev">◀ 前</button>
    <input id="slider" type="range" min="0" value="0">
    <button id="next">次 ▶</button>
    <span id="pos" class="dim"></span>
  </div>
  <span class="dim">← → でステップ移動</span>
</header>
<div id="wrap">
  <div id="board">
    <div id="turnbar"></div>
    <div id="opp" class="side-half half-opp"></div>
    <div id="me" class="side-half half-me"></div>
  </div>
  <div id="side"><div class="lab">このステップのイベント</div><div id="logs"></div></div>
</div>
<script>
const DATA = {data};
const NAMES = DATA.names;
let idx = 0;
const $ = s => document.querySelector(s);
if(DATA.winner!=null){{
  $('#outcome').innerHTML = `<span class="badge l-result">勝者: ${{NAMES[DATA.winner]}}</span>`
    + `<span class="dim"> （${{NAMES[0]}} ${{DATA.rewards[0]}} / ${{NAMES[1]}} ${{DATA.rewards[1]}}）</span>`;
}}
function slot(s, isActive){{
  if(!s) return '';
  const pct = s.maxHp ? Math.max(0,Math.round(100*s.hp/s.maxHp)) : 0;
  const low = pct<=33?'low':'';
  const ene = s.energy.length ? `<div class="meta ene">⚡${{s.energy.length}} <span class="dim">${{s.etypes.join('·')}}</span></div>`:'';
  const tool = s.tools.length ? `<div class="meta tool">🛠 ${{s.tools.join(', ')}}</div>`:'';
  return `<div class="slot ${{isActive?'active':''}}">
    <div class="cn" title="${{s.name}}">${{s.name}}</div>
    <div class="meta">HP ${{s.hp}}/${{s.maxHp}}</div>
    <div class="hpbar ${{low}}"><i style="width:${{pct}}%"></i></div>${{ene}}${{tool}}</div>`;
}}
function half(p, who, mine, activeTurn, flip){{
  const act = p.active ? `<div class="lab">バトル場</div><div class="row">${{slot(p.active,true)}}</div>` : '<div class="empty">バトル場 なし</div>';
  const bench = p.bench.length ? `<div class="lab">ベンチ (${{p.bench.length}})</div><div class="row">${{p.bench.map(b=>slot(b,false)).join('')}}</div>` : '<div class="empty">ベンチ なし</div>';
  const st = p.status.length ? `<span class="badge" style="color:#ff9c9c">${{p.status.join(',')}}</span>`:'';
  let hand;
  if(p.handCards && p.handCards.length)
    hand = `<div class="lab">手札 (${{p.hand}})</div><div class="hand">${{p.handCards.map(c=>`<span class="chip">${{c}}</span>`).join('')}}</div>`;
  else if(p.hand>0)
    hand = `<div class="lab">手札 (${{p.hand}})</div><div class="hand">${{Array(p.hand).fill('<span class="chip back">🂠</span>').join('')}}</div>`;
  else hand = '';
  const head = `<div class="phead"><div class="nm">${{mine?'▼ ':''}}${{who}} ${{activeTurn?'<span class="badge" style="color:#ffcf5c">手番</span>':''}}${{st}}</div>
    <div><span class="prizes">サイド ${{p.prize}}</span><span class="badge">手札 ${{p.hand}}</span><span class="badge">山 ${{p.deck}}</span><span class="badge">トラ ${{p.discard}}</span></div></div>`;
  // flip(相手側): 手札→ベンチ→バトル場 の順でバトル場を中央(P0側)に向ける
  return flip ? `${{head}}${{hand}}${{bench}}${{act}}` : `${{head}}${{act}}${{bench}}${{hand}}`;
}}
function render(){{
  const step = DATA.steps[idx];
  $('#slider').value = idx; $('#pos').textContent = `${{idx}} / ${{DATA.steps.length-1}}`;
  const v = step.view;
  if(v){{
    const ap = v.active_player;
    $('#turnbar').innerHTML = `<span class="who">ターン ${{v.turn}}</span> — 手番: <b style="color:#ffcf5c">${{NAMES[ap]||('P'+ap)}}</b>`
      + (v.stadium?` <span class="badge">スタジアム: ${{v.stadium}}</span>`:'')
      + (v.result!=null && v.result!=-1?` <span class="badge l-result">結果: ${{NAMES[v.result]||('P'+v.result)}} の勝ち</span>`:'');
    $('#opp').innerHTML = half(v.players[1], NAMES[1]||'P1', false, ap===1, true);
    $('#me').innerHTML  = half(v.players[0], NAMES[0]||'P0', true, ap===0, false);
  }}
  $('#logs').innerHTML = step.logs.length
    ? step.logs.map(([k,t])=>`<div class="logitem l-${{k}}">${{t}}</div>`).join('')
    : '<div class="empty">（イベントなし）</div>';
}}
function go(n){{ idx=Math.max(0,Math.min(DATA.steps.length-1,n)); render(); }}
$('#prev').onclick=()=>go(idx-1); $('#next').onclick=()=>go(idx+1);
$('#slider').max=DATA.steps.length-1; $('#slider').oninput=e=>go(+e.target.value);
document.onkeydown=e=>{{ if(e.key==='ArrowLeft')go(idx-1); if(e.key==='ArrowRight')go(idx+1); }};
render();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay", help="リプレイJSON (例: input_data/submission_replay/82775814.json)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    data = build(a.replay)
    stem = os.path.splitext(os.path.basename(a.replay))[0]
    out = a.out or f"out/replay_{stem}.html"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    html = HTML.format(title=stem, episode=data.get("episode"),
                       data=json.dumps(data, ensure_ascii=False))
    open(out, "w", encoding="utf-8").write(html)
    print(f"→ {out} を生成（{len(data['steps'])}ステップ）。ブラウザで開いてください。")
    print(f"  対戦: {data['names'][0]} vs {data['names'][1]}")


if __name__ == "__main__":
    main()
