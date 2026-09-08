"""Pure-function tests for the scoring engine. No network, no LLM, no database."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.scoring.normalize import (cagr, percentile, percentile_rank, safe_div,
                                   winsorize, winsorized_percentile_rank)
from api.scoring.composite import (assign_tier, geometric_score,
                                   pillar_contributions, confidence)
from api.scoring.profiles import resolve_weights
from api.scoring.pillars import compute_pillars


class TestNormalize(unittest.TestCase):
    def test_percentile_rank_is_ordered_and_bounded(self):
        r = percentile_rank([1, 2, 3, 4, 5])
        self.assertEqual(r, sorted(r))
        self.assertTrue(all(0 < x <= 1 for x in r))

    def test_ties_share_a_midrank(self):
        r = percentile_rank([5, 5, 5, 9])
        self.assertEqual(r[0], r[1])
        self.assertEqual(r[1], r[2])
        self.assertGreater(r[3], r[0])

    def test_missing_values_stay_missing(self):
        r = percentile_rank([1, None, 3])
        self.assertIsNone(r[1])

    def test_floor_prevents_zero(self):
        r = percentile_rank([1, 2, 3], floor=0.05)
        self.assertGreaterEqual(min(r), 0.05)

    def test_winsorize_clamps_outliers(self):
        vals = [1, 2, 3, 4, 1000]
        w = winsorize(vals, 5, 95)
        self.assertLess(max(w), 1000)

    def test_percentile_matches_known_values(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3.0)
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0), 1.0)
        self.assertEqual(percentile([1, 2, 3, 4, 5], 100), 5.0)

    def test_safe_div_refuses_to_invent_values(self):
        self.assertIsNone(safe_div(1, 0))
        self.assertIsNone(safe_div(None, 5))
        self.assertEqual(safe_div(10, 4), 2.5)

    def test_cagr(self):
        self.assertAlmostEqual(cagr(100, 121, 2), 0.10, places=6)
        self.assertIsNone(cagr(0, 100, 2))
        self.assertIsNone(cagr(100, 100, 0))


class TestComposite(unittest.TestCase):
    def test_faa_tier_thresholds(self):
        # FAA AC 150/5060-5: plan at 60% of ASV, build at 80%.
        self.assertEqual(assign_tier(0.85)["tier"], "A")
        self.assertEqual(assign_tier(0.80)["tier"], "A")
        self.assertEqual(assign_tier(0.79)["tier"], "B")
        self.assertEqual(assign_tier(0.60)["tier"], "B")
        self.assertEqual(assign_tier(0.59)["tier"], "C")
        self.assertEqual(assign_tier(0.10)["tier"], "D")
        self.assertIsNone(assign_tier(None)["tier"])

    def test_geometric_mean_is_not_compensatory(self):
        """The core economic claim: a zero pillar cannot be bought off.

        An airport that is maximally congested but impossible to build on must
        not outrank a balanced one. Under an arithmetic mean it would.
        """
        w = {"saturation": .3, "unmet_demand": .25, "growth": .2,
             "feasibility": .15, "monetization": .1}
        jammed_unbuildable = {"saturation": 1.0, "unmet_demand": 1.0,
                              "growth": 1.0, "feasibility": 0.01, "monetization": 1.0}
        balanced = {k: 0.55 for k in w}
        self.assertLess(geometric_score(jammed_unbuildable, w),
                        geometric_score(balanced, w))
        arithmetic = sum(jammed_unbuildable[k] * w[k] for k in w) * 100
        self.assertGreater(arithmetic, geometric_score(balanced, w),
                           "arithmetic mean should have ranked it higher - "
                           "that is precisely why we use geometric")

    def test_score_is_bounded(self):
        w = {"saturation": 1.0}
        self.assertAlmostEqual(geometric_score({"saturation": 1.0}, w), 100.0, places=6)
        self.assertGreater(geometric_score({"saturation": 0.01}, w), 0)

    def test_contributions_sum_to_one(self):
        w, _ = resolve_weights("investment")
        p = {"saturation": .6, "unmet_demand": .4, "growth": .5,
             "feasibility": .3, "monetization": .8}
        rows = pillar_contributions(p, w)
        self.assertAlmostEqual(sum(r["share_of_shortfall"] for r in rows), 1.0, places=3)

    def test_confidence_penalises_weak_inputs(self):
        good = confidence({"a": 1.0, "b": 1.0}, "faa_capacity_profile", 2)
        poor = confidence({"a": 0.3, "b": 0.2}, "peer_regression", 30)
        self.assertGreater(good["score"], poor["score"])
        self.assertEqual(good["label"], "high")
        self.assertTrue(poor["reasons"])


class TestPillars(unittest.TestCase):
    def _cohort(self):
        return [
            dict(code="AAA", dc_ratio=0.9, taxi_out_p50=22, del15_rate=.3, peaking=3.0,
                 slot_level=3, spill_rate=.2, upgauge_delta=.03, catchment_gap=.1,
                 cagr_pax_5y=.01, taf_cagr=.01, intl_share=.2, lh_share=.1,
                 gauge=140, n_destinations=90, feasibility=0.1),
            dict(code="BBB", dc_ratio=0.4, taxi_out_p50=11, del15_rate=.1, peaking=1.6,
                 slot_level=None, spill_rate=.04, upgauge_delta=.001, catchment_gap=.6,
                 cagr_pax_5y=.04, taf_cagr=.03, intl_share=.03, lh_share=.0,
                 gauge=110, n_destinations=25, feasibility=0.9),
        ]

    def test_pillars_bounded_and_present(self):
        for p in compute_pillars(self._cohort()):
            for k in ("saturation", "unmet_demand", "growth", "feasibility", "monetization"):
                self.assertIsNotNone(p[k], k)
                self.assertGreaterEqual(p[k], 0.0)
                self.assertLessEqual(p[k], 1.0)

    def test_slot_control_raises_unmet_demand(self):
        a, b = compute_pillars(self._cohort())
        self.assertGreater(a["unmet_demand"], b["unmet_demand"])

    def test_missing_inputs_reduce_coverage(self):
        rows = self._cohort()
        rows[1] = {**rows[1], "spill_rate": None, "upgauge_delta": None,
                   "catchment_gap": None}
        a, b = compute_pillars(rows)
        self.assertLess(b["coverage"]["unmet_demand"], a["coverage"]["unmet_demand"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
