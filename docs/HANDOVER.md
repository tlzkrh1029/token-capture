# 토큰캡처 정밀조사 파이프라인 · Claude Code 인계 문서

작성일 2026-10-09 · 작성 주체: Cowork 세션(claude.ai) · 인수 주체: Claude Code

> **2026-10-10 보완:** 같은 폴더의 `HANDOVER-ADDENDUM.md`를 이 문서와 함께 읽으십시오. 두 문서의 내용이 다르면 보완 문서를 따릅니다.

---

## 0. 이 문서를 읽는 법

이 문서는 **아무 맥락이 없는 상태에서 시작하는 Claude Code**를 위해 썼습니다. 이전 대화, 프로젝트 문서, 아티팩트 저장소에 흩어져 있던 것을 전부 한 곳에 모았으므로, 이 문서 하나와 동봉한 `universe.json`만 있으면 작업을 시작할 수 있습니다.

읽는 순서는 다음과 같습니다.

1. **1장**에서 목표와 완료 기준을 확인합니다.
2. **4장**에서 지난 설계가 왜 실패했는지 읽습니다. 같은 실수를 반복하지 않기 위한 금지 목록이 여기 있습니다.
3. **6장과 7장**은 데이터 소스와 채점식의 정밀 명세입니다. 코드를 쓸 때 이 두 장을 기준으로 삼습니다.
4. **9장과 10장**이 실제로 만들 것입니다.
5. **14장**의 검증 절차를 통과해야 완료입니다.

동봉 파일: `universe.json` (추적 대상 46종목의 정의와 산출식 상수, 저장소에 그대로 넣습니다), `score_reference.py` (채점 로직의 참조 구현. `python score_reference.py --selftest`를 실행하면 2026-09-17과 2026-09-19 두 회차의 실측 입력 84행을 다시 계산해 아티팩트 저장소에 저장된 값과 전부 일치하는지 확인합니다. 새로 짠 `score.py`는 이 파일과 같은 결과를 내야 합니다).

**인계 직전에 발견한 불일치 한 가지를 먼저 밝혀 둡니다.** 2026-09-17 오후에 다른 세션에서 적용한 두 가지 변경(NEAR 항목 재정의와 "순 캡처율이 음수이면 계수를 곱하지 않는다"는 규칙)이, 같은 날 밤 이 세션이 46종목판 `meta/universe`를 version 4로 쓰면서 덮어써졌습니다. 그 결과 저장소의 `meta/universe`에는 NEAR가 옛 정의(slug `near`)로 들어 있고 `formula.neg` 항목이 없습니다. 동봉한 `universe.json`은 두 변경을 다시 합친 판이며, 이것이 기준입니다(3-2절, 7-1절, 8장).

---

## 1. 목표와 완료 기준

### 목표

**크립토 종목별 토큰캡처(token capture)에 관한 정밀조사를 사람 개입 없이 매주 수행하는 파이프라인을 만듭니다.** 토큰캡처란 프로토콜이 번 돈이 토큰 보유자에게 실제로 얼마나 귀속되는지를 뜻합니다. "프로토콜이 돈을 번다"와 "그 토큰이 돈을 가져간다"는 다른 명제이고, 이 조사는 후자만 측정합니다.

### 완료 기준

다음 다섯 가지가 모두 충족되어야 완료입니다.

1. GitHub Actions 워크플로가 **매주 토요일** 자동으로 돌아 46개(이상) 종목의 수치를 수집하고 채점한 뒤 `data/snapshots/YYYY-MM-DD.json`과 `data/latest.json`을 저장소에 커밋합니다. 이 과정에서 **Claude 사용량은 0**입니다.
2. 수집 실패가 전체의 10%를 넘으면 워크플로가 **실패 상태로 끝나** GitHub가 이메일 알림을 보냅니다. 조용히 틀린 값을 쌓지 않습니다.
3. `backtest.py`가 과거 시점 T의 등급을 재구성하고 T 이후 90일 수익률과의 **스피어만 순위상관**을 출력합니다. 이것이 모델의 예측력을 판정하는 장치입니다.
4. claude.ai 아티팩트 `토큰캡처 등급표`의 저장소에 새 스냅샷이 매주 들어가, 표와 종목별 추이 차트가 갱신됩니다. 이 단계만 Claude가 담당하되, 하는 일은 "파일 하나 읽어서 저장소에 넣기"로 제한합니다.
5. 첫 실행을 **수동으로 돌려** 46개 행이 나오고, 2026-09-19 스냅샷의 값과 같은 자릿수에서 일치하는 것을 확인합니다(14장).

### 하지 않는 것

- 매수·매도 판단이나 투자 권유를 만들지 않습니다. 이 파이프라인은 캡처 지표만 측정합니다.
- 격주 신규 종목 발굴은 판단이 필요한 일이라 스크립트화하지 않습니다. 그 절차는 11장에 적어 두었고 Claude가 계속 맡습니다.

---

## 2. 배경: 왜 이런 모델인가

이 모델은 2026-09-15에 검토한 원문 정리본의 결함을 고치면서 만들어졌습니다. 원문은 등급 부여 기준이 문서 안에 없었고, 소각형·매입형·분배형을 한 축에 뒤섞었으며, 배출(신규 발행)을 차감하지 않았고, 렌더링된 페이지의 판독값을 썼습니다(AERO 7일 귀속액을 $9.2M으로 적었으나 API 실측은 $1.65M, CAKE와 DEEP은 런레이트의 방향이 뒤집혀 있었습니다. NEAR의 $1.1M은 나중에 판독 오류가 아니라 슬러그 혼동으로 밝혀졌으므로 8장을 보십시오).

그래서 다음 원칙으로 다시 만들었습니다.

- **모든 수치는 `api.llama.fi`와 `coins.llama.fi`의 JSON에서만** 가져옵니다. 렌더링된 웹페이지 판독값은 쓰지 않습니다.
- **배출을 먼저 차감**합니다. 소각보다 발행이 많으면 순 캡처율이 음수가 되어야 합니다. 실제로 CC(Canton), VELO, CRV, ETH, SOL, VVV, NEAR가 음수입니다. 음수에는 할인 계수를 곱하지 않습니다(7-1절).
- **귀속 실질성을 구분**합니다. 매입한 토큰이 DAO나 회사 트레저리에 남으면(RAY, MPLX, SPK, LINK, DBR, DYDX, ZRO, BONK, AAVE) 홀더가 받은 게 아니므로 계수 0.35를 곱합니다.
- **집행 자동성과 이력을 할인**합니다. 사람 결정이 끼어들수록, 시작한 지 얼마 안 됐을수록 깎습니다.

2026-09-17에 수행한 내러티브 검증(`claude/토큰캡처-내러티브-검증-2026-09-17.md`)의 결론은 다음과 같습니다. 바이백 테마는 "buyback meta"라는 이름으로 실재하지만, 단순히 "바이백을 한다"는 조건만으로는 Messari·CryptoRank·Tokenomist 세 곳의 연구가 모두 초과수익을 찾지 못했습니다. 남은 우위는 배출 차감 후 순 귀속률과 집행 자동성으로 거르는 데 있고, 그것이 이 모델의 구조입니다. 다만 **UNI는 소각이 열 배 커진 뒤에 가격이 회복되었고 HYPE는 매출이 43% 줄어드는 동안 가격이 올랐으므로**, 매출 성장률이라는 축이 빠져 있다는 점이 가장 큰 미검증 과제입니다(13장).

---

## 3. 지금까지 만들어진 것

