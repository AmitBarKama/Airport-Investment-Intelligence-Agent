"""Backtest: does the model recover a list it was never shown?

The FAA independently publishes which US airports are capacity-constrained:

    Level 3 (slot-controlled)      JFK, LGA, DCA
    Level 2 (schedule-facilitated) EWR, ORD, SFO, LAX

The saturation pillar is built from traffic, delay and runway capacity. It
never sees that designation. If it is measuring anything real, those airports
should surface near the top of a national saturation ranking. That is a
backtest against an external regulator rather than against my own judgment,
and it is the single most convincing evidence the score is not arbitrary.

IMPORTANT: this test is only meaningful against REAL traffic data. Under the
synthetic gravity model the traffic volumes are modelled from runway
infrastructure, so the test is skipped rather than allowed to pass or fail on
numbers that mean nothing. Load a BTS T-100 export and it runs for real.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.scoring.composite import score_cohort
from api.scoring.pillars import compute_pillars
from api.scoring.profiles import resolve_weights

LEVEL_3 = ["JFK", "LGA", "DCA"]
LEVEL_2 = ["EWR", "ORD", "SFO", "LAX"]
FAA_CONSTRAINED = LEVEL_3 + LEVEL_2


def data_mode():
    try:
        return db.meta().get("data_mode")
    except Exception:
        return None


class TestFAABacktest(unittest.TestCase):

    @unittest.skipUnless(data_mode() == "real",
                         "requires REAL BTS T-100 traffic; synthetic volumes make "
                         "this test meaningless (see module docstring)")
    def test_saturation_recovers_faa_constrained_airports(self):
        cohort = db.list_airports(limit=1000)
        pillars = compute_pillars(cohort)
        ranked = sorted(
            [(p["saturation"] or 0, p["code"]) for p in pillars], reverse=True)
        top = [c for _, c in ranked[:25]]
        missing = [a for a in FAA_CONSTRAINED if a not in top]
        self.assertEqual(missing, [],
                         f"saturation pillar missed FAA-constrained airports: {missing}")

    @unittest.skipUnless(data_mode() == "real", "requires REAL traffic data")
    def test_slot_controlled_airports_are_top_decile_on_saturation(self):
        """Slot-controlled airports must rank near the top nationally.

        This checks RANK, not the absolute FAA tier, and deliberately so.
        The tier depends on Annual Service Volume, and for airports without a
        published FAA capacity profile our ASV comes from a runway-count
        lookup with placeholder values. That lookup credits JFK with the
        capacity of a generic four-runway airfield, which is far more than it
        really has: JFK is slot-controlled precisely because its usable
        capacity is much lower than its runway count suggests. So JFK lands in
        tier C on our numbers even though it is demonstrably constrained.

        That is a known weakness of the ASV placeholder, not of the ranking,
        and it is exactly why `asv_source` is reported with every answer and
        drags the confidence score down. Ranking is the robust claim; the
        absolute tier is only as good as the capacity denominator.
        """
        cohort = db.list_airports(limit=1000)
        pillars = compute_pillars(cohort)
        ranked = sorted([(p["saturation"] or 0, p["code"]) for p in pillars], reverse=True)
        order = [c for _, c in ranked]
        decile = max(10, len(order) // 10)
        for code in FAA_CONSTRAINED:
            if code in order:
                self.assertLess(order.index(code), decile,
                                f"{code} is FAA capacity-constrained but ranks "
                                f"{order.index(code) + 1} of {len(order)} on saturation")


class TestStructuralBacktest(unittest.TestCase):
    """These run on ANY data mode, because they test REAL structural facts.

    Runway geometry comes from OurAirports regardless of traffic mode, so
    these assertions are meaningful even in synthetic mode.
    """

    def setUp(self):
        if data_mode() is None:
            self.skipTest("no database; run python3 -m etl.build")

    def test_closely_spaced_parallels_are_identified(self):
        """SFO and SEA cannot run independent parallel approaches; the wide-
        spaced hubs can. This is computed from real threshold coordinates."""
        for code in ("SFO", "SEA"):
            a = db.get_airport(code)
            if a:
                self.assertTrue(a["imc_constrained"],
                                f"{code} should be flagged IMC-constrained")
        for code in ("DFW", "DEN", "ORD", "ATL"):
            a = db.get_airport(code)
            if a:
                self.assertFalse(a["imc_constrained"],
                                 f"{code} has widely spaced parallels")

    def test_sfo_parallel_separation_matches_published_geometry(self):
        """SFO's 28L/28R are documented at roughly 750 ft apart."""
        a = db.get_airport("SFO")
        if not a:
            self.skipTest("SFO not in database")
        self.assertIsNotNone(a["max_parallel_separation_ft"])
        self.assertTrue(700 <= a["max_parallel_separation_ft"] <= 800,
                        f"expected ~750 ft, got {a['max_parallel_separation_ft']}")

    def test_curated_slot_levels_loaded(self):
        for code in LEVEL_3:
            a = db.get_airport(code)
            if a:
                self.assertEqual(a["slot_level"], 3, code)
        for code in LEVEL_2:
            a = db.get_airport(code)
            if a:
                self.assertEqual(a["slot_level"], 2, code)

    def test_least_expandable_airports_score_low_on_feasibility(self):
        """LGA and SNA are the canonical 'congested but unbuildable' cases."""
        for code in ("LGA", "SNA", "DCA"):
            a = db.get_airport(code)
            if a:
                self.assertLess(a["feasibility"], 0.2, code)
        for code in ("DEN", "DFW"):
            a = db.get_airport(code)
            if a:
                self.assertGreater(a["feasibility"], 0.7, code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
