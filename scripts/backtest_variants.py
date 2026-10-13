# -*- coding: utf-8 -*-
"""
backtest_variants.py : 산출식 변형들을 여러 기준일·기간에서 비교한다. (2026-10-13 메모의 "배출과 캡처 분리" 검토용)

  python scripts/backtest_variants.py [--cache DIR] [--out data/backtest/variants.json] [--md data/backtest/variants.md]

기준일 T 는 2025-10-01 부터 2026-07-01 까지 매월 1일과 2026-06-17, 기간 H 는 30·60·90·180일이다(T+H 가 오늘 이후면 건너뛴다).
T 시점 재구성은 backtest.py 의 reconstruct() 를 그대로 쓴다(창 정의, STRUCTURE 표, inc_qty30 환산 포함).

변형(모두 T 시점 값):
  adj      현행 ②안: net ≥ 0 이면 net × 계수곱, net < 0 이면 net 그대로
  adj_nn   음수 규칙 없음: 항상 net × 계수곱
  adjR     배출 무시: raw × 계수곱 (캡처 강도만)
  adjR_dil 두 축: adjR × k_dil2.  k_dil2 = 1 (배출 미확인 또는 배출 ≤ 귀속), 배출 > 귀속이면 clamp(귀속 ÷ 배출, 0.30, 1.00)
  net, raw 기준선
통계: 각 (변형, T, H) 마다 ρ(변형, 초과수익)과 상·하위 5분위 초과수익 중앙값 차이. 변형별로 평균 ρ, 양수 비율, 평균 5분위 차이를 모은다.
주의: 46종목은 2026-09 에 "캡처가 있는 종목"으로 고른 것이라 과거 시점 결과에는 생존 편향이 있다.
"""
import argparse
import datetime as dt
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C      # noqa: E402
import backtest as B    # noqa: E402

DEFAULT_TS = ["2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01",
              "2026-04-01", "2026-05-01", "2026-06-01", "2026-06-17", "2026-07-01"]
HS = [30, 60, 90, 180]
VARIANTS = ["adj", "adj_nn", "adjR", "adjR_dil", "net", "raw"]


def variant_values(r):
    x = r["_exact"]
    k = r["k"]
    kprod = k["acc"] * k["auto"] * k["stab"] * k["dil"] * k["hist"]
    raw, net = x["raw_T"], x["net_T"]
    inc = r.get("inc30_T")
    hr30 = r["hr30_T"]
    ratio = (inc / (hr30 / 1e6)) if (inc is not None and hr30 > 0) else None     # 배출 ÷ 귀속
    kd2 = 1.0 if (ratio is None or ratio <= 1) else max(0.30, min(1.0, 1.0 / ratio))
    return {"adj": x["adj_T"], "adj_nn": net * kprod, "adjR": raw * kprod, "adjR_dil": raw * kprod * kd2,
            "net": net, "raw": raw, "emission_ratio": ratio}