### 3-1. 아티팩트

- URL: `https://claude.ai/artifact/YQg1tsjpAD2WnYjTpxsxfQ`
- 제목: 토큰캡처 등급표
- 내용: 정렬·필터 되는 46종목 표, 각 행을 펼치면 계산 경로와 다섯 계수와 네 가지 추이 차트(조정·원시 캡처율, 귀속액·시총 지수, 7일÷30일 런레이트비, 등급 변동 이력)가 나옵니다.
- 페이지는 `boot.js`에 박힌 부트스트랩 스냅샷으로 먼저 그려진 뒤, 런타임 `db` 기능으로 저장소의 `snapshots` 컬렉션을 읽어 이력을 덧입힙니다. 이 페이지는 **외부 주소를 직접 읽을 수 없습니다**(아티팩트 CSP가 외부 fetch를 막습니다). 그래서 GitHub의 결과를 저장소에 넣어 주는 단계가 필요합니다(11장).

### 3-2. 아티팩트 저장소(db) 현재 상태

| 컬렉션/문서 | 내용 | 현재 |
|---|---|---|
| `snapshots/<YYYY-MM-DD>` | 그 주의 전 종목 채점 결과 `{date, rows[]}` | `2026-09-17`(38행, version 3), `2026-09-19`(46행) 두 건 |
| `meta/universe` | 추적 대상 정의와 산출식 상수 | **version 4, 46종목. 아래 불일치 참조** |
| `meta/state` | 루프 상태 `{lastWeekly, lastResearch, nextResearch, researchCount}` | `lastWeekly=2026-09-19`, `nextResearch=2026-10-03` |

문서 하나의 상한은 256KiB, 아티팩트당 5,000문서입니다. 스냅샷 하나가 약 30KB이므로 주 1회 기준 문제없습니다.

**`meta/universe` version 4의 불일치.** 이 문서의 변경 이력은 다음과 같습니다.

| version | 시각(UTC) | 변경 | 주체 |
|---|---|---|---|
| 1 | 2026-09-17 03:56 무렵 | 38종목 최초 작성 | 이 세션 |
| 2 | 2026-09-17 12:13 이전 | NEAR 재정의: slug `near`→`near-intents`, 귀속 방식 "순수 수수료 소각"→"매수 후 보유", 집행 "코드 자동"→"정기 집행", 이력 1.00→0.85, `inc30` 7.14 추가, `circ` 1,306,540,000 | 별도 세션(NEAR 강세 분석, `claude/NEAR-강세-원인-2026-09-17.md` 7-3절), DONGWOO 승인 |
| 3 | 2026-09-17 12:13 이전 | `formula.neg` 추가(순 캡처율이 음수이면 계수 미적용, ②안). 같은 시각 예약 작업 두 개의 본문에도 같은 규칙을 넣음 | 같은 별도 세션(`claude/토큰캡처-등급모델-2026-09-17.md` 8-2·8-3절), DONGWOO 결정 |
| 4 | 2026-09-17 14:23 | 46종목으로 확장. **version 1 기반 파일로 썼기 때문에 version 2·3의 변경이 빠짐** | 이 세션 |

따라서 `snapshots/2026-09-19`의 NEAR 행은 옛 정의(slug `near`, 30일 귀속액 $40,579, 순 캡처율 0.01%)로 계산되어 있습니다. 다만 음수 규칙 자체는 예약 작업 본문에도 따로 적혀 있었으므로 2026-09-19 스냅샷에도 적용되어 있습니다(ETH −0.446, CRV −3.288, SOL −3.786, VVV −3.905, CC −3.924, VELO −16.629가 모두 순 캡처율과 같습니다).

동봉 `universe.json`은 version 4에 version 2·3을 다시 합친 것이고(`source_note` 필드에 경위를 적었습니다), **브리지 작업(11-1절)의 첫 실행 때 이 내용을 `meta/universe`에 version 5로 써서** 저장소와 저장소 밖의 정의를 다시 맞춥니다. 이후로는 GitHub 저장소의 `universe.json`이 단일 기준이고 `meta/universe`는 그 사본입니다.

행 하나의 필드는 다음과 같습니다. GitHub 스크립트의 출력도 **이 모양을 그대로** 따라야 아티팩트 페이지가 읽습니다.

```
t, n, slug, cg, mc, fdv, price, hr30, hr7, rr, raw, net, adj, g,
inc, ver, acc, auto, stab, k{acc, auto, stab, dil, hist}, hist, note
```

### 3-3. 예약 작업(claude.ai)

| 이름 | ID | 일정(UTC) | 상태 | 처리 |
|---|---|---|---|---|
| 토큰캡처 주간 갱신 (토 18:00 KST) | `trig_01VBieQsYUtDeQzELqVakfpP` | `0 9 * * 6` | 9/26, 10/3 수집 차단 | **지시문을 브리지 작업으로 교체**(11장) |
| 토큰캡처 보완 실행 (토 21:00 KST) | `trig_01QeLt5P1qf3RcYjRTGVbE3D` | `0 12 * * 6` | 전제가 틀려 헛돎 | **삭제** |

### 3-4. 프로젝트 문서(claude.ai 프로젝트 `[🟢P] 일일 크립토 브리핑 Agent !`)

- `claude/토큰캡처-등급모델-2026-09-17.md` 산출식 확정본과 1주차 결과. 8절에 NEAR 재정의와 음수 규칙 도입 경위
- `claude/NEAR-강세-원인-2026-09-17.md` NEAR 강세 분석. 7절에 Intents 매입·발행 수치와 온체인 잔고
- `claude/토큰캡처-내러티브-검증-2026-09-17.md` 내러티브 실재성 검증, LIT·VVV 조사, 누락 종목 탐색
- `claude/토큰캡처-정리본-검토-2026-09-15.md` 원문 검토
- `claude/토큰캡처-주간갱신-수집차단-2026-09-26.md`, `…-3주연속차단-2026-10-03.md` 등 네 건 실패 기록

### 3-5. 로컬 참조 파일(Cowork 컨테이너, 휘발 가능)

`/home/claude/tokencapture/`에 `compute.py`, `universe.py`, `db_universe.json`, `snapshot.json`, `index.html`이 있으나 컨테이너가 사라지면 없어집니다. 필요한 것은 전부 이 문서와 동봉 파일로 옮겼습니다.

---

## 4. 지난 설계가 실패한 원인과 금지 사항

이 장은 반드시 읽어야 합니다. 네 번의 예약 실행이 전부 실패한 원인이 여기에 있습니다.

### 4-1. 무인 실행에서 WebFetch는 주소마다 승인을 요구한다

Claude의 예약 작업이 WebFetch로 `api.llama.fi`를 부르면, 대화 중에는 사람이 승인해 주지만 **무인 실행에서는 승인 요청이 응답 없이 만료되어 `PROVENANCE_REQUIRED`로 거부**됩니다. 46개 종목이면 승인 창이 50번 넘게 뜨는 설계였고, 그래서 사용자가 승인하지 않았습니다. 같은 호스트의 다른 주소를 검색으로 먼저 열어 두는 우회도 2026-10-03 실측으로 성립하지 않는 것이 확인되었습니다.

**결론: 수집은 Claude 세션이 아니라 스크립트가 해야 합니다.** 이것이 GitHub Actions로 옮기는 이유입니다.

### 4-2. Cowork 컨테이너는 DefiLlama를 직접 부르지 못한다

