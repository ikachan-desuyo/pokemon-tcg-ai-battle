"""GitHub Pages版ビジュアライザ用に、カード名/技名マップを静的JSとして書き出す。

replay_viewer.py が読むのと同じソース(JP_Card_Data.csv + cg.api)から
docs/cards-data.js (window.CARD_DATA=...) を生成。ブラウザ側はこれを使い、
ユーザーが選んだ生ログ(JSON)をクライアントだけで描画できる。

実行: python tools/gen_viewer_data.py
"""
import sys, os, json
sys.path.insert(0, ".")
import importlib.util

spec = importlib.util.spec_from_file_location("rv", "tools/replay_viewer.py")
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)

data = {
    "name": {str(k): v for k, v in rv.NAME.items()},
    "atkByDmg": {f"{cid}:{dmg}": nm for (cid, dmg), nm in rv._JP_ATK_BY_DMG.items()},
    "atkDmg": {str(k): v for k, v in rv._ATK_DMG.items()},
    "atkEn": {str(k): v for k, v in rv._ATK_EN.items()},
}
os.makedirs("docs", exist_ok=True)
out = "docs/cards-data.js"
with open(out, "w", encoding="utf-8") as f:
    f.write("window.CARD_DATA=" + json.dumps(data, ensure_ascii=False) + ";\n")
print(f"→ {out} を生成（カード{len(data['name'])}件 / 技名{len(data['atkByDmg'])}件）")
