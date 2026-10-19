# token-capture · 토큰캡처 정밀조사 파이프라인

크립토 종목별 **토큰캡처**(프로토콜이 번 돈이 토큰 보유자에게 실제로 얼마나 귀속되는지)를 사람 개입 없이 매주 측정한다.
설계 전문은 `docs/HANDOVER.md`와 `docs/HANDOVER-ADDENDUM.md`에 있다. 이 문서는 그 요약과 운영 절차다.

매수·매도 판단이나 투자 권유는 만들지 않는다. 캡처 지표만 측정한다.

## 구조

```
GitHub Actions (.github/workflows/weekly.yml, 토요일 06:17 UTC = 15:17 KST, 보충 실행 07:47 UTC = 16:47 KST, Claude 사용량 0)
  scripts/fetch.py  ──▶ api.llama.fi(귀속액) · coins.llama.fi(가격) 직접 호출 → data/raw/YYYY-MM-DD.json
  scripts/score.py  ──▶ data/universe.json 으로 채점 → data/snapshots/YYYY-MM-DD.json, data/latest.json, data/history.csv
  commit            ──▶ data/ 를 저장소에 커밋
        │
        ▼
Claude 예약 작업 (토 19:30 KST 브리지, HANDOVER.md 11-1절)
  raw.githubusercontent.com/tlzkrh1029/token-capture/main/data/latest.json 을 읽어
  아티팩트 저장소 snapshots/<date>, meta/state, (바뀌었으면) meta/universe 에 쓴다
        │
        ▼
아티팩트 `토큰캡처 등급표` 가 저장소를 읽어 표·차트 갱신
```

```
scripts/common.py          HTTP 재시도, 날짜, 경로, 산출식 상수
scripts/fetch.py           주간 수집
scripts/score.py           채점 (score_reference.py 와 같은 결과를 내야 한다)
scripts/score_reference.py 채점식 참조 구현(검증본). `--selftest` 로 2026-09-17·09-19 실측 84행을 재현한다
scripts/backtest.py        과거 시점 T 재구성 + 스피어만 순위상관 (12장)
scripts/audit_chart.py     일별 시계열로 저장값 점검 (보완 문서 2절)
scripts/seed_snapshots.py  직전 스냅샷 재생성 (보완 문서 3절)
tests/test_score.py        score.py ↔ score_reference.py 일치 검증
tests/fixtures/universe-2026-10-09.json  동봉 universe.json 의 고정본. 참조 검증·테스트·시드 재생성의 기준
data/universe.json         추적 대상 46종목 정의와 산출식 상수 (단일 기준)
data/raw/                  수집 원본 (감사용, 그대로 보존)
data/snapshots/            채점 결과 {date, rows}  (아티팩트 행 형식)
data/latest.json           최신 스냅샷 + meta (브리지가 읽음)
data/history.csv           날짜별 평탄 파일
artifact/index.html        대시보드 아티팩트(https://claude.ai/artifact/YQg1tsjpAD2WnYjTpxsxfQ)의 페이지 원본. boot.js 는 artifact/gen_boot.py 로 latest.json·universe.json 에서 만들어 함께 올린다
data/backtest/             백테스트 결과 <T>.json 과 summary.md
```

## 채점 모델 (HANDOVER.md 7장)

```
ANN = 365/30 = 12.1667
mc  = price × circ / 1e6                       시총(백만 달러)
raw = (hr30/1e6) / mc × 100 × ANN               원시 캡처율 %
net = ((hr30/1e6) − inc30) / mc × 100 × ANN     순 캡처율 % (inc30 이 null 이면 raw 와 같음)
rr  = (hr7 × 30/7) / hr30                       런레이트비
adj = net × k_acc × k_auto × k_stab × k_dil × k_hist   (net ≥ 0)
adj = net                                        (net < 0, 계수 미적용 — 2026-09-17 ②안)
```

| 계수 | 규칙 |
|---|---|
| k_acc 귀속 실질성 | 소각·분배 1.00, 매수 후 보유 0.35 |
| k_auto 집행 자동성 | 코드 자동 1.00, 정기 집행 0.90, 불규칙 0.65, 정지 0.00 |
| k_stab 수치 안정성 | hr30=0 → 0, 주기형 목록 → 0.90, 그 밖에 clamp(rr, 0.30, 1.00) |
| k_dil 미래 희석 | max(0.40, (1/fdv)^0.5) |
| k_hist 집행 이력 | 12개월 이상 1.00, 6~12 0.85, 3~6 0.70, 3개월 미만 0.50 |