컨테이너의 egress 정책이 `api.llama.fi`, `coins.llama.fi`, `defillama.com`, `api.coingecko.com`을 비롯한 시세·귀속액 호스트 전부를 CONNECT 단계에서 거부합니다(응답 코드 000). 열려 있는 것은 `api.github.com`, `raw.githubusercontent.com`, `pypi.org`, `registry.npmjs.org` 계열뿐입니다. **따라서 Cowork 컨테이너에서는 수집 스크립트를 실제 API에 대고 시험할 수 없습니다.** 시험은 GitHub Actions의 수동 실행이나 Claude Code가 도는 사용자 컴퓨터에서 해야 합니다.

### 4-3. 응답에 1,097일치 배열이 기본으로 붙어 온다

`api.llama.fi/summary/fees/<slug>`는 `total30d` 같은 합계와 함께 `totalDataChart`(일별 시계열, 약 1,097개)를 **기본으로 포함**해 돌려줍니다. 주소에 `excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true`를 붙이면 빠집니다. 지난 설계는 이것을 빠뜨려 30일 숫자 하나를 얻으려고 매번 수천 개 숫자를 언어 모델 문맥에 실어 날랐습니다. **주간 수집에서는 반드시 두 파라미터를 붙입니다.** 반대로 백테스트(12장)에서는 이 배열이 필요하므로 그때만 뺍니다.

### 4-4. WebFetch는 JSON을 작은 모델이 요약해 넘긴다

WebFetch는 응답을 작은 모델에게 읽혀 요약을 돌려줍니다. 스칼라 필드 여섯 개를 읽는 정도는 맞았지만, `totalDataChart`에서 구간 합계를 뽑게 하자 **항목 수를 틀리고(30일 구간에 27개) 배열 길이까지 다르게 보고**했습니다. 숫자는 스크립트가 파싱해야 합니다. 이 점도 GitHub Actions로 옮기는 근거입니다.

### 4-5. 서브에이전트 병렬은 과잉이었다

46개의 작은 호출을 서브에이전트 네 개에 나눠 돌리는 설계는 각 에이전트가 자기 문맥을 통째로 갖기 때문에 사용량만 늘립니다. 스크립트에서는 순차 호출로 충분하고, 필요하면 `concurrent.futures`로 8개 정도만 동시 실행합니다.

### 4-6. 보완 실행의 전제가 틀렸다

"사용량 한도가 19:00에 초기화되므로 21:00에는 회복되어 있다"는 전제로 21:00 보완 실행을 두었는데, 실패 원인은 한도가 아니라 승인이었으므로 시간이 지나도 풀리지 않았습니다. 네 번 중 두 번이 이 작업이었고 전부 헛돌았습니다. **삭제합니다.**

### 4-7. 토요일 18:00에 다른 작업과 같은 분에 발사된다

사용자의 `경제 캘린더 ① 알림`이 `0 8,9,23 * * *`(UTC)로 돌아 토요일 18:00 KST에 토큰캡처 갱신과 **같은 분**에 시작합니다. GitHub Actions로 옮기면 이 충돌은 자연히 사라집니다. 남는 Claude 브리지 작업은 다른 시각(예: 토 19:30 KST)에 둡니다.

### 4-8. 금지 목록 요약

- WebFetch로 수치를 수집하지 않습니다.
- 렌더링된 defillama.com 페이지 판독값을 쓰지 않습니다.
- 주간 수집에서 `totalDataChart`를 받지 않습니다.
- 수집 실패를 추정값으로 메우지 않습니다. 직전 스냅샷 값을 쓰되 `carried: true`로 표시합니다.
- 토큰 보유자에게 가지 않는 매입(트레저리 보유)을 소각·분배와 같은 점수로 치지 않습니다.
- 서로 다른 집계 기준의 바이백 총액(CoinGecko $1.4B, Allium $638M, Tokenomist $18.8B)을 섞어 인용하지 않습니다.

---

## 5. 새 구조: GitHub Actions

```
GitHub Actions (토요일, 무인, Claude 사용량 0)
  fetch.py  ──▶ api.llama.fi / coins.llama.fi 직접 호출
  score.py  ──▶ universe.json 읽어 채점
  commit    ──▶ data/snapshots/YYYY-MM-DD.json, data/latest.json
        │
        ▼
Claude 예약 작업 (토 19:30 KST, 한 줄짜리 브리지)
  curl raw.githubusercontent.com/.../data/latest.json
  Artifact write_db → snapshots/<date>, meta/state
        │
        ▼
아티팩트 페이지가 저장소를 읽어 표·차트 갱신
```

격주 신규 종목 리서치는 별도의 Claude 작업으로 남고, 결과를 저장소의 `data/universe.json`에 커밋합니다(11장).

GitHub 계정 `tlzkrh1029`가 Cowork 세션에 이미 연결되어 있어 `gh api`의 저장소 범위 엔드포인트를 쓸 수 있는 것을 확인했습니다. 저장소 이름과 공개 여부는 사용자가 정합니다. **비공개여도 월 2,000분 무료라 충분하고, 공개면 브리지가 `raw.githubusercontent.com`을 토큰 없이 읽을 수 있어 더 간단합니다.**

---

## 6. 데이터 소스 정밀 명세

### 6-1. 귀속액(Holders Revenue)

```
GET https://api.llama.fi/summary/fees/<slug>?dataType=dailyHoldersRevenue&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true
```

응답의 최상위 스칼라 필드(2026-09-17 실측):

| 필드 | 의미 | 용도 |
|---|---|---|
| `total24h` | 최근 24시간 | 참고 |
| `total48hto24h` | 24~48시간 전 | 참고 |
| `total7d` | 최근 7일 합계 | k안정 (런레이트비) |
| `total30d` | 최근 30일 합계 | **핵심 분자** |
| `total1y` | 최근 1년 합계 | 성장 지표 분모(13장) |
| `annualized1y` | 연환산 | 참고 |
| `totalAllTime` | 누적 | 집행 이력 참고 |

**DefiLlama의 Holders Revenue 정의**: "subset of revenue that is distributed to tokenholders by means of buyback and burn, burning fees or direct distribution to stakers". 즉 매수소각·수수료소각·스테이커분배 세 가지를 **합산**한 값입니다. 그래서 우리 모델은 `acc`(귀속 방식) 열로 다시 나눕니다.

**체인은 체인 이름이 slug입니다**: `tron`, `injective`, `canton`, `ethereum`, `solana`, `bsc`. `/protocol/fees/` 경로로는 404가 나므로 반드시 `/summary/fees/` 경로를 씁니다. NEAR는 예외입니다. 체인 slug `near`는 가스 소각분(30일 약 $3.9만)만 집계하고, 홀더 귀속의 97%를 차지하는 Intents 매입분은 별도 slug `near-intents`(30일 $1,141,893, 2026-09-17 실측)에 잡힙니다. `universe.json`은 `near-intents`를 쓰며, 가스 소각 효과는 배출액(`inc30`)을 온체인 순발행으로 정의하는 방식으로 흡수했습니다(8장).

**같은 호스트의 다른 dataType**: `dailyRevenue`(프로토콜 수익), `dailyFees`(총 수수료). 11장의 ①Revenue→Token 전환율을 쓰려면 `dailyRevenue`도 받습니다. 다만 Venice(VVV)처럼 매출이 오프체인 정산이라 DefiLlama가 소각액 자체를 Revenue로 정의한 경우가 있으므로, 전환율은 참고 지표로만 둡니다.

