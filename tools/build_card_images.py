"""日本語カード画像の一括取得(一度だけ実行するビルドスクリプト)。

JP_Card_Data.csv(カード名/エキスパンションマーク/コレクション番号)を起点に、
ポケモンカード公式のカード検索API(resultAPI.php)→詳細ページで内部cardIDを照合し、
画像を 幅300px WebP(q80) に縮小して docs/images/cards/{id}.webp へ保存する。
併せて docs/card-images.json (id→{name, image}) を生成する。

運用配慮: 1リクエスト1.0秒スロットル・UA明示・再開可能(既存webpはスキップ)。
以後のランタイム(リプレイビューア)は完全オフライン=公式サイトへのアクセスはゼロ。

usage:
  python tools/build_card_images.py            # 全カード
  python tools/build_card_images.py --limit 5  # 動作確認
"""
import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs" / "images" / "cards"
MAP_PATH = ROOT / "docs" / "card-images.json"
UA = {"User-Agent": "Mozilla/5.0 (personal replay-viewer asset build; one-time; contact via github ikachan-desuyo)"}
THROTTLE = 1.0
_last = [0.0]


def fetch(url):
    wait = THROTTLE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def search_ids(name):
    q = urllib.parse.quote(name)
    url = (f"https://www.pokemon-card.com/card-search/resultAPI.php?keyword={q}"
           f"&se_ta=&regulation_sidebar_form=all&pg=&illust=&sm_and_keyword=true")
    d = json.loads(fetch(url))
    return [c.get("cardID") for c in (d.get("cardList") or []) if c.get("cardID")]


def detail(card_id):
    html = fetch(f"https://www.pokemon-card.com/card-search/details.php/card/{card_id}/regu/all").decode(
        "utf-8", "ignore")
    m_img = re.search(r'card_images/large/([^/"]+)/([^"]+\.jpg)', html)
    m_no = re.search(r'&nbsp;(\d+)&nbsp;/&nbsp;(\d+)&nbsp;', html)
    m_h1 = re.search(r'<h1[^>]*>([^<]+)', html)
    return ((m_img.group(1), f"https://www.pokemon-card.com/assets/images/card_images/large/"
                             f"{m_img.group(1)}/{m_img.group(2)}") if m_img else (None, None),
            int(m_no.group(1)) if m_no else None,
            (m_h1.group(1).strip() if m_h1 else ""))


def _norm(name):
    """カード名の照合用正規化(【草】→草 等の表記ゆれ吸収)。"""
    return re.sub(r"[【】\s]", "", name or "")


def save_webp(img_bytes, out_path):
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w = 300
    im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    im.save(out_path, "WEBP", quality=80)


def load_csv():
    """カードID → (日本語名, エキスパンションマーク, コレクション番号int|None)"""
    cards = {}
    for row in csv.DictReader(open(ROOT / "data" / "JP_Card_Data.csv")):
        cid = row["カード ID"].strip()
        if not cid or cid in cards:
            continue
        no = row["コレクション番号"].split("/")[0].strip()
        cards[cid] = (row["カード名"].strip(), row["エキスパンションマーク"].strip(),
                      int(no) if no.isdigit() else None)
    return cards


def main(argv):
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    DEST.mkdir(parents=True, exist_ok=True)
    mapping = json.load(open(MAP_PATH)) if MAP_PATH.exists() else {}
    cards = load_csv()
    todo = [k for k in sorted(cards, key=int) if not (DEST / f"{k}.webp").exists()]
    if limit:
        todo = todo[:limit]
    print(f"対象 {len(todo)} / 全{len(cards)}枚 (既存はスキップ)")
    fails = []
    for n, cid in enumerate(todo, 1):
        name, mark, colno = cards[cid]
        try:
            # 基本エネ(id1-8)は公式カード検索の索引外→英語版(Limitless SVE)でフォールバック
            # (エネカードは絵柄に文字がほぼ無く日英で視覚差なし)
            if cid.isdigit() and int(cid) <= 8:
                url = (f"https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpci/SVE/"
                       f"SVE_{int(cid):03d}_R_EN_LG.png")
                save_webp(fetch(url), DEST / f"{cid}.webp")
                mapping[cid] = {"name": name, "image": f"images/cards/{cid}.webp"}
                print(f"[{n}/{len(todo)}] ○ {cid} {name} (EN fallback)")
                continue
            cand = search_ids(name)
            picked = None
            loose = None
            scan = 40 if mark in ("n/a", "") else 12   # マーク無し(基本エネ)は部分一致ノイズが多く全走査
            for pc in cand[:scan]:
                (setcode, img_url), page_no, page_name = detail(pc)
                if not img_url or _norm(page_name) != _norm(name):
                    continue              # カード名不一致(部分一致ヒットの別カード)は常に除外
                if setcode == mark and (colno is None or page_no == colno):
                    picked = img_url
                    break
                if loose is None:
                    loose = img_url
            if picked is None and loose and (len(cand) == 1 or mark in ("n/a", "")):
                picked = loose            # 名前一致済みの唯一候補/マーク無し(基本エネ=どの絵柄でも同一)
            if picked is None:
                fails.append((cid, name, mark, colno, len(cand)))
                print(f"[{n}/{len(todo)}] ✗ {cid} {name} ({mark} {colno}) 候補{len(cand)}")
                continue
            save_webp(fetch(picked), DEST / f"{cid}.webp")
            mapping[cid] = {"name": name, "image": f"images/cards/{cid}.webp"}
            print(f"[{n}/{len(todo)}] ○ {cid} {name}")
        except Exception as e:
            fails.append((cid, name, mark, colno, f"error:{e}"))
            print(f"[{n}/{len(todo)}] ✗ {cid} {name} error: {e}")
        if n % 20 == 0:
            json.dump(mapping, open(MAP_PATH, "w"), ensure_ascii=False, indent=0)
    json.dump(mapping, open(MAP_PATH, "w"), ensure_ascii=False, indent=0)
    print(f"\n完了: 成功{len(mapping)} 失敗{len(fails)}")
    for f in fails:
        print("  FAIL:", f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
