# 브리지 작업 지시문 초안 (HANDOVER.md 11-1절)

claude.ai 예약 작업 `토큰캡처 주간 갱신` (`trig_01VBieQsYUtDeQzELqVakfpP`)의 지시문과 일정을 아래로 교체한다.
일정은 `30 10 * * 6` (UTC, 토요일 19:30 KST). 이 지시문은 저장소에 `main` 브랜치가 있어야 동작한다.

---

토큰캡처 등급표 아티팩트를 GitHub 저장소의 최신 스냅샷으로 갱신하는 주간 브리지 작업입니다. 수집과 채점은 GitHub Actions(저장소 tlzkrh1029/token-capture, 토요일 15:17 KST, 보충 실행 16:47 KST. GitHub 쪽 지연으로 실제 실행은 몇 시간 늦을 수 있음)가 이미 끝냈으므로, 이 작업은 결과 파일 하나를 읽어 아티팩트 저장소에 넣기만 합니다. WebFetch 로 수치를 수집하거나 값을 다시 계산하지 않습니다. 무인 실행이므로 질문하지 말고 끝까지 진행합니다.

1. 파일 받기. Bash 로 `curl -sSL https://raw.githubusercontent.com/tlzkrh1029/token-capture/main/data/latest.json -o /tmp/latest.json` 을 실행합니다. 명령이 거부되거나 실패하면 같은 명령을 한 번 더 실행하고, 그래도 안 되면 `python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/tlzkrh1029/token-capture/main/data/latest.json', '/tmp/latest.json')"` 로 받습니다. 그래도 실패하면(404, 네트워크 오류) "GitHub 저장소에서 latest.json 을 읽지 못했다"고 보고하고 끝냅니다.

2. 신선도 확인. `/tmp/latest.json` 의 `date` 가 오늘(KST) 또는 어제가 아니면 "GitHub 쪽이 이번 주 실행을 못 했다(마지막 date …)"고 보고하고 끝냅니다. 아티팩트 저장소에는 아무것도 쓰지 않습니다. 보고에는 "GitHub 의 Actions 탭에서 tokencapture-weekly 를 Run workflow 로 수동 실행한 뒤 이 작업을 다시 실행하면 된다"는 안내를 덧붙입니다.

3. 중복 확인. 아티팩트 `https://claude.ai/artifact/YQg1tsjpAD2WnYjTpxsxfQ` 의 저장소에서 ArtifactData(read_db) 로 `meta/state` 를 읽습니다. `lastWeekly` 가 `/tmp/latest.json` 의 `date` 와 같으면 "이미 반영됨"이라고 보고하고 끝냅니다.

4. 쓰기.
   - `snapshots/<date>` 에 `{"date": <date>, "rows": <rows>}` 를 set 합니다. `rows` 는 latest.json 의 `rows` 를 그대로 씁니다(필드를 고치거나 빼지 않습니다).
   - `meta/state` 를 update 해 `lastWeekly` 를 `<date>` 로 바꿉니다.
   - latest.json 의 `meta.universe_updated` 가 `meta/universe` 문서의 `updated` 와 다르면, `curl -sSL https://raw.githubusercontent.com/tlzkrh1029/token-capture/main/data/universe.json -o /tmp/universe.json` 으로 받아 `meta/universe` 에 set 합니다(`if_version` 은 방금 읽은 현재 버전). 첫 실행에서는 저장소의 `meta/universe` 가 version 4(2026-09-17)이고 저장소 파일의 `updated` 는 그보다 뒤이므로 반드시 이 갱신이 일어나야 합니다.

5. 보고(푸시 알림). 다음을 짧게 적습니다.
   - 등급 변동: latest.json 의 `meta.grade_changes` (종목, 이전 → 이후 등급)
   - 상위 5개: `rows` 앞 다섯 행의 `t`, `adj`, `g`
   - 순 캡처율이 양수에서 음수로 바뀐 종목: `rows` 의 `net` 이 음수인데 직전 스냅샷(`snapshots/<meta.previous>`)에서는 양수였던 종목
   - `meta.carried` (직전 값을 쓴 종목과 필드), `meta.stale_suspect` (직전 주와 hr30·hr7 이 같은 종목. 주기형 목록 종목은 정상이어도 같을 수 있다는 점을 함께 적음), `meta.failures`
   - GitHub 실행 여부(2단계에서 멈췄으면 그 사실)

주의: 저장소(tlzkrh1029/token-capture)에 푸시하거나 파일을 고치지 않습니다. 다른 아티팩트를 만들지 않습니다.

---

## 교체 전 지시문 (2026-10-10 교체, 되돌릴 때 참고)

`trig_01VBieQsYUtDeQzELqVakfpP` 의 교체 전 이름은 "토큰캡처 주간 갱신 (토 18:00 KST)", 일정은 `0 9 * * 6` 이었다. 교체 전 지시문은 WebFetch 로 `coins.llama.fi`·`api.llama.fi` 를 직접 불러 파이썬으로 채점하고 `snapshots/<date>` 와 `meta/state` 를 쓰며, `meta/state.nextResearch` 이후면 격주 리서치까지 수행하는 내용이었다(HANDOVER.md 3-3절·4장에 실패 원인이 정리되어 있다). 격주 리서치 절차는 HANDOVER.md 11-3절에 그대로 남아 있다.

`trig_01QeLt5P1qf3RcYjRTGVbE3D` (토큰캡처 보완 실행, 토 21:00 KST, `0 12 * * 6`)는 같은 날 비활성화했다. HANDOVER.md 11-2절은 삭제를 지시하지만, 예약 작업을 삭제하면 그 작업이 만든 세션 기록도 함께 지워지므로 삭제는 사용자 확인 뒤에 한다.