등급: S+ ≥12, S ≥8, A ≥5, B+ ≥3, B ≥1.5, C ≥0.4, D 그 미만(음수 포함).

행 필드(아티팩트 페이지가 읽는 모양, 순서 고정): `t, n, slug, cg, mc, fdv, price, hr30, hr7, rr, raw, net, adj, g, inc, ver, acc, auto, stab, k{acc, auto, stab, dil, hist}, hist, note`.
그 뒤에 선택 필드가 붙을 수 있다: `growth`(성장배수), `rev30`·`fees30`(DefiLlama 30일 프로토콜 수익·총수수료), `payout`(귀속률 % = hr30 ÷ rev30 × 100), `carried`·`carried_fields`(직전 값 사용), `stale_suspect`(직전 주와 hr30·hr7 동일). `growth`·`rev30`·`fees30`·`payout`은 채점에 쓰지 않는 보조 지표다. 2026-10-14부터 `adjg`(배출 차감 전 조정 캡처율 = 원시 캡처율 × 다섯 계수)와 그 등급 `gg` 도 붙는다. 배출을 차감한 순 캡처율이 음수이면 계수를 적용하지 않는 규칙 때문에 배출이 큰 종목은 D 로 몰리므로, 귀속 강도(배출 전)와 희석(배출 후)을 따로 읽기 위한 보조 지표다. `history.csv` 에도 `adjg` 열이 있다.

## 수집 규칙 (6장, 보완 문서 1절)

- 귀속액: `api.llama.fi/summary/fees/<slug>?dataType=dailyHoldersRevenue&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true`. 동시 8개, 1·2·4초 백오프 3회. 주간 수집은 반드시 두 exclude 파라미터를 붙인다(백테스트만 뺀다).
- 매출: 같은 주소에 `dataType=dailyRevenue`, `dailyFees` 로 프로토콜 수익과 총수수료도 받아 `rev30`·`fees30`·`payout`(귀속률)을 행에 넣는다. 보조 지표라 실패해도 종료 조건에 넣지 않는다(ASTER 처럼 수익 항목이 없는 어댑터는 비워 둔다).
- `total30d` 가 `null` 로 오면(응답은 200) 수집 실패로 센다. 0 으로 바꾸지 않는다. 2026-10-10 기준 DODO 가 그렇다(어댑터 기록이 2026-08-29 에서 끝남).
- 가격 순서: ① `coins.llama.fi/prices/current/coingecko:<cg>` (25개씩) → ② 빠진 종목은 DefiLlama 응답의 컨트랙트 주소로 `coins.llama.fi` 재조회 → ③ 그래도 없으면 CoinGecko `simple/price` 같은 id. 환경변수 `COINGECKO_API_KEY` 가 있으면 데모 키 헤더(`x-cg-demo-api-key`)로 보낸다. 키는 코드나 커밋에 넣지 않고 저장소 Secrets 에만 둔다.
- 종료 조건: hr30 실패가 전체의 10% 초과 또는 가격 실패 3개 초과 → raw 파일을 쓴 뒤 `exit 1`. 워크플로가 실패로 끝나고 GitHub 가 이메일을 보낸다.
- 실패 종목은 score.py 가 직전 스냅샷 값을 쓰고 `carried: true`, `carried_fields` 를 넣는다. 같은 필드가 2주 연속 실패하면 행을 만들지 않고 `latest.json` 의 `meta.failures` 에 남긴다. "2주 연속"은 직전 스냅샷이 7일 이상 전일 때만 성립하며, 같은 주의 재실행(하루 이틀 뒤 수동 실행)은 같은 실패로 보고 다시 carried 로 둔다.
- `inc_qty30` 이 있는 종목(2026-10-14 리서치 이후 42종목)은 매주 `inc30 = inc_qty30 × 그날 가격 ÷ 1e6` 으로 다시 계산하고 `universe.json` 의 `inc30`, `inc_ref_price`, `inc_ref_date`, `updated` 를 갱신해 함께 커밋한다.
- `stale_suspect`: 수집에 성공했는데 hr30·hr7 이 직전 스냅샷과 정확히 같으면 표시한다(둘 다 0 인 "실현 0" 행은 제외). 주기형 목록 종목은 정상이어도 같을 수 있다. 워크플로는 실패시키지 않는다.

