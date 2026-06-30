"""行動クローン(模倣学習)の共有コード。学習(train_policy)と推論(ImitationBot)で同一の
選択肢解決・特徴量化を使い、1位ブリジュラス(ShumpeiNomura)の思考を再現する。

各選択肢を『カードid/対象/技/ダメージ』に解決し、固定長の特徴ベクトルへ。
盤面の生dict(Observation.current / リプレイのcurrent)と option の生dict(Option.raw)に対して
同じ関数が使えるため、学習データと実戦の特徴量が一致する。
"""
from .state_encoder import caps

# 1位デッキの主要カードid(one-hot用)
DECK_IDS = [8, 169, 190, 57, 1097, 1121, 1152, 1192, 1213, 1227, 1122, 1182, 1244, 1123, 1159]
ATTACKERS = (190, 169)
# 特徴に使う option type(主要)
OTYPES = [7, 8, 9, 10, 12, 13, 14, 3, 1, 2, 6]  # PLAY,ATTACH,EVOLVE,ABILITY,RETREAT,ATTACK,END,CARD,YES,NO,ENERGY


def _spot_at(player, area, index):
    spots = {4: player.get("active"), 5: player.get("bench"), 2: player.get("hand")}.get(area) or []
    if index is not None and 0 <= index < len(spots) and spots[index]:
        sp = spots[index]
        return sp.get("id") if isinstance(sp, dict) else sp
    return None


def resolve(op, cur, me):
    """選択肢(生dict)を意味(カードid/対象id/技id/ダメージ)に解決。リプレイ・実戦共通。"""
    t = op.get("type")
    p = cur["players"][me]
    out = {"otype": t, "card_id": None, "target_id": None, "attack_id": None, "damage": 0}
    if t in (3, 4, 5):
        pl = cur["players"][op.get("playerIndex", op.get("player_index", me))]
        out["card_id"] = _spot_at(pl, op.get("area"), op.get("index"))
    elif t == 7:
        out["card_id"] = _spot_at(p, 2, op.get("index"))
    elif t in (8, 9, 10):
        out["card_id"] = _spot_at(p, op.get("area", 2), op.get("index"))
        ipa = op.get("inPlayArea", op.get("in_play_area"))
        ipi = op.get("inPlayIndex", op.get("in_play_index"))
        out["target_id"] = _spot_at(p, ipa, ipi)
    elif t == 12:
        out["card_id"] = _spot_at(p, 4, 0)
    elif t == 13:
        aid = op.get("attackId", op.get("attack_id")) or op.get("skillId")
        out["attack_id"] = aid
        out["card_id"] = _spot_at(p, 4, 0)
    return out


def board_ctx(cur, me):
    p = cur["players"][me]; o = cur["players"][1 - me]
    act = (p.get("active") or [None])[0]
    oact = (o.get("active") or [None])[0]
    bench = [b for b in (p.get("bench") or []) if b]
    in_play = [act] + bench
    return {
        "turn": cur.get("turn", 0),
        "my_prizes": len(p.get("prize") or []),
        "opp_prizes": len(o.get("prize") or []),
        "my_bench": len(bench),
        "my_hand": p.get("handCount", len(p.get("hand") or [])),
        "opp_active_hp": (oact.get("hp") or 0) if oact else 0,
        "opp_active_pv": (caps(oact.get("id"))["pv"] if oact else 0),
        "my_active_id": (act.get("id") if act else None),
        "my_active_energy": len((act.get("energyCards") or []) if act else []),
        "attacker_in_play": 1 if any(s and s.get("id") in ATTACKERS for s in in_play) else 0,
    }


def _en_count(sp):
    return len(sp.get("energyCards") or []) if isinstance(sp, dict) else 0


def featurize(ctx, opt, atk_dmg=None):
    """(盤面文脈, 解決済み選択肢) → 固定長特徴。option固有・盤面依存の信号を含めて忠実度を上げる。"""
    f = []
    for t in OTYPES:                      # option種別 one-hot
        f.append(1.0 if opt["otype"] == t else 0.0)
    cid = opt["card_id"]
    for d in DECK_IDS:                     # カード one-hot + other
        f.append(1.0 if cid == d else 0.0)
    f.append(1.0 if (cid is not None and cid not in DECK_IDS) else 0.0)
    cp = caps(cid) if cid else None        # カード能力
    f += [(cp["max_dmg"] / 100.0) if cp else 0.0, (cp["min_cost"] if cp else 0),
          (cp["evo"] if cp else 0), (cp["has_ability"] if cp else 0), (cp["pv"] if cp else 0)]
    # 攻撃: ダメージ + KO/lethal判定(最重要) + サイド価値
    dmg = opt.get("damage", 0)
    if not dmg and atk_dmg and opt.get("attack_id"):
        dmg = atk_dmg.get(opt["attack_id"], 0)
    is_atk = opt["otype"] == 13
    ohp = ctx.get("opp_active_hp", 0)
    kos = 1.0 if (is_atk and dmg > 0 and ohp > 0 and dmg >= ohp) else 0.0
    f += [dmg / 100.0, 1.0 if is_atk else 0.0, kos,
          min(dmg / ohp, 2.0) if (is_atk and ohp > 0) else 0.0,
          (kos * ctx.get("opp_active_pv", 0))]            # KOで取れるサイド価値
    # 対象: 攻撃役へのエネ付与/進化か + 対象の現エネ
    tgt = opt.get("target_id")
    f += [1.0 if tgt in ATTACKERS else 0.0]
    # 文脈×カード(timing/状況): turn・残りサイド・ベンチ数 でカード優先が変わるのを学習
    turn = min(ctx.get("turn", 0), 12) / 12.0
    pr = ctx.get("my_prizes", 6) / 6.0
    bn = ctx.get("my_bench", 0) / 5.0
    have_atk = ctx.get("attacker_in_play", 0)
    for d in DECK_IDS:
        on = 1.0 if cid == d else 0.0
        f.append(on * turn)
    for d in DECK_IDS:
        f.append((1.0 if cid == d else 0.0) * pr)
    for d in DECK_IDS:
        f.append((1.0 if cid == d else 0.0) * bn)
    # 攻撃役が場に無い時のカード優先(進化前/サーチを優先する思考)
    for d in DECK_IDS:
        f.append((1.0 if cid == d else 0.0) * (1 - have_atk))
    return f


FEATURE_DIM = len(OTYPES) + len(DECK_IDS) + 1 + 5 + 5 + 1 + len(DECK_IDS) * 4


def policy_scores(X, params):
    """選択肢の特徴行列 X(n×d) を方策で採点(各選択肢のスコア n個)。線形/MLP両対応。
    学習(train_policy)と推論(ImitationBot)で同じ計算を使うための共有関数。"""
    import numpy as np
    X = np.asarray(X, dtype=float)
    if params.get("type") == "mlp":
        W1 = np.asarray(params["W1"]); b1 = np.asarray(params["b1"])
        w2 = np.asarray(params["w2"]); b2 = float(params["b2"])
        A1 = np.maximum(0.0, X @ W1 + b1)
        return A1 @ w2 + b2
    return X @ np.asarray(params["w"])
