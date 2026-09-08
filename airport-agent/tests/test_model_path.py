"""The model path must be as grounded as the keyword path, not just smarter.

The regression this locks down: `_run_graph` returned `evidence=None`,
`sources=[]` and `followup=None`, so an answer produced by the model arrived
without the evidence panel, the BTS/FAA provenance pills, or the follow-up
offer. Switching a user from the keyless planner to a real model therefore
looked like a downgrade, and the existing contract test did not catch it
because it asserted only that those KEYS were present -- never that they
carried anything.

Scripted model, so this needs no key and no network.
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import db
from api.agent import llm
from api.agent.loop import run


def has_db():
    try:
        db.meta(); return True
    except Exception:
        return False


def _stub(script):
    """A scripted chat model that can be bound to tools.

    GenericFakeChatModel.bind_tools raises a bare NotImplementedError, which
    `build_graph` calls unconditionally -- so the obvious stub makes the whole
    graph fail and fall back to the keyless planner, and the assertions then
    pass against the wrong path entirely.
    """
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class _Scripted(GenericFakeChatModel):
        def bind_tools(self, *args, **kwargs):
            return self

    return _Scripted(messages=iter(script))


@unittest.skipUnless(llm.llm_available(), "needs LangChain: make install")
@unittest.skipUnless(has_db(), "no database; run python3 -m etl.build")
class TestModelPathIsGrounded(unittest.TestCase):

    def _run_scripted(self, question, tool, args):
        from langchain_core.messages import AIMessage
        script = [
            AIMessage(content="", tool_calls=[
                {"name": tool, "args": args, "id": "call_1"}]),
            AIMessage(content="Short answer, narrated by the model."),
        ]
        with mock.patch("api.agent.graph.build_model",
                        return_value=_stub(script)):
            return list(run(question))

    def test_evidence_survives_the_model_path(self):
        done = self._run_scripted("how busy is ORD", "airport_profile",
                                  {"code": "ORD"})[-1]
        self.assertTrue(done.get("evidence"),
                        "evidence is empty: the evidence panel would not render")
        self.assertEqual(done.get("evidence_tool"), "airport_profile")

    def test_sources_survive_the_model_path(self):
        done = self._run_scripted("how busy is ORD", "airport_profile",
                                  {"code": "ORD"})[-1]
        labels = [s["label"] for s in (done.get("sources") or [])]
        self.assertTrue(labels, "no provenance pills: the answer looks unsourced")
        self.assertIn("BTS T-100", labels)

    def test_followup_survives_the_model_path(self):
        done = self._run_scripted("how busy is ORD", "airport_profile",
                                  {"code": "ORD"})[-1]
        self.assertTrue(done.get("followup"),
                        "no follow-up offer: the conversation dead-ends")

    def test_the_model_actually_answered(self):
        """Guard against this passing because we quietly fell back."""
        done = self._run_scripted("how busy is ORD", "airport_profile",
                                  {"code": "ORD"})[-1]
        self.assertNotIn("built-in planner", (done.get("provider") or ""))
        self.assertTrue(done.get("traces"), "no tool was called")

    def test_both_paths_agree_on_the_done_contract(self):
        """Same keys AND same emptiness rules, which is what the old test missed."""
        model_done = self._run_scripted("how busy is ORD", "airport_profile",
                                        {"code": "ORD"})[-1]
        with mock.patch("api.agent.llm.llm_available", return_value=False):
            keyless_done = list(run("how busy is ORD"))[-1]
        for key in ("text", "evidence", "evidence_tool", "sources", "followup",
                    "state", "traces", "provider"):
            self.assertIn(key, model_done)
            self.assertIn(key, keyless_done)
            self.assertEqual(
                bool(model_done[key]), bool(keyless_done[key]),
                f"{key!r} is populated on one path and empty on the other")


if __name__ == "__main__":
    unittest.main(verbosity=2)
