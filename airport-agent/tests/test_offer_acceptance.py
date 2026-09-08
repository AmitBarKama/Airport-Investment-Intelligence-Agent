"""Answering "yes" to the agent's own question must do the thing.

The reported symptom: "the conversation mode has no context to my answer, I say
yes for its question and it can't continue." Every answer ends with an offer,
but offers were plain strings with no action attached and nothing persisted, so
an affirmative matched no handler and fell through to the out-of-scope refusal:
the agent asking a question and then refusing to answer it.
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.agent import render, tools as T
from api.agent.loop import run
from api.agent.tools import TOOLS
from api.agent import schemas

REFUSAL = "I can't help with that one"


def has_db():
    try:
        db.meta(); return True
    except Exception:
        return False


def converse(questions):
    """Drive real turns with the keyword planner pinned."""
    state, log = {}, []
    with mock.patch("api.agent.llm.llm_available", return_value=False):
        for q in questions:
            tool, text, followup = None, "", None
            for ev in run(q, [], state, False):
                if ev["type"] == "tool_trace":
                    tool = ev["name"]
                elif ev["type"] == "done":
                    state, text = ev["state"], ev["text"]
                    followup = ev.get("followup")
            log.append({"q": q, "tool": tool, "text": text, "followup": followup})
    return state, log


@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestAcceptingAnOffer(unittest.TestCase):

    def test_yes_please_runs_the_offered_analysis(self):
        _, log = converse(["top 5 airports to invest in", "yes please"])
        self.assertTrue(log[0]["followup"], "nothing was offered to accept")
        self.assertEqual(log[1]["tool"], "explain_score")
        self.assertNotIn(REFUSAL, log[1]["text"])

    def test_every_plain_affirmative_works(self):
        for word in ("yes", "sure", "go on", "go ahead", "do it", "ok"):
            _, log = converse(["top 5 airports to invest in", word])
            self.assertEqual(log[1]["tool"], "explain_score", word)
            self.assertNotIn(REFUSAL, log[1]["text"], word)

    def test_the_other_offer_can_be_chosen(self):
        _, log = converse(["top 5 airports to invest in", "the other one"])
        self.assertEqual(log[1]["tool"], "sensitivity_analysis")

    def test_an_ordinal_still_means_an_airport_not_an_offer(self):
        """"the second one" has always meant the second airport. It still does."""
        _, log = converse(["top 5 airports to invest in", "and the second one?"])
        self.assertEqual(log[1]["tool"], "airport_profile")

    def test_a_refusal_is_never_the_answer_to_our_own_question(self):
        _, log = converse(["what is the best airport to invest in", "yes"])
        self.assertNotIn(REFUSAL, log[1]["text"])

    def test_ok_with_no_pending_offer_still_nudges(self):
        """And still never resolves to the state of Oklahoma."""
        _, log = converse(["ok"])
        self.assertIsNone(log[0]["tool"])
        self.assertNotIn("Oklahoma", log[0]["text"])
        self.assertNotIn(REFUSAL, log[0]["text"])

    def test_no_is_not_an_acceptance(self):
        _, log = converse(["top 5 airports to invest in", "no thanks"])
        self.assertNotEqual(log[1]["tool"], "explain_score")


@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestOffersAreExecutable(unittest.TestCase):
    """An offer the agent cannot perform is worse than no offer."""

    CASES = [
        ("rank_airports", lambda: T.rank_airports(profile="investment", top_n=5)),
        ("airport_profile", lambda: T.airport_profile(code="DFW")),
        ("unmet_demand", lambda: T.unmet_demand(code="DFW")),
        ("explain_score", lambda: T.explain_score(code="DFW", profile="investment")),
        ("flight_mix", lambda: T.flight_mix(code="DFW", dimension="haul")),
    ]

    def test_offered_actions_name_real_tools_with_valid_arguments(self):
        for tool, make in self.CASES:
            for offer in render.offers(tool, make()):
                if not offer.get("tool"):
                    continue                      # label-only, nothing to run
                self.assertIn(offer["tool"], TOOLS, f"{tool} offers unknown tool")
                if offer["args"]:
                    _, issues = schemas.validate_args(offer["tool"], offer["args"])
                    bad = [i for i in issues if i.startswith("missing required")]
                    self.assertFalse(bad, f"{tool} -> {offer['tool']}: {bad}")

    def test_the_sentence_is_derived_from_the_offers(self):
        """One source for the words and the action, so they cannot drift."""
        for tool, make in self.CASES:
            result = make()
            offs = render.offers(tool, result)
            sentence = render.followup(tool, result)
            if not offs:
                self.assertIsNone(sentence)
                continue
            self.assertIn(offs[0]["label"], sentence)

    def test_the_first_offer_is_always_the_runnable_one(self):
        """"yes" runs the first thing named, so it must be performable."""
        for tool, make in self.CASES:
            offs = render.offers(tool, make())
            if offs:
                self.assertTrue(offs[0].get("tool"),
                                f"{tool}'s first offer cannot be acted on")


if __name__ == "__main__":
    unittest.main()
