"""Asking for N airports must return N airports.

The reported symptom: "I keep asking for top 5 and it just repeats to invest in
some airport." `ORDINALS` maps "top" to index 0, and the ordinal loop runs
before the ranking path, so with any prior ranking in state "top 5 airports"
resolved to ranked[0] and came back as one airport's profile card -- the same
airport, every single time.
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.agent import render, tools as T
from api.agent.providers import RuleBasedProvider

AFTER_RANK = {"last_airports": ["DFW", "DEN", "ORD"],
              "last_ranking": ["DFW", "DEN", "ORD"],
              "last_profile": "investment"}


def has_db():
    try:
        db.meta(); return True
    except Exception:
        return False


def route(msg, state=None):
    r = RuleBasedProvider(state=dict(state or {})).chat(
        "", [{"role": "user", "content": msg}])
    if r.tool_calls:
        return r.tool_calls[0].name, r.tool_calls[0].arguments
    return None, {"text": r.text}


class TestListRequestsAreNotOrdinals(unittest.TestCase):

    def test_top_5_returns_a_ranking_not_one_airport(self):
        tool, args = route("top 5 airports to invest in", AFTER_RANK)
        self.assertEqual(tool, "rank_airports")
        self.assertEqual(args.get("top_n"), 5)

    def test_the_count_is_honoured(self):
        for msg, want in (("top 3 airports", 3), ("what are the top 10 airports", 10),
                          ("show me the top 7 airports", 7)):
            _, args = route(msg, AFTER_RANK)
            self.assertEqual(args.get("top_n"), want, msg)

    def test_a_bare_list_request_mid_conversation_is_not_refused(self):
        """"give me the top 5" names nothing aviation but plainly means the ranking."""
        tool, args = route("give me the top 5", AFTER_RANK)
        self.assertEqual(tool, "rank_airports")
        self.assertEqual(args.get("top_n"), 5)

    def test_a_scoped_list_keeps_its_place(self):
        tool, args = route("top 3 airports in texas", AFTER_RANK)
        self.assertEqual(tool, "rank_airports")
        self.assertEqual(args.get("states"), ["TX"])
        self.assertEqual(args.get("top_n"), 3)

    def test_real_ordinals_still_resolve(self):
        """The guard must not break the referent it shares a keyword with."""
        self.assertEqual(route("and the second one?", AFTER_RANK)[1].get("code"), "DEN")
        self.assertEqual(route("the top one", AFTER_RANK)[1].get("code"), "DFW")

    def test_requested_n_is_clamped(self):
        self.assertEqual(RuleBasedProvider._requested_n("top 1 airports"), 3)
        self.assertEqual(RuleBasedProvider._requested_n("top 99 airports"), 25)
        self.assertEqual(RuleBasedProvider._requested_n("best airports"), 10)


@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestRenderedRowCount(unittest.TestCase):

    def test_a_top_5_ranking_renders_five_rows(self):
        """render.py capped the table at six regardless of what was asked."""
        text, _ = render.render("rank_airports",
                                T.rank_airports(profile="investment", top_n=5))
        rows = [l for l in text.splitlines() if l.startswith("| **")]
        self.assertEqual(len(rows), 5)

    def test_a_top_10_ranking_renders_ten_rows(self):
        text, _ = render.render("rank_airports",
                                T.rank_airports(profile="investment", top_n=10))
        rows = [l for l in text.splitlines() if l.startswith("| **")]
        self.assertEqual(len(rows), 10)


class TestOrdinalFormatting(unittest.TestCase):

    def test_first_is_not_1th(self):
        """The rank was formatted f"{n}th", so the top airport was "1th"."""
        self.assertEqual(render._ordinal(1), "1st")
        self.assertEqual(render._ordinal(2), "2nd")
        self.assertEqual(render._ordinal(3), "3rd")
        self.assertEqual(render._ordinal(4), "4th")

    def test_the_teens_are_not_1st_2nd_3rd(self):
        for n in (11, 12, 13):
            self.assertTrue(render._ordinal(n).endswith("th"), n)
        self.assertEqual(render._ordinal(21), "21st")


if __name__ == "__main__":
    unittest.main()
