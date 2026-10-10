# -*- coding: utf-8 -*-
"""
seed_snapshots.py : 첫 실행 전에 직전 스냅샷을 준비한다. (HANDOVER-ADDENDUM.md 3절)

score_reference.py 의 SELFTEST 입력(2026-09-17 38종목, 2026-09-19 46종목)을 score.py 로 다시 계산해
data/snapshots/<date>.json 에 넣고 history.csv 에도 두 날짜의 행을 추가한다.
2026-09-19 는 selftest 와 같이 NEAR 만 당시 정의(slug near, version 4)로 덮어쓴다.
두 파일에는 최상위에 "seeded": true 를 넣어 재생성본임을 표시한다.
universe 는 기본적으로 고정본 tests/fixtures/universe-2026-10-09.json 을 쓴다. data/universe.json 은 score.py 가 매주
inc30 을 다시 쓰므로 시드 재생성의 기준으로 쓸 수 없다. 이미 있는 스냅샷은 --force 없이는 덮어쓰지 않는다.

  python scripts/seed_snapshots.py [--universe tests/fixtures/universe-2026-10-09.json] [--snapshot-dir data/snapshots] [--history data/history.csv] [--force]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C          # noqa: E402
import score as S           # noqa: E402
import score_reference as R  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=C.UNIVERSE_FIXTURE_PATH)
    ap.add_argument("--snapshot-dir", default=C.SNAPSHOT_DIR)
    ap.add_argument("--history", default=C.HISTORY_PATH)
    ap.add_argument("--force", action="store_true", help="이미 있는 스냅샷 파일을 덮어쓴다")
    a = ap.parse_args(argv)
    universe = C.load_universe(a.universe)
    for date, case in sorted(R.SELFTEST.items()):
        path = os.path.join(a.snapshot_dir, f"{date}.json")
        if os.path.exists(path) and not a.force:
            C.log(f"[seed] {date} 는 이미 있습니다. 덮어쓰려면 --force (건너뜀)")
            continue
        snap = S.score(universe, case["inputs"], date, overrides=case.get("overrides"))
        snap["seeded"] = True
        snap["seed_note"] = ("score_reference.py 의 SELFTEST 입력으로 재생성한 스냅샷. " + case.get("note", "")).strip()
        C.dump_json(snap, path)
        S.append_history(snap, a.history, seeded=True)
        top = ", ".join(f"{r['t']} {r['adj']:.2f}({r['g']})" for r in snap["rows"][:5])
        C.log(f"[seed] {date} {len(snap['rows'])}행 → {os.path.relpath(path, C.REPO_ROOT)}  상위5: {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
