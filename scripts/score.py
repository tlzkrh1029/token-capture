# -*- coding: utf-8 -*-
"""
score.py : 채점. data/raw/<date>.json 과 data/universe.json 으로 스냅샷을 만든다.
(HANDOVER.md 7장·9-2절, HANDOVER-ADDENDUM.md 1·2절)

  python scripts/score.py [--date YYYY-MM-DD] [--raw data/raw/<date>.json] [--universe data/universe.json]

산출식은 scripts/score_reference.py 와 같다(같은 입력에 대해 mc, raw, net, adj, rr 이 ±0.002 안에서 일치해야 한다).
그 위에 다음을 더한다.
  * inc_qty30 이 있는 종목(NEAR, VVV)은 채점 전에 inc30 = inc_qty30 × 그날 가격 ÷ 1e6 으로 다시 계산하고
    universe.json 의 inc30·inc_ref_price·inc_ref_date 를 갱신한다. 가격 수집에 실패한 종목은 직전 값을 유지한다.
  * 수집 실패 종목은 직전 스냅샷의 값을 쓰고 행에 "carried": true, "carried_fields": [...] 를 넣는다.
    같은 필드가 2주 연속 실패하면 행을 만들지 않고 failures 에 남긴다. 직전 스냅샷에도 없으면 행을 만들지 않는다.
    "2주 연속" 은 직전 스냅샷이 7일 이상 전일 때만 성립한다(같은 주의 재실행은 같은 실패로 센다).
  * hr30·hr7 이 직전 주와 정확히 같으면(수집에 성공했는데도) "stale_suspect": true 를 넣고 로그와 latest.json 의 meta 에 적는다.
    둘 다 0 인 행(실현 0)은 같은 값이 당연하므로 제외한다. 주기형 목록 종목은 정상이어도 같은 값이 나올 수 있다.
  * growth = hr30 ÷ (hr1y ÷ ANN) 을 행에 기록한다(13장. 채점에는 쓰지 않는다).
  * rev30·fees30(DefiLlama 30일 프로토콜 수익·총수수료)과 payout(귀속률 % = hr30 ÷ rev30 × 100)을 행에 기록한다(채점에는 쓰지 않는다).
출력
  data/snapshots/<date>.json  {date, rows}
  data/latest.json            {date, rows, meta:{fetched_at, failures, universe_updated, count, ...}}
  data/history.csv            날짜별 평탄 파일(같은 날짜 행은 교체)
  표준 출력                   직전 스냅샷 대비 등급 변동 종목
행 필드(아티팩트 페이지가 읽는 모양이므로 순서를 바꾸지 않는다):
  t, n, slug, cg, mc, fdv, price, hr30, hr7, rr, raw, net, adj, g,
  inc, ver, acc, auto, stab, k{acc, auto, stab, dil, hist}, hist, note
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

HISTORY_COLUMNS = ["date", "t", "adj", "g", "mc", "hr30", "hr7", "net", "raw", "price", "payout", "adjg", "flags"]


# ---------------------------------------------------------------------------
# 산출식 (score_reference.py 와 동일)
# ---------------------------------------------------------------------------
def grade(adj, bands=C.BANDS):
    for th, g in bands:
        if adj >= th:
            return g
    return "D"


def score_one(tok, price, hr30, hr7, k_acc, k_auto, lumpy, bands=C.BANDS):
    """종목 정의 tok(universe.tokens[i])와 주간 입력으로 행 하나를 만든다."""
    circ, fdv, inc = tok["circ"], tok["fdv"], tok.get("inc30")
    mc = price * circ / 1e6                                  # 시가총액, 백만 달러
    raw = (hr30 / 1e6) / mc * 100 * C.ANN                    # 원시 캡처율 %
    netv = (hr30 / 1e6 - inc) if inc is not None else (hr30 / 1e6)
    net = netv / mc * 100 * C.ANN                            # 순 캡처율 %
    rr = (hr7 * 30 / 7) / hr30 if hr30 else None             # 7일 런레이트 ÷ 30일

    if hr30 == 0:
        ks, stab = 0.0, "실현 0"
    elif tok["t"] in lumpy:
        ks, stab = 0.90, "주기형"
    else:
        ks = max(0.30, min(1.00, rr))
        stab = "가속" if rr > 1.15 else ("감속" if rr < 0.85 else "안정")
    ka = k_acc[tok["acc"]]
    ku = k_auto[tok["auto"]]
    kd = max(0.40, (1.0 / fdv) ** 0.5)
    kh = tok["hist_k"]

    # 음수 규칙(2026-09-17 ②안): 순 캡처율이 음수이면 계수를 곱하지 않는다.
    # 할인 계수를 음수에 곱하면 값이 0 쪽으로 올라가 점수가 좋아지기 때문이다. (7-1절)
    adj = net if net < 0 else net * ka * ku * ks * kd * kh

    return {
        "t": tok["t"], "n": tok["n"], "slug": tok["slug"], "cg": tok["cg"],
        "mc": round(mc, 3), "fdv": fdv, "price": price, "hr30": hr30, "hr7": hr7,
        "rr": (round(rr, 3) if rr is not None else None),
        "raw": round(raw, 3), "net": round(net, 3), "adj": round(adj, 3), "g": grade(adj, bands),
        "inc": inc, "ver": inc is not None,
        "acc": tok["acc"], "auto": tok["auto"], "stab": stab,
        "k": {"acc": ka, "auto": ku, "stab": round(ks, 3), "dil": round(kd, 4), "hist": kh},
        "hist": tok["hist"], "note": tok["note"],
    }


def score(universe, inputs, date, overrides=None):
    """
    score_reference.score() 와 같은 인터페이스. 검증(tests/)과 시드 생성(seed_snapshots.py)이 쓴다.
    inputs : {sym: [price, hr30, hr7]} 또는 {sym: {"price":..,"hr30":..,"hr7":..}}
    """
    k_acc, k_auto, lumpy, bands = C.formula_constants(universe)
    rows = []
    for tok in universe["tokens"]:
        sym = tok["t"]
        if sym not in inputs:
            continue
        x = inputs[sym]
        price, hr30, hr7 = (x["price"], x["hr30"], x["hr7"]) if isinstance(x, dict) else x
        if overrides and sym in overrides:
            tok = dict(tok, **overrides[sym])
        rows.append(score_one(tok, price, hr30, hr7, k_acc, k_auto, lumpy, bands))
    rows.sort(key=lambda r: -r["adj"])
    return {"date": date, "rows": rows}


# ---------------------------------------------------------------------------
# 주간 채점
# ---------------------------------------------------------------------------
def recompute_inc(universe, price, date):
    """inc_qty30 이 있는 종목의 inc30 을 그날 가격으로 다시 환산한다(6-4절). 바뀐 종목 목록을 돌려준다."""
    changed = []
    for tok in universe["tokens"]:
        q = tok.get("inc_qty30")
        p = price.get(tok["t"])
        if q is None or p is None:
            continue
        new_inc = round(q * p / 1e6, 3)
        if tok.get("inc30") != new_inc or tok.get("inc_ref_date") != date:
            changed.append((tok["t"], tok.get("inc30"), new_inc, p))
        tok["inc30"] = new_inc
        tok["inc_ref_price"] = p
        tok["inc_ref_date"] = date
    return changed


def payout_of(hr_row, rev_row):
    """귀속률 % = 30일 귀속액 ÷ 30일 프로토콜 수익 × 100. 수익이 없거나 0 이면 None. (보조 지표, 채점에는 쓰지 않는다)"""
    if not hr_row or not rev_row:
        return None
    h30, r30 = hr_row.get("total30d"), rev_row.get("total30d")
    if h30 is None or not r30:
        return None
    return round(h30 / r30 * 100, 1)


def growth_of(hr_row):
    """성장배수 g = total30d ÷ (total1y ÷ ANN). (13장) 계산할 수 없으면 None."""
    if not hr_row:
        return None
    h30, h1y = hr_row.get("total30d"), hr_row.get("total1y")
    if h30 is None or not h1y:
        return None
    return round(h30 / (h1y / C.ANN), 3)


WEEK_DAYS = 7   # "2주 연속 실패" 판정은 직전 스냅샷이 7일 이상 전일 때만 한다. 같은 주의 재실행은 같은 실패로 센다.


def build_rows(universe, raw, prev, date):
    """
    raw(fetch.py 출력)와 직전 스냅샷 prev 로 행을 만든다.
    반환: rows, failures(행을 만들지 못한 종목), carried(표시된 종목), stale(stale_suspect 종목)
    """
    k_acc, k_auto, lumpy, bands = C.formula_constants(universe)
    prev_rows = {r["t"]: r for r in (prev or {}).get("rows", [])}
    prev_date = (prev or {}).get("date")
    # 직전 스냅샷이 한 주 이상 전이면 거기서 carried 였던 필드의 재실패는 "2주 연속 실패"다.
    # 하루 이틀 뒤의 재실행(수동 실행, 같은 주 보완)은 같은 실패로 보고 다시 carried 로 둔다.
    second_week = bool(prev_date) and (C.parse_date(date) - C.parse_date(prev_date)).days >= WEEK_DAYS
    rows, failures, carried, stale = [], [], [], []
    for tok in universe["tokens"]:
        sym = tok["t"]
        hr_row = (raw.get("hr") or {}).get(sym)
        price = (raw.get("price") or {}).get(sym)
        pr = prev_rows.get(sym)
        prev_carried = set((pr or {}).get("carried_fields") or [])
        carried_fields = []

        hr_ok = bool(hr_row) and hr_row.get("total30d") is not None
        if hr_ok:
            hr30 = float(hr_row["total30d"])
            hr7 = float(hr_row.get("total7d") or 0.0)
        else:
            if pr is None:
                failures.append({"t": sym, "kind": "hr", "reason": "귀속액 미확인(직전 스냅샷에도 없음)"})
                continue
            if "hr30" in prev_carried and second_week:
                failures.append({"t": sym, "kind": "hr", "reason": f"귀속액 미확인(2주 연속 실패, 직전 {prev_date}부터 carried)"})
                continue
            hr30, hr7 = pr["hr30"], pr["hr7"]
            carried_fields += ["hr30", "hr7"]

        if price is None:
            if pr is None or pr.get("price") is None:
                failures.append({"t": sym, "kind": "price", "reason": "가격 미확인(직전 스냅샷에도 없음)"})
                continue
            if "price" in prev_carried and second_week:
                failures.append({"t": sym, "kind": "price", "reason": f"가격 미확인(2주 연속 실패, 직전 {prev_date}부터 carried)"})
                continue
            price = pr["price"]
            carried_fields.append("price")

        row = score_one(tok, price, hr30, hr7, k_acc, k_auto, lumpy, bands)
        row["growth"] = growth_of(hr_row) if hr_ok else None
        rev_row = (raw.get("rev") or {}).get(sym)
        fees_row = (raw.get("fees") or {}).get(sym)
        row["rev30"] = (rev_row or {}).get("total30d")
        row["fees30"] = (fees_row or {}).get("total30d")
        row["payout"] = payout_of(hr_row, rev_row) if hr_ok else None
        # 배출 차감 전 조정 캡처율(원시 캡처율 × 다섯 계수)과 그 등급. 배출(희석)과 캡처(귀속 강도)를 따로 보기 위한 보조 지표다.
        k = row["k"]
        row["adjg"] = round(row["raw"] * k["acc"] * k["auto"] * k["stab"] * k["dil"] * k["hist"], 3)
        row["gg"] = grade(row["adjg"], bands)
        if carried_fields:
            row["carried"] = True
            row["carried_fields"] = carried_fields
            carried.append((sym, carried_fields))
        if hr_ok and pr is not None and hr30 == pr.get("hr30") and hr7 == pr.get("hr7") and not (hr30 == 0 and hr7 == 0):
            row["stale_suspect"] = True
            stale.append(sym)
        rows.append(row)
    rows.sort(key=lambda r: -r["adj"])
    return rows, failures, carried, stale


def grade_changes(rows, prev):
    prev_rows = {r["t"]: r for r in (prev or {}).get("rows", [])}
    out = []
    for r in rows:
        p = prev_rows.get(r["t"])
        if p is None:
            out.append({"t": r["t"], "from": None, "to": r["g"], "adj_from": None, "adj_to": r["adj"]})
        elif p["g"] != r["g"]:
            out.append({"t": r["t"], "from": p["g"], "to": r["g"], "adj_from": p["adj"], "adj_to": r["adj"]})
    return out


def row_flags(row):
    flags = []
    if row.get("carried"):
        flags.append("carried:" + "+".join(row.get("carried_fields") or []))
    if row.get("stale_suspect"):
        flags.append("stale_suspect")
    if row.get("seeded"):
        flags.append("seeded")
    return ";".join(flags)


def append_history(snapshot, path=C.HISTORY_PATH, seeded=False):
    """history.csv 에 snapshot 의 행을 덧붙인다. 같은 날짜의 기존 행은 교체한다."""
    date = snapshot["date"]
    existing = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            existing = [r for r in rd if r.get("date") != date]
    new = []
    for r in snapshot["rows"]:
        flags = row_flags(dict(r, seeded=seeded))
        new.append({"date": date, "t": r["t"], "adj": r["adj"], "g": r["g"], "mc": r["mc"],
                    "hr30": r["hr30"], "hr7": r["hr7"], "net": r["net"], "raw": r["raw"],
                    "price": r["price"], "payout": ("" if r.get("payout") is None else r.get("payout")),
                    "adjg": ("" if r.get("adjg") is None else r.get("adjg")), "flags": flags})
    allrows = existing + new
    allrows.sort(key=lambda r: (r["date"], -float(r["adj"])))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLUMNS)
        w.writeheader()
        w.writerows(allrows)


def print_table(snap):
    C.log(f"{'':3}{'종목':7}{'등급':>4}{'조정%':>9}{'순%':>9}{'원시%':>9}{'시총$M':>11}{'RR':>7}  {'추세':6}{'귀속방식'}")
    for i, r in enumerate(snap["rows"], 1):
        rr = "-" if r["rr"] is None else f"{r['rr']:.2f}"
        mark = ("*" if r.get("carried") else "") + ("?" if r.get("stale_suspect") else "")
        C.log(f"{i:<3}{(r['t'] + mark):7}{r['g']:>4}{r['adj']:>9.2f}{r['net']:>9.2f}{r['raw']:>9.2f}"
              f"{r['mc']:>11.1f}{rr:>7}  {r['stab']:6}{r['acc']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="토큰캡처 주간 채점")
    ap.add_argument("--date", default=None)
    ap.add_argument("--raw", default=None, help="기본 data/raw/<date>.json")
    ap.add_argument("--universe", default=C.UNIVERSE_PATH)
    ap.add_argument("--snapshot-dir", default=C.SNAPSHOT_DIR)
    ap.add_argument("--latest", default=C.LATEST_PATH)
    ap.add_argument("--history", default=C.HISTORY_PATH)
    ap.add_argument("--no-universe-write", action="store_true", help="inc30 재환산 결과를 universe.json 에 쓰지 않는다")
    a = ap.parse_args(argv)
    date = a.date or C.today_utc()
    raw_path = a.raw or os.path.join(C.RAW_DIR, f"{date}.json")

    universe = C.load_universe(a.universe)
    raw = C.load_json(raw_path)
    if raw.get("date") and raw["date"] != date:
        C.warn(f"raw 의 date({raw['date']})와 --date({date})가 다릅니다")
    prev_date, prev = C.previous_snapshot(date, a.snapshot_dir)
    C.log(f"[score] {date} raw={os.path.relpath(raw_path, C.REPO_ROOT)} 직전 스냅샷={prev_date}")

    # 1) inc30 재환산 (6-4절)
    changed = recompute_inc(universe, raw.get("price") or {}, date)
    for sym, old, new, p in changed:
        C.log(f"[score] inc30 재환산 {sym}: {old} → {new} (가격 {p})")
    if changed:
        universe["updated"] = date
        if not a.no_universe_write:
            C.save_universe(universe, a.universe)
            C.log(f"[score] universe.json 갱신 (updated={date})")

    # 2) 채점
    rows, failures, carried, stale = build_rows(universe, raw, prev, date)
    snap = {"date": date, "rows": rows}
    changes = grade_changes(rows, prev)
    k_acc, k_auto, lumpy, bands = C.formula_constants(universe)

    meta = {
        "fetched_at": raw.get("fetched_at"),
        "failures": (raw.get("failures") or []) + failures,
        "universe_updated": universe.get("updated"),
        "count": len(rows),
        "expected": len(universe["tokens"]),
        "previous": prev_date,
        "carried": [{"t": s, "fields": f} for s, f in carried],
        "stale_suspect": stale,
        "stale_note": ("hr30·hr7 이 직전 주와 정확히 같은 종목. 주기형 목록(" + ", ".join(sorted(lumpy)) +
                       ")의 종목은 정상이어도 같은 값이 나올 수 있다"),
        "grade_changes": changes,
        "inc_recomputed": [{"t": s, "from": o, "to": n, "price": p} for s, o, n, p in changed],
    }
    snap_path = os.path.join(a.snapshot_dir, f"{date}.json")
    C.dump_json(snap, snap_path)
    C.dump_json({"date": date, "rows": rows, "meta": meta}, a.latest)
    append_history(snap, a.history)

    # 3) 로그
    print_table(snap)
    C.log(f"[score] 행 {len(rows)}/{len(universe['tokens'])}  저장: {os.path.relpath(snap_path, C.REPO_ROOT)}, "
          f"{os.path.relpath(a.latest, C.REPO_ROOT)}, {os.path.relpath(a.history, C.REPO_ROOT)}")
    if carried:
        C.log("[score] carried(직전 값 사용): " + ", ".join(f"{s}({'+'.join(f)})" for s, f in carried))
    if stale:
        C.log("[score] stale_suspect(hr30·hr7 이 직전 주와 동일): " + ", ".join(stale)
              + f"  — 주기형 목록 종목은 정상이어도 같을 수 있음: {', '.join(sorted(lumpy))}")
    for f in failures:
        C.log(f"[score] 행 제외 {f['t']:6} {f['reason']}")
    if changes:
        C.log(f"[score] 등급 변동 ({prev_date} → {date}):")
        for c in changes:
            C.log(f"    {c['t']:6} {c['from'] or '신규':3} → {c['to']:3}  adj {c['adj_from']} → {c['adj_to']}")
    else:
        C.log("[score] 등급 변동 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