**백테스트용 일별 시계열**: 두 exclude 파라미터를 빼면 `totalDataChart`가 `[[unixTimestamp, value], ...]` 형태로 붙어 옵니다. 2026-09-17 기준 Aerodrome은 1,097개였습니다. 타임스탬프는 UTC 자정 기준 일 단위입니다.

### 6-2. 가격

```
GET https://coins.llama.fi/prices/current/coingecko:<id1>,coingecko:<id2>,...
GET https://coins.llama.fi/prices/historical/<unixTimestamp>/coingecko:<id1>,...
```

응답: `{"coins": {"coingecko:<id>": {"symbol", "price", "timestamp", "confidence"}}}`

- Cowork 컨테이너의 프록시는 긴 URL에 403을 돌려줘 **6개 이하**로 끊어야 했습니다. GitHub Actions에는 그 제약이 없지만, 안전하게 **25개 이하**로 묶습니다.
- `historical`은 요청 시각에 가장 가까운 가격을 돌려줍니다. 응답의 `timestamp`를 기록해 두어야 합니다.
- **응답에 없는 id는 `coins` 객체에서 아예 빠집니다.** 오류가 아니라 키 부재로 나타나므로 반드시 확인합니다.

### 6-3. 시가총액

`coins.llama.fi`는 유통량을 주지 않습니다. 시총은 **`price × circ`**로 계산하며, `circ`(유통량)는 `universe.json`에 보관하고 격주 리서치에서 갱신합니다. 유통량은 주 단위로 거의 변하지 않습니다.

대안으로 `GET https://api.llama.fi/protocols`가 프로토콜별 `mcap`을 주지만(체인은 없음), 응답이 5,000개 이상의 큰 배열이고 일부 종목이 빠질 수 있어 1차 소스로 쓰지 않습니다. 교차 검증용으로는 쓸 만합니다.

### 6-4. 배출액(Incentives)

순 캡처율의 차감 항목이며 단위는 백만 달러입니다. 현재 13종목만 값이 있고(`universe.json`의 `inc30`), 출처는 다음과 같습니다.

- AERO, VELO, CRV, CAKE, RAY, JUP, PENDLE, CVX: DefiLlama 프로토콜 페이지의 Incentives 30일 값(2026-09-17 수동 판독)
- CC: 공식 발행 스케줄(주간 1.521억 CC)을 가격으로 환산한 추정치
- ETH, SOL: 공개된 연 인플레이션율을 시총에 곱한 추정치
- VVV: 연 발행 250만 VVV를 가격으로 환산(30일 환산 수량 205,479 VVV)
- NEAR: 온체인 총공급의 실측 순증가(2025-10-26 1,278,110,057 → 2026-09-17 1,306,542,614, 연환산 약 2.49%)에서 구한 30일 순발행 약 2,654,000 NEAR × 2026-09-17 가격 $2.69

**`inc30`은 달러 고정값이라 가격이 크게 움직이면 빨리 낡습니다.** 그래서 `universe.json`에 발행 수량 필드를 두었습니다. `inc_qty30`(30일 발행 수량)이 있는 종목(NEAR, VVV)은 `inc30 = inc_qty30 × 그날 가격 ÷ 1e6`으로 **주간 실행 때마다 스크립트가 다시 계산**하고, `inc_ref_price`와 `inc_ref_date`를 그날 값으로 갱신합니다. `inc_qty30`이 `null`인 종목의 `inc30`은 격주 리서치에서 사람이 다시 조사합니다. 이 자동 환산은 2026-09-17에 예약 작업 본문에 "격주 리서치 때 수량 × 그날 가격으로 다시 계산한다"고 넣었던 규칙을 주간으로 앞당긴 것이며, 9/19 이후 한 번도 실행되지 못했으므로 첫 실행에서 NEAR와 VVV의 `inc30`이 바뀌는 것이 정상입니다.

**그 밖의 자동화는 미해결 과제입니다**(15장). DefiLlama에 `api.llama.fi/emission/<slug>` 계열 엔드포인트가 있으나 검증하지 않았습니다. 자동화 전까지는 `universe.json`의 값을 그대로 쓰고, `inc30`이 `null`이면 차감하지 않으며 행에 `ver: false`를 표시합니다.

### 6-5. 식별자 대응표

`universe.json`의 `slug`(DefiLlama)와 `cg`(CoinGecko id)가 기준입니다. 틀리기 쉬운 것만 적습니다.

| 종목 | slug | cg | 주의 |
|---|---|---|---|
| NEAR | `near-intents` | `near` | **체인 slug `near`가 아닙니다.** 체인 slug는 가스 소각분만 집계합니다(6-1절). 2026-09-19 스냅샷은 옛 slug로 수집된 값입니다 |
| CC | `canton` | `canton-network` | `canton`은 가격이 안 나옵니다 |
| DEEP | `deepbook` | `deep` | `deepbook`은 가격이 안 나옵니다 |
| BNB | `bsc` | `binancecoin` | |
| CRV | `curve-finance` | `curve-dao-token` | `curve-dex`는 별개 하위 항목입니다 |
| VELO | `velodrome` | `velodrome-finance` | `velo`는 Stellar의 다른 토큰입니다 |
| ETHFI | `ether.fi` | `ether-fi` | |
| DYDX | `dydx` | `dydx-chain` | |
| JUP | `jupiter` | `jupiter-exchange-solana` | |
| JTO | `jito` | `jito-governance-token` | |
| INJ | `injective` | `injective-protocol` | |
| SPK | `spark` | `spark-2` | |
| ASTER | `aster` | `aster-2` | |
| LIT | `lighter` | `lighter` | 심볼 LIT이 4개 병존합니다(Litentry 등). id로만 대조합니다 |
| STONK | `stonkfun` | `stonk-2` | **`coins.llama.fi`가 가격을 돌려주지 않습니다.** 15장 |
| PONS | `pons` | `pons` | 2026-06-17 이전 과거 가격이 없습니다(상장 전) |

### 6-6. 호출 예절

DefiLlama 공개 API는 키가 없고 요율 제한이 느슨하지만, 동시 요청은 8개 이하로 두고 실패 시 지수 백오프로 3회까지 재시도합니다. User-Agent에 저장소 이름을 넣습니다.

---

## 7. 채점 모델 전체 명세

### 7-1. 산출식

```
연환산 계수 ANN = 365 / 30 = 12.1667

시총(백만달러)   mc   = price × circ / 1e6
원시 캡처율(%)   raw  = (hr30 / 1e6) / mc × 100 × ANN
순 캡처율(%)     net  = ((hr30 / 1e6) − inc30) / mc × 100 × ANN      (inc30이 null이면 raw와 같음)
런레이트비       rr   = (hr7 × 30 / 7) / hr30                           (hr30이 0이면 null)

조정 캡처율(%)   adj  = net × k_acc × k_auto × k_stab × k_dil × k_hist      (net ≥ 0 일 때)
                 adj  = net                                                  (net < 0 일 때, 계수 미적용)
```

**음수 규칙(2026-09-17 도입, ②안).** 순 캡처율이 음수이면 다섯 계수를 곱하지 않고 순 캡처율을 그대로 조정 캡처율로 씁니다. 계수는 귀속의 질을 할인하는 장치인데 음수에 곱하면 값이 0 쪽으로 올라가 오히려 점수가 좋아지기 때문입니다. 예를 들어 NEAR는 매입분을 보유한다는 이유로 k_acc 0.35를 받는데, 규칙이 없으면 순 캡처율 −2.07%가 −0.50%로 올라가 매입분을 소각했을 경우보다 순위가 높아집니다. 음수 종목의 계수 값은 참고용으로 행의 `k`에 그대로 남깁니다. 계수를 귀속액에만 곱하는 ①안(`adj = (hr30 × 계수곱 − inc30) ÷ mc × 100 × ANN`)은 AERO를 B+에서 D로 떨어뜨리는 등 양수 종목까지 바꾸므로 채택하지 않았고, 재검토 대상으로만 남겨 두었습니다(15장).

