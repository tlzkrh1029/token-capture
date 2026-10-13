# -*- coding: utf-8 -*-
"""
fetch.py : 주간 수집. 귀속액(Holders Revenue)과 가격을 받아 data/raw/YYYY-MM-DD.json 에 그대로 보존한다.
(HANDOVER.md 6장·9-1절, HANDOVER-ADDENDUM.md 1절)

  python scripts/fetch.py [--date YYYY-MM-DD] [--universe data/universe.json] [--out data/raw/<date>.json]

수집 규칙
  귀속액  api.llama.fi/summary/fees/<slug>?dataType=dailyHoldersRevenue
          &excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true   (주간 수집은 반드시 두 파라미터를 붙인다)
          동시 8개, 실패 시 1·2·4초 백오프로 3회 재시도. 스칼라 필드만 추출한다.
          total30d 가 null 이면(응답은 200) 수집 실패로 센다. 추정값으로 메우지 않는다.
  가격    1) coins.llama.fi/prices/current/coingecko:<cg>  (25개씩 묶음)
          2) 1)에서 빠진 id → coins.llama.fi 에 DefiLlama 응답의 토큰 컨트랙트 주소(<chain>:<address>)로 다시 조회
             (접두사 없는 0x 주소는 ethereum, base58 주소는 solana 로 보고, chains 의 체인도 후보로 같이 보낸다)
          3) 그래도 없으면 CoinGecko simple/price 에 같은 id 로 조회 (환경변수 COINGECKO_API_KEY 가 있으면 데모 키 헤더로 보냄)
          모든 출처에서 실패한 종목은 null 로 두고 failures 에 남긴다. 직전 가격으로 대체하는 일은 score.py 가 한다.
  매출    같은 주소에 dataType=dailyRevenue, dailyFees 로 프로토콜 수익과 총수수료 스칼라도 받는다(귀속률 = 귀속액 ÷ 수익).
          보조 지표이므로 실패해도 종료 조건에는 넣지 않는다.
종료 조건
  hr30 수집 실패가 전체의 10%를 넘거나 가격 실패가 3개를 넘으면 raw 파일을 쓴 뒤 exit 1 로 끝낸다.
"""
import argparse
import concurrent.futures as cf
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

HR_FAIL_RATIO = 0.10
PRICE_FAIL_MAX = 3

# DefiLlama 응답의 chains 이름 → coins.llama.fi 체인 키. 컨트랙트 주소 조회(2단계)에 쓴다.
CHAIN_KEYS = {
    "ethereum": "ethereum", "solana": "solana", "base": "base", "arbitrum": "arbitrum",
    "bsc": "bsc", "binance": "bsc", "polygon": "polygon", "optimism": "optimism", "avalanche": "avax",
    "sui": "sui", "near": "near", "tron": "tron", "sonic": "sonic", "hyperliquid l1": "hyperliquid",
    "cronos": "cronos", "linea": "linea", "scroll": "scroll", "blast": "blast", "mantle": "mantle",
}


def fetch_hr_one(tok):
    url = C.LLAMA_FEES_SCALAR.format(slug=urllib.parse.quote(tok["slug"], safe=""))
    d = C.http_get_json(url)
    out = {k: d.get(k) for k in C.HR_SCALAR_FIELDS}
    out["slug"] = tok["slug"]
    out["name"] = d.get("name")
    out["gecko_id"] = d.get("gecko_id")
    out["address"] = d.get("address")
    out["chains"] = d.get("chains")
    return out


def fetch_hr(tokens):
    hr, failures = {}, []
    with cf.ThreadPoolExecutor(max_workers=C.HR_CONCURRENCY) as ex:
        futs = {ex.submit(fetch_hr_one, t): t for t in tokens}
        for fut in cf.as_completed(futs):
            t = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # HttpError 포함
                failures.append({"t": t["t"], "kind": "hr", "slug": t["slug"], "reason": str(e)})
                continue
            hr[t["t"]] = r
            if r.get("total30d") is None:
                failures.append({"t": t["t"], "kind": "hr", "slug": t["slug"],
                                 "reason": "total30d null (응답 200, 최근 30일 기록 없음 또는 어댑터 정지)"})
    return hr, failures


def fetch_scalar_one(tok, data_type):
    """같은 slug 의 다른 dataType(dailyRevenue, dailyFees) 스칼라를 받는다. 귀속률(holders ÷ revenue) 계산용."""
    url = C.LLAMA_FEES_SCALAR.replace("dataType=dailyHoldersRevenue", "dataType=" + data_type) \
        .format(slug=urllib.parse.quote(tok["slug"], safe=""))
    d = C.http_get_json(url)
    return {k: d.get(k) for k in ("total24h", "total7d", "total30d", "total1y")}


