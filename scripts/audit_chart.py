# -*- coding: utf-8 -*-
"""
audit_chart.py : 일별 시계열(totalDataChart)로 저장값을 점검한다. (HANDOVER-ADDENDUM.md 2절)

2026-09-17 과 2026-09-19 의 hr30·hr7 이 정확히 같았던 8종목(ORCA, BONK, INJ, VVS, DEEP, YB, CRV, VELO)에 대해
  1) 매일 기록되는지, 아니면 주·월 단위로 몰려서 기록되는지
  2) 일별 자료로 다시 계산한 기준일(--asof, 기본 2026-09-19)의 30일·7일 합계가 저장값과 같은지
를 확인해 종목별로 보고만 한다. 주기형 목록(formula.lumpy) 추가나 저장값 수정은 하지 않는다(승인 필요).

  python scripts/audit_chart.py [--tokens ORCA,BONK,...] [--asof 2026-09-19] [--snapshot data/snapshots/2026-09-19.json]

창 정의: DefiLlama 의 total30d 가 어느 창을 쓰는지 확정하기 위해 두 가지를 모두 계산한다.
  A = 기준일 포함 30일(asof-29 .. asof),  B = 기준일 제외 30일(asof-30 .. asof-1). 7일도 같다.
"""
import argparse
import datetime as dt
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

DEFAULT_TOKENS = ["ORCA", "BONK", "INJ", "VVS", "DEEP", "YB", "CRV", "VELO"]


def fetch_chart(slug):
    d = C.http_get_json(C.LLAMA_FEES.format(slug=urllib.parse.quote(slug, safe="")))
    chart = d.get("totalDataChart") or []
    series = {C.from_unix(ts): (v or 0.0) for ts, v in chart}
    return series, {k: d.get(k) for k in C.HR_SCALAR_FIELDS}


def window_sum(series, end, days, inclusive=True):
    """end 를 포함(inclusive)하거나 제외한 days 일 창의 합과 기록된 날 수."""
    last = end if inclusive else end - dt.timedelta(days=1)
    first = last - dt.timedelta(days=days - 1)
    total, n, nz = 0.0, 0, 0
    d = first
    while d <= last:
        if d in series:
            n += 1
            total += series[d]
            if series[d]:
                nz += 1
        d += dt.timedelta(days=1)
    return total, n, nz


def cadence(series, end, days=90):
    """최근 days 일의 기록 양상: 기록된 날 수, 0 이 아닌 날 수, 가장 긴 공백(일)."""
    first = end - dt.timedelta(days=days - 1)
    dates = sorted(d for d in series if first <= d <= end)
    nonzero = [d for d in dates if series[d]]
    gap = 0
    for a, b in zip(nonzero, nonzero[1:]):
        gap = max(gap, (b - a).days)
    return len(dates), len(nonzero), gap, (nonzero[0] if nonzero else None), (nonzero[-1] if nonzero else None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", default=",".join(DEFAULT_TOKENS))
    ap.add_argument("--asof", default="2026-09-19")
    ap.add_argument("--snapshot", default=None, help="기본 data/snapshots/<asof>.json")
    ap.add_argument("--universe", default=C.UNIVERSE_PATH)
    a = ap.parse_args(argv)
    asof = C.parse_date(a.asof)
    snap = C.load_json(a.snapshot or os.path.join(C.SNAPSHOT_DIR, f"{a.asof}.json"))
    stored = {r["t"]: r for r in snap["rows"]}
    universe = C.load_universe(a.universe)
    toks = {t["t"]: t for t in universe["tokens"]}
    today = C.parse_date(C.today_utc())
    lumpy = set(universe.get("formula", {}).get("lumpy", []))

    for sym in [s.strip() for s in a.tokens.split(",") if s.strip()]:
        tok = toks[sym]
        series, scalars = fetch_chart(tok["slug"])
        s = stored.get(sym)
        n_days, n_nz, gap, first_nz, last_nz = cadence(series, asof)
        a30, na30, _ = window_sum(series, asof, 30, True)
        b30, nb30, _ = window_sum(series, asof, 30, False)
        a7, na7, _ = window_sum(series, asof, 7, True)
        b7, nb7, _ = window_sum(series, asof, 7, False)
        # 오늘의 summary 스칼라와 차트 창을 비교해 DefiLlama 창 정의를 확인한다
        ta30, _, _ = window_sum(series, today, 30, True)
        tb30, _, _ = window_sum(series, today, 30, False)
        chart_last = max(series) if series else None
        C.log(f"== {sym} ({tok['slug']}) 차트 {len(series)}일, 마지막 기록 {chart_last}, 주기형 목록: {'예' if sym in lumpy else '아니오'}")
        C.log(f"   최근 90일({asof} 기준): 기록 {n_days}일, 0 아닌 날 {n_nz}일, 0 아닌 기록 사이 최대 공백 {gap}일, "
              f"첫/마지막 비영 기록 {first_nz}/{last_nz}")
        if s:
            def mark(x, ref):
                return "일치" if ref is not None and abs(x - ref) <= max(1.0, abs(ref) * 1e-4) else "불일치"
            C.log(f"   저장값 hr30={s['hr30']:,.2f} hr7={s['hr7']:,.2f}")
            C.log(f"   창A(기준일 포함) 30일={a30:,.2f}({na30}일) {mark(a30, s['hr30'])}  7일={a7:,.2f}({na7}일) {mark(a7, s['hr7'])}")
            C.log(f"   창B(기준일 제외) 30일={b30:,.2f}({nb30}일) {mark(b30, s['hr30'])}  7일={b7:,.2f}({nb7}일) {mark(b7, s['hr7'])}")
        C.log(f"   오늘({today}) API total30d={scalars.get('total30d')}  차트 창A={ta30:,.2f}  창B={tb30:,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