### 7-2. 다섯 계수

| 계수 | 규칙 | 근거 |
|---|---|---|
| **k_acc** 귀속 실질성 | 순수 수수료 소각, 매수 후 소각, 매수 후 분배, 직접 수수료 분배, 매수 후 소각·분배 → `1.00`. 매수 후 보유 → `0.35` | 트레저리에 남는 매입분은 홀더가 받은 가치가 아닙니다 |
| **k_auto** 집행 자동성 | 코드 자동 `1.00`, 정기 집행 `0.90`, 불규칙 `0.65`, 정지 `0.00` | AAVE가 2026-04-19에 실제로 멈춘 사례 |
| **k_stab** 수치 안정성 | hr30이 0이면 `0`. 주기형 목록이면 `0.90` 고정. 그 밖에는 `clamp(rr, 0.30, 1.00)` | 가속은 보상하지 않고 감속만 반영합니다 |
| **k_dil** 미래 희석 | `max(0.40, (1 / fdv) ** 0.5)`, fdv는 FDV÷시총 배수(최대공급 기준) | 공급이 두 배면 토큰당 귀속은 절반 |
| **k_hist** 집행 이력 | 현행 구조의 무중단 집행 기간. 12개월 이상 `1.00`, 6~12개월 `0.85`, 3~6개월 `0.70`, 3개월 미만 `0.50` | 신생 프로토콜의 일시적 급증을 할인합니다 |

**주기형 목록(k_stab 0.90 고정)**: `BONK, DODO, DYDX, GEOD, MPLX, RAIL, SKY, SPK, USUAL, XVS, ZRO`. 이들은 주·월·분기 단위로 분배해서 7일 창에 0이 찍히거나 몰려 찍히므로 런레이트비가 의미를 갖지 못합니다.

`stab` 라벨은 다음과 같이 붙입니다. hr30이 0이면 `실현 0`, 주기형이면 `주기형`, rr > 1.15면 `가속`, rr < 0.85면 `감속`, 그 밖에는 `안정`.

### 7-3. 등급 구간(조정 캡처율, 연환산 %)

| 등급 | 구간 |
|---|---|
| S+ | 12 이상 |
| S | 8 이상 12 미만 |
| A | 5 이상 8 미만 |
| B+ | 3 이상 5 미만 |
| B | 1.5 이상 3 미만 |
| C | 0.4 이상 1.5 미만 |
| D | 0.4 미만 (음수 포함) |

### 7-4. 참조 구현

동봉한 `score_reference.py`가 위 식의 검증된 구현입니다. `python score_reference.py --selftest`를 실행하면 두 회차의 실측 입력(가격, hr30, hr7)을 내장 자료로 다시 계산해 저장소의 값과 대조하며, 2026-10-09에 실행한 결과는 다음과 같습니다.

```
[2026-09-17] 38행  상위5: STONK 13.92(S+), PONS 10.18(S), ORE 8.38(S), PUMP 6.71(A), ORCA 5.59(A)
   OK: 38종목 전부 저장값과 일치 (허용오차 ±0.002)
[2026-09-19] 46행  상위5: STONK 16.66(S+), PONS 10.17(S), ORE 7.25(A), PUMP 6.61(A), CVX 5.91(A)
   OK: 46종목 전부 저장값과 일치 (허용오차 ±0.002)
SELFTEST PASS
```

새로 짠 `score.py`는 같은 입력에 대해 `mc, raw, net, adj, rr`이 소수 셋째 자리 반올림 기준 ±0.002 안에서 일치하고 `g`가 같아야 합니다. `score_reference.py`의 `score(universe, inputs, date)`를 그대로 가져다 써도 됩니다. 2026-09-19 검증 사례는 NEAR만 당시 정의(slug `near`)로 덮어쓰고 계산하는데, 그 회차가 version 4 정의로 계산되었기 때문입니다(3-2절). 새 파이프라인에서는 덮어쓰기 없이 `universe.json`의 현재 정의를 씁니다.

### 7-5. 2026-09-19 스냅샷 상위(46종목 기준, 비교용)

STONK 16.66(S+), PONS 10.17(S), ORE 7.25(A), PUMP 6.61(A), CVX 5.91(A). 첫 수동 실행 결과가 이 자릿수에서 벗어나면 뭔가 잘못된 것입니다. 음수 종목은 VELO −16.63, CC −3.92, VVV −3.91, SOL −3.79, CRV −3.29, ETH −0.45였습니다.

---

## 8. 추적 대상 46종목

전체 정의는 동봉 `universe.json`의 `tokens` 배열에 있습니다. 항목마다 `t, n, slug, cg, circ, fdv, acc, auto, hist_k, hist, inc30, inc_qty30, inc_ref_price, inc_ref_date, note`가 들어 있습니다(뒤의 세 필드는 6-4절의 자동 환산용이며 NEAR와 VVV에만 값이 있습니다). 아래는 귀속 방식별 요약입니다.

| 귀속 방식 | 종목 |
|---|---|
| 순수 수수료 소각 | CC, TRX, UNI, ETH, SOL, BNB, INJ, DEEP |
| 매수 후 소각 | HYPE, PUMP, PONS, STONK, CAKE, JUP, LIT, JTO(정지), GEOD, EDGE, VVV |
| 매수 후 소각·분배 | SKY |
| 매수 후 분배 | ASTER, PENDLE, ORCA, XVS, VVS, DODO, ETHFI(정지) |
| 직접 수수료 분배 | AERO, CRV, CVX, VELO, RAIL, YB, USUAL |
| 매수 후 보유 (k_acc 0.35) | RAY, ORE, BONK, SPK, MPLX, AAVE(정지), DBR, DYDX, LINK, ZRO, **NEAR**, SYRUP |

`universe.json`에는 `watchlist`도 들어 있습니다. DefiLlama에 수록되지 않아 채점할 수 없는 CEX 토큰(WBT, BGB, GT, KCS), 조건 미충족으로 대기 중인 종목(ENA는 USDe 공급 $7.5B 도달 시 발동, GMX, LDO, SEA, KNTQ), 검토 후 제외한 종목(OKB 등)의 사유가 적혀 있습니다. 격주 리서치가 이 목록을 다시 봅니다.

**특별히 주의할 종목**

