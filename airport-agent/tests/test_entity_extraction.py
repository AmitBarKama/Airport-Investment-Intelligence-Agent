"""Entity extraction: what counts as a state code, and what counts as an airport.

Two defects with one shape -- a token was accepted as an entity on far too
little evidence, or rejected on far too much. Both fed the scope guard, so a
bad match let nonsense through and a missed match refused a real question.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import config, db
from api.agent.providers import RuleBasedProvider


class TestTwoLetterStateCodes(unittest.TestCase):

    def test_bare_acknowledgement_is_not_oklahoma(self):
        """The original defect, named.

        A bare "ok" resolved to OK, ranked Oklahoma's four airports, and -- the
        compounding half -- the bogus place match was also what convinced
        _looks_aviation the message was in scope at all.
        """
        self.assertEqual(db.resolve_state("ok"), (None, None))

    def test_every_ambiguous_english_word_is_stopped(self):
        for token in sorted(db.AMBIGUOUS_TWO_LETTER):
            code, _ = db.resolve_state(token)
            self.assertIsNone(code, f"bare {token!r} resolved to {code}")

    def test_the_stoplist_only_holds_real_state_codes(self):
        """A stoplist that drifts past its purpose is a silent bug."""
        codes = set(config.US_STATES.values())
        for token in db.AMBIGUOUS_TWO_LETTER:
            self.assertIn(token.upper(), codes,
                          f"{token!r} is not a state code; it does not belong here")

    def test_unambiguous_codes_still_resolve(self):
        for token, want in (("ca", "CA"), ("tx", "TX"), ("ny", "NY"),
                            ("wa", "WA"), ("fl", "FL")):
            self.assertEqual(db.resolve_state(token)[0], want)

    def test_state_names_still_resolve(self):
        self.assertEqual(db.resolve_state("oklahoma")[0], "OK")
        self.assertEqual(db.resolve_state("airports in oklahoma")[0], "OK")

    def test_acknowledgement_answers_without_running_a_tool(self):
        for token in ("ok", "okay", "sure", "got it", "yep"):
            r = RuleBasedProvider(state={"last_airports": ["SFO"]}).chat(
                "", [{"role": "user", "content": token}])
            self.assertFalse(r.tool_calls, f"{token!r} triggered {r.tool_calls}")


class TestAirportCodeExtraction(unittest.TestCase):

    def test_lowercase_codes_are_seen(self):
        """"jfk is in which city?" was invisible to routing and to the guard."""
        self.assertEqual(RuleBasedProvider._codes("jfk is in which city?"), ["JFK"])

    def test_mixed_case_and_order_is_preserved(self):
        self.assertEqual(RuleBasedProvider._codes("compare LAX and sna"),
                         ["LAX", "SNA"])

    def test_ordinary_three_letter_words_are_not_codes(self):
        for q in ("why are the fees so high",
                  "what is the top new airport",
                  "how has it not had any"):
            self.assertEqual(RuleBasedProvider._codes(q), [], f"{q!r}")

    def test_validity_comes_from_the_database(self):
        """'ZZZ' is a three-letter token and is not an airport."""
        self.assertEqual(RuleBasedProvider._codes("tell me about ZZZ"), [])

    def test_words_that_are_also_codes_need_capitals(self):
        """DAY is Dayton and also an ordinary word; FAR is Fargo."""
        self.assertEqual(RuleBasedProvider._codes("how full is DAY"), ["DAY"])
        self.assertEqual(RuleBasedProvider._codes("per day traffic"), [])

    def test_a_named_airport_is_always_in_scope(self):
        """A code in the message must never reach the out-of-scope refusal."""
        p = RuleBasedProvider(state={})
        for q in ("jfk is in which city?", "how full is ord", "tell me about sfo"):
            self.assertTrue(p._looks_aviation(q, q),
                            f"{q!r} was judged off-topic")


if __name__ == "__main__":
    unittest.main()
