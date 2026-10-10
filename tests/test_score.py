# -*- coding: utf-8 -*-
"""
score.py 가 score_reference.py 와 같은 결과를 내는지 검증한다. (HANDOVER.md 7-4절, 14장 6단계)

  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import common as C          # noqa: E402
import score as S           # noqa: E402
import score_reference as R  # noqa: E402

TOL = 0.002


class ScoreMatchesReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = C.load_universe(os.path.join(ROOT, "data", "universe.json"))

    def _compare(self, date):
        case = R.SELFTEST[date]
        ours = S.score(self.universe, case["inputs"], date, overrides=case.get("overrides"))
        ref = R.score(self.universe, case["inputs"], date, overrides=case.get("overrides"))
        self.assertEqual([r["t"] for r in ours["rows"]], [r["t"] for r in ref["rows"]], "정렬 순서")
        by_ref = {r["t"]: r for r in ref["rows"]}
        for r in ours["rows"]:
            x = by_ref[r["t"]]
            for k in ("mc", "raw", "net", "adj"):
                self.assertAlmostEqual(r[k], x[k], delta=TOL, msg=f"{date} {r['t']} {k}")
            self.assertEqual(r["g"], x["g"], f"{date} {r['t']} g")
            self.assertEqual(r["rr"] is None, x["rr"] is None, f"{date} {r['t']} rr None")
            if r["rr"] is not None:
                self.assertAlmostEqual(r["rr"], x["rr"], delta=TOL, msg=f"{date} {r['t']} rr")
            self.assertEqual(list(r.keys()), list(x.keys()), f"{date} {r['t']} 행 필드 순서")
            self.assertEqual(r["k"], x["k"], f"{date} {r['t']} k")
        # 저장값(expect)과도 직접 대조한다
        for sym, (mc, raw, net, adj, g, rr) in case["expect"].items():
            r = next(rw for rw in ours["rows"] if rw["t"] == sym)
            self.assertAlmostEqual(r["mc"], mc, delta=max(0.01, abs(mc) * 1e-5), msg=f"{date} {sym} mc(저장값)")
            self.assertAlmostEqual(r["raw"], raw, delta=TOL, msg=f"{date} {sym} raw(저장값)")
            self.assertAlmostEqual(r["net"], net, delta=TOL, msg=f"{date} {sym} net(저장값)")
            self.assertAlmostEqual(r["adj"], adj, delta=TOL, msg=f"{date} {sym} adj(저장값)")
            self.assertEqual(r["g"], g, f"{date} {sym} g(저장값)")

    def test_2026_09_17(self):
        self._compare("2026-09-17")

    def test_2026_09_19(self):
        self._compare("2026-09-19")

    def test_negative_rule(self):
        """순 캡처율이 음수이면 계수를 곱하지 않는다(7-1절)."""
        tok = {"t": "X", "n": "X", "slug": "x", "cg": "x", "circ": 1e6, "fdv": 4.0, "acc": "매수 후 보유",
               "auto": "불규칙", "hist_k": 0.5, "hist": "", "inc30": 10.0, "note": ""}
        r = S.score_one(tok, 1.0, 1_000_000, 100_000, C.K_ACC, C.K_AUTO, set())
        self.assertLess(r["net"], 0)
        self.assertEqual(r["adj"], r["net"])
        self.assertEqual(r["g"], "D")

    def test_build_rows_carry_and_stale(self):
        """실패 종목은 직전 값을 쓰고 carried, 같은 값이면 stale_suspect, 2주 연속 실패면 제외."""
        uni = {"formula": self.universe["formula"],
               "tokens": [t for t in self.universe["tokens"] if t["t"] in ("HYPE", "AERO", "ORCA", "JTO")]}
        prev = {"date": "2026-09-19", "rows": [
            {"t": "HYPE", "g": "B", "adj": 1.6, "price": 90.0, "hr30": 6.4e7, "hr7": 1.3e7},
            {"t": "AERO", "g": "B+", "adj": 3.7, "price": 0.67, "hr30": 14239916, "hr7": 1596476,
             "carried": True, "carried_fields": ["price"]},
            {"t": "ORCA", "g": "A", "adj": 5.0, "price": 1.46, "hr30": 410060, "hr7": 119271},
            {"t": "JTO", "g": "D", "adj": 0, "price": 0.44, "hr30": 0, "hr7": 0},
        ]}
        raw = {"hr": {"HYPE": {"total30d": None, "total7d": None},          # 귀속액 실패 → carry
                      "AERO": {"total30d": 15e6, "total7d": 2e6},
                      "ORCA": {"total30d": 410060, "total7d": 119271, "total1y": 2e6},   # 직전과 동일 → stale
                      "JTO": {"total30d": 0, "total7d": 0}},
               "price": {"HYPE": 85.0, "AERO": None, "ORCA": 2.4, "JTO": 0.5}}       # AERO 가격 2주 연속 실패 → 제외
        rows, failures, carried, stale = S.build_rows(uni, raw, prev, "2026-10-10")
        by = {r["t"]: r for r in rows}
        self.assertIn("HYPE", by)
        self.assertTrue(by["HYPE"]["carried"])
        self.assertEqual(by["HYPE"]["carried_fields"], ["hr30", "hr7"])
        self.assertEqual(by["HYPE"]["hr30"], 6.4e7)
        self.assertNotIn("AERO", by)
        self.assertEqual([f["t"] for f in failures], ["AERO"])
        self.assertTrue(by["ORCA"].get("stale_suspect"))
        self.assertEqual(stale, ["ORCA"])
        self.assertIsNone(by["JTO"].get("stale_suspect"))        # 0·0 은 제외
        self.assertAlmostEqual(by["ORCA"]["growth"], 410060 / (2e6 / C.ANN), places=2)

    def test_recompute_inc(self):
        uni = {"tokens": [dict(t) for t in self.universe["tokens"] if t["t"] in ("NEAR", "VVV", "ETH")]}
        changed = S.recompute_inc(uni, {"NEAR": 5.0, "VVV": None, "ETH": 2500.0}, "2026-10-10")
        by = {t["t"]: t for t in uni["tokens"]}
        self.assertEqual([c[0] for c in changed], ["NEAR"])
        self.assertAlmostEqual(by["NEAR"]["inc30"], 2654000 * 5.0 / 1e6, places=3)
        self.assertEqual(by["NEAR"]["inc_ref_date"], "2026-10-10")
        self.assertEqual(by["VVV"]["inc30"], 5.137)               # 가격 실패 → 직전 값 유지
        self.assertEqual(by["ETH"]["inc30"], 121.0)               # inc_qty30 없음 → 그대로


if __name__ == "__main__":
    unittest.main()