- **LIT**: 2026-12-29에 팀·투자자 몫 총공급 50%(5억 LIT)의 12개월 클리프가 풀리고 36개월 선형으로 나옵니다. 현행 매수 규모는 그 유입의 약 4.9%만 흡수합니다. 소각 집행 이력은 2026-07-10 한 번뿐입니다. 클리프 이후 `fdv`와 `hist_k`를 다시 봐야 합니다.
- **VVV**: 매수 후 소각이 실재하나 연 발행(약 $62.5M)이 연 소각(약 $9.6M)의 5배를 넘어 순 캡처율이 −4.38%입니다. DefiLlama가 매출을 소각액으로 정의하므로 "매출의 100% 귀속" 같은 서술은 순환 논리입니다.
- **CC(Canton)**: 원시 캡처율은 15%대로 상위권이지만 주간 1.521억 CC 발행이 소각을 넘어 순 −3.98%입니다. `inc30`이 추정치라는 점을 기억합니다.
- **NEAR**: 2026-09-17 오후에 재정의된 항목입니다(3-2절의 version 2). Intents 수익으로 NEAR를 공개시장에서 사들이지만 소각하지 않고 멀티시그 `buybacks.multisignature.near`에 보유합니다(2026-09-17 잔고 1,666,414.65 NEAR, DefiLlama 방법론도 "소각하지 않음"으로 적습니다). 그래서 귀속 방식은 "매수 후 보유"(k_acc 0.35), 집행은 "정기 집행", 이력은 매입 개시일 2026-02-23 기준 0.85입니다. 30일 매입액 약 $114만은 같은 기간 순발행 약 265만 NEAR(약 $714만)의 15~21%에 그쳐 순 캡처율은 −2.07%(D)입니다. 매입분을 소각하기로 결정되면 `acc`를 "매수 후 소각"으로 올립니다. 2026-09-19 스냅샷의 NEAR 행(순 0.01%)은 옛 정의로 계산된 값이므로 비교 대상으로 쓰지 않습니다.
- **JTO**: 2026-07-13 JIP-38로 매수·소각 구조가 도입되었으나 DefiLlama 어댑터가 귀속액을 전혀 집계하지 않아 누적까지 0입니다. 0을 실제 붕괴로 읽지 않습니다.

---

## 9. 저장소 파일 구성과 스크립트 요구사항

```
<repo>/
├── .github/workflows/weekly.yml        토요일 예약 + 수동 실행
├── scripts/
│   ├── fetch.py                        수집: 귀속액·가격 → data/raw/YYYY-MM-DD.json
│   ├── score.py                        채점: raw + universe → snapshot
│   ├── backtest.py                     과거 시점 재구성 + 순위상관
│   └── common.py                       HTTP 재시도, 날짜, 상수
├── data/
│   ├── universe.json                   추적 대상 정의 (동봉 파일 그대로)
│   ├── raw/YYYY-MM-DD.json             수집 원본 (감사용, 그대로 보존)
│   ├── snapshots/YYYY-MM-DD.json       채점 결과 (아티팩트 행 형식)
│   ├── latest.json                     최신 스냅샷 + 수집 메타 (브리지가 읽음)
│   └── history.csv                     날짜별 t, adj, g, mc, hr30 (분석용 평탄 파일)
├── README.md                           이 문서의 요약 + 운영 절차
└── requirements.txt                    비워 두거나 표준 라이브러리만
```

### 9-1. `fetch.py`

- `data/universe.json`을 읽어 slug와 cg 목록을 만듭니다.
- 귀속액: slug마다 6-1의 주소를 호출합니다. 동시 8개, 실패 시 1·2·4초 백오프로 3회 재시도. 받은 JSON에서 `total24h, total7d, total30d, total1y, annualized1y, totalAllTime`만 추출합니다.
- 가격: cg를 25개씩 묶어 `prices/current`를 호출합니다. `coins`에 키가 없는 id는 `null`로 둡니다.
- 출력 `data/raw/YYYY-MM-DD.json`: `{date, fetched_at(UTC ISO), hr: {t: {...}}, price: {t: price|null}, failures: [...]}`.
- **종료 조건**: hr30 수집 실패가 전체의 10%를 넘거나 가격 실패가 3개를 넘으면 `sys.exit(1)`로 실패시킵니다. 이것이 알림의 근거가 됩니다.

### 9-2. `score.py`

- raw와 universe를 읽어 7장의 식대로 채점합니다. 음수 규칙(7-1절)을 빠뜨리면 `score_reference.py --selftest`와 같은 검증에서 ETH·CRV·SOL·CC·VELO·VVV가 어긋나므로 바로 드러납니다.
- 채점 전에 `inc_qty30`이 있는 종목(NEAR, VVV)의 `inc30`을 `inc_qty30 × 그날 가격 ÷ 1e6`으로 다시 계산하고, `data/universe.json`의 `inc30`, `inc_ref_price`, `inc_ref_date`를 갱신해 함께 커밋합니다(6-4절). 가격 수집에 실패한 종목은 환산하지 않고 직전 값을 유지합니다.
- 실패 종목은 직전 스냅샷(`data/snapshots/`의 가장 최근 파일)의 값을 쓰고 행에 `"carried": true`를 넣습니다. 직전 스냅샷에도 없으면 행을 만들지 않고 `failures`에 남깁니다.
- 행 형식은 3-2의 필드를 그대로 따릅니다. `k`는 `{acc, auto, stab, dil, hist}` 객체, `ver`는 `inc30 is not null`.
- `rows`는 `adj` 내림차순 정렬.
- 출력: `data/snapshots/YYYY-MM-DD.json`(`{date, rows}`), `data/latest.json`(`{date, rows, meta: {fetched_at, failures, universe_updated, count}}`), `data/history.csv`에 행 추가.
- 직전 스냅샷과 비교해 **등급이 바뀐 종목 목록**을 표준 출력에 찍습니다. 워크플로 로그에서 바로 보이게 합니다.

### 9-3. `backtest.py`

12장 참조.

### 9-4. `common.py`

`http_get_json(url, retries=3)`, `today_utc()`, `batched(iterable, n)`, 상수 `ANN`, `K_ACC`, `K_AUTO`, `BANDS`.

---

## 10. 워크플로 명세 (`.github/workflows/weekly.yml`)

```yaml
name: tokencapture-weekly
on:
  schedule:
    - cron: "0 9 * * 6"        # 토요일 09:00 UTC = 18:00 KST (GitHub 혼잡 시 수십 분 지연 가능)
  workflow_dispatch:           # 첫 실행 검증과 수동 재실행용
permissions:
  contents: write
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: python scripts/fetch.py
      - run: python scripts/score.py
      - name: commit
        run: |
          git config user.name "tokencapture-bot"
          git config user.email "bot@users.noreply.github.com"
          git add data/
          git commit -m "weekly snapshot $(date -u +%F)" || echo "no changes"
          git push
```

- `fetch.py`가 `exit 1`로 끝나면 커밋 없이 워크플로가 실패하고, GitHub 기본 설정에서 저장소 소유자에게 **실패 이메일**이 갑니다. 저장소 설정 → Notifications에서 Actions 알림이 켜져 있는지 확인합니다.
- 공개 저장소의 예약 워크플로는 60일간 저장소 활동이 없으면 자동 비활성화되지만, 이 워크플로 자체의 주간 커밋이 활동으로 잡혀 유지됩니다.
- 같은 날 두 번 돌아도 `data/snapshots/YYYY-MM-DD.json`이 덮어쓰기되므로 중복 데이터 점은 생기지 않습니다.

---

## 11. Claude에 남는 두 작업과 예약 작업 정리

### 11-1. 브리지 작업 (주간, 토 19:30 KST)

기존 `trig_01VBieQsYUtDeQzELqVakfpP`의 **지시문과 일정을 교체**합니다. 일정은 `30 10 * * 6`(UTC). GitHub가 지연되어도 90분 여유가 있습니다.

지시문 요지:

