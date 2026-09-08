"""Model configuration, .env loading, and the LangGraph path.

The config tests run everywhere. The graph tests need LangChain and skip
cleanly without it, so the suite stays green on a machine that has not run
`make install` — the same pattern already used for the database and the FAA
backtest.
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import config
from api.agent import llm


class TestDotenvLoading(unittest.TestCase):
    """A .env that is written but never read is worse than no .env at all:
    the app looks configured and silently is not."""

    def _load(self, text):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w") as fh:
                fh.write(text)
            before = dict(os.environ)
            try:
                config._load_dotenv(path)
                return {k: v for k, v in os.environ.items() if k not in before}
            finally:
                os.environ.clear(); os.environ.update(before)

    def test_reads_simple_pairs(self):
        got = self._load("W_TEST_A=hello\nW_TEST_B=world\n")
        self.assertEqual(got.get("W_TEST_A"), "hello")
        self.assertEqual(got.get("W_TEST_B"), "world")

    def test_ignores_comments_and_blanks(self):
        got = self._load("# a comment\n\n  \nW_TEST_C=1\n")
        self.assertEqual(got.get("W_TEST_C"), "1")
        self.assertNotIn("# a comment", got)

    def test_strips_quotes_and_keeps_inner_equals(self):
        got = self._load('W_TEST_D="a=b=c"\n')
        self.assertEqual(got.get("W_TEST_D"), "a=b=c")

    def test_real_environment_wins(self):
        os.environ["W_TEST_E"] = "from-shell"
        try:
            self._load("W_TEST_E=from-file\n")
            self.assertEqual(os.environ["W_TEST_E"], "from-shell")
        finally:
            os.environ.pop("W_TEST_E", None)

    def test_missing_file_is_not_an_error(self):
        config._load_dotenv("/nonexistent/path/.env")   # must not raise


class TestModelSpec(unittest.TestCase):

    def _spec(self, **env):
        """Drive llm_spec() directly.

        Reloading the module would re-run the .env loader and pick up the real
        file, so the module attributes are set explicitly instead.
        """
        before_env = dict(os.environ)
        saved = {k: getattr(config, k) for k in ("LLM", "LLM_PROVIDER", "LLM_MODEL")}
        for k in ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
                  "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        config.LLM = env.get("LLM", "")
        config.LLM_PROVIDER = env.get("LLM_PROVIDER", "auto")
        config.LLM_MODEL = env.get("LLM_MODEL", "")
        try:
            return config.llm_spec()
        finally:
            for k, v in saved.items():
                setattr(config, k, v)
            os.environ.clear(); os.environ.update(before_env)

    def test_provider_model_form(self):
        self.assertEqual(self._spec(LLM="openai:gpt-4o-mini"), "openai:gpt-4o-mini")

    def test_friendly_alias_maps_to_langchain_provider(self):
        """People write "gemini"; LangChain calls it google_genai."""
        self.assertEqual(self._spec(LLM="gemini:gemini-3.5-flash-lite"),
                         "google_genai:gemini-3.5-flash-lite")

    def test_provider_without_model_gets_a_default(self):
        self.assertTrue(self._spec(LLM="groq:").startswith("groq:"))
        self.assertNotEqual(self._spec(LLM="groq:"), "groq:")

    def test_nothing_configured_means_keyless(self):
        self.assertEqual(self._spec(), "")

    def test_deprecated_split_form_still_works(self):
        self.assertEqual(
            self._spec(LLM_PROVIDER="gemini", LLM_MODEL="gemini-3.5-flash-lite"),
            "google_genai:gemini-3.5-flash-lite")


class TestGracefulAbsence(unittest.TestCase):
    """Without LangChain the app must still run, not crash."""

    def test_describe_never_raises(self):
        self.assertIsInstance(llm.describe(), str)

    def test_hint_names_the_package_to_install(self):
        self.assertIn("pip install", llm.missing_dependency_hint())

    @unittest.skipIf(llm.llm_available(), "LangChain installed")
    def test_build_model_fails_actionably(self):
        with self.assertRaises(RuntimeError) as ctx:
            llm.build_model()
        self.assertIn("pip install", str(ctx.exception))

    def test_keyless_path_still_answers(self):
        from api.agent.loop import run
        events = list(run("which airports in the east are worth expanding"))
        self.assertEqual(events[-1]["type"], "done")
        self.assertTrue(events[-1]["text"])


@unittest.skipUnless(llm.llm_available(), "needs LangChain: make install")
class TestGraphWithStubModel(unittest.TestCase):
    """Exercise the LangGraph loop with a scripted model: no key, no network."""

    def _stub(self, script):
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        return GenericFakeChatModel(messages=iter(script))

    def test_graph_builds(self):
        from api.agent.graph import build_graph
        graph, system_text, _ = build_graph({})
        self.assertIn("airport", system_text.lower())
        self.assertIsNotNone(graph)

    def test_event_contract_matches_the_keyless_path(self):
        """The frontend depends on these keys; both paths must agree.

        Pinned to the keyless planner: unpinned, this drove whichever planner
        was configured, so adding a model key turned it into a live network
        test. The model path's own contract is asserted in test_model_path.py.
        """
        from unittest import mock
        from api.agent.loop import run
        with mock.patch("api.agent.llm.llm_available", return_value=False):
            events = list(run("how busy is Denver"))
        done = events[-1]
        for key in ("text", "state", "traces", "unverified_numbers",
                    "externally_sourced_numbers", "provider"):
            self.assertIn(key, done, f"done event missing {key!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