def fetch_scalars(tokens, data_type, kind):
    """dailyRevenue / dailyFees 를 종목마다 받는다. 실패해도 주간 실행을 멈추지 않는다(귀속률은 보조 지표)."""
    out, failures = {}, []
    with cf.ThreadPoolExecutor(max_workers=C.HR_CONCURRENCY) as ex:
        futs = {ex.submit(fetch_scalar_one, t, data_type): t for t in tokens}
        for fut in cf.as_completed(futs):
            t = futs[fut]
            try:
                out[t["t"]] = fut.result()
            except Exception as e:
                out[t["t"]] = None
                failures.append({"t": t["t"], "kind": kind, "slug": t["slug"], "reason": str(e)})
    return out, failures


def _llama_prices(keys, batch_failures=None):
    """
    coins.llama.fi/prices/current 를 25개씩 호출해 {key: {price, timestamp, confidence}} 로 돌려준다.
    한 묶음이 실패해도 나머지 묶음의 결과는 버리지 않는다. 실패한 묶음은 batch_failures 에 남긴다.
    """
    got = {}
    for batch in C.batched(keys, C.PRICE_BATCH):
        url = C.LLAMA_PRICE_CURRENT.format(keys=",".join(batch))
        try:
            d = C.http_get_json(url)
        except Exception as e:
            C.warn(f"coins.llama.fi 묶음 실패({len(batch)}개):", e)
            if batch_failures is not None:
                batch_failures.append({"kind": "price_batch", "keys": list(batch), "reason": str(e)})
            continue
        got.update(d.get("coins", {}))
    return got


def _address_keys(hr_row):
    """
    DefiLlama 응답의 address/chains 로 coins.llama.fi 조회 키(<chain>:<address>) 후보 목록을 만든다.
    DefiLlama 관례: 접두사가 있는 주소('base:0x…')는 그대로, 접두사 없는 0x 주소는 이더리움 메인넷,
    접두사 없는 base58 주소는 Solana 다. 그 뒤에 chains 에 적힌 체인으로 만든 키도 후보로 붙인다.
    """
    if not hr_row:
        return []
    addr = hr_row.get("address")
    if not addr or not isinstance(addr, str):
        return []
    keys = []
    if ":" in addr:
        keys.append(addr)
    elif addr.startswith("0x"):
        keys.append(f"ethereum:{addr}")
    else:
        keys.append(f"solana:{addr}")
    bare = addr.split(":", 1)[1] if ":" in addr else addr
    for ch in hr_row.get("chains") or []:
        key = CHAIN_KEYS.get(str(ch).lower())
        if key and f"{key}:{bare}" not in keys:
            keys.append(f"{key}:{bare}")
    return keys


def _coingecko_prices(ids):
    """CoinGecko simple/price. 키 없이 호출하되 COINGECKO_API_KEY 가 있으면 데모 키 헤더를 붙인다. 429 는 5·10·20초 백오프."""
    headers = {}
    key = os.environ.get("COINGECKO_API_KEY", "").strip()
    if key:
        headers["x-cg-demo-api-key"] = key
    got = {}
    for batch in C.batched(ids, 50):
        url = C.COINGECKO_SIMPLE_PRICE.format(ids=",".join(batch))
        d = C.http_get_json(url, retries=3, headers=headers, backoff=(5, 10, 20))
        for cid, v in (d or {}).items():
            if isinstance(v, dict) and v.get("usd") is not None:
                got[cid] = float(v["usd"])
    return got


