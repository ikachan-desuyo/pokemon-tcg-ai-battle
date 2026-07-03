"""Known問題のライフサイクル管理(Issue Tracker)。ReplayReviewerの検出結果を「件数」でなく
「発見→検出器追加→修正→Known推移→卒業→再発監視」として管理する(2026-07-03 ユーザ設計)。

ステータス5段階: Open → Confirmed → Fix Applied → Graduated → Regressed
  - 計測で件数0×(Fix Applied|Regressed) → Graduated(卒業日を記録)
  - 計測で件数>0×Graduated → Regressed(⚠卒業済みIssueの再発 を警告・regressions+=1)
  - 未登録ファミリが検出されたら自動でOpen登録(first_seen記録)
レジストリ: qa_issues.json(リポジトリ内=長期資産)。observational=trueのissueは観測カウンタ
(FetchSkew等=違反件数でない)としてTop3から除外。
"""
import json, os, datetime

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa_issues.json")


def load() -> dict:
    return json.load(open(PATH)) if os.path.exists(PATH) else {}


def save(reg: dict):
    json.dump(reg, open(PATH, "w"), ensure_ascii=False, indent=1)


def update(counts: dict, date: str | None = None):
    """counts: {検出シグネチャ: 件数}(1計測サイクル分・両サイド合算)。
    登録issueのmatch前方一致で集計→cycles追記→ステータス遷移。未登録ファミリはOpenで自動登録。
    返り値: (registry, alerts)"""
    date = date or datetime.date.today().isoformat()
    reg = load()
    alerts = []
    for name, iss in reg.items():
        c = sum(n for k, n in counts.items() if k.startswith(iss["match"]))
        iss.setdefault("cycles", []).append(c)
        st = iss.get("status")
        if c > 0 and st == "Graduated":
            iss["status"] = "Regressed"
            iss["regressions"] = iss.get("regressions", 0) + 1
            alerts.append(f"⚠ 卒業済みIssueの再発: {name} {c}件 (卒業日 {iss.get('graduated')})")
        elif c == 0 and st in ("Fix Applied", "Regressed"):
            iss["status"] = "Graduated"
            iss["graduated"] = date
    matches = [iss["match"] for iss in reg.values()]
    fams = {}
    for k, n in counts.items():
        if any(k.startswith(m) for m in matches):
            continue
        f = k.split("|")[0]
        fams[f] = fams.get(f, 0) + n
    for f, n in fams.items():
        if n > 0 and f not in reg:
            reg[f] = {"status": "Open", "detector": f, "match": f,
                      "first_seen": date, "cycles": [n], "regressions": 0}
            alerts.append(f"新規→ Open登録: {f} {n}件")
    save(reg)
    return reg, alerts


def report(reg: dict) -> str:
    """Top3 Known(前回比%)＋ライフサイクル表。レビュー報告4項目の④(Known再発件数)の材料。"""
    lines = []
    live = []
    for name, iss in reg.items():
        cyc = iss.get("cycles") or [0]
        if iss.get("observational"):
            continue
        if cyc[-1] > 0:
            prev = cyc[-2] if len(cyc) >= 2 else None
            live.append((cyc[-1], prev, name))
    lines.append("--- Top3 Known(観測カウンタ除く・前回比) ---")
    if not live:
        lines.append("  (現サイクルのKnown発火なし)")
    for c, prev, name in sorted(live, reverse=True)[:3]:
        pc = f"前回{prev}件({'+' if c > prev else ''}{(c - prev) * 100 // prev}%)" if prev else "初回"
        lines.append(f"  {name}: {c}件 | {pc}")
    lines.append("--- Issueライフサイクル ---")
    order = {"Regressed": 0, "Open": 1, "Confirmed": 2, "Fix Applied": 3, "Graduated": 4}
    for name, iss in sorted(reg.items(), key=lambda x: order.get(x[1].get("status"), 9)):
        cyc = iss.get("cycles") or []
        tail = "→".join(str(c) for c in cyc[-5:])
        obs = "(観測)" if iss.get("observational") else ""
        lines.append(f"  [{iss.get('status'):<11}] {name}{obs}: {tail} | 発見{iss.get('first_seen')}"
                     + (f" 卒業{iss.get('graduated')}" if iss.get("graduated") else "")
                     + (f" 再発{iss['regressions']}" if iss.get("regressions") else ""))
    return "\n".join(lines)