## 운영 절차

### 로컬 검증

```
python scripts/score_reference.py --selftest --universe tests/fixtures/universe-2026-10-09.json   # SELFTEST PASS 여야 한다
python -m unittest discover -s tests -v                                                           # score.py 가 참조 구현과 일치하는지
python scripts/fetch.py --date 2026-10-10 && python scripts/score.py --date 2026-10-10
```

참조 검증과 테스트는 `data/universe.json` 이 아니라 고정본 `tests/fixtures/universe-2026-10-09.json` 을 쓴다. `data/universe.json` 은 매주 NEAR·VVV 의 `inc30` 이 다시 쓰이므로 2026-09-17·09-19 저장값을 재현하는 기준이 될 수 없다.

### 첫 실행 검증 (14장)

1. Actions 탭에서 `tokencapture-weekly` 를 **Run workflow** 로 수동 실행한다. 오늘(UTC) 스냅샷이 이미 커밋돼 있으면 건너뛰므로, 다시 수집하려면 `force` 입력을 켠다.
2. 로그: `귀속액 성공 N/46`, `가격 성공 46/46`, 실패 목록, 등급 변동 목록. 행 수는 46 이어야 한다(보완 문서 1절. STONK 는 CoinGecko id 가 `stonk-3` 으로 바뀌어 이제 `coins.llama.fi` 에서 가격이 나온다). 2026-10-10 기준 DODO 는 `total30d` 가 `null` 이라 직전 값을 쓴 `carried` 행으로 들어간다. 이 상태가 직전 스냅샷보다 7일 이상 지난 실행에서도 이어지면 그때는 DODO 가 빠져 45행이 되고 `meta.failures` 에 "2주 연속 실패"로 남는다.
3. `data/snapshots/<오늘>.json` 의 행 수 46, 필드 전부 존재, `rows[0]` 이 `adj` 최댓값.
4. 값 대조: NEAR `hr30` 은 백만 달러대(`near-intents`)여야 하고 수만 달러대면 체인 slug 를 잘못 쓴 것이다. 음수 종목(ETH, CRV, SOL, CC, VELO, VVV, NEAR 등)은 `adj` 와 `net` 이 같아야 한다.
5. 브리지 작업을 한 번 수동 발사해 아티팩트 저장소에 새 문서가 생기는지 본다. 첫 실행에서는 `meta/universe` 가 version 5 로 갱신되어야 한다(3-2절 불일치 해소).
6. 보완 실행 작업(`trig_01QeLt5P1qf3RcYjRTGVbE3D`)을 삭제한다.

### 매주

워크플로가 토요일 15:17 KST 에 돌고, 16:47 KST 에 보충 실행이 한 번 더 예약되어 있다. 보충 실행은 오늘 스냅샷이 이미 커밋돼 있으면 `check` 단계에서 건너뛴다. 2026-10-17~19 에 6시간 간격 탐침 cron 으로 재 본 결과 예약 실행은 등록되어 있었지만 예정 시각보다 2시간 20분에서 5시간까지 늦게 생성됐다(GitHub 쪽 지연). 그래서 19:30 KST 브리지가 읽기 전에 끝나도록 실행 시각을 오후로 앞당겼다. 2026-08 이후 GitHub 예약 스케줄러가 실행을 아예 만들지 않는 사례도 보고되어 있고 그 경우 보충 cron 도 소용이 없으므로, 그때는 브리지나 사람이 Run workflow(workflow_dispatch)로 돌리는 것이 유일한 우회책이다. 정각 예약은 GitHub 혼잡으로 지연되거나 통째로 빠질 수 있어(2026-10-17 첫 예약 실행이 기록 없이 빠졌다) 분 값을 정각에서 비켜 두었다. 실패 이메일이 오면 Actions 로그의 `[fetch] 실패` 줄을 본다. 재실행은 Run workflow(`force` 켜기). 같은 날 두 번 돌아도 같은 파일을 덮어쓰므로 중복 데이터 점은 생기지 않는다. 브리지(토 19:30 KST)가 "GitHub 쪽이 이번 주 실행을 못 했다"고 알리면 Run workflow 로 수동 실행한 뒤 브리지를 다시 실행한다.

