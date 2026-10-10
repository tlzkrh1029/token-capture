# -*- coding: utf-8 -*-
"""
backtest.py : 과거 시점 T 의 등급을 재구성하고 T 이후 H 일 수익률과의 스피어만 순위상관을 낸다. (HANDOVER.md 12장·13장)

  python scripts/backtest.py --T 2026-06-17 [--H 90] [--out data/backtest/2026-06-17.json]
  python scripts/backtest.py --all          # T = 2026-04-01, 05-01, 06-01, 06-17, 07-01 → 각 JSON + data/backtest/summary.md

입력
  * 종목마다 exclude 파라미터를 뺀 주소로 totalDataChart(일별 [unix, value])를 받는다. 주간 수집과 달리 여기서만 받는다.
  * 가격은 coins.llama.fi/prices/historical/<T>, /<T+H>. BTC(coingecko:bitcoin)도 같이 받아 초과수익을 낸다.
T 시점 재구성
  * 창 정의: DefiLlama 의 total30d 는 기준일을 제외한 직전 30일(완결 일자)의 합계임을 audit_chart.py 로 확인했다(2026-10-10).
    따라서 hr30_T = [T-30, T-1] 합계, hr7_T = [T-7, T-1], hr1y_T = [T-365, T-1]. 창 안의 기록 수가 창 길이와 다르면 경고한다.
  * mc_T = price_T × circ(현재 값). 유통량은 현재 값을 그대로 쓰므로 근사다.
  * fdv, acc, auto, hist_k 는 현재 universe.json 값을 쓴다. 단 T 이후 구조가 바뀐 종목은 STRUCTURE 표(아래)로
    T 시점 기준으로 되돌리거나 제외한다. 판별 규칙은 STRUCTURE 의 주석에 있다.
  * inc30 은 현재 값(달러 고정)이라 T 시점과 다르다. inc_qty30 이 있는 NEAR·VVV 만 수량 × T 시점 가격으로 환산한다(6-4절).
    배출액이 있는 종목에 한해 근사라는 점을 출력에 적는다.
  * hist_k 의 T 시점 재계산은 달력 개월 수(정수)로 한다. 순위상관은 반올림하지 않은 값으로 계산한다.
출력(JSON 과 표준 출력)
  * 종목별 adj_T, grade_T, return, BTC 대비 초과수익
  * ρ(adj_T, return), ρ(adj_T, 초과수익), 표본 수, p값(scipy 가 있으면 scipy, 없으면 순열검정 1,000회)
  * 등급 그룹별 평균·중앙값 수익률
  * 기준선: ρ(raw_T, return), ρ(hr30_T/mc_T, return)  — 둘은 서로 단조 변환이라 순위상관이 같다(확인용으로 둘 다 낸다), ρ(net_T, return)
  * 음수 처리 변형: 현행 ②안(adj_T) 과 ①안 adj1_T = (hr30_T/1e6 × 계수곱 − inc30) ÷ mc_T × 100 × ANN
  * 성장 계수 변형(13장): g_T = hr30_T ÷ (hr1y_T ÷ ANN), k_growth 매핑 후 ρ(adj_T × k_growth, return)
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import random
import statistics
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C   # noqa: E402
import score as S    # noqa: E402

DEFAULT_TS = ["2026-04-01", "2026-05-01", "2026-06-01", "2026-06-17", "2026-07-01"]
BTC_KEY = "coingecko:bitcoin"

# ---------------------------------------------------------------------------
# T 시점 구조 판별 표 (12-2절). universe.json 의 note·hist 에서 날짜가 확인되는 종목만 적는다.
#   start : 현행 귀속 구조의 개시일. T < start 이면 "구조 개시 전"으로 제외한다.
#           start 가 있으면 hist_k 도 T 시점 기준으로 다시 계산한다(12개월 이상 1.00, 6~12 0.85, 3~6 0.70, 3개월 미만 0.50).
#   stop  : 집행이 중단된 날. T < stop 이면 당시에는 집행 중이었으므로 auto 를 active_auto 로 되돌린다.
#   start 가 없는 종목(ORE, SPK 등 '개시 미확인')은 현재 정의를 그대로 쓴다.
#   날짜가 '2026-07' 처럼 월만 있으면 그 달 1일로 적었다.
#   추가 규칙(자료 기반): auto 가 '정지'인데 T 시점 hr30_T > 0 이고 stop 날짜를 모르는 종목(ETHFI)은 복원할 수 없으므로 제외한다.
# ---------------------------------------------------------------------------
STRUCTURE = {
    "PUMP":   {"start": "2026-04-01", "why": "2026-04 정책 전환(순수익 50% 매입 소각)"},
    "UNI":    {"start": "2025-12-28", "why": "UNIfication 소각 개시"},
    "PONS":   {"start": "2026-07-01", "why": "2026-07 매입 소각 개시"},
    "STONK":  {"start": "2026-08-01", "why": "2026-08 공개"},
    "LIT":    {"start": "2026-07-10", "why": "첫 소각 2026-07-10"},
    "JTO":    {"start": "2026-07-13", "why": "JIP-38 가결"},
    "AAVE":   {"start": "2025-04-09", "stop": "2026-04-19", "active_auto": "정기 집행",
               "why": "2025-04-09 개시, 2026-04-19 중단. 중단 전에는 재무위원회의 주간 집행이었으므로 '정기 집행'으로 되돌림(가정)"},
    "BONK":   {"start": "2025-12-01", "why": "2025-12 BNKK 전환"},
    "PENDLE": {"start": "2026-01-01", "why": "sPENDLE 2026-01"},
    "NEAR":   {"start": "2026-02-23", "why": "Intents 매입 2026-02-23 개시. near-intents 차트도 이 날부터"},
    "EDGE":   {"start": "2026-04-03", "why": "2026-04-03 개시"},
    "VVV":    {"start": "2026-04-15", "why": "2026-04-15 프로그램형 엔진"},
    "SYRUP":  {"start": "2026-08-01", "why": "MIP-019 매수 2026-08"},
    "DYDX":   {"start": "2025-11-13", "why": "2025-11-13 거버넌스 승인"},
    "LINK":   {"start": "2025-08-07", "why": "Payment Abstraction 2025-08-07"},
    "ZRO":    {"start": "2025-09-01", "why": "2025-09 개시"},
    "DBR":    {"start": "2025-06-01", "why": "Reserve Fund 2025-06 가동"},
    "YB":     {"start": "2025-12-01", "why": "2025-12 fee switch"},
    "USUAL":  {"start": "2025-01-13", "why": "2025-01-13 개시"},
}

# 성장 계수 제안 매핑(13장). 채택 여부는 이 스크립트의 결과로 결정한다.
K_GROWTH = [(1.5, 1.10), (1.0, 1.00), (0.7, 0.85), (float("-inf"), 0.70)]


def hist_k_from_months(m):
    if m >= 12:
        return 1.00
    if m >= 6:
        return 0.85
    if m >= 3:
        return 0.70
    return 0.50


def k_growth_of(g):
    if g is None:
        return 1.0
    for th, k in K_GROWTH:
        if g >= th:
            return k
    return 0.70


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def fetch_chart(slug, cache_dir=None):
    path = os.path.join(cache_dir, urllib.parse.quote(slug, safe="") + ".json") if cache_dir else None
    if path and os.path.exists(path):
        return C.load_json(path)
    d = C.http_get_json(C.LLAMA_FEES.format(slug=urllib.parse.quote(slug, safe="")))
    chart = d.get("totalDataChart") or []
    out = {"slug": slug, "chart": [[int(ts), (v or 0.0)] for ts, v in chart]}
    if path:
        C.dump_json(out, path)
    return out


def fetch_all_charts(tokens, cache_dir=None):
    charts, failures = {}, {}
    with cf.ThreadPoolExecutor(max_workers=C.HR_CONCURRENCY) as ex:
        futs = {ex.submit(fetch_chart, t["slug"], cache_dir): t["t"] for t in tokens}
        for fut in cf.as_completed(futs):
            sym = futs[fut]
            try:
                charts[sym] = {C.from_unix(ts): v for ts, v in fut.result()["chart"]}
            except Exception as e:
                failures[sym] = str(e)
    return charts, failures


def fetch_historical_prices(keys, date):
    ts = C.to_unix(date)
    got = {}
    for batch in C.batched(keys, C.PRICE_BATCH):
        url = C.LLAMA_PRICE_HISTORICAL.format(ts=ts, keys=",".join(batch))
        d = C.http_get_json(url)
        got.update(d.get("coins", {}))
    return got


def window_sum(series, end_exclusive, days):
    """[end-days, end-1] 창의 합과 기록 수. end_exclusive 는 기준일 T(그날은 제외)."""
    last = end_exclusive - dt.timedelta(days=1)
    first = last - dt.timedelta(days=days - 1)
    total, n = 0.0, 0
    d = first
    while d <= last:
        v = series.get(d)
        if v is not None:
            total += v
            n += 1
        d += dt.timedelta(days=1)
    return total, n


# ---------------------------------------------------------------------------
# 통계 (표준 라이브러리만)
# ---------------------------------------------------------------------------
def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def _pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def spearman(x, y, perms=1000, seed=0):
    """스피어만 ρ 와 p값. scipy 가 있으면 scipy.stats.spearmanr, 없으면 순열검정(perms 회, 고정 시드)."""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return {"rho": None, "p": None, "n": n, "method": None}
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    try:
        from scipy.stats import spearmanr  # type: ignore
        rho, p = spearmanr(xs, ys)
        return {"rho": round(float(rho), 4), "p": round(float(p), 4), "n": n, "method": "scipy"}
    except Exception:
        pass
    rx, ry = _ranks(xs), _ranks(ys)
    rho = _pearson(rx, ry)
    if rho is None:
        return {"rho": None, "p": None, "n": n, "method": "permutation"}
    rng = random.Random(seed)
    hits = 0
    ry2 = list(ry)
    for _ in range(perms):
        rng.shuffle(ry2)
        r = _pearson(rx, ry2)
        if r is not None and abs(r) >= abs(rho) - 1e-12:
            hits += 1
    return {"rho": round(rho, 4), "p": round((hits + 1) / (perms + 1), 4), "n": n, "method": f"permutation({perms})"}


# ---------------------------------------------------------------------------
# T 시점 재구성
# ---------------------------------------------------------------------------
def months_between(a, b):
    """a 부터 b 까지 지난 달력 개월 수(정수). 같은 날짜면 한 달로 센다(예: 04-01 → 07-01 = 3개월)."""
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        m -= 1
    return m


def reconstruct(universe, charts, prices_T, prices_TH, T, H, chart_failures):
    k_acc, k_auto, lumpy, bands = C.formula_constants(universe)
    TH = T + dt.timedelta(days=H)
    btc_T = (prices_T.get(BTC_KEY) or {}).get("price")
    btc_TH = (prices_TH.get(BTC_KEY) or {}).get("price")
    btc_ret = (btc_TH / btc_T - 1) if btc_T and btc_TH else None
    rows, excluded, warnings = [], [], []
    for tok in universe["tokens"]:
        sym = tok["t"]
        if sym in chart_failures:
            excluded.append({"t": sym, "reason": f"차트 수집 실패: {chart_failures[sym]}"})
            continue
        st = STRUCTURE.get(sym, {})
        tok_T = dict(tok)
        notes = []
        if st.get("start"):
            start = C.parse_date(st["start"])
            if T < start:
                excluded.append({"t": sym, "reason": f"구조 개시 전({st['start']}): {st['why']}"})
                continue
            m = months_between(start, T)
            hk = hist_k_from_months(m)
            if hk != tok["hist_k"]:
                notes.append(f"hist_k {tok['hist_k']}→{hk} (T 시점 {m}개월)")
            tok_T["hist_k"] = hk
        if st.get("stop"):
            stop = C.parse_date(st["stop"])
            if T < stop and tok["auto"] == "정지":
                tok_T["auto"] = st.get("active_auto", "정기 집행")
                notes.append(f"auto 정지→{tok_T['auto']} (중단일 {st['stop']} 이전)")
        series = charts.get(sym, {})
        hr30, n30 = window_sum(series, T, 30)
        hr7, n7 = window_sum(series, T, 7)
        hr1y, n1y = window_sum(series, T, 365)
        if n30 != 30:
            warnings.append(f"{sym}: 30일 창 기록 {n30}개")
        if n30 == 0:
            excluded.append({"t": sym, "reason": "T 이전 30일에 일별 기록 없음(차트 시작 전)"})
            continue
        if tok_T["auto"] == "정지" and hr30 > 0 and not st.get("stop"):
            excluded.append({"t": sym, "reason": f"현재 '정지'이나 T 시점 hr30={hr30:,.0f}>0, 중단일 미확인으로 복원 불가"})
            continue
        key = f"coingecko:{tok['cg']}"
        pT = (prices_T.get(key) or {}).get("price")
        pTH = (prices_TH.get(key) or {}).get("price")
        if not pT or not pTH:
            excluded.append({"t": sym, "reason": f"가격 없음 (T:{'있음' if pT else '없음'}, T+H:{'있음' if pTH else '없음'})"})
            continue
        # inc_qty30 이 있는 종목(NEAR, VVV)은 6-4절과 같이 수량 × T 시점 가격으로 배출액을 환산한다. 나머지는 현재 달러 고정값.
        if tok_T.get("inc_qty30") is not None:
            tok_T["inc30"] = round(tok_T["inc_qty30"] * pT / 1e6, 3)
            notes.append(f"inc30 {tok.get('inc30')}→{tok_T['inc30']} (inc_qty30 × T 시점 가격)")
        row = S.score_one(tok_T, pT, hr30, hr7, k_acc, k_auto, lumpy, bands)
        kprod = row["k"]["acc"] * row["k"]["auto"] * row["k"]["stab"] * row["k"]["dil"] * row["k"]["hist"]
        inc = tok_T.get("inc30")
        # 통계는 반올림하지 않은 값으로 낸다(반올림하면 가짜 동순위가 생긴다). 행에는 반올림한 값을 적는다.
        mc = pT * tok_T["circ"] / 1e6
        raw_x = (hr30 / 1e6) / mc * 100 * C.ANN
        net_x = ((hr30 / 1e6) - (inc if inc is not None else 0.0)) / mc * 100 * C.ANN
        adj_x = net_x if net_x < 0 else net_x * kprod
        adj1 = ((hr30 / 1e6) * kprod - (inc or 0.0)) / mc * 100 * C.ANN           # ①안
        g = (hr30 / (hr1y / C.ANN)) if hr1y and n1y >= 30 else None
        kg = k_growth_of(g)
        adj_g = adj_x * kg if net_x >= 0 else adj_x
        ret = pTH / pT - 1
        exc = (ret - btc_ret) if btc_ret is not None else None
        rows.append({
            "t": sym, "slug": tok["slug"], "acc": tok_T["acc"], "auto": tok_T["auto"],
            "price_T": pT, "price_TH": pTH,
            "price_T_ts": (prices_T.get(key) or {}).get("timestamp"), "price_TH_ts": (prices_TH.get(key) or {}).get("timestamp"),
            "mc_T": round(mc, 3),
            "hr30_T": round(hr30, 2), "hr7_T": round(hr7, 2), "hr1y_T": round(hr1y, 2), "n30": n30, "n1y": n1y,
            "rr_T": row["rr"], "raw_T": round(raw_x, 3), "net_T": round(net_x, 3), "adj_T": round(adj_x, 3), "grade_T": row["g"],
            "adj1_T": round(adj1, 3), "growth_T": (round(g, 3) if g is not None else None), "k_growth": kg,
            "adj_growth_T": round(adj_g, 3), "k": row["k"], "inc30_T": inc, "simple_T": round(hr30 / 1e6 / mc, 6),
            "return": round(ret, 4), "excess": (round(exc, 4) if exc is not None else None),
            "notes": notes,
            "_exact": {"adj_T": adj_x, "raw_T": raw_x, "net_T": net_x, "adj1_T": adj1, "adj_growth_T": adj_g,
                       "simple_T": hr30 / 1e6 / mc, "return": ret, "excess": exc},
        })
    rows.sort(key=lambda r: -r["_exact"]["adj_T"])
    return rows, excluded, warnings, btc_ret


def summarize(rows):
    def col(k):
        return [r["_exact"][k] for r in rows]
    stats = {
        "adj_vs_return": spearman(col("adj_T"), col("return")),
        "adj_vs_excess": spearman(col("adj_T"), col("excess")),
        "raw_vs_return": spearman(col("raw_T"), col("return")),
        "simple_vs_return": spearman(col("simple_T"), col("return")),
        "net_vs_return": spearman(col("net_T"), col("return")),
        "adj1_vs_return": spearman(col("adj1_T"), col("return")),
        "adj1_vs_excess": spearman(col("adj1_T"), col("excess")),
        "adj_growth_vs_return": spearman(col("adj_growth_T"), col("return")),
        "adj_growth_vs_excess": spearman(col("adj_growth_T"), col("excess")),
    }
    groups = {}
    for r in rows:
        groups.setdefault(r["grade_T"], []).append(r)
    order = ["S+", "S", "A", "B+", "B", "C", "D"]
    by_grade = []
    for gname in order:
        rs = groups.get(gname)
        if not rs:
            continue
        rets = [r["return"] for r in rs]
        exs = [r["excess"] for r in rs if r["excess"] is not None]
        by_grade.append({"grade": gname, "n": len(rs), "mean_return": round(statistics.mean(rets), 4),
                         "median_return": round(statistics.median(rets), 4),
                         "mean_excess": (round(statistics.mean(exs), 4) if exs else None),
                         "tokens": [r["t"] for r in rs]})
    return stats, by_grade


def run_one(universe, charts, chart_failures, T_str, H, cache_dir=None):
    T = C.parse_date(T_str)
    TH = T + dt.timedelta(days=H)
    today = C.parse_date(C.today_utc())
    if TH > today:
        C.warn(f"T+H={TH} 가 오늘 이후라 {today} 가격을 씁니다")
        TH = today
    keys = [f"coingecko:{t['cg']}" for t in universe["tokens"]] + [BTC_KEY]
    prices_T = fetch_historical_prices(keys, T)
    prices_TH = fetch_historical_prices(keys, TH)
    rows, excluded, warnings, btc_ret = reconstruct(universe, charts, prices_T, prices_TH, T, H, chart_failures)
    stats, by_grade = summarize(rows)
    inc_syms = [r["t"] for r in rows if r["inc30_T"] is not None]
    for r in rows:
        r.pop("_exact", None)
    result = {
        "T": T_str, "H": H, "T_plus_H": TH.isoformat(), "generated": C.now_utc_iso(),
        "btc_return": (round(btc_ret, 4) if btc_ret is not None else None),
        "assumptions": [
            "hr30_T·hr7_T·hr1y_T 는 totalDataChart 에서 기준일 T 를 제외한 직전 30·7·365일 합계(DefiLlama total30d 창 정의와 동일)",
            "mc_T = price_T × 현재 유통량(circ). 유통량은 T 시점 값이 아니라 현재 값이므로 근사",
            "fdv·acc·auto·hist_k 는 현재 universe.json 값. STRUCTURE 표의 종목만 T 시점 기준으로 되돌리거나 제외",
            f"inc30 은 현재 값(달러 고정)이라 T 시점과 다르다(inc_qty30 이 있는 NEAR·VVV 만 수량 × T 시점 가격으로 환산). 배출액이 있는 {len(inc_syms)}종목({', '.join(inc_syms)})의 net_T·adj_T·adj1_T 는 근사",
            "①안 adj1_T = (hr30_T/1e6 × 계수곱 − inc30) ÷ mc_T × 100 × ANN. ②안(현행) adj_T 는 net<0 이면 계수 미적용",
            "raw_T 와 hr30_T/mc_T 단순비율은 서로 단조 변환이므로 순위상관이 같다. 순위상관은 반올림하지 않은 값으로 계산한다",
            "p값은 scipy 가 없으면 고정 시드 순열검정 1,000회",
        ],
        "rows": rows, "excluded": excluded, "warnings": warnings, "stats": stats, "by_grade": by_grade,
    }
    return result


def fmt_pct(x):
    return "n/a" if x is None else f"{x:+.1%}"


def fmt_rho(s):
    if not s or s.get("rho") is None:
        return "n/a"
    return f"{s['rho']:+.3f} (p={s['p']}, n={s['n']})"


def print_result(res):
    C.log(f"=== 백테스트 T={res['T']} H={res['H']}일 (T+H={res['T_plus_H']}) BTC 수익률 {fmt_pct(res['btc_return'])}")
    C.log(f"{'종목':7}{'등급':>4}{'adj_T':>8}{'net_T':>8}{'raw_T':>8}{'①adj1':>8}{'g_T':>6}{'수익률':>9}{'초과':>9}  비고")
    for r in res["rows"]:
        g = "-" if r["growth_T"] is None else f"{r['growth_T']:.2f}"
        ex = "-" if r["excess"] is None else f"{r['excess']:+.1%}"
        C.log(f"{r['t']:7}{r['grade_T']:>4}{r['adj_T']:>8.2f}{r['net_T']:>8.2f}{r['raw_T']:>8.2f}{r['adj1_T']:>8.2f}{g:>6}"
              f"{fmt_pct(r['return']):>9}{ex:>9}  {'; '.join(r['notes'])}")
    st = res["stats"]
    C.log("스피어만 ρ:")
    for k, label in [("adj_vs_return", "adj_T ~ 수익률"), ("adj_vs_excess", "adj_T ~ 초과수익"),
                     ("raw_vs_return", "기준선 raw_T ~ 수익률"), ("simple_vs_return", "기준선 hr30/mc ~ 수익률"),
                     ("net_vs_return", "기준선 net_T ~ 수익률"), ("adj1_vs_return", "①안 adj1_T ~ 수익률"),
                     ("adj1_vs_excess", "①안 adj1_T ~ 초과수익"), ("adj_growth_vs_return", "성장계수 adj×k_g ~ 수익률"),
                     ("adj_growth_vs_excess", "성장계수 adj×k_g ~ 초과수익")]:
        C.log(f"  {label:26} {fmt_rho(st[k])}")
    C.log("등급 그룹별 수익률:")
    for g in res["by_grade"]:
        C.log(f"  {g['grade']:3} n={g['n']:2} 평균 {fmt_pct(g['mean_return'])} 중앙값 {fmt_pct(g['median_return'])} "
              f"초과(평균) {fmt_pct(g['mean_excess'])}  {', '.join(g['tokens'])}")
    if res["excluded"]:
        C.log("제외:")
        for e in res["excluded"]:
            C.log(f"  {e['t']:7} {e['reason']}")
    if res["warnings"]:
        C.log("경고: " + "; ".join(res["warnings"]))


def write_summary(results, path):
    lines = ["# 백테스트 요약", "",
             f"생성 {C.now_utc_iso()} · `scripts/backtest.py --all` · H={results[0]['H']}일", "",
             "스피어만 순위상관 ρ (p값, 표본 수). 양수이면 등급이 높을수록 이후 수익률이 높았다는 뜻이다.", "",
             "| T | 표본 | BTC | adj_T~수익률 | adj_T~초과 | raw_T~수익률 | net_T~수익률 | ①안 adj1~수익률 | 성장계수 adj×k_g~수익률 |",
             "|---|---|---|---|---|---|---|---|---|"]
    wins_growth = wins_adj_over_raw = wins_adj1 = 0
    for r in results:
        st = r["stats"]
        n = st["adj_vs_return"]["n"]
        lines.append(f"| {r['T']} | {n} | {fmt_pct(r['btc_return'])} | {fmt_rho(st['adj_vs_return'])} | {fmt_rho(st['adj_vs_excess'])} | "
                     f"{fmt_rho(st['raw_vs_return'])} | {fmt_rho(st['net_vs_return'])} | {fmt_rho(st['adj1_vs_return'])} | "
                     f"{fmt_rho(st['adj_growth_vs_return'])} |")
        a, g, rw, a1 = (st["adj_vs_return"]["rho"], st["adj_growth_vs_return"]["rho"],
                        st["raw_vs_return"]["rho"], st["adj1_vs_return"]["rho"])
        if a is not None and g is not None and g > a:
            wins_growth += 1
        if a is not None and rw is not None and a > rw:
            wins_adj_over_raw += 1
        if a is not None and a1 is not None and a1 > a:
            wins_adj1 += 1
    k = len(results)
    lines += ["", "## 판정", "",
              f"- 성장 계수(13장): ρ(adj×k_growth) 가 ρ(adj) 보다 높은 T 는 {k}곳 중 {wins_growth}곳. "
              f"채택 기준은 네 곳 이상이므로 **{'채택' if wins_growth >= 4 else '채택하지 않음'}**.",
              f"- 다섯 계수의 기여: ρ(adj) 가 기준선 ρ(raw) 보다 높은 T 는 {k}곳 중 {wins_adj_over_raw}곳.",
              f"- 음수 처리 ①안(15장 보류 과제): ρ(adj1) 가 현행 ②안 ρ(adj) 보다 높은 T 는 {k}곳 중 {wins_adj1}곳.",
              "", "## 등급 그룹별 평균 수익률", ""]
    for r in results:
        lines.append(f"### T={r['T']} (T+H={r['T_plus_H']}, BTC {fmt_pct(r['btc_return'])})")
        lines.append("")
        lines.append("| 등급 | n | 평균 | 중앙값 | 초과(평균) | 종목 |")
        lines.append("|---|---|---|---|---|---|")
        for g in r["by_grade"]:
            lines.append(f"| {g['grade']} | {g['n']} | {fmt_pct(g['mean_return'])} | {fmt_pct(g['median_return'])} | {fmt_pct(g['mean_excess'])} | {', '.join(g['tokens'])} |")
        if r["excluded"]:
            lines.append("")
            lines.append("제외: " + "; ".join(f"{e['t']}({e['reason']})" for e in r["excluded"]))
        lines.append("")
    lines += ["## 가정", ""] + [f"- {a}" for a in results[0]["assumptions"]] + [""]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    C.log(f"[backtest] 요약 저장: {os.path.relpath(path, C.REPO_ROOT)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="토큰캡처 백테스트")
    ap.add_argument("--T", default=None, help="기준 시점 YYYY-MM-DD")
    ap.add_argument("--H", type=int, default=90, help="전방 구간(일). 기본 90")
    ap.add_argument("--all", action="store_true", help=f"T = {', '.join(DEFAULT_TS)} 를 모두 돌리고 summary.md 를 쓴다")
    ap.add_argument("--out", default=None, help="결과 JSON 경로. 기본 data/backtest/<T>.json")
    ap.add_argument("--universe", default=C.UNIVERSE_PATH)
    ap.add_argument("--cache", default=None, help="차트 캐시 디렉터리(선택, 저장소 밖)")
    a = ap.parse_args(argv)
    if not a.T and not a.all:
        ap.error("--T 또는 --all 이 필요합니다")
    universe = C.load_universe(a.universe)
    Ts = DEFAULT_TS if a.all else [a.T]
    C.log(f"[backtest] 차트 수집 {len(universe['tokens'])}종목 …")
    charts, chart_failures = fetch_all_charts(universe["tokens"], a.cache)
    if chart_failures:
        C.warn("차트 수집 실패:", chart_failures)
    results = []
    for T in Ts:
        res = run_one(universe, charts, chart_failures, T, a.H, a.cache)
        out = a.out if (a.out and not a.all) else os.path.join(C.BACKTEST_DIR, f"{T}.json")
        C.dump_json(res, out, indent=1)
        print_result(res)
        C.log(f"[backtest] 저장: {os.path.relpath(out, C.REPO_ROOT)}")
        results.append(res)
    if a.all:
        write_summary(results, os.path.join(C.BACKTEST_DIR, "summary.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
