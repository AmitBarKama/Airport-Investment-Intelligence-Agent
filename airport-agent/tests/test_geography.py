"""Geography: the bug class that produced identical answers for east and west."""
import ast as _ast, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import config, db
from api.agent.providers import RuleBasedProvider


class TestRegionResolution(unittest.TestCase):

    def test_compass_words_never_substring_match(self):
        """The original defect, named.

        "west" used to resolve to "midwest" and "east" to "northeast", because
        matching tested `phrase in key` as well as `key in phrase` and took
        whichever came first in dict order. A confidently wrong region is worse
        than no match, because the caller cannot tell.
        """
        for word, wrong in (("west", "midwest"), ("east", "northeast"),
                            ("south", "southeast"), ("north", "northeast")):
            _, label, _ = db.resolve_region_scored(word)
            self.assertIsNotNone(label, f"{word!r} should resolve")
            self.assertNotEqual(label, wrong,
                                f"{word!r} silently became {wrong!r}")

    def test_east_and_west_are_different_places(self):
        east, _ = db.resolve_region("the east")
        west, _ = db.resolve_region("the west")
        self.assertTrue(set(east).isdisjoint(set(west)),
                        "east and west must not overlap")

    def test_resolution_is_order_independent(self):
        """Catch the class, not just the instance."""
        import random
        keys = list(config.REGIONS)
        for _ in range(5):
            random.shuffle(keys)
            shuffled = {k: config.REGIONS[k] for k in keys}
            original, config.REGIONS = config.REGIONS, shuffled
            try:
                _, label, _ = db.resolve_region_scored("west")
            finally:
                config.REGIONS = original
            self.assertEqual(label, "west")

    def test_every_state_resolves(self):
        for name, code in config.US_STATES.items():
            got, _ = db.resolve_state(name)
            self.assertEqual(got, code, name)

    def test_state_names_never_resolve_to_an_airport(self):
        """"airports in florida" used to return one small field in Fort Myers."""
        for word in ("florida", "texas", "california", "washington", "georgia"):
            self.assertIsNone(RuleBasedProvider._name_guess(word, 0.90),
                              f"{word!r} was read as an airport name")

    def test_typos_resolve_rather_than_refuse(self):
        p = RuleBasedProvider()
        self.assertTrue(p._has_aviation_word("what ariporst are in the east"))
        self.assertTrue(p._has_aviation_word("aiport capasity"))
        # ordinary words must not be mistaken for aviation vocabulary
        self.assertFalse(p._has_aviation_word("please import my report"))


class TestRoutingKeepsThePlace(unittest.TestCase):

    def _route(self, q):
        r = RuleBasedProvider(state={}).chat("s", [{"role": "user", "content": q}])
        return (r.tool_calls[0].name, r.tool_calls[0].arguments) if r.tool_calls else (None, r.text)

    def test_named_region_is_never_dropped(self):
        """The user's actual complaint: the place was silently discarded."""
        east = self._route("which airports should i invest in in the east")
        west = self._route("and in the west")
        self.assertEqual(east[0], "rank_airports")
        self.assertEqual(west[0], "rank_airports")
        self.assertNotEqual(east[1].get("region"), west[1].get("region"),
                            "east and west produced the same query")

    def test_state_questions_rank_the_state(self):
        tool, args = self._route("which airports in texas should we expand")
        self.assertEqual(tool, "rank_airports")
        self.assertEqual(args.get("states"), ["TX"])

    def test_unresolvable_place_never_ranks_nationally(self):
        """Answering about the whole country is how the bug stayed invisible."""
        tool, text = self._route("which airports in the pacific rim should we expand")
        self.assertIsNone(tool, f"expected a clarification, got {tool}")
        self.assertIn("could not work out where", text)

    def test_no_place_named_may_rank_nationally(self):
        tool, _ = self._route("where should we invest")
        self.assertEqual(tool, "rank_airports")


if __name__ == "__main__":
    unittest.main(verbosity=2)
