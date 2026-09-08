"""Tool-layer contract tests. Needs data/airports.db (run `python3 -m etl.build`)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.agent import tools as T
from unittest import mock

from api.agent.loop import numeric_guard, run as _run_agent

def keyless():
    """Pin the keyword planner for the duration of a block.

    These tests describe what the KEYLESS planner does with a sentence -- that a
    recall question calls no tool, that a named region lands in `last_region`.
    Left unpinned they drove whichever planner happened to be configured, so the
    moment a model key was added the suite quietly became a live-model
    integration test: slow, network-dependent, and asserting behaviour no LLM
    guarantees. The model path has its own test; see test_model_path.py.
    """
    return mock.patch("api.agent.llm.llm_available", return_value=False)


def run_agent(*args, **kwargs):
    """Drive a full turn with the keyword planner pinned."""
    with keyless():
        return list(_run_agent(*args, **kwargs))


def has_db():
    try:
        db.meta(); return True
    except Exception:
        return False


@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestTools(unittest.TestCase):

    def test_every_tool_reports_provenance(self):
        """Provenance must travel WITH the number, so the model cannot quote a
        figure without its caveat also being in context."""
        results = {
            "list_airports": T.list_airports(region="new england"),
            "rank_airports": T.rank_airports(region="new england", profile="terminal"),
            "airport_profile": T.airport_profile("SFO"),
            "flight_mix": T.flight_mix("ANC"),
            "unmet_demand": T.unmet_demand("SFO"),
            "compare_airports": T.compare_airports(["LAX", "SNA"]),
            "explain_score": T.explain_score("BOS"),
            "sensitivity_analysis": T.sensitivity_analysis(region="new england", n_draws=50),
        }
        for name, r in results.items():
            self.assertNotIn("error", r, f"{name} errored: {r.get('error')}")
            self.assertIn("assumptions", r, name)
            self.assertIn("data_vintage", r, name)

    def test_unknown_airport_errors_cleanly(self):
        r = T.airport_profile("ZZZZZ")
        self.assertIn("error", r)

    def test_unknown_region_lists_valid_options(self):
        r = T.list_airports(region="Middle Earth")
        self.assertIn("error", r)
        self.assertIn("known_regions", r)

    def test_unknown_profile_is_rejected(self):
        r = T.rank_airports(region="new england", profile="nonsense")
        self.assertIn("error", r)
        self.assertIn("available_profiles", r)

    def test_compare_requires_two(self):
        self.assertIn("error", T.compare_airports(["SFO"]))

    def test_flight_mix_returns_denominators(self):
        """Ratios without denominators are unfalsifiable."""
        r = T.flight_mix("ANC")
        self.assertIn("total_departures", r["headline"])
        self.assertIn("long_haul_departures", r["headline"])
        self.assertRegex(r["headline"]["stated_as"], r"\d[\d,]* of \d[\d,]* departures")

    def test_long_haul_threshold_is_disclosed_and_configurable(self):
        a = T.flight_mix("ANC", long_haul_nmi=2000)
        b = T.flight_mix("ANC", long_haul_nmi=3500)
        self.assertGreater(a["headline"]["long_haul_share"], b["headline"]["long_haul_share"])
        self.assertIn("No ICAO/IATA standard", a["assumptions"]["long_haul_note"])

    def test_weights_can_be_overridden_and_are_renormalised(self):
        r = T.rank_airports(region="new england", weights={"growth": 5.0})
        self.assertAlmostEqual(sum(r["weights"].values()), 1.0, places=6)
        self.assertGreater(r["weights"]["growth"], 0.5)

    def test_sna_legal_constraint_is_surfaced(self):
        """A legally capped airport must not read as simply uncongested."""
        r = T.compare_airports(["LAX", "SNA"])
        sna = next(a for a in r["airports"] if a["code"] == "SNA")
        self.assertTrue(sna["curfew"])
        self.assertTrue(sna["passenger_cap"])
        self.assertIn("settlement", (sna["constraint"] or "").lower())
        self.assertIn("DEMAND-constrained", r["interpretation_warning"])

    def test_sfo_runway_geometry_is_computed_from_real_coordinates(self):
        r = T.airport_profile("SFO")
        sep = r["capacity"]["widest_parallel_separation_ft"]
        self.assertIsNotNone(sep)
        self.assertLess(sep, 1000, "SFO's parallels are ~750 ft apart")
        self.assertFalse(r["capacity"]["independent_ifr_approaches"])
        self.assertTrue(r["capacity"]["imc_constrained"])

    def test_unmet_demand_separates_measured_from_inferred(self):
        r = T.unmet_demand("SFO")
        self.assertTrue(any(d["type"] == "measured" for d in r["drivers"]))
        self.assertTrue(r["unknown"])
        self.assertIn("MEASURED", r["epistemic_note"])

    def test_synthetic_data_is_flagged(self):
        r = T.airport_profile("BOS")
        v = r["data_vintage"]
        if v.get("data_mode") == "synthetic":
            self.assertIsNotNone(v.get("warning"))
            self.assertIn("SYNTHETIC", v["warning"])


@unittest.skipUnless(has_db(), "no database")
class TestAgentLoop(unittest.TestCase):

    def test_numeric_guard_classifies_by_provenance(self):
        """The guard now separates 'made up' from 'the publisher's claim'."""
        unverified, external = numeric_guard("about 12,345 passengers", ['{"pax": 12345}'])
        self.assertEqual((unverified, external), ([], []))

        unverified, _ = numeric_guard("about 99,999 passengers", ['{"pax": 12345}'])
        self.assertIn("99,999", unverified)

        # small numbers and years are ignored as ordinals/dates
        self.assertEqual(numeric_guard("ranked 3rd in 2025", ["{}"]), ([], []))

        # a figure that appears only in web findings is real but not ours
        unverified, external = numeric_guard(
            "a $8,500,000,000 programme", ["{}"],
            ['{"claim": "the $8,500,000,000 terminal programme"}'])
        self.assertEqual(unverified, [])
        self.assertIn("8,500,000,000", external)

    def test_turn_terminates_with_done(self):
        evs = list(run_agent("What is the unmet flight demand in SFO airport and why?"))
        self.assertEqual(evs[-1]["type"], "done")
        self.assertTrue(any(e["type"] == "tool_trace" for e in evs))

    def test_state_carries_referents_for_followups(self):
        evs = list(run_agent("Which airports in New England are candidates for terminal expansion?"))
        state = evs[-1]["state"]
        self.assertEqual(state.get("last_region"), "new england")
        self.assertTrue(state.get("last_airports"))
        follow = list(run_agent("Is that ranking stable?", state=state))
        names = [e["name"] for e in follow if e["type"] == "tool_trace"]
        self.assertIn("sensitivity_analysis", names)

    def test_answers_carry_no_unverified_numbers(self):
        for q in ("What is the percentage of long haul flights out of Anchorage airport?",
                  "Compare LA and Santa Ana airport congestion levels."):
            done = list(run_agent(q))[-1]
            self.assertEqual(done.get("unverified_numbers"), [], q)


if __name__ == "__main__":
    unittest.main(verbosity=2)