def quintile_spread(pairs):
    """pairs=[(value, excess)]. 상위 20% 초과수익 중앙값 − 하위 20% 중앙값."""
    pairs = sorted([p for p in pairs if p[1] is not None], key=lambda p: p[0])
    n = len(pairs)
    q = max(2, n // 5)
    if n < 10:
        return None
    lo = statistics.median(p[1] for p in pairs[:q])
    hi = statistics.median(p[1] for p in pairs[-q:])
    return hi - lo


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    ap.add_argument("--universe", default=C.UNIVERSE_PATH)
    ap.add_argument("--out", default=os.path.join(C.BACKTEST_DIR, "variants.json"))
    ap.add_argument("--md", default=os.path.join(C.BACKTEST_DIR, "variants.md"))
    a = ap.parse_args(argv)
    universe = C.load_universe(a.universe)
    today = C.parse_date(C.today_utc())
    C.log(f"[variants] 차트 수집 {len(universe['tokens'])}종목 …")
    charts, chart_failures = B.fetch_all_charts(universe["tokens"], a.cache)
    keys = [f"coingecko:{t['cg']}" for t in universe["tokens"]] + [B.BTC_KEY]
    price_cache = {}

    def prices_at(d):
        if d not in price_cache:
            price_cache[d] = B.fetch_historical_prices(keys, d)
        return price_cache[d]

    cells = []     # {T, H, variant, rho, n, spread}
    per_T = {}
    for T_str in DEFAULT_TS:
        T = C.parse_date(T_str)
        pT = prices_at(T)
        rows, excluded, warnings, _ = B.reconstruct(universe, charts, pT, pT, T, 0, chart_failures)
        if len(rows) < 10:
            C.log(f"[variants] {T_str}: 표본 {len(rows)}개로 부족, 건너뜀")
            continue
        vals = {r["t"]: variant_values(r) for r in rows}
        per_T[T_str] = {"n": len(rows), "excluded": [e["t"] for e in excluded],
                        "emission_ratio": {r["t"]: (round(vals[r["t"]]["emission_ratio"], 2) if vals[r["t"]]["emission_ratio"] is not None else None) for r in rows}}
        for H in HS:
            TH = T + dt.timedelta(days=H)
            if TH > today:
                continue
            pTH = prices_at(TH)
            btc = (pT.get(B.BTC_KEY) or {}).get("price"), (pTH.get(B.BTC_KEY) or {}).get("price")
            btc_ret = (btc[1] / btc[0] - 1) if btc[0] and btc[1] else None
            rets = {}
            for r in rows:
                key = f"coingecko:{r['cg'] if 'cg' in r else ''}"
                pt = r["price_T"]
                tok = next(t for t in universe["tokens"] if t["t"] == r["t"])
                p2 = (pTH.get(f"coingecko:{tok['cg']}") or {}).get("price")
                if pt and p2:
                    rr = p2 / pt - 1
                    rets[r["t"]] = (rr, (rr - btc_ret) if btc_ret is not None else None)
            for v in VARIANTS:
                xs = [vals[t][v] for t in rets]
                ex = [rets[t][1] for t in rets]
                st = B.spearman(xs, ex)
                cells.append({"T": T_str, "H": H, "variant": v, "rho": st["rho"], "p": st["p"], "n": st["n"],
                              "spread": quintile_spread(list(zip(xs, ex))), "btc": (round(btc_ret, 4) if btc_ret is not None else None)})
        C.log(f"[variants] {T_str}: 표본 {len(rows)} 제외 {len(excluded)}")

    # 집계
    agg = {}
    for v in VARIANTS:
        cs = [c for c in cells if c["variant"] == v and c["rho"] is not None]
        if not cs:
            continue
        agg[v] = {"cells": len(cs), "mean_rho": round(statistics.mean(c["rho"] for c in cs), 3),
                  "median_rho": round(statistics.median(c["rho"] for c in cs), 3),
                  "share_positive": round(sum(1 for c in cs if c["rho"] > 0) / len(cs), 2),
                  "mean_spread": (round(statistics.mean(c["spread"] for c in cs if c["spread"] is not None), 4)
                                  if any(c["spread"] is not None for c in cs) else None)}
        for H in HS:
            hs = [c for c in cs if c["H"] == H]
            if hs:
                agg[v][f"mean_rho_H{H}"] = round(statistics.mean(c["rho"] for c in hs), 3)
                agg[v][f"share_pos_H{H}"] = round(sum(1 for c in hs if c["rho"] > 0) / len(hs), 2)
    out = {"generated": C.now_utc_iso(), "Ts": DEFAULT_TS, "Hs": HS, "variants": VARIANTS, "cells": cells, "agg": agg, "per_T": per_T,
           "assumptions": ["T 시점 재구성은 backtest.py 와 동일(창 정의, STRUCTURE 표, NEAR·VVV inc_qty30 환산)",
                           "adjR_dil 의 k_dil2 는 배출 > 귀속일 때만 귀속÷배출로 완만히 할인(하한 0.30). 배출 미확인 종목은 1.0",
                           "초과수익 = 토큰 수익률 − BTC 수익률. ρ 는 변형값과 초과수익의 스피어만 순위상관",
                           "5분위 차이 = 변형값 상위 20% 종목의 초과수익 중앙값 − 하위 20% 중앙값",
                           "46종목은 2026-09 에 캡처가 있는 종목으로 선정되어 과거 시점 결과에 생존 편향이 있다",
                           "T+H 가 오늘 이후인 (T, H) 는 계산하지 않는다"]}
    C.dump_json(out, a.out, indent=1)

    # 마크다운
    L = ["# 산출식 변형 비교", "", f"생성 {out['generated']} · `scripts/backtest_variants.py` · 기준일 {len(per_T)}개 · 기간 {', '.join(str(h) for h in HS)}일", "",
         "변형: adj(현행 ②안) · adj_nn(음수 규칙 없음) · adjR(배출 무시, 캡처 강도만) · adjR_dil(두 축: adjR × 완만한 희석 할인) · net · raw", "",
         "## 집계 (모든 기준일·기간)", "", "| 변형 | 셀 수 | 평균 ρ | 중앙값 ρ | ρ>0 비율 | 평균 5분위 차이 | 평균 ρ H30 | H60 | H90 | H180 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for v in VARIANTS:
        g = agg.get(v)
        if not g:
            continue
        def h(x): return "n/a" if x is None else (f"{x:+.3f}" if isinstance(x, float) and abs(x) < 10 else str(x))
        L.append(f"| {v} | {g['cells']} | {g['mean_rho']:+.3f} | {g['median_rho']:+.3f} | {g['share_positive']:.0%} | "
                 f"{('n/a' if g['mean_spread'] is None else format(g['mean_spread'], '+.1%'))} | "
                 + " | ".join(h(g.get(f'mean_rho_H{H}')) for H in HS) + " |")
    for H in HS:
        L += ["", f"## H={H}일 · ρ(변형, BTC 대비 초과수익)", "", "| T | n | BTC | " + " | ".join(VARIANTS) + " |", "|---|---|---|" + "---|" * len(VARIANTS)]
        for T_str in DEFAULT_TS:
            cs = {c["variant"]: c for c in cells if c["T"] == T_str and c["H"] == H}
            if not cs:
                continue
            any_c = next(iter(cs.values()))
            L.append(f"| {T_str} | {any_c['n']} | {('n/a' if any_c['btc'] is None else format(any_c['btc'], '+.0%'))} | "
                     + " | ".join(("n/a" if cs[v]["rho"] is None else f"{cs[v]['rho']:+.2f}") for v in VARIANTS) + " |")
    L += ["", "## 가정", ""] + [f"- {x}" for x in out["assumptions"]] + [""]
    os.makedirs(os.path.dirname(a.md), exist_ok=True)
    with open(a.md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    C.log(f"[variants] 저장: {os.path.relpath(a.out, C.REPO_ROOT)}, {os.path.relpath(a.md, C.REPO_ROOT)}")
    for v in VARIANTS:
        g = agg.get(v)
        if g:
            C.log(f"  {v:9} 평균ρ {g['mean_rho']:+.3f} 중앙ρ {g['median_rho']:+.3f} 양수 {g['share_positive']:.0%} 5분위차 {('n/a' if g['mean_spread'] is None else format(g['mean_spread'], '+.1%'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
