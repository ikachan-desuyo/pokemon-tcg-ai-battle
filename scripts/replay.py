"""1試合を記録し、自己完結HTMLのリプレイビューアを生成する。

cg エンジンで2デッキを対戦させ、ターンごとの盤面スナップショットと
イベントログ（日本語ナレーション）を収集し、ブラウザでターン送りして
閲覧できる単一HTMLファイルを書き出す。

使い方:
    python3 scripts/replay.py                                  # deck.csv vs sample_deck.csv
    python3 scripts/replay.py --deck0 decks/deck.csv --deck1 decks/kangaskhan.csv
    python3 scripts/replay.py --out replays/foo.html --seed-note "..."

前提: リポジトリ直下に cg/（エンジン）があること。
カード名は input_data/extracted/JP_Card_Data.csv（あれば日本語）、無ければ
data/cards.csv（英語）で解決する。攻撃名は cg.api.all_attack（英語）。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JP_CSV = ROOT / "input_data" / "extracted" / "JP_Card_Data.csv"
EN_CSV = ROOT / "data" / "cards.csv"

AREA = {1: "山", 2: "手札", 3: "トラッシュ", 4: "バトル場", 5: "ベンチ",
        6: "サイド", 7: "スタジアム"}


def load_names() -> dict[int, str]:
    """card_id -> 表示名（JPがあれば日本語、無ければ英語）。"""
    names: dict[int, str] = {}
    if JP_CSV.exists():
        with JP_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    names[int(r["カード ID"])] = r["カード名"]
                except (KeyError, ValueError):
                    continue
    elif EN_CSV.exists():
        with EN_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    names[int(r["card_id"])] = r["name"]
                except (KeyError, ValueError):
                    continue
    return names


def load_kinds() -> dict[int, str]:
    """card_id -> 種別タグ（poke/energy/sup/item）。チップの色分け用。"""
    kinds: dict[int, str] = {}
    if EN_CSV.exists():
        with EN_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    cid = int(r["card_id"])
                except (KeyError, ValueError):
                    continue
                stage = (r.get("stage") or "")
                if "Pokémon" in stage and "Tool" not in stage:
                    kinds[cid] = "poke"
                elif "Energy" in stage:
                    kinds[cid] = "energy"
                elif "Supporter" in stage:
                    kinds[cid] = "sup"
                else:
                    kinds[cid] = "item"
    return kinds


def load_attack_names() -> dict[int, str]:
    try:
        from cg.api import all_attack  # type: ignore
        return {a.attackId: a.name for a in all_attack()}
    except Exception:
        return {}


def load_deck(path: str | Path) -> list[int]:
    return [int(l.split(",")[0]) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")][:60]


def make_agent(deck_csv: str):
    """csv stem から専用 bot を割り当て（無ければ HeuristicBot）。"""
    from cabt_bot.bots.deck_registry import DECK_BOTS
    from cabt_bot.bots import HeuristicBot
    from cabt_bot.models import Observation
    stem = Path(deck_csv).stem
    bot_cls = DECK_BOTS.get(stem, HeuristicBot)
    bot = bot_cls()
    return bot, (lambda obs: bot.select(Observation.from_dict(obs)))


def _poke(sp, names):
    if not sp:
        return None
    return {
        "name": names.get(sp.get("id"), f"#{sp.get('id')}"),
        "hp": sp.get("hp"), "maxHp": sp.get("maxHp"),
        "e": len(sp.get("energyCards") or []),
        "tools": [names.get(t.get("id"), "") for t in (sp.get("tools") or [])],
    }


def _snap(p, names):
    return {
        "active": _poke((p.get("active") or [None])[0], names),
        "bench": [_poke(b, names) for b in (p.get("bench") or []) if b],
        "prize": len(p.get("prize") or []),
        "hand": p.get("handCount"),
        "deck": p.get("deckCount"),
        "discard": len(p.get("discard") or []),
    }


def narrate(L, names, atk):
    t = L.get("type")
    pi = L.get("playerIndex")
    who = f"P{pi}"
    cid = L.get("cardId")
    cn = names.get(cid, f"#{cid}") if cid is not None else ""
    if t == 2:
        return ("turn", f"――― {who} のターン ―――")
    if t == 4:
        return ("draw", f"{who} ドロー: {cn}")
    if t == 10:
        return ("play", f"{who} {cn} をプレイ")
    if t == 11:
        tgt = names.get(L.get("cardIdTarget"), "")
        return ("attach", f"{who} {cn} を {tgt} に付与")
    if t == 12:
        frm = names.get(L.get("cardIdTarget"), "")
        return ("evolve", f"{who} {frm} → {cn} に進化")
    if t == 6:
        fa, ta = AREA.get(L.get("fromArea"), "?"), AREA.get(L.get("toArea"), "?")
        return ("move", f"{who} {cn}: {fa}→{ta}")
    if t == 15:
        return ("attack", f"{who} {cn} の {atk.get(L.get('attackId'), 'こうげき')}！")
    if t == 16:
        v = L.get("value") or 0
        if v > 0:
            return ("dmg", f"　→ {cn} に {v} ダメージ")
        return None
    if t == 23:
        return ("result", f"★ 勝者 P{L.get('result')}（reason {L.get('reason')}）")
    return None  # shuffle / has_basic / turn_end / *_reverse などは省略


def record(deck0, deck1, names, atk, kinds, max_steps=6000):
    from cg.game import battle_finish, battle_select, battle_start
    _, a0 = make_agent(deck0)
    _, a1 = make_agent(deck1)
    agents = (a0, a1)
    d0, d1 = load_deck(deck0), load_deck(deck1)
    obs, _ = battle_start(d0, d1)
    if obs is None:
        raise RuntimeError("battle_start に失敗（デッキが不正？）")

    state_by_turn: dict[int, dict] = {}
    events_by_turn: dict[int, list] = {}
    owner_by_turn: dict[int, int] = {}
    # 手札は手番側(自分視点)だけ実物が見える → 見えた時点の手札を保持
    hand_by_player: dict[int, list] = {0: [], 1: []}
    result = {"winner": -1, "reason": None}
    try:
        for _ in range(max_steps):
            cur = obs.get("current")  # 生 dict（全要素 plain）
            turn = cur["turn"] if cur else 0
            for L in (obs.get("logs") or []):
                if L.get("type") == 2:  # TURN_START
                    owner_by_turn[turn] = L.get("playerIndex")
                if L.get("type") == 23:
                    result = {"winner": L.get("result"), "reason": L.get("reason")}
                n = narrate(L, names, atk)
                if n is not None:
                    events_by_turn.setdefault(turn, []).append(n)
            if cur is not None:
                for pi in (0, 1):
                    pl = cur["players"][pi]
                    h = pl.get("hand") or []
                    # 手札が完全に見えている（公開）ときだけ更新。相手は [] のまま枚数のみ
                    if len(h) == pl.get("handCount", -1):
                        hand_by_player[pi] = [
                            {"n": names.get(c.get("id"), f"#{c.get('id')}"),
                             "k": kinds.get(c.get("id"), "item")} for c in h]
                s0 = _snap(cur["players"][0], names); s0["handCards"] = list(hand_by_player[0])
                s1 = _snap(cur["players"][1], names); s1["handCards"] = list(hand_by_player[1])
                state_by_turn[turn] = {"p0": s0, "p1": s1}
                if cur["result"] != -1:
                    break
            sel_data = obs.get("select")
            if not sel_data or not sel_data.get("option"):
                break
            who = cur["yourIndex"] if cur is not None else 0
            try:
                sel = agents[who](obs)
            except Exception:
                n = len(sel_data["option"])
                sel = list(range(min(max(1, sel_data.get("minCount", 1)), n)))
            obs = battle_select(sel)
    finally:
        battle_finish()

    frames = []
    for turn in sorted(state_by_turn):
        s = state_by_turn[turn]
        frames.append({
            "turn": turn,
            "owner": owner_by_turn.get(turn),
            "p0": s["p0"], "p1": s["p1"],
            "events": events_by_turn.get(turn, []),
        })
    return frames, result


HTML_TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{--bg:#0f1420;--panel:#1b2233;--ink:#e8edf6;--mut:#8a96ad;--you:#2563eb;--opp:#b91c1c;
--hp:#22c55e;--hpl:#374151;--card:#283246;--acc:#f59e0b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,"Segoe UI",sans-serif}
header{padding:10px 16px;background:#0b0f18;border-bottom:1px solid #222b3f;position:sticky;top:0;z-index:5}
h1{font-size:15px;margin:0 0 6px}
.sub{color:var(--mut);font-size:12px}
.wrap{display:grid;grid-template-columns:1fr 320px;gap:12px;padding:12px;max-width:1100px;margin:0 auto}
.board{display:flex;flex-direction:column;gap:8px}
.side{background:var(--panel);border-radius:10px;padding:10px}
.side.opp{border-top:3px solid var(--opp)} .side.you{border-top:3px solid var(--you)}
.side h2{font-size:13px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}
.tag{font-size:11px;color:#fff;padding:1px 7px;border-radius:9px}
.tag.opp{background:var(--opp)} .tag.you{background:var(--you)}
.meta{color:var(--mut);font-size:12px;font-weight:400}
.pips{display:inline-flex;gap:2px;vertical-align:middle;margin-left:4px}
.pip{width:9px;height:9px;border-radius:50%;background:var(--acc)}
.row{display:flex;gap:8px;flex-wrap:wrap}
.card{background:var(--card);border-radius:8px;padding:8px;min-width:120px;flex:0 0 auto}
.card.active{border:1px solid var(--acc);min-width:170px}
.card .nm{font-weight:600;font-size:13px;margin-bottom:4px}
.card.active .nm{font-size:15px}
.hpbar{height:7px;background:var(--hpl);border-radius:4px;overflow:hidden;margin:3px 0}
.hpbar>i{display:block;height:100%;background:var(--hp)}
.hpt{font-size:11px;color:var(--mut)}
.badges{margin-top:4px;font-size:11px;color:var(--mut)}
.e{color:#fde68a} .tool{color:#a5b4fc}
.empty{color:var(--mut);font-style:italic;padding:6px}
.benchlbl{font-size:11px;color:var(--mut);margin:6px 0 2px}
.hand{display:flex;gap:4px;flex-wrap:wrap;margin-top:2px}
.chip{background:#1f2940;border:1px solid #3a4a66;border-radius:6px;padding:2px 7px;font-size:12px}
.chip.poke{border-left:3px solid var(--acc)} .chip.energy{border-left:3px solid #fde68a}
.chip.sup{border-left:3px solid #93c5fd} .chip.item{border-left:3px solid #86efac}
.hand-hidden{color:var(--mut);font-size:12px;font-style:italic}
.ownerbadge{font-size:10px;color:#0b0f18;background:var(--acc);border-radius:8px;padding:1px 6px;margin-left:6px}
aside{background:var(--panel);border-radius:10px;padding:10px;align-self:start;position:sticky;top:64px;max-height:80vh;overflow:auto}
aside h3{font-size:13px;margin:0 0 6px}
.ev{padding:2px 0;font-size:13px;border-bottom:1px solid #222b3f}
.ev.turn{color:var(--acc);font-weight:600;border:0;margin-top:6px}
.ev.attack{color:#fca5a5} .ev.dmg{color:#fda4af;padding-left:8px}
.ev.evolve{color:#86efac} .ev.attach{color:#fde68a} .ev.play{color:#93c5fd}
.ev.result{color:#fff;background:#334155;border-radius:6px;padding:4px 6px;margin-top:6px;font-weight:700}
.ev.draw,.ev.move{color:var(--mut)}
.ctrl{display:flex;gap:8px;align-items:center;margin-top:8px}
button{background:#243049;color:var(--ink);border:1px solid #344056;border-radius:7px;padding:6px 12px;cursor:pointer;font-size:14px}
button:hover{background:#2d3b58} button:disabled{opacity:.4;cursor:default}
input[type=range]{flex:1}
.tcount{font-variant-numeric:tabular-nums;min-width:120px;text-align:center}
.win-you{color:#60a5fa} .win-opp{color:#f87171}
</style></head><body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">P0(下/青)= __DECK0__　vs　P1(上/赤)= __DECK1__　／　結果: <b id="res"></b></div>
</header>
<div class="wrap">
  <div class="board">
    <div class="side opp"><h2><span><span class="tag opp">P1</span> __DECK1__<span id="ob1"></span></span><span class="meta" id="m1"></span></h2>
      <div id="act1"></div><div class="benchlbl">ベンチ</div><div class="row" id="bench1"></div>
      <div class="benchlbl">手札</div><div class="hand" id="hand1"></div></div>
    <div class="side you"><h2><span><span class="tag you">P0</span> __DECK0__<span id="ob0"></span></span><span class="meta" id="m0"></span></h2>
      <div id="act0"></div><div class="benchlbl">ベンチ</div><div class="row" id="bench0"></div>
      <div class="benchlbl">手札</div><div class="hand" id="hand0"></div></div>
    <div class="ctrl">
      <button id="prev">◀ 前</button>
      <span class="tcount" id="tc"></span>
      <button id="next">次 ▶</button>
      <input type="range" id="slider" min="0" value="0">
    </div>
  </div>
  <aside><h3>このターンのログ</h3><div id="log"></div></aside>
</div>
<script>
const R = __PAYLOAD__;
const F = R.frames;
let i = 0;
const $ = id => document.getElementById(id);
function pips(n){let s='<span class="pips">';for(let k=0;k<n;k++)s+='<span class="pip"></span>';return s+'</span>';}
function cardHTML(p, active){
  if(!p) return '<div class="card'+(active?' active':'')+'"><div class="empty">（なし）</div></div>';
  const pct = p.maxHp? Math.max(0,Math.round(100*p.hp/p.maxHp)):0;
  let b='';
  if(p.e>0) b+='<span class="e">⚡×'+p.e+'</span> ';
  if(p.tools&&p.tools.length) b+='<span class="tool">🔧'+p.tools.join(',')+'</span>';
  return '<div class="card'+(active?' active':'')+'"><div class="nm">'+p.name+'</div>'+
    '<div class="hpbar"><i style="width:'+pct+'%"></i></div>'+
    '<div class="hpt">HP '+p.hp+'/'+p.maxHp+'</div>'+
    (b?'<div class="badges">'+b+'</div>':'')+'</div>';
}
function handHTML(pl){
  const hc = pl.handCards || [];
  if(hc.length === 0)
    return pl.hand>0? '<span class="hand-hidden">'+pl.hand+'枚（非公開）</span>' : '<span class="hand-hidden">（なし）</span>';
  let s = hc.map(c=>'<span class="chip '+c.k+'">'+c.n+'</span>').join('');
  if(hc.length !== pl.hand) s += ' <span class="hand-hidden">(直近 '+hc.length+'枚 / 現在 '+pl.hand+'枚)</span>';
  return s;
}
function side(pl, actId, benchId, metaId, handId){
  $(actId).innerHTML = cardHTML(pl.active, true);
  $(benchId).innerHTML = pl.bench.length? pl.bench.map(b=>cardHTML(b,false)).join('') : '<div class="empty">（ベンチなし）</div>';
  $(metaId).innerHTML = 'サイド'+pips(pl.prize)+' 手札:'+pl.hand+' 山:'+pl.deck+' トラッシュ:'+pl.discard;
  $(handId).innerHTML = handHTML(pl);
}
function render(){
  const f = F[i];
  side(f.p1,'act1','bench1','m1','hand1');
  side(f.p0,'act0','bench0','m0','hand0');
  $('ob1').innerHTML = f.owner===1? '<span class="ownerbadge">手番</span>':'';
  $('ob0').innerHTML = f.owner===0? '<span class="ownerbadge">手番</span>':'';
  $('log').innerHTML = (f.events.length? f.events : [['mut','（イベントなし）']])
     .map(e=>'<div class="ev '+e[0]+'">'+e[1].replace(/</g,'&lt;')+'</div>').join('');
  const owner = f.owner==null? '' : ('　手番: P'+f.owner);
  $('tc').textContent = 'Turn '+f.turn+' / '+F[F.length-1].turn+owner;
  $('slider').value = i;
  $('prev').disabled = i<=0; $('next').disabled = i>=F.length-1;
}
$('prev').onclick=()=>{if(i>0){i--;render();}};
$('next').onclick=()=>{if(i<F.length-1){i++;render();}};
$('slider').max = F.length-1;
$('slider').oninput=e=>{i=+e.target.value;render();};
document.onkeydown=e=>{if(e.key==='ArrowLeft')$('prev').click();if(e.key==='ArrowRight')$('next').click();};
const w=R.result.winner;
$('res').innerHTML = w===0? '<span class="win-you">P0（下）の勝ち</span>' :
  w===1? '<span class="win-opp">P1（上）の勝ち</span>' : '引き分け/未決着';
render();
</script>
</body></html>"""