def fetch_prices(tokens, hr):
    price, price_meta, failures = {}, {}, []
    # 1) coins.llama.fi, coingecko:<cg>
    keys = {f"coingecko:{t['cg']}": t for t in tokens}
    got = _llama_prices(list(keys), failures)
    for k, t in keys.items():
        c = got.get(k)
        if c and c.get("price") is not None:
            price[t["t"]] = float(c["price"])
            price_meta[t["t"]] = {"source": "llama:coingecko", "key": k,
                                  "timestamp": c.get("timestamp"), "confidence": c.get("confidence")}
    # 2) 빠진 종목은 컨트랙트 주소로 coins.llama.fi 재조회 (후보 키 여러 개를 한 번에 보내고 응답에 있는 것을 쓴다)
    missing = [t for t in tokens if t["t"] not in price]
    addr_keys = {}
    for t in missing:
        for k in _address_keys(hr.get(t["t"])):
            addr_keys.setdefault(k, t)
    if addr_keys:
        got = _llama_prices(list(addr_keys), failures)
        for k, t in addr_keys.items():
            c = got.get(k)
            if t["t"] in price or not c or c.get("price") is None:
                continue
            price[t["t"]] = float(c["price"])
            price_meta[t["t"]] = {"source": "llama:address", "key": k,
                                  "timestamp": c.get("timestamp"), "confidence": c.get("confidence")}
    # 3) 그래도 없으면 CoinGecko 에 같은 id 로
    missing = [t for t in tokens if t["t"] not in price]
    if missing:
        try:
            got = _coingecko_prices([t["cg"] for t in missing])
        except Exception as e:
            C.warn("CoinGecko 3단계 실패:", e)
            got = {}
        for t in missing:
            if t["cg"] in got:
                price[t["t"]] = got[t["cg"]]
                price_meta[t["t"]] = {"source": "coingecko", "key": t["cg"], "timestamp": int(time.time())}
    for t in tokens:
        if t["t"] not in price:
            price[t["t"]] = None
            failures.append({"t": t["t"], "kind": "price", "cg": t["cg"],
                             "reason": "coins.llama.fi(coingecko id·컨트랙트 주소)와 CoinGecko 모두 가격 없음"})
    return price, price_meta, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description="토큰캡처 주간 수집")
    ap.add_argument("--date", default=None, help="스냅샷 날짜(UTC). 기본은 오늘")
    ap.add_argument("--universe", default=C.UNIVERSE_PATH)
    ap.add_argument("--out", default=None, help="기본 data/raw/<date>.json")
    a = ap.parse_args(argv)
    date = a.date or C.today_utc()
    out = a.out or os.path.join(C.RAW_DIR, f"{date}.json")

    universe = C.load_universe(a.universe)
    tokens = universe["tokens"]
    C.log(f"[fetch] {date} 종목 {len(tokens)}개")

    hr, hr_fail = fetch_hr(tokens)
    rev, rev_fail = fetch_scalars(tokens, "dailyRevenue", "rev")
    fees, fees_fail = fetch_scalars(tokens, "dailyFees", "fees")
    price, price_meta, price_fail = fetch_prices(tokens, hr)
    failures = hr_fail + price_fail + rev_fail + fees_fail

    raw = {
        "date": date,
        "fetched_at": C.now_utc_iso(),
        "universe_updated": universe.get("updated"),
        "count": len(tokens),
        "hr": {t["t"]: hr.get(t["t"]) for t in tokens},
        "rev": rev,
        "fees": fees,
        "price": price,
        "price_meta": price_meta,
        "failures": failures,
    }
    C.dump_json(raw, out, indent=1)

    hr_ok = sum(1 for t in tokens if hr.get(t["t"]) and hr[t["t"]].get("total30d") is not None)
    price_ok = sum(1 for t in tokens if price.get(t["t"]) is not None)
    rev_ok = sum(1 for t in tokens if rev.get(t["t"]) and rev[t["t"]].get("total30d") is not None)
    C.log(f"[fetch] 귀속액 성공 {hr_ok}/{len(tokens)}, 가격 성공 {price_ok}/{len(tokens)}, 매출(보조) {rev_ok}/{len(tokens)}")
    by_src = {}
    for t in tokens:
        m = price_meta.get(t["t"])
        if m:
            by_src.setdefault(m["source"], []).append(t["t"])
    for src, syms in by_src.items():
        if src != "llama:coingecko":
            C.log(f"[fetch] 가격 출처 {src}: {', '.join(syms)}")
    for f in failures:
        C.log(f"[fetch] 실패 {f['kind']:5} {f['t']:6} {f['reason']}")
    C.log(f"[fetch] 저장: {out}")

    n_hr_fail = len(tokens) - hr_ok
    n_price_fail = len(tokens) - price_ok
    if n_hr_fail > HR_FAIL_RATIO * len(tokens):
        C.log(f"[fetch] 귀속액 실패 {n_hr_fail}개가 {HR_FAIL_RATIO:.0%} 를 넘어 실패로 끝냅니다")
        return 1
    if n_price_fail > PRICE_FAIL_MAX:
        C.log(f"[fetch] 가격 실패 {n_price_fail}개가 {PRICE_FAIL_MAX}개를 넘어 실패로 끝냅니다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
