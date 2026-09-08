"""Identity lookups: the bug class where "what is it called" became a ranking.

Three questions of one shape -- name, city, location -- used to produce three
different wrong answers, because no handler claimed them and the outcome was
decided by whatever incidental vocabulary the sentence happened to contain.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.agent.providers import RuleBasedProvider

# The state a second turn would carry after "what is the unmet demand at SFO?"
AFTER_SFO = {
    "last_airports": ["SFO"],
    "turns": [{"n": 1, "q": "What is the unmet flight demand at SFO, and why?",
               "tool": "unmet_demand", "codes": ["SFO"],
               "summary": "10.5% spill", "answer_head": "Short answer"}],
}


def route(msg, state=None):
    """(tool_name, args, text) for one turn through the keyless router."""
    r = RuleBasedProvider(state=dict(state or {})).chat(
        "", [{"role": "user", "content": msg}])
    if r.tool_calls:
        return r.tool_calls[0].name, r.tool_calls[0].arguments, ""
    return None, {}, r.text


class TestIdentityQuestionsAreAnswered(unittest.TestCase):
    """Each of these is a lookup. None of them is an analysis."""

    def test_name_of_the_remembered_airport(self):
        """The original defect, named.

        "what is the name of that airport?" ranked 624 airports nationally and
        opened by recommending a different airport, silently moving the
        conversation off the one the user was asking about.
        """
        tool, _, text = route("what is the name of that airport?", AFTER_SFO)
        self.assertIsNone(tool, "an identity question must not call a tool")
        self.assertIn("San Francisco", text)

    def test_city_survives_a_typo(self):
        """'aiport' is the transcript's actual spelling."""
        tool, _, text = route("what city is that aiport at?", AFTER_SFO)
        self.assertIsNone(tool)
        self.assertIn("San Francisco", text)

    def test_city_of_a_lowercase_code(self):
        """This was refused as out of scope while JFK sat in the mart."""
        tool, _, text = route("jfk is in which city?", AFTER_SFO)
        self.assertIsNone(tool)
        self.assertIn("New York", text)

    def test_identity_answer_names_the_state_too(self):
        _, _, text = route("what city is JFK in?", AFTER_SFO)
        self.assertIn("NY", text)

    def test_never_the_out_of_scope_refusal(self):
        for q in ("what is the name of that airport?",
                  "what city is that aiport at?",
                  "jfk is in which city?",
                  "which city is ORD in",
                  "where is BDL"):
            _, _, text = route(q, AFTER_SFO)
            self.assertNotIn("I can't help with that one", text,
                             f"{q!r} was refused on data we hold")


class TestAnalysisStillRoutes(unittest.TestCase):
    """Removing the noun triggers must not make the agent stop analysing."""

    def test_ranking_questions_still_rank(self):
        for q in ("which airports in New England are worth expanding",
                  "best airports to expand",
                  "where should we invest",
                  "investment opportunities"):
            tool, _, _ = route(q)
            self.assertEqual(tool, "rank_airports", f"{q!r} stopped ranking")

    def test_named_analysis_intents_are_untouched(self):
        for q, expected in (("compare LAX and SNA", "compare_airports"),
                            ("what is the unmet demand at SFO", "unmet_demand"),
                            ("why is BDL ahead of PVD", "explain_score")):
            tool, _, _ = route(q)
            self.assertEqual(tool, expected, f"{q!r} misrouted")

    def test_identity_phrasing_around_an_analysis_is_an_analysis(self):
        """"which city has the best airports to invest in" is not a lookup."""
        tool, _, _ = route("which city has the best airports to invest in")
        self.assertEqual(tool, "rank_airports")

    def test_bare_noun_no_longer_triggers_a_ranking(self):
        """'airport' is a subject marker, not an intent marker."""
        tool, _, _ = route("what is the name of that airport?", AFTER_SFO)
        self.assertNotEqual(tool, "rank_airports")


class TestTranscriptReplay(unittest.TestCase):
    """The six turns that shipped, asserted as a sequence."""

    def test_the_four_turns_the_fix_covers(self):
        expected = [("what is the name of that airport?", "San Francisco"),
                    ("what city is that aiport at?", "San Francisco"),
                    ("ok", "Happy to keep going"),
                    ("jfk is in which city?", "New York")]
        for msg, want in expected:
            tool, _, text = route(msg, AFTER_SFO)
            self.assertIsNone(tool, f"{msg!r} should answer, not run a tool")
            self.assertIn(want, text, f"{msg!r} -> {text[:70]!r}")


if __name__ == "__main__":
    unittest.main()