1. Bash로 `curl -sSL https://raw.githubusercontent.com/<owner>/<repo>/main/data/latest.json -o /tmp/latest.json`을 실행합니다. 이 호스트는 컨테이너에서 열려 있는 것이 2026-10-03에 확인되었습니다. 비공개 저장소면 대신 `gh api repos/<owner>/<repo>/contents/data/latest.json`으로 받아 base64를 풉니다.
2. `date`가 오늘(KST) 또는 어제가 아니면 "GitHub 쪽이 이번 주 실행을 못 했다"고 보고하고 끝냅니다. 저장소에는 아무것도 쓰지 않습니다.
3. Artifact 도구 `read_db`로 `meta/state.lastWeekly`를 읽어 이미 같은 날짜면 끝냅니다.
4. `write_db`로 `snapshots/<date>`에 `{date, rows}`를 set 하고, `meta/state`를 update 해 `lastWeekly`를 그 날짜로 바꿉니다. `latest.json`의 `meta.universe_updated`가 `meta/universe.updated`와 다르면 저장소의 `data/universe.json`을 같은 방법으로 받아 `meta/universe`에 set 합니다(`if_version`을 현재 버전으로 지정). **첫 실행에서는 반드시 이 갱신이 일어나야 합니다.** 저장소의 `meta/universe`는 version 4이고 동봉 `universe.json`의 `updated`는 `2026-10-09`이므로 조건이 성립하며, 이것으로 3-2절의 불일치가 해소됩니다.
5. 푸시 알림: 등급 변동 종목, 상위 5개, 순공급이 증가로 돌아선 종목, `carried`가 붙은 종목, GitHub 실패 여부.

이 작업은 WebFetch를 쓰지 않으므로 승인 문제가 없습니다. 토큰 소모는 파일 크기(약 30KB) 수준입니다. 지시문을 교체할 때 2026-09-17 12:13 UTC에 본문에 넣었던 음수 규칙과 inc30 재환산 문장은 더 이상 필요 없습니다. 둘 다 GitHub 쪽 `score.py`가 맡기 때문입니다.

### 11-2. 보완 실행 삭제

`trig_01QeLt5P1qf3RcYjRTGVbE3D`를 삭제합니다. 대체는 필요 없습니다. GitHub가 실패하면 이메일이 오고, 브리지가 "이번 주 실행 없음"을 알립니다.

### 11-3. 격주 신규 종목 리서치 (Claude, 판단 필요)

`meta/state.nextResearch`(현재 2026-10-03, 이미 지났음)를 기준으로 14일마다 수행합니다. 무인 실행으로 두려면 그 예약 작업의 승인 설정을 "자동"으로 켜야 WebSearch→WebFetch 경로가 열립니다. 아니면 사용자가 격주로 대화 중에 직접 돌립니다. 절차는 다음과 같습니다.

1. `https://defillama.com/token-rights`(Active Buybacks·Fee Switch ON 필터)와 `https://defillama.com/holders-revenue` 상위 60개에서 `universe.json`에 없는 프로토콜을 찾습니다.
2. 후보마다 1차 출처(공식 문서, 거버넌스 기록)로 확인합니다: 거래되는 토큰의 존재와 CoinGecko 1000위 안, 귀속 방식 다섯 가지 중 하나, 집행 자동성 네 가지 중 하나, 현행 구조의 무중단 집행 개월 수, 유통량, 최대공급 기준 FDV 배수. 추정값은 넣지 않습니다.
3. 기존 종목 중 프로그램이 개시·중단·비율 변경된 것은 `acc, auto, hist_k, note`를 고칩니다. `watchlist.pending`의 조건(ENA의 USDe $7.5B 등)이 충족되었는지 봅니다.
4. 유통량(`circ`)과 FDV 배수(`fdv`)를 CoinGecko 또는 DefiLlama 토큰 페이지로 갱신합니다.
5. `data/universe.json`을 저장소에 커밋합니다(`gh api repos/<owner>/<repo>/contents/data/universe.json` PUT, sha 필요). 동시에 아티팩트 `meta/universe`를 갱신하고 `meta/state`의 `lastResearch`, `nextResearch`(+14일), `researchCount`를 올립니다.

---

## 12. 백테스트 설계 (`scripts/backtest.py`)

모델의 예측력을 판정하는 장치입니다. 2026-09-17에 WebFetch로 시도하다 실패했던 것으로, 스크립트에서는 쉽게 됩니다.

### 12-1. 입력

- 기준 시점 `T` (예: `2026-06-17`), 전방 구간 `H` (기본 90일)
- 종목마다 두 exclude 파라미터를 **뺀** 주소로 `totalDataChart`를 받습니다(일별 `[unix, value]`).
- 가격은 `prices/historical/<T>`와 `prices/historical/<T+H>`.

### 12-2. T 시점 재구성

- `hr30_T` = T 이전 30일(T 포함, T−29일까지)의 일별 값 합계. 항목 수가 30개가 아니면 경고를 찍습니다.
- `hr7_T` = T 이전 7일 합계.
- `hr1y_T` = T 이전 365일 합계 (13장 성장 지표용).
- `mc_T` = `price_T × circ`. 유통량은 현재 값을 그대로 쓰므로 근사입니다. 이 가정을 출력에 명시합니다.
- `fdv, acc, auto, hist_k`는 현재 `universe.json` 값을 씁니다. 엄밀히는 T 시점 값이어야 하지만 대부분 느리게 변합니다. 단, T 이후에 구조가 바뀐 종목(예: 2026-06-27 Aavenomics 3.0, 2026-07-10 LIT 첫 소각, 2026-07-13 JTO JIP-38)은 `universe.json`의 `note`와 `hist`로 판별해 **T 시점 기준으로 되돌리거나 제외**합니다. 이 판별 규칙을 코드 주석에 남깁니다.
- 7장 식으로 `adj_T`와 등급을 계산합니다.

### 12-3. 출력

- 종목별 `adj_T, grade_T, return_T→T+H, BTC 대비 초과수익`
- **스피어만 순위상관** `ρ(adj_T, return)`과 `ρ(adj_T, 초과수익)`, 표본 수, p값(scipy가 있으면, 없으면 순열검정 1,000회)
- 등급 그룹별 평균·중앙값 수익률 표
- 비교 기준선: `ρ(raw_T, return)`(할인 전 원시 캡처율만 썼을 때)와 `ρ(hr30_T/mc_T 단순비율, return)`. 다섯 계수가 실제로 예측력을 더하는지 보려면 이 기준선과 비교해야 합니다.
- 음수 처리 변형: 현행 ②안(`adj_T`)과 함께 ①안(`(hr30_T × 계수곱 − inc30) ÷ mc_T × 100 × ANN`)으로도 `ρ`를 냅니다. 15장의 보류 과제를 자료로 결정하기 위해서입니다. 다만 `inc30`은 현재 값이라 T 시점과 다르므로, 배출액이 있는 13종목에 한해 근사라는 점을 출력에 적습니다.
- NEAR는 `near-intents` 차트가 2026-02-23부터 시작하므로 그 이전 T에서는 제외합니다. 2026-09-19 스냅샷의 NEAR 행은 옛 slug 값이므로 백테스트 검증 기준으로 쓰지 않습니다.

### 12-4. 실행 계획

- T를 `2026-04-01, 2026-05-01, 2026-06-01, 2026-06-17, 2026-07-01`로 다섯 번 돌려 한 시점의 우연을 걸러냅니다.
- 2026-09-17 조사에서 확인된 2026-06-17 → 09-17 수익률(DefiLlama 과거 가격 API 기준)이 있으므로 그 시점부터 검증합니다. 당시 기록: LIT +165.7%, PUMP +140.5%, RAY +123.6%, UNI +103.5%, … BTC +16.1%, … VELO +24.7%, CC −37.5%, BONK −44.3%, JTO −47.1%. PONS는 T0 가격이 없고 STONK는 양쪽 다 없었습니다.
- 결과를 `data/backtest/<T>.json`과 요약 `data/backtest/summary.md`로 저장합니다.

