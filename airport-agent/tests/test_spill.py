"""Spill-model behaviour tests."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.scoring.spill import (expected_load, expected_spill, spill_estimate,
                               solve_unconstrained_demand, DEFAULT_K)


class TestSpill(unittest.TestCase):
    SEATS = 1_000_000

    def test_spill_rises_with_load_factor(self):
        rates = [spill_estimate(self.SEATS * lf, self.SEATS)["spill_rate"]
                 for lf in (0.6, 0.7, 0.8, 0.85, 0.9, 0.95)]
        self.assertEqual(rates, sorted(rates))

    def test_low_load_factor_means_negligible_spill(self):
        self.assertLess(spill_estimate(self.SEATS * 0.6, self.SEATS)["spill_rate"], 0.02)

    def test_high_load_factor_means_material_spill(self):
        self.assertGreater(spill_estimate(self.SEATS * 0.95, self.SEATS)["spill_rate"], 0.20)

    def test_solver_round_trips(self):
        """Recovered demand must reproduce the observed load."""
        for lf in (0.7, 0.85, 0.95):
            pax = self.SEATS * lf
            mu = solve_unconstrained_demand(pax, self.SEATS)
            self.assertAlmostEqual(
                expected_load(mu, DEFAULT_K * mu, self.SEATS), pax, delta=pax * 1e-4)

    def test_demand_never_below_observed(self):
        for lf in (0.5, 0.8, 0.99):
            r = spill_estimate(self.SEATS * lf, self.SEATS)
            self.assertGreaterEqual(r["unconstrained_demand"], r["observed_pax"])

    def test_expected_spill_at_capacity_equals_half_normal_mean(self):
        # With mu == S, E[(D-S)+] = sigma * phi(0) = sigma * 0.3989...
        sigma = 1000.0
        self.assertAlmostEqual(expected_spill(10_000, sigma, 10_000),
                               sigma * 0.3989422804, places=4)

    def test_degenerate_inputs_do_not_raise(self):
        for args in ((0, 100), (100, 0), (None, None), (-5, 10)):
            self.assertIn("note", spill_estimate(*args))


if __name__ == "__main__":
    unittest.main(verbosity=2)
