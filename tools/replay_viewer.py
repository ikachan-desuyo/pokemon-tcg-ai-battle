"""Kaggle cabtエピソードのリプレイ(JSON)を、ローカルで開ける自己完結HTMLビジュアライザに変換する。

各stepの全盤面(current)とイベント(logs)をカード名/技名/エリア名に解決して埋め込み、
ブラウザ上で『盤面(両者のバトル場・ベンチ・エネ・HP・状態)＋イベントログ』をステップ再生できる。
依存なし(単一HTML)。実行:
  python tools/replay_viewer.py input_data/submission_replay/82775814.json
  → out/replay_82775814.html を生成（ブラウザで開く）
"""
import sys, os, json, argparse
sys.path.insert(0, ".")
from cabt_bot import load_cards
from cabt_bot.enums import AreaType, LogType, EnergyType
try:
    from cg.api import all_attack
    ATK = {a.attackId: a.name for a in all_attack()}
except Exception:
    ATK = {}

C = load_cards()
NAME = {cid: (getattr(c, "name", None) or f"#{cid}") for cid, c in C.items()}
AREA = {int(a): a.name for a in AreaType}
ETYPE = {int(e): e.name for e in EnergyType}


def cname(cid):
    return NAME.get(cid, f"#{cid}")


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
    return {
        "prize": len(p.get("prize") or []),
        "hand": p.get("handCount", len(p.get("hand") or [])),
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
        return ("attack", f"⚔ {who} 攻撃: {cname(lg.get('cardId'))} 〔{ATK.get(lg.get('attackId'),'技#'+str(lg.get('attackId')))}〕")
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


def build(replay_path):
    d = json.load(open(replay_path, encoding="utf-8"))
    steps = d["steps"]
    agents = d.get("info", {}).get("Agents", [])
    names = [a.get("Name", f"P{i}") for i, a in enumerate(agents)] or ["P0", "P1"]
    out_steps = []
    last_cur = None
    for i, st in enumerate(steps):
        obs = st[0]["observation"]
        cur = obs.get("current") or last_cur
        if obs.get("current"):
            last_cur = obs["current"]
        logs = [_fmt_log(lg) for lg in (obs.get("logs") or [])]
        view = None
        if cur:
            view = {
                "turn": cur.get("turn"),
                "active_player": cur.get("yourIndex"),
                "result": cur.get("result"),
                "stadium": _stadium_name(cur.get("stadium")),
                "players": [_player(cur["players"][0]), _player(cur["players"][1])],
            }
        out_steps.append({"i": i, "view": view, "logs": logs})
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
function half(p, who, mine, activeTurn){{
  const act = p.active ? `<div class="lab">バトル場</div><div class="row">${{slot(p.active,true)}}</div>` : '<div class="empty">バトル場 なし</div>';
  const bench = p.bench.length ? `<div class="lab">ベンチ (${{p.bench.length}})</div><div class="row">${{p.bench.map(b=>slot(b,false)).join('')}}</div>` : '<div class="empty">ベンチ なし</div>';
  const st = p.status.length ? `<span class="badge" style="color:#ff9c9c">${{p.status.join(',')}}</span>`:'';
  return `<div class="phead"><div class="nm">${{mine?'▼ ':''}}${{who}} ${{activeTurn?'<span class="badge" style="color:#ffcf5c">手番</span>':''}}${{st}}</div>
    <div><span class="prizes">サイド ${{p.prize}}</span><span class="badge">手札 ${{p.hand}}</span><span class="badge">山 ${{p.deck}}</span><span class="badge">トラ ${{p.discard}}</span></div></div>${{act}}${{bench}}`;
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
    $('#opp').innerHTML = half(v.players[1], NAMES[1]||'P1', false, ap===1);
    $('#me').innerHTML  = half(v.players[0], NAMES[0]||'P0', true, ap===0);
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