---

## 13. 성장 계수 (검정 후 결정)

**추가 여부는 12장의 결과로 결정합니다.** 설계안만 적습니다.

- 성장배수 `g = total30d ÷ (total1y ÷ 12.1667)`. 현재 30일 런레이트가 직전 1년 월평균의 몇 배인지입니다. 같은 호출에 `total1y`가 들어 있어 추가 비용이 없습니다. 백테스트에서는 `hr30_T ÷ (hr1y_T ÷ 12.1667)`로 재구성합니다.
- 제안 매핑 `k_growth`: g ≥ 1.5 → 1.10, 1.0 ≤ g < 1.5 → 1.00, 0.7 ≤ g < 1.0 → 0.85, g < 0.7 → 0.70. 상한을 1.10으로 낮게 둔 이유는, 크립토에서 수수료 매출은 가격·거래량을 따라 움직여 **모멘텀 요인과 상당 부분 겹치기 때문**입니다.
- 판정 규칙: `ρ(adj × k_growth, return)`이 다섯 T 중 **네 곳 이상에서** `ρ(adj, return)`보다 높을 때만 채택합니다. 채택하면 `universe.json`의 `formula`에 매핑을 추가하고 `score.py`와 아티팩트 페이지의 산출 모델 설명을 함께 고칩니다.
- 채택하지 않더라도 `g`는 행에 `growth` 필드로 기록해 표에서 볼 수 있게 합니다.

---

## 14. 첫 실행 검증 절차

1. 저장소를 만들고 9장의 파일을 넣습니다. `data/universe.json`은 동봉 파일 그대로입니다.
2. GitHub Actions 탭에서 `tokencapture-weekly`를 **Run workflow**로 수동 실행합니다.
3. 로그에서 확인합니다: 수집 성공 수가 46(STONK 가격 실패는 예상된 것이므로 45여도 정상), `failures` 목록, 등급 변동 목록.
4. `data/snapshots/<오늘>.json`을 열어 행 수 46, 각 행에 3-2의 필드가 전부 있는지, `rows[0]`이 `adj` 최댓값인지 봅니다.
5. **값 대조**: 2026-09-19 스냅샷(아티팩트 저장소 `snapshots/2026-09-19`)과 같은 종목의 `hr30`, `mc`, `adj`를 비교합니다. 3주가 지났으니 값은 다르지만 **자릿수는 같아야** 합니다. 예를 들어 HYPE `hr30`은 수천만 달러, DEEP은 수만 달러 수준입니다. NEAR는 예외로, slug가 `near-intents`로 바뀌었으므로 `hr30`이 백만 달러대(2026-09-17 실측 $1,141,893)로 나와야 정상이고, 수만 달러대로 나오면 체인 slug `near`를 잘못 쓴 것입니다. 음수 종목(ETH, CRV, SOL, CC, VELO, VVV, NEAR)은 `adj`와 `net`이 같아야 합니다.
6. `python score_reference.py --selftest`가 `SELFTEST PASS`를 내는지 확인한 뒤, 같은 내장 입력(파일 안의 `SELFTEST` 사전)을 `score.py`에 넣어 결과가 같은지 확인합니다. `score_reference.py`의 `score()` 함수를 그대로 가져다 썼다면 이 단계는 자동으로 통과합니다.
7. 브리지 작업을 한 번 수동 발사(`fire_trigger`)해 아티팩트 저장소에 새 문서가 생기고 페이지의 "누적 주차"가 올라가는지 봅니다.
8. 보완 실행 작업을 삭제합니다.

---

## 15. 미해결 과제

| 과제 | 상태 | 비고 |
|---|---|---|
| `meta/universe` version 4 불일치 | **첫 브리지 실행에서 해소** | 3-2절. 동봉 `universe.json`을 version 5로 써서 NEAR 재정의와 `formula.neg`를 저장소에 복원. `snapshots/2026-09-19`의 NEAR 행은 옛 정의로 계산된 값이므로 그대로 두되, 아티팩트 차트에서 NEAR의 9/19 점이 튀어 보이는 것은 이 때문임 |
| 음수 처리 ①안 재검토 | 보류 | 7-1절. 계수를 귀속액에만 곱하는 안. 2026-10-03 격주 리서치에서 재검토하기로 했으나 그 리서치가 실행되지 못함. 백테스트(12장)에서 ②안과 ①안의 순위상관을 함께 내면 자료에 근거해 결정 가능 |
| STONK 가격 | `coins.llama.fi`가 `stonk-2`를 돌려주지 않음 | 2026-09-17에는 CoinGecko 시총÷유통량으로 환산. 대안 id가 있는지, 또는 DefiLlama `protocol` 페이지의 토큰 가격 필드를 쓸 수 있는지 확인 |
| 배출액(`inc30`) 자동화 | 13종목만 값 보유, 그중 NEAR·VVV는 수량 기반 자동 환산(6-4절) | 나머지 11종목은 달러 고정값. `api.llama.fi/emission/<slug>` 또는 `/emissions` 엔드포인트 검증. 자동화되면 33개 미확인 종목의 순 캡처율이 내려갈 가능성만 있음 |
| 유통량 자동화 | 격주 수동 | `api.llama.fi/protocols`의 `mcap`로 교차 검증 가능 |
| 등급·수익률 순위상관 | 미측정 | 12장. 가장 중요한 과제 |
| 성장 계수 | 설계만 | 13장 |
| 2026-09-26, 10-03 주차 결손 | 재구성 가능 | 12장의 `totalDataChart` 방식으로 두 주차를 소급 계산해 채울 수 있음. 단, 가격은 `historical`로 받고 행에 `"reconstructed": true` 표시 |
| LIT 2026-12-29 클리프 | 예정 | 클리프 직후 격주 리서치에서 `fdv`와 `hist_k` 재평가 |
| ENA 편입 | 조건 대기 | USDe 공급 $7.5B 도달 시 fee switch 발동. 도달 여부를 격주 리서치에서 확인 |
| CEX 토큰 4종 | 채점 불가 | WBT, BGB, GT, KCS는 DefiLlama 미수록. 거래소 공시로 대체 수집할지 결정 필요 |
| 아티팩트 산출 모델 설명 | 문구 갱신 필요 | 성장 계수 채택 시 `index.html`의 `.kdefs` 블록과 밴드 설명 수정 |

---

## 16. 참고 출처

- DefiLlama Holders Revenue 랭킹: `https://defillama.com/holders-revenue`
- DefiLlama Token Rights: `https://defillama.com/token-rights`
- DefiLlama 지표 정의: `https://defillama.com/data-definitions`
- 내러티브 검증 근거: Tokenomist "Crypto's $19B Buyback and Burn Meta" (2026-07-30), CryptoRank "Do Buybacks Work in 2025?" (2025-10-24), Keyrock "Designing Token Buybacks" (2025-10-23), Messari "The Bear Case for Token Buybacks" (2025-03), Delphi Digital "State of Token Markets" (2026-06-02)
- 개별 종목 1차 출처는 `universe.json`의 `note`와 프로젝트 문서 `claude/토큰캡처-내러티브-검증-2026-09-17.md` 10장에 있습니다.

---

*이 문서의 모든 수치는 2026-09-17 또는 2026-10-03 실측이며, 그 이후 변동은 반영되어 있지 않습니다. 첫 수동 실행이 현재 값을 다시 받아옵니다.*
