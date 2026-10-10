# -*- coding: utf-8 -*-
"""
common.py : 토큰캡처 파이프라인의 공용 모듈

HTTP 재시도, 날짜, 경로, 산출식 상수를 모아 둔다. 외부 패키지를 쓰지 않는다.
(HANDOVER.md 9-4절)
"""
import datetime as dt
import glob
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")
BACKTEST_DIR = os.path.join(DATA_DIR, "backtest")
UNIVERSE_PATH = os.path.join(DATA_DIR, "universe.json")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.csv")

# ---------------------------------------------------------------------------
# 산출식 상수 (HANDOVER.md 7장). universe.json 의 formula 가 있으면 그것을 우선한다.
# ---------------------------------------------------------------------------
ANN = 365 / 30                                   # 30일 값을 연환산하는 계수 = 12.1667
BANDS = [(12, "S+"), (8, "S"), (5, "A"), (3, "B+"), (1.5, "B"), (0.4, "C")]   # 미만이면 D
K_ACC = {"순수 수수료 소각": 1.00, "매수 후 소각": 1.00, "매수 후 분배": 1.00,
         "직접 수수료 분배": 1.00, "매수 후 소각·분배": 1.00, "매수 후 보유": 0.35}
K_AUTO = {"코드 자동": 1.00, "정기 집행": 0.90, "불규칙": 0.65, "정지": 0.00}

# ---------------------------------------------------------------------------
# 데이터 소스 (HANDOVER.md 6장)
# ---------------------------------------------------------------------------
LLAMA_FEES = "https://api.llama.fi/summary/fees/{slug}?dataType=dailyHoldersRevenue"
LLAMA_FEES_SCALAR = LLAMA_FEES + "&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
LLAMA_PRICE_CURRENT = "https://coins.llama.fi/prices/current/{keys}"
LLAMA_PRICE_HISTORICAL = "https://coins.llama.fi/prices/historical/{ts}/{keys}"
COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
USER_AGENT = "token-capture (https://github.com/tlzkrh1029/token-capture)"
PRICE_BATCH = 25          # coins.llama.fi 한 번에 묶는 id 수 (6-2절)
HR_CONCURRENCY = 8        # api.llama.fi 동시 요청 수 (6-6절)
HR_SCALAR_FIELDS = ["total24h", "total48hto24h", "total7d", "total30d",
                    "total1y", "annualized1y", "totalAllTime"]


class HttpError(Exception):
    def __init__(self, url, status=None, reason=""):
        super().__init__(f"{status} {reason} <{url}>")
        self.url, self.status, self.reason = url, status, reason


def http_get_json(url, retries=3, timeout=60, headers=None, backoff=(1, 2, 4)):
    """
    GET 요청을 보내 JSON 을 돌려준다. 실패하면 backoff 초 만큼 쉬고 retries 번까지 다시 시도한다.
    기본 backoff 는 1·2·4초다(HANDOVER.md 9-1절). 429 처럼 요율 제한이면 Retry-After 를 존중한다.
    모든 시도가 실패하면 HttpError 를 던진다.
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except urllib.error.HTTPError as e:
            wait = None
            if e.code == 429:
                ra = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = float(ra) if ra else None
                except ValueError:
                    wait = None
            last = HttpError(url, e.code, e.reason)
            if 400 <= e.code < 500 and e.code not in (408, 425, 429):
                raise last                       # 404 등은 다시 시도해도 같다
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as e:
            wait = None
            last = HttpError(url, None, repr(e))
        if attempt < retries:
            delay = backoff[min(attempt, len(backoff) - 1)]
            if wait:
                delay = max(delay, min(wait, 60))
            time.sleep(delay)
    raise last


def today_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def now_utc_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_date(s):
    return dt.date.fromisoformat(s)


def to_unix(d):
    """date 또는 'YYYY-MM-DD' 를 UTC 자정 unix 초로 바꾼다."""
    if isinstance(d, str):
        d = parse_date(d)
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def from_unix(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()


def batched(iterable, n):
    """iterable 을 n 개씩 묶어 리스트로 돌려준다."""
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(obj, path, indent=None):
    """ensure_ascii=False 로 쓴다. indent 가 None 이면 한 줄 압축형(스냅샷)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if indent is None:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, fh, ensure_ascii=False, indent=indent)
            fh.write("\n")


def load_universe(path=UNIVERSE_PATH):
    return load_json(path)


# 동봉 universe.json(2026-10-09) 을 그대로 둔 고정본. score.py 가 매주 data/universe.json 의 inc30 을 다시 쓰므로
# 참조 검증(score_reference.py --selftest), 단위 테스트, 시드 재생성은 이 고정본을 기준으로 한다.
UNIVERSE_FIXTURE_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "universe-2026-10-09.json")


def save_universe(universe, path=UNIVERSE_PATH):
    # 동봉 universe.json 과 같은 indent=1 형식으로 쓴다.
    dump_json(universe, path, indent=1)


def formula_constants(universe):
    """universe.formula 에서 k_acc, k_auto, lumpy, bands 를 꺼낸다. 없으면 기본값."""
    f = universe.get("formula", {})
    k_acc = f.get("k_acc", K_ACC)
    k_auto = f.get("k_auto", K_AUTO)
    lumpy = set(f.get("lumpy", []))
    bands = [(float(th), g) for th, g in f.get("bands", BANDS)]
    return k_acc, k_auto, lumpy, bands


def list_snapshots(snapshot_dir=SNAPSHOT_DIR):
    """data/snapshots 의 (date, path) 를 날짜 오름차순으로 돌려준다."""
    out = []
    for p in glob.glob(os.path.join(snapshot_dir, "????-??-??.json")):
        out.append((os.path.basename(p)[:-5], p))
    out.sort()
    return out


def previous_snapshot(before_date, snapshot_dir=SNAPSHOT_DIR):
    """before_date 보다 앞선 가장 최근 스냅샷을 (date, dict) 로 돌려준다. 없으면 (None, None)."""
    cands = [(d, p) for d, p in list_snapshots(snapshot_dir) if d < before_date]
    if not cands:
        return None, None
    d, p = cands[-1]
    return d, load_json(p)


def log(*args):
    print(*args, file=sys.stdout, flush=True)


def warn(*args):
    print("WARN:", *args, file=sys.stderr, flush=True)