### 격주 리서치 (11-3절, Claude 가 수행)

신규 종목 발굴, `acc/auto/hist_k/note` 수정, `circ`·`fdv` 갱신, `inc_qty30` 이 없는 종목의 `inc30` 재조사. 결과를 `data/universe.json` 에 커밋하고 `updated` 를 올린다. 브리지가 다음 주에 `meta/universe` 를 따라 갱신한다.

2026-10-13 리서치(`docs/research-2026-10-13.md`)부터 종목마다 설명 필드가 붙는다: `sector`, `policy`(재원 기준·홀더 귀속 비율·목적지·집행·주기·개시일·최근 6개월 변경·DefiLlama 집계 정의·출처·신뢰도), `unlocks`(향후 6개월), `flags`(주의 사항), `inc_method`·`inc_confidence`(배출 수량의 산정 방법과 신뢰도), `research_date`. 배출 수량 규칙은 `formula.inc_lumpy` 에 있다: 신뢰도 high·medium 만 `inc_qty30` 으로 차감하고, low 는 `inc_qty30_est` 에만 둔다. 배출이 비선형인 종목(HYPE)은 최근 수회 평균 평활값을 `inc_qty30` 으로 쓰고 이번 창 실측은 `inc_qty30_window` 에 둔다. 채점에 직접 영향을 주는 `acc`·`auto` 변경과 신규 종목 편입은 보고서 4-2절·5절의 승인 대기 표에 있고, 승인 전에는 반영하지 않는다.

### 백테스트 (12장)

```
python scripts/backtest.py --all            # T = 2026-04-01, 05-01, 06-01, 06-17, 07-01, H=90 → data/backtest/
python scripts/backtest.py --T 2026-06-17   # 한 시점만
python scripts/backtest_variants.py         # 산출식 변형(음수 규칙 없음, 배출 무시, 두 축)을 기준일 11개·기간 4종에서 비교 → data/backtest/variants.md
```

창 정의: DefiLlama 의 `total30d` 는 기준일을 제외한 직전 30일 합계다(`audit_chart.py` 로 2026-10-10 확인). 백테스트도 같은 창을 쓴다.
T 이후 구조가 바뀐 종목은 `backtest.py` 의 `STRUCTURE` 표로 T 시점 기준으로 되돌리거나 제외한다(`hist_k` 는 달력 개월 수로 다시 계산). `inc_qty30` 이 있는 NEAR·VVV 의 배출액은 수량 × T 시점 가격으로 환산하고, 나머지 배출액은 현재 달러값이라 근사다. 순위상관은 반올림하지 않은 값으로 계산한다. 결과와 판정(성장 계수 채택 여부 등)은 `data/backtest/summary.md` 에 있다.

### 점검 도구

```
python scripts/audit_chart.py --asof 2026-09-19     # 8종목의 일별 기록 양상과 저장값 대조 (보고만, 수정하지 않음)
python scripts/seed_snapshots.py --force            # 2026-09-17·09-19 스냅샷 재생성 (seeded: true). 고정본 universe 를 쓴다
```

## 인계 문서와 다르게 한 것

- **STONK CoinGecko id** `stonk-2` → `stonk-3`. 2026-10-10 에 `stonk-2` 는 CoinGecko 에서 "coin not found" 였고, DefiLlama 의 `gecko_id` 와 Solana 주소(`6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx`)가 `stonk-3` 과 일치했다. `coins.llama.fi` 가 `stonk-3` 가격을 돌려주므로 CoinGecko 폴백 없이 46행이 나온다.
- **가격 폴백 순서**에 컨트랙트 주소 조회를 CoinGecko 앞에 두었다. 같은 호스트이고 키가 없으며, CoinGecko 는 공용 IP 에서 간헐적으로 429 를 돌려준다.
- **`total30d: null`** 은 0 이 아니라 수집 실패로 다룬다(carried → 2주 뒤 제외). 어댑터가 멈춘 것을 조용히 0 으로 쌓지 않기 위해서다.
- **stale_suspect** 에서 hr30·hr7 이 둘 다 0 인 행은 제외한다. 정지 종목이 매주 표시되면 경고가 의미를 잃는다.