def build_html(frames, result, deck0, deck1):
    payload = {"frames": frames, "result": result}
    title = f"Replay: {Path(deck0).stem} vs {Path(deck1).stem}"
    return (HTML_TMPL
            .replace("__TITLE__", html.escape(title))
            .replace("__DECK0__", html.escape(Path(deck0).stem))
            .replace("__DECK1__", html.escape(Path(deck1).stem))
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)))


def main() -> int:
    ap = argparse.ArgumentParser(description="対戦リプレイHTMLを生成")
    ap.add_argument("--deck0", default="decks/deck.csv")
    ap.add_argument("--deck1", default="decks/sample_deck.csv")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not (ROOT / "cg" / "api.py").exists():
        print("エンジン cg/ が見つかりません（リポジトリ直下に配置）", file=sys.stderr)
        return 1

    names = load_names()
    atk = load_attack_names()
    kinds = load_kinds()
    frames, result = record(args.deck0, args.deck1, names, atk, kinds)
    out = Path(args.out) if args.out else (
        ROOT / "replays" / f"{Path(args.deck0).stem}_vs_{Path(args.deck1).stem}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(frames, result, args.deck0, args.deck1), encoding="utf-8")
    print(f"✅ {out}  ({len(frames)}ターン, 勝者P{result['winner']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
