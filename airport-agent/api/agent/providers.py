"""LLM providers behind one interface, plus a keyless fallback planner.

The model is the most swappable part of this system: all figures come from
deterministic Python, so changing provider changes tone, not answers. Selection
is one environment variable.

Providers speak HTTP through urllib (stdlib) so the backend needs no packages.

RuleBasedProvider is the important one for robustness: when no API key is
configured the agent still works. It pattern-matches the question to a tool
call and renders the result with templates. It is not conversational, and it
says so, but a reviewer with no key still sees the whole deterministic
pipeline run end to end.
"""
from __future__ import annotations

import json
import difflib
import re
from dataclasses import dataclass, field

from .. import config, db
from . import schemas


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    reason: str = ""      # why this tool, surfaced in developer mode


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict | None = None


class BaseProvider:
    name = "base"
    conversational = True

    def chat(self, system: str, messages: list[dict]) -> LLMResponse:
        raise NotImplementedError


# --------------------------------------------------------------------------
class RuleBasedProvider(BaseProvider):
    """Keyless fallback: route questions to tools by intent matching.

    Not a language model, and it says so. But it must never dead-end. An agent
    that answers "I could not map that to a query" has failed the user twice:
    once by not understanding, and once by making its own limitation their
    problem. So every path here ends in a real tool call or a genuinely useful
    reply, and conversational context (what we just discussed) is used to
    resolve follow-ups like "what about Hartford?" or "why the second one?".
    """

    name = "built-in planner (no API key)"
    conversational = False

    REGION_WORDS = sorted(config.REGIONS, key=len, reverse=True)
    METRO_WORDS = sorted(config.METRO_GROUPS, key=len, reverse=True)

    ORDINALS = {"first": 0, "1st": 0, "top": 0, "second": 1, "2nd": 1,
                "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4,
                "last": -1}

    STOPWORDS = {
        "what", "which", "where", "the", "and", "for", "out", "of", "in", "is",
        "are", "airport", "airports", "flights", "flight", "percentage", "level",
        "levels", "congestion", "compare", "versus", "vs", "against", "demand",
        "unmet", "long", "haul", "terminal", "expansion", "candidates", "strong",
        "why", "how", "much", "many", "that", "this", "it", "stable", "ranking",
        "tell", "me", "about", "give", "show", "list", "best", "top", "good",
        "should", "would", "could", "does", "look", "like", "think", "know",
        "want", "need", "make", "take", "into", "with", "from", "there", "their",
        # Intent words that must never be mistaken for an airport name: there
        # is an airport whose name fuzzy-matches "promising", and matching it
        # turns a strategy question into a random airport profile.
        "promising", "interesting", "opportunity", "opportunities", "invest",
        "investment", "capacity", "candidate", "recommend", "worth", "right",
        "now", "something", "anything", "options", "ideas", "next", "value",
    }

    def __init__(self, state: dict | None = None, history: list | None = None):
        self.state = state or {}
        self.history = history or []

    # ------------------------------------------------------------------ main
    def chat(self, system: str, messages: list[dict]) -> LLMResponse:
        user = next((m["content"] for m in reversed(messages)
                     if m["role"] == "user"), "")
        q = (user or "").lower().strip()

        # A tool already ran this turn: let the renderer narrate it.
        if any(m["role"] == "tool" for m in messages):
            return LLMResponse(text="")

        for handler in (self._recall, self._affirmative, self._identity, self._smalltalk,
                        self._explicit_intent, self._followup,
                        self._entity_intent, self._last_resort):
            out = handler(q, user)
            if out is not None:
                return out
        return self._capabilities()

    @staticmethod
    def _call(name, args, reason=""):
        return LLMResponse(tool_calls=[ToolCall("rb_1", name, args, reason)])

    # ------------------------------------------------------------- handlers
    def _recall(self, q, raw):
        """Answer questions about the conversation itself, from memory.

        These must not re-run a tool. Asking "what did I ask you first?" and
        getting a fresh airport profile is the clearest possible sign that an
        agent is not really following the conversation.
        """
        turns = self.state.get("turns") or []
        if not turns:
            return None

        wants_first = re.search(r"\b(first|originally|start(ed)?|begin)\b", q)
        wants_recap = re.search(r"\b(recap|summar|what have we|so far|covered)\b", q)
        asks_question = re.search(r"\b(what|which)\b.*\b(ask|asked|question)", q)
        asks_said = re.search(r"\b(what did you (just )?say|tell me again|repeat that)\b", q)

        if asks_question:
            t = turns[0] if wants_first else turns[-1]
            which = "first" if wants_first else "last"
            return LLMResponse(text=(
                f"Your {which} question was: *\u201c{t['q']}\u201d*\n\n"
                f"I answered it with `{t['tool']}` and found: {t['summary']}."))

        if asks_said:
            t = turns[-1]
            return LLMResponse(text=(
                f"I said: {t['answer_head']}…\n\nThat came from `{t['tool']}`. "
                f"Want me to go over any part of it again?"))

        if wants_recap:
            lines = [f"{t['n']}. *\u201c{t['q']}\u201d* \u2192 {t['summary']}" for t in turns]
            return LLMResponse(text=(
                "Here is what we have covered so far:\n\n" + "\n".join(lines) +
                "\n\nWhere would you like to go next?"))
        return None

    # "What is it called", "what city is it in", "where is it" are lookups,
    # not analyses. With no handler for them they fell through to _last_resort,
    # where a stray "airport" produced a national ranking, a typo produced a
    # profile card and a bare code produced a refusal -- three different wrong
    # answers to one question shape.
    IDENTITY_RE = re.compile(
        r"\bwhat(?:'s| is| are|s)?\s+(?:the\s+)?names?\b"
        r"|\bwhat\s+(?:is|was)\s+(?:it|that|this)\s+called\b"
        r"|\b(?:what|which)\s+(?:city|town|state)\b"
        r"|\bis\s+in\s+which\b"
        r"|\bwhere\s+(?:is|are)\b")
    # An identity phrasing wrapped around an analysis is still an analysis:
    # "which city has the best airports to invest in" is not a lookup.
    IDENTITY_BLOCK = ("invest", "expansion", "expand", "rank", "opportunit",
                      "candidate", "congest", "unmet", "spill", "stable",
                      "compare", "score", "worth")

    AFFIRM_RE = re.compile(
        r"^(?:yes|yeah|yep|yup|sure|ok|okay|k|please|go on|go ahead|do it|"
        r"sounds good|why not|both|do both|the other one)"
        r"[\s,.!]*(?:please|then|thanks|thank you)?[\s.!?]*$")

    def _affirmative(self, q, raw):
        """Run the thing we just offered.

        Every answer ends with an offer. Nothing used to record what was
        offered, so "yes please" matched no handler and reached the
        out-of-scope refusal -- the agent asking a question and then refusing
        to answer it. With no pending offer this returns None so the ordinary
        acknowledgement nudge still applies; it never refuses.
        """
        if not self.AFFIRM_RE.match(q):
            return None
        actionable = [o for o in (self.state.get("last_offers") or []) if o.get("tool")]
        if not actionable:
            return None
        second = re.search(r"\b(?:second|other one|latter)\b", q)
        offer = actionable[-1] if (second and len(actionable) > 1) else actionable[0]
        args = dict(offer.get("args") or {})

        # Some offers can only name their subject once the conversation is in
        # hand -- "test whether that ranking holds" needs the ranking.
        if offer["tool"] == "sensitivity_analysis" and not args.get("codes") \
                and not args.get("region"):
            ranked = (self.state.get("last_ranking")
                      or self.state.get("last_airports") or [])
            if len(ranked) < 2:
                return None
            args["codes"] = ranked[:8]
        if offer["tool"] == "rank_airports" and "weights" in args:
            args.setdefault("profile", self.state.get("last_profile") or "investment")
            if self.state.get("last_region"):
                args.setdefault("region", self.state["last_region"])

        return self._call(offer["tool"], args,
                          f"accepted the offer to {offer['label']}")

    def _identity(self, q, raw):
        """Say the name, the city and the state. Nothing else."""
        if not self.IDENTITY_RE.search(q):
            return None
        if any(w in q for w in self.IDENTITY_BLOCK):
            return None
        codes = self._codes(raw)
        target = (codes[0] if codes
                  else self._name_guess(q, self.STRICT_NAME_MATCH) or self._recent())
        if not target:
            return None
        a = db.get_airport(target)
        if not a:
            return None
        city, state = (a.get("city") or "").strip(), (a.get("state") or "").strip()
        where = f"{city}, {state}" if city and state else (city or state)
        if re.search(r"\b(city|town|state|where)\b", q) and where:
            text = f"**{a['code']} — {a['name']}** is in {where}."
        else:
            text = f"That one is **{a['name']}** ({a['code']})"
            text += f", in {where}." if where else "."
        return LLMResponse(text=text + "\n\nWant its traffic and capacity picture, "
                                       "or how it scores for expansion?")

    def _nudge(self):
        """Acknowledge without answering a question that was not asked."""
        turns = self.state.get("turns") or []
        codes = (turns[-1].get("codes") if turns else None) or []
        if codes:
            return (f"Happy to keep going. I can explain how {codes[0]} scored, compare "
                    f"it with a peer, or move somewhere else — say which.")
        return ("Happy to keep going. Name an airport, a US state or a region and I'll "
                "pull its capacity picture.")

    def _smalltalk(self, q, raw):
        # A bare acknowledgement is not a question. "ok" used to resolve to the
        # state of Oklahoma and produce a ranking nobody asked for.
        if re.fullmatch(r"(ok|okay|k|kk|sure|cool|right|fine|nice|got it|"
                        r"yep|yes|yeah|no|nope|alright|thanks ok)[!. ]*", q):
            return LLMResponse(text=self._nudge())
        if re.fullmatch(r"(hi|hey|hello|yo|hiya)[!. ]*", q):
            return LLMResponse(text=(
                "Hello. I look at US airports and work out where adding capacity "
                "would actually pay off.\n\nAsk me something like *which airports "
                "in New England are worth expanding*, or name any airport and I'll "
                "pull its traffic, capacity and constraints."))
        if any(w in q for w in ("what can you do", "help me", "how do you work",
                               "what do you do", "capabilities")):
            return self._capabilities()
        if any(w in q for w in ("thank", "cheers", "nice one", "great")):
            return LLMResponse(text="Happy to help. Anything else you want me to dig into?")
        # Out of scope, stated plainly rather than guessed at.
        if any(w in q for w in ("stock", "share price", "buy shares", "invest in airline",
                               "ticket price", "book a flight", "cheapest flight")):
            return LLMResponse(text=(
                "That's outside what I do. I look at airport *capacity* and where "
                "expansion capital would pay off, not airline equities or fares.\n\n"
                "I can tell you which airports are running out of room, though. "
                "Want me to?"))
        if "heathrow" in q or "gatwick" in q or any(
                w in q for w in ("europe", "asia", "canada", "mexico", "international airport in")):
            if not db.resolve_airport(raw):
                return LLMResponse(text=(
                    "I only cover US commercial-service airports. The data behind me "
                    "is FAA and BTS, so anywhere outside the US is a blank to me.\n\n"
                    "Ask me about a US airport and I'll go deep."))
        return None

    def _explicit_intent(self, q, raw):
        codes = self._codes(raw)
        region = next((r for r in self.REGION_WORDS if r in q), None)

        if any(w in q for w in ("unmet", "suppressed", "latent", "turned away",
                                "spill", "turning away", "pent up", "pent-up")):
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("unmet_demand", {"code": t},
                                  "asked about demand being suppressed or turned away")
        if any(w in q for w in ("long haul", "long-haul", "longhaul", "haul mix",
                                "short haul", "medium haul", "haul")):
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("flight_mix", {"code": t, "dimension": "haul"},
                                  "asked about haul length, so split the route network by distance")
        if any(w in q for w in ("international share", "domestic", "international mix")):
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("flight_mix", {"code": t, "dimension": "international"},
                                  "asked about the domestic/international split")
        if any(w in q for w in ("destination", "routes", "where does", "fly to")):
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("flight_mix", {"code": t, "dimension": "destination"},
                                  "asked where this airport flies to")
        if any(w in q for w in ("announced", "announce", "expansion plan", "plans to",
                                "new terminal", "master plan", "promised", "planning to",
                                "getting bigger", "capital program", "capital programme",
                                "what are they building", "under construction")):
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("capital_programmes", {"code": t},
                                  "asked what the airport has announced, which is news "
                                  "rather than something in the traffic data")
        if any(w in q for w in ("stable", "robust", "sensitiv", "hold up", "reliable",
                                "confident", "trust")):
            if region:
                return self._call("sensitivity_analysis", {"region": region},
                                  "asked whether the ranking is trustworthy, so re-rank under perturbed weights")
            if len(codes) >= 2:
                return self._call("sensitivity_analysis", {"codes": codes})
            if self.state.get("last_region"):
                return self._call("sensitivity_analysis", {"region": self.state["last_region"]})
            if self.state.get("last_airports"):
                return self._call("sensitivity_analysis",
                                  {"codes": self.state["last_airports"][:8]})
        if any(w in q for w in ("compare", " vs ", "versus", " against ", "side by side",
                                "difference between", "better than", "compare to",
                                "compared to", "how does it compare")):
            targets = codes if len(codes) >= 2 else self._multi_name_guess(q)
            # "compare it to the first one" names one side by ordinal. Without
            # this the ordinal is ignored and the previous comparison is simply
            # repeated verbatim, which reads as the agent not listening.
            ordinal_target = self._ordinal_target(q)
            if ordinal_target:
                current = (self.state.get("last_airports") or [])
                other = next((c for c in current if c != ordinal_target), None)
                pair = [c for c in (ordinal_target, other) if c]
                if len(pair) >= 2:
                    return self._call("compare_airports", {"codes": pair},
                                      f"an ordinal referred to {ordinal_target} in the "
                                      f"ranking, so compare it against the current subject")
            if len(targets) < 2:
                targets = (targets or []) + [c for c in self.state.get("last_airports", [])
                                             if c not in (targets or [])]
            if len(targets) >= 2:
                return self._call("compare_airports", {"codes": targets[:4]},
                                  "two or more airports named, so compare them side by side")
        if q.startswith("why") or "explain" in q or "how come" in q or "break down" in q:
            t = codes[0] if codes else self._name_guess(q) or self._recent()
            if t:
                return self._call("explain_score", {"code": t, "profile": self._profile(q)},
                                  "asked why, so decompose the score into its pillars")
        return None

    @staticmethod
    def _wants_a_list(q):
        """A request for N things is not a reference to one thing.

        "top" is in ORDINALS, so with any prior ranking in state "top 5 airports"
        resolved to ranked[0] and came back as one airport profile -- the same
        airport, every time the user asked. "the top one" is unaffected.
        """
        return bool(re.search(r"\b(?:top|first|best)\s+\d{1,2}\b", q)
                    or re.search(r"\b(?:list|show me|give me)\b.*\bairports\b", q))

    @staticmethod
    def _requested_n(q, default=10):
        """"top 5" means five. This count used to be hardcoded at ten."""
        m = (re.search(r"\b(?:top|best|first)\s+(\d{1,2})\b", q)
             or re.search(r"\b(\d{1,2})\s+airports\b", q))
        return max(3, min(25, int(m.group(1)))) if m else default

    def _ordinal_target(self, q):
        """Resolve "the first one" / "the second" against the last ranking."""
        if self._wants_a_list(q):
            return None
        ranked = self.state.get("last_ranking") or self.state.get("last_airports") or []
        if not ranked:
            return None
        for word, idx in sorted(self.ORDINALS.items(),
                                key=lambda kv: (q.find(kv[0]) if kv[0] in q else 999)):
            if re.search(rf"\b{word}\b", q):
                try:
                    return ranked[idx]
                except IndexError:
                    return None
        return None

    def _followup(self, q, raw):
        """Resolve references to what we were just talking about."""
        last = self.state.get("last_airports") or []

        # "what about Hartford?" -> add it to the comparison
        m = re.search(r"what about ([a-z .'-]+)", q)
        if m:
            span = m.group(1).strip()
            # A follow-up can widen the geography, not just name another
            # airport: "what about the west" used to be a flat refusal.
            place = db.resolve_place(span)
            if place["kind"] == "region":
                return self._call("rank_airports",
                                  {"region": place["label"],
                                   "profile": self.state.get("last_profile", "investment")},
                                  f"follow-up widened the question to {place['label']}")
            if place["kind"] == "state":
                return self._call("rank_airports",
                                  {"states": place["states"],
                                   "profile": self.state.get("last_profile", "investment")},
                                  f"follow-up moved to {place['label']}")
            extra = self._name_guess(span)
            if extra:
                others = [c for c in last if c != extra][:2]
                if others:
                    return self._call("compare_airports", {"codes": [extra] + others})
                return self._call("airport_profile", {"code": extra})

        # "the second one", "the top one". Resolve against the last RANKING
        # where there is one: after a comparison, "the first one" still means
        # the airport that came first in the ranking we were discussing.
        ranked = [] if self._wants_a_list(q) else (self.state.get("last_ranking") or last)
        for word, idx in sorted(self.ORDINALS.items(),
                                key=lambda kv: (q.find(kv[0]) if kv[0] in q else 999)):
            if re.search(rf"\b{word}\b", q) and ranked:
                try:
                    target = ranked[idx]
                except IndexError:
                    continue
                if any(w in q for w in ("why", "explain", "score")):
                    return self._call("explain_score", {"code": target})
                return self._call("airport_profile", {"code": target})

        # re-weighting: "what if growth mattered more"
        if any(w in q for w in ("weight", "if growth", "care more", "prioriti",
                                "matter more", "instead of")):
            weights = {}
            for pillar, words in {
                "growth": ("growth", "growing", "expand"),
                "saturation": ("congestion", "congested", "busy", "saturation"),
                "unmet_demand": ("unmet", "demand", "suppressed"),
                "feasibility": ("feasib", "buildable", "room to build", "expandab"),
                "monetization": ("revenue", "monetis", "monetiz", "international"),
            }.items():
                if any(w in q for w in words):
                    weights[pillar] = 0.45
            if weights:
                args = {"weights": weights, "profile": self.state.get("last_profile", "investment")}
                if self.state.get("last_region"):
                    args["region"] = self.state["last_region"]
                elif last:
                    args["codes"] = last
                return self._call("rank_airports", args)
        return None

    STRICT_NAME_MATCH = 0.90

    # Words that appear inside airport names but carry no identifying signal on
    # their own. "Will Rogers WORLD Airport" meant that "who won the world cup"
    # resolved to Oklahoma City. A single generic word is never enough to name
    # an airport.
    NAME_NOISE = {
        "world", "international", "national", "regional", "municipal", "county",
        "memorial", "field", "airport", "airpark", "park", "city", "town",
        "valley", "river", "lake", "point", "spring", "springs", "grand",
        "union", "central", "north", "south", "east", "west", "new", "old",
        "great", "little", "big", "high", "sky", "air", "base", "station",
        "island", "beach", "bay", "hill", "hills", "ridge", "creek", "falls",
        "metro", "metropolitan", "executive", "general", "state", "public",
        "capital", "cherry", "gateway", "heritage", "liberty", "freedom",
        "legion", "veterans", "pioneer", "harbor", "harbour", "coast", "canyon",
        "desert", "forest", "prairie", "summit", "crossing", "landing",
    } | set(config.US_STATES) | set(config.REGIONS)
    # State and region names are places, never airport names. Without this
    # "airports in florida" fuzzy-matches an airport CALLED something-Florida
    # and answers about one small field instead of the state.

    def _entity_intent(self, q, raw):
        # If nothing in the sentence looks like aviation, do not go hunting for
        # an airport name. Fishing for a fuzzy match is how "what is the capital
        # of France" became an airport profile.
        if not self._looks_aviation(q, raw):
            return None
        codes = self._codes(raw)
        profile = self._profile(q)
        n = self._requested_n(q)

        # One resolver for every kind of place, so a region, a state, a metro
        # area and an airport are all understood the same way.
        place = db.resolve_place(q)
        if place["kind"] == "region":
            return self._call("rank_airports",
                              {"region": place["label"], "profile": profile, "top_n": n},
                              f"named the region '{place['label']}', so rank its airports "
                              f"on the {profile} profile")
        if place["kind"] == "state":
            return self._call("rank_airports",
                              {"states": place["states"], "profile": profile, "top_n": n},
                              f"named the state '{place['label']}', so rank airports there")
        if place["kind"] == "metro":
            return self._call("rank_airports",
                              {"metro": place["label"], "profile": profile, "top_n": n},
                              f"named the {place['label']} metro area, so rank its airports")

        if len(codes) >= 2:
            return self._call("compare_airports", {"codes": codes[:4]},
                              "several airport codes present, so compare them")
        if len(codes) == 1:
            return self._call("airport_profile", {"code": codes[0]},
                              "one airport named, so pull its full profile")
        named = self._multi_name_guess(q, self.STRICT_NAME_MATCH)
        if len(named) >= 2:
            return self._call("compare_airports", {"codes": named[:4]},
                              "several airports named, so compare them")
        if len(named) == 1:
            return self._call("airport_profile", {"code": named[0]},
                              "one airport named, so pull its full profile")
        return None

    AVIATION_WORDS = (
        "airport", "airports", "flight", "flights", "flying", "fly", "runway",
        "terminal", "gate", "passenger", "passengers", "airline", "airlines",
        "aviation", "capacity", "congest", "delay", "delays", "hub", "route",
        "routes", "traffic", "expansion", "expand", "invest", "seat", "seats",
        "carrier", "departure", "departures", "landing", "takeoff", "haul",
        "enplanement", "slot", "taxi", "boarding", "concourse", "apron",
    )

    @staticmethod
    def _signature(word: str) -> str:
        return "".join(sorted(word))

    @classmethod
    def _has_aviation_word(cls, q: str) -> bool:
        """Aviation vocabulary, tolerant of one slipped keystroke.

        Two signals, because neither alone is enough. difflib catches
        insertions and deletions ("aiport", "termnal") but cannot separate
        "ariporst" from "airport" (0.80) without also matching the ordinary
        word "import" (0.77). A sorted-letter signature catches exactly that
        transposition class. Applied only to longer tokens, since short words
        collide easily -- sorted("east") == sorted("seat").
        """
        if any(w in q for w in cls.AVIATION_WORDS):
            return True
        sigs = {cls._signature(w): w for w in cls.AVIATION_WORDS if len(w) >= 6}
        for token in re.findall(r"[a-z]{4,}", q):
            if difflib.get_close_matches(token, cls.AVIATION_WORDS, n=1, cutoff=0.86):
                return True
            if len(token) >= 6 and cls._signature(token) in sigs:
                return True
        return False

    def _looks_aviation(self, q, raw):
        """Is this question about airports at all?

        A named place counts: "which ones in Florida" is clearly our subject
        even though it contains no aviation noun.
        """
        if self._has_aviation_word(q):
            return True
        if self._codes(raw) or self._name_guess(q, self.STRICT_NAME_MATCH):
            return True
        return db.resolve_place(q).get("kind") is not None

    def _out_of_scope(self, q, raw):
        """Say so, plainly, and point somewhere useful.

        Silently running a ranking because a question mentioned nothing we
        understand is worse than admitting it: the user gets a confident
        answer to a question they did not ask.
        """
        return LLMResponse(text=(
            "I can't help with that one. I only know about US airport capacity: "
            "how full airports are, where demand is being turned away, and where "
            "expansion money would go furthest.\n\n"
            "I can rank the airports in any US region or state, compare any two on "
            "congestion, or go deep on a single airport. Try *the West*, *Florida*, "
            "or just name an airport."))

    def _unresolved_place(self, q, raw):
        """We heard a place but could not resolve it. Never answer nationally."""
        known = ", ".join(f"*{r}*" for r in
                          ["New England", "the East", "the West", "the South",
                           "the Midwest", "the Gulf Coast", "the Great Lakes"])
        return LLMResponse(text=(
            "I caught that you meant somewhere specific, but I could not work out "
            "where.\n\nI understand US regions like " + known + ", any US state by "
            "name, metro areas like *Los Angeles* or *the Bay Area*, and individual "
            "airports by code or name.\n\nWhich did you mean?"))

    def _last_resort(self, q, raw):
        """Still no match: answer the most useful question nearby.

        A ranking question with no place attached is almost always "so where
        should we be looking?", so answer that rather than asking them to
        rephrase.
        """
        # Strong signals name our subject outright; weak ones ("best", "worth",
        # "recommend") are ordinary English and only count alongside aviation
        # vocabulary, or "recommend a restaurant" becomes an airport ranking.
        # "airport", "airline" and "aviation" used to live here. They are
        # subject markers, present in almost every question this agent sees
        # including pure lookups -- deciding whether we are the right agent is
        # _looks_aviation's job. As intent markers they turned "what is the
        # name of that airport?" into a 624-airport national ranking.
        STRONG = ("invest", "opportunit", "candidate", "expansion", "expand",
                  "capacity", "congest")
        WEAK = ("worth", "where should", "best", "top", "recommend", "promising",
                "look at", "options")
        # The user named somewhere and we could not work out where. Answering
        # about the whole country instead is how "which airports in the east"
        # and "and in the west" produced the same answer. Say so instead.
        place = db.resolve_place(q)
        if place["looks_like_place"] and not place["kind"]:
            return self._unresolved_place(q, raw)

        # "give me the top 5" names nothing aviation, so the scope guard used to
        # refuse it outright. Mid-conversation it plainly means the ranking we
        # were already discussing.
        if self._wants_a_list(q) and (self.state.get("last_ranking")
                                      or self.state.get("last_airports")):
            args = {"profile": self.state.get("last_profile") or self._profile(q),
                    "top_n": self._requested_n(q)}
            if self.state.get("last_region"):
                args["region"] = self.state["last_region"]
            return self._call("rank_airports", args,
                              "asked for a list of N, and a ranking was already "
                              "the subject")

        if any(w in q for w in STRONG) or (
                any(w in q for w in WEAK) and self._looks_aviation(q, raw)):
            return self._call("rank_airports",
                              {"profile": self._profile(q),
                               "top_n": self._requested_n(q)},
                              "an investment question with no place named, so rank nationally")
        if self._recent() and self._looks_aviation(q, raw):
            return self._call("airport_profile", {"code": self._recent()},
                              "follow-up with no new subject, so stay on the last airport")
        if not self._looks_aviation(q, raw):
            return self._out_of_scope(q, raw)
        return None

    def _capabilities(self):
        return LLMResponse(text=(
            "Here's what I can do.\n\n"
            "- **Rank airports** for expansion in a region or metro area, using FAA "
            "capacity thresholds rather than my own opinion\n"
            "- **Compare** any two airports on congestion, delays and constraints\n"
            "- **Estimate unmet demand** at an airport, and explain what's causing it\n"
            "- **Break down the flight mix**, including long-haul share\n"
            "- **Explain any score**, and test whether the ranking survives different "
            "assumptions\n\n"
            "Try: *which airports in New England are worth expanding*, "
            "*compare LAX and SNA*, or just name an airport.\n\n"
            "One caveat worth knowing: I'm running without a language-model key, so I "
            "match your question to an analysis by keyword rather than really reading "
            "it. Set `GROQ_API_KEY` for proper conversation. The numbers are identical "
            "either way, because they all come from the same deterministic code."))

    # ------------------------------------------------------------- utilities
    @staticmethod
    def _profile(q):
        if "terminal" in q or "gate" in q or "concourse" in q:
            return "terminal"
        if "runway" in q or "airfield" in q:
            return "airfield"
        if "congest" in q or "delay" in q or "busy" in q or "crowded" in q:
            return "congestion"
        return "investment"

    def _recent(self):
        last = self.state.get("last_airports") or []
        return last[0] if last else None

    # Three-letter English words that are never what the user meant. DAY
    # (Dayton) and FAR (Fargo) are real codes as well as ordinary words, so
    # they count only when the writer capitalised them.
    CODE_STOP = {"THE", "AND", "FOR", "WHY", "ARE", "WAS", "ITS", "CAN", "YOU",
                 "HOW", "WHO", "ONE", "TWO", "OUT", "HAS", "HAD", "NOT", "BUT",
                 "ALL", "ANY", "MAY", "NEW", "NOW", "SEE", "TOP", "GET", "GOT",
                 "LET", "SAY", "ASK", "OFF", "PER", "USA", "AIR", "USE", "END",
                 "OWN", "WAY", "LOW", "BIG", "ITS", "ONE"}
    CODE_UPPER_ONLY = {"DAY", "FAR"}

    @classmethod
    def _codes(cls, raw):
        """Airport codes named in the message, in the order they appear.

        Matched case-insensitively: "jfk is in which city?" used to be invisible
        to routing AND to the scope guard, so a question about an airport that
        is in the dataset came back as out of scope. Validity is a question for
        the database, not for a hand-maintained allowlist.
        """
        text = raw or ""
        out, seen = [], set()
        for m in re.findall(r"\b([A-Za-z]{3})\b", text):
            c = m.upper()
            if c in seen or c in cls.CODE_STOP:
                continue
            seen.add(c)
            if c in cls.CODE_UPPER_ONLY and not re.search(rf"\b{c}\b", text):
                continue
            if db.code_exists(c):
                out.append(c)
        return out

    @classmethod
    def _ngrams(cls, q: str) -> list[str]:
        """Word n-grams (longest first) that might name an airport."""
        words = re.findall(r"[a-z']+", q.lower())
        out = []
        for size in (3, 2, 1):
            for i in range(len(words) - size + 1):
                span = words[i:i + size]
                if any(w in cls.STOPWORDS for w in span):
                    continue
                if size == 1 and (len(span[0]) < 4 or span[0] in cls.NAME_NOISE):
                    continue
                out.append(" ".join(span))
        return out

    @classmethod
    def _best_span(cls, text: str) -> tuple[str | None, float]:
        best, score = None, 0.0
        for span in cls._ngrams(text):
            bonus = 0.04 * (len(span.split()) - 1)   # prefer longer spans
            for sc, a in db.score_airport_match(span)[:1]:
                if sc + bonus > score:
                    best, score = a["code"], sc + bonus
        return best, score

    @classmethod
    def _name_guess(cls, q: str, threshold: float = 0.75) -> str | None:
        """Resolve an airport name in free text.

        `threshold` is raised by the caller when the sentence contains no
        aviation vocabulary at all. Without that, ordinary words fuzzy-match
        airport names and "how do I cook pasta" comes back as an airport
        profile, which is a far worse failure than admitting we don't know.
        """
        best, score = cls._best_span(q)
        return best if score >= threshold else None

    @classmethod
    def _multi_name_guess(cls, q: str, threshold: float = 0.75) -> list[str]:
        out: list[str] = []
        for part in re.split(r"\b(?:and|vs\.?|versus|against|between|,)\b", q.lower()):
            metro_codes, _ = db.resolve_metro(part)
            if metro_codes:
                if metro_codes[0] not in out:
                    out.append(metro_codes[0])
                continue
            best, score = cls._best_span(part)
            if best and score >= threshold and best not in out:
                out.append(best)
        return out


# --------------------------------------------------------------------------
def get_provider() -> BaseProvider:
    """The keyless planner.

    Model access moved to LangChain (see api/agent/llm.py and graph.py). This
    remains the no-key path: it answers by matching questions to the same
    deterministic tools, so the app still works with nothing configured, and the
    routing and memory tests run without any third-party package installed.
    """
    return RuleBasedProvider()
