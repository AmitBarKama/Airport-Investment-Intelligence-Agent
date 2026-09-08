"""Conversation memory, and the structural guarantee that web search cannot score."""
import ast, json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.agent import tools as T
from api.agent.loop import run
from api.agent.prompts import memory_block


def has_db():
    try:
        db.meta(); return True
    except Exception:
        return False




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


def converse(questions):
    state, log = {}, []
    for q in questions:
        tool, text = None, ""
        with keyless():
            events = list(run(q, state=state))
        for ev in events:
            if ev["type"] == "tool_trace":
                tool = ev["name"]
            elif ev["type"] == "done":
                state, text = ev["state"], ev["text"]
        log.append({"q": q, "tool": tool, "text": text})
    return state, log


@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestMemory(unittest.TestCase):

    def test_ordinals_resolve_against_the_ranking(self):
        """"the first one" must survive a later comparison overwriting state."""
        state, log = converse([
            "which airports in New England should we invest in",
            "what about Boston",
            "and the second one?",
        ])
        self.assertTrue(state.get("last_ranking"))
        second = state["last_ranking"][1]
        self.assertIn(second, log[-1]["text"])

    def test_meta_questions_use_no_tool(self):
        """Re-running a query is the clearest sign of an agent not listening."""
        _, log = converse([
            "which airports in New England should we invest in",
            "what did I ask you first?",
        ])
        self.assertIsNone(log[-1]["tool"], "recall should not call a tool")
        self.assertIn("New England", log[-1]["text"])

    def test_recap_lists_the_conversation(self):
        _, log = converse(["how busy is Denver", "unmet demand at SFO", "give me a recap"])
        self.assertIsNone(log[-1]["tool"])
        self.assertIn("Denver", log[-1]["text"])

    def test_state_stays_bounded_and_serialisable(self):
        """State rides in SSE and localStorage; it must summarise, not transcribe."""
        state, _ = converse(["how busy is Denver"] * 6)
        blob = json.dumps(state)
        self.assertLess(len(blob), 12000, "state is growing into a transcript")
        self.assertLessEqual(len(state.get("turns", [])), 8)

    def test_llm_receives_the_referents(self):
        state, _ = converse(["which airports in New England should we invest in"])
        block = memory_block(state)
        self.assertIn("Most recent ranking", block)
        self.assertIn("the first one", block)


class TestSearchIsolation(unittest.TestCase):
    """Search must be structurally incapable of reaching a score."""

    def test_scoring_never_imports_search_or_tools(self):
        """A structural proof, not a promise."""
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "api", "scoring")
        forbidden = {"websearch", "tools", "urllib", "requests"}
        for fn in os.listdir(root):
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(root, fn)).read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[-1]]
                for n in names:
                    self.assertNotIn(n, forbidden,
                                     f"api/scoring/{fn} imports {n!r}")

    @unittest.skipUnless(has_db(), "no database")
    def test_search_tool_degrades_without_a_key(self):
        r = T.capital_programmes("ORD")
        self.assertTrue(r["excluded_from_scoring"])
        self.assertIn("assumptions", r)
        self.assertIn("data_vintage", r)
        # falls back to the curated file rather than to nothing
        self.assertTrue(r["unavailable"] or r["findings"])

    @unittest.skipUnless(has_db(), "no database")
    def test_ranking_carries_no_web_evidence(self):
        r = T.rank_airports(region="new england")
        self.assertNotIn("findings", r)
        for label in [s["label"] for s in r["sources"]]:
            self.assertNotEqual(label, "Web")


if __name__ == "__main__":
    unittest.main(verbosity=2)
