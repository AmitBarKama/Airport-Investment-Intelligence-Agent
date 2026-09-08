"""Deterministic narration of tool results.

Used when no LLM is configured, and as the source of the short `speech_text`
for voice mode. Templates, not generation: the wording is fixed, so it cannot
drift from the numbers.

Answers follow the house structure from the design spec:

    1. Direct answer     -- lead with what matters
    2. Why               -- the main factors, in plain language
    3. Evidence          -- the table or numbers
    4. Caveat            -- assumptions and uncertainty
    5. Next question     -- offered separately, rendered as a card

The tone target is an analyst talking to another analyst: no preamble, no
restating the question, no "based on my analysis of the data".
"""
from __future__ import annotations

NAMES = {"A": "build now", "B": "plan now", "C": "monitor", "D": "no capacity case"}

# A single feasibility ladder. Three unrelated ladders used to disagree inside
# one answer: an airport at 0.70 read as "has room" in the prose and "some"
# room in the adjacent table cell.
FEASIBILITY_BUILDABLE = 0.60
FEASIBILITY_BANDS = ((0.75, "plenty"), (0.50, "some"), (0.0, "very little"))


def _ordinal(n) -> str:
    """1st, 2nd, 3rd -- and 11th/12th/13th, which the naive rule gets wrong.

    The rank was formatted as f"{n}th", so the top airport was reported as
    "1th out of 624".
    """
    if n is None:
        return "?"
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _room(v):
    """Room-to-build label, or None when we simply do not know."""
    if v is None:
        return None
    return next(label for threshold, label in FEASIBILITY_BANDS if v >= threshold)


def _min(v, digits=1):
    return "not loaded" if v is None else f"{v:.{digits}f} min"


def _short_name(row: dict) -> str:
    """A name a person would actually say out loud."""
    n = (row.get("name") or row.get("code") or "").strip()
    for suffix in (" International Airport", " Regional Airport", " Municipal Airport",
                   " International Jetport", " International Ai", " Airport"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n or row.get("code", "")


def _pct(v, digits=1):
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def _num(v):
    return "n/a" if v is None else f"{round(v):,}"


def _spoken_pct(v):
    return "n/a" if v is None else f"{round(v * 100)}%"


def render(tool: str, result: dict) -> tuple[str, str]:
    """Return (markdown_for_screen, short_text_for_speech)."""
    if not isinstance(result, dict):
        return str(result), str(result)
    if result.get("error"):
        msg = result["error"]
        return f"I couldn't answer that. {msg}", msg
    if result.get("ambiguous"):
        opts = ", ".join(f"{c['code']} ({c['city']})" for c in result["candidates"][:4])
        msg = f"That could mean a few airports: {opts}. Which did you mean?"
        return msg, msg
    fn = _RENDERERS.get(tool)
    if not fn:
        return "Done.", "Done."
    return fn(result)


def offers(tool: str, result: dict | None) -> list[dict]:
    """What the agent is offering to do next, as executable actions."""
    if not result or result.get("error") or result.get("ambiguous"):
        return []
    fn = _OFFERS.get(tool)
    try:
        return fn(result) if fn else []
    except (KeyError, TypeError):
        return []


def followup(tool: str, result: dict | None) -> str | None:
    """The 'next question' the agent offers at the end of an answer."""
    return offer_sentence(offers(tool, result))



# ─────────────────────────── the investment case ───────────────────────────
def _fmt_growth(v):
    return None if v is None else f"{v * 100:.1f}% a year"


def _gateway_phrase(gws: list[dict]) -> str | None:
    """Turn route geography into the sentence an analyst would actually say."""
    if not gws:
        return None
    top = gws[0]
    if top["share"] >= 0.55:
        return f"it is primarily a {top['region']} gateway"
    if len(gws) >= 2:
        return (f"its long-haul flying splits between {gws[0]['region']} and "
                f"{gws[1]['region']}")
    return f"its long-haul flying runs mostly to {top['region']}"


def _constraint_kind(k: dict) -> tuple[str | None, str | None]:
    """(what is binding, how hard it is to undo)."""
    if k.get("passenger_cap"):
        return ("a legal passenger cap",
                "that is a negotiation with the surrounding community, not a construction project")
    if k.get("slot_level") == 3:
        return ("federal slot controls",
                "you cannot buy your way past that with concrete")
    if k.get("land_locked") and k.get("imc_constrained"):
        return ("a hemmed-in site and closely spaced runways",
                "terminal work is possible, new runway capacity effectively is not")
    if k.get("land_locked"):
        return ("a land-locked site", "there is nowhere to put another runway")
    if k.get("imc_constrained"):
        return ("runway geometry", "arrival rates collapse whenever the weather closes in")
    if k.get("slot_level") == 2:
        return ("schedule coordination with the FAA", "growth is managed rather than free")
    return (None, None)


def investment_thesis(code: str, name: str, k: dict, tier: str, tier_label: str) -> str:
    """Argue the case in plain language, from facts, not from pillar numbers.

    The score decides the ordering. This explains, in the words a person would
    use, why the ordering came out that way: where the demand is, whether the
    airport is full, and whether you could physically spend money there.
    """
    short = name
    for suffix in (" International Airport", " Regional Airport", " Municipal Airport",
                   " International Jetport", " Airport"):
        if short.endswith(suffix):
            short = short[: -len(suffix)]; break

    dc = k.get("dc_ratio")
    full = dc is not None and dc >= 0.60
    growth = k.get("growth")
    spill = k.get("spill_rate")
    binding, undo = _constraint_kind(k)
    feas = k.get("feasibility")
    buildable = feas is not None and feas >= FEASIBILITY_BUILDABLE
    gateway = _gateway_phrase(k.get("gateways") or [])

    # ── the demand story ────────────────────────────────────────────────
    demand = []
    if growth and growth > 0.02:
        demand.append(f"traffic is growing about {_fmt_growth(growth)}")
    elif growth is not None:
        demand.append(f"traffic is close to flat at {_fmt_growth(growth)}")
    if k.get("destinations"):
        demand.append(f"it already serves {k['destinations']} destinations")
    if gateway:
        demand.append(gateway)
    if (k.get("intl_share") or 0) >= 0.20:
        demand.append(f"{k['intl_share']:.0%} of its departures leave the country, "
                      f"which is the traffic that pays for terminals")
    demand_txt = ("**Where the demand is.** " +
                  _sentence(demand) + ".") if demand else ""

    # ── the capacity story ──────────────────────────────────────────────
    cap = []
    if dc is not None:
        cap.append(f"it is running at about {dc:.0%} of the annual traffic its runways "
                   f"can absorb, which puts it in tier {tier}, {tier_label.lower()}")
    if spill and spill > 0.10:
        cap.append(f"and the load factors suggest it is already turning away roughly "
                   f"{spill:.0%} of the demand that wants to be there")
    if binding:
        cap.append(f"what is actually holding it back is {binding}")
    cap_txt = ("**How full it is.** " + _sentence(cap) + ".") if cap else ""

    # ── the build story: the part investors actually care about ─────────
    if buildable:
        build = (f"**Whether you can build.** This is the part that decides it. "
                 f"{short} has room. {k.get('judgment') or 'There is space to add capacity.'} "
                 f"Plenty of airports are busier; far fewer are busy *and* buildable, "
                 f"and only the second kind is investable.")
    else:
        build = (f"**Whether you can build.** Here is the problem. "
                 f"{k.get('judgment') or 'Expansion options are very limited.'}")
        if undo:
            build += f" {undo[0].upper()}{undo[1:]}."

    # ── the verdict ─────────────────────────────────────────────────────
    if full and buildable:
        verdict = (f"**{short} ({code}) is the one I would put money into.** "
                   f"It is close to full, and unusually for a busy airport, it has "
                   f"somewhere to grow.")
    elif buildable and growth and growth > 0.03:
        verdict = (f"**{short} ({code}) is where I would start.** "
                   f"It is not the busiest airport on this list, and that is the point: "
                   f"demand is climbing into capacity you can actually add.")
    elif not buildable and full:
        verdict = (f"**{short} ({code}) tops the congestion numbers, and I would still "
                   f"be careful.** It is full, but being full is only half the argument.")
    else:
        verdict = f"**{short} ({code}) leads this list.**"

    # ── the risk ────────────────────────────────────────────────────────
    if k.get("passenger_cap") or k.get("curfew"):
        risk = ("**What would go wrong.** Its ceiling is legal, not physical. Capacity "
                "you build cannot be used until the agreement changes, so the deal is "
                "really a bet on that negotiation.")
    elif not buildable:
        risk = ("**What would go wrong.** You could be right about the demand and still "
                "lose, because there is nowhere to put the capacity.")
    elif dc is not None and dc < 0.45:
        risk = ("**What would go wrong.** There is no capacity emergency here yet. The "
                "case rests on growth continuing, so it is a slower, more patient play "
                "than the congested airports.")
    elif growth is None:
        risk = ("**What would go wrong.** I cannot see the growth trend here, because only "
                "one year of traffic is loaded. That matters: this case rests on demand "
                "continuing to rise, and right now that is the one thing I cannot check. "
                "Load a second year of T-100 and I can.")
    else:
        risk = ("**What would go wrong.** Demand growth is the assumption doing the work. "
                "If it flattens, the capacity you added sits idle.")

    return "\n\n".join(x for x in [verdict, demand_txt, cap_txt, build, risk] if x)


def _sentence(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][0].upper() + parts[0][1:]
    joined = ", ".join(parts[:-1]) + ", and " + parts[-1] if len(parts) > 2 else \
             parts[0] + ", " + parts[1]
    return joined[0].upper() + joined[1:]


# ---------------------------------------------------------------- renderers
def _rank(r: dict) -> tuple[str, str]:
    rows = r.get("results", [])
    if not rows:
        return ("I couldn't find any airports matching that. Want to widen the area?",
                "I couldn't find any airports matching that.")
    top = rows[0]
    k = top.get("key_metrics", {})
    k = {**k, "slot_level": k.get("slot_level")}

    body = [investment_thesis(top["code"], top["name"], k, top["tier"], top["tier_label"])]

    if len(rows) > 1:
        runners = rows[1:4]
        lines = ["", "**How the rest of the field looks.**", "",
                 "| Airport | Verdict | Growth | How full | Room to build | Score |",
                 "|---|---|---|---|---|---|"]
        # Was rows[:6], so a top-10 request rendered six and a top-5 request
        # rendered five only by accident. The tool already applied top_n; the
        # cap here is just readability.
        for x in rows[:12]:
            m = x.get("key_metrics", {})
            g = "n/a" if m.get("growth") is None else f"{m['growth']*100:.1f}%"
            fullness = "n/a" if m.get("dc_ratio") is None else f"{m['dc_ratio']:.0%}"
            room = _room(m.get("feasibility")) or "unknown"
            verdict = _one_line_verdict(m)
            lines.append(f"| **{x['code']}** {x['name'][:20]} | {verdict} | {g} | "
                         f"{fullness} | {room} | {x['score']} |")
        body.append("\n".join(lines))

    note = (r.get("filters_applied") or {}).get("region_note")
    if note:
        body.insert(1, f"_{note}. Say the word if you meant somewhere else._")

    w = ", ".join(f"{kk.replace('_', ' ')} {v:.0%}" for kk, v in r["weights"].items() if v > 0)
    body.append(f"\nFor transparency on the ordering: I weighted this {w}, and scored "
                f"every airport against {r['normalised_against']}. It is a screening "
                f"view, not a valuation. Ask me whether the ranking survives different "
                f"weightings and I will test it.")

    # The profile card has always carried this; the ranking card did not, so the
    # tier -- the strongest-sounding claim in the answer -- was presented as a
    # regulator's judgment with its denominator's caveat left on the other page.
    if (k.get("asv_source") or "") != "faa_capacity_profile":
        body.append(
            "\n_Capacity caveat: the annual service volume behind every \u201chow full\u201d "
            "figure and every FAA tier above is derived from runway configuration, not "
            "transcribed from published FAA capacity profiles. Treat the ordering as "
            "sound and the absolute percentages as indicative._")

    speech = (f"I'd put money into {top['code']} first. "
              + (f"It's growing at {k['growth']*100:.0f} percent a year and it has room "
                 f"to build, which most busy airports don't. "
                 if k.get("growth") else "")
              + "Want me to walk through the case?")
    return "\n\n".join(body), speech


def _one_line_verdict(m: dict) -> str:
    """One phrase per airport, using the SAME feasibility ladder as the prose.

    Missing data is reported as missing. The previous version coerced absent
    values to zero, so an airport we simply had no feasibility figure for was
    described as "hard to expand" -- absent data presented as a negative
    finding, which the system prompt explicitly forbids.
    """
    feas, dc, growth = m.get("feasibility"), m.get("dc_ratio"), m.get("growth")
    if m.get("passenger_cap") or m.get("curfew"):
        return "capped by agreement"
    if dc is None and feas is None:
        return "not enough data"
    busy = dc is not None and dc >= FEASIBILITY_BUILDABLE
    can_build = feas is not None and feas >= FEASIBILITY_BUILDABLE
    if busy and can_build:
        return "busy and buildable"
    if busy and feas is not None:
        return "busy, nowhere to build"
    if busy:
        return "busy, buildability unknown"
    if feas is not None and feas >= 0.75 and growth is not None and growth > 0.03:
        return "growth play, room to grow"
    if feas is not None and feas < 0.35:
        return "hard to expand"
    return "worth watching"


def _profile(r: dict) -> tuple[str, str]:
    t, c, o = r["traffic"], r["capacity"], r["operations"]
    lead = (f"**{r['code']} — {r['name']}** handled {_num(t['passengers'])} passengers on "
            f"{_num(t['departures'])} departures, at a {_pct(t['load_factor'])} load factor.")
    why = (f"On capacity it runs at {_pct(c['demand_capacity_ratio'], 0)} of its estimated "
           f"annual service volume, which puts it in **tier {c['tier']} — "
           f"{c['tier_label'].lower()}** under FAA AC 150/5060-5.")
    ev = ["", f"- **Airfield**: {c['runway_config']}, {c['n_runways']} runways"]
    # Only claim delay figures if we actually have them. This used to print
    # "None min median taxi-out" on every single airport.
    if o.get("median_taxi_out_min") is not None:
        ev.append(f"- **Delays**: {_min(o['median_taxi_out_min'])} median taxi-out, "
                  f"{_pct(o['pct_departures_delayed_15min'])} delayed over 15 minutes")
    else:
        ev.append(f"- **Delays**: {o.get('source') or 'not loaded'}")
    ev.append(f"- **Mix**: {_pct(t['long_haul_share'])} long haul, "
              f"{_pct(t['international_share'])} international, "
              f"{t['n_destinations']} destinations")
    if c.get("imc_note"):
        ev.append(f"- **Weather constraint**: {c['imc_note']}")
    if r["constraints"].get("fact"):
        ev.append(f"- **Constraint**: {r['constraints']['fact']}")
    caveat = f"\n**Caveat:** {c['asv_caveat']}"
    speech = (f"{r['code']} handled about {_num(t['passengers'])} passengers at roughly "
              f"{_spoken_pct(t['load_factor'])} load factor. It's tier {c['tier']}, "
              f"{c['tier_label'].lower()}.")
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _mix(r: dict) -> tuple[str, str]:
    h = r["headline"]
    if r["dimension"] != "haul":
        return "Here's how that splits out.", "Here's how that splits out."
    share = h["long_haul_share"]
    thr = int(r["assumptions"]["long_haul_threshold_nmi"])

    lead = (f"**Roughly {_pct(share)} of departures out of {r['code']} are long haul** "
            f"— that's {h['stated_as']}.")
    why = (f"Before you quote that figure anywhere, you should know it depends on where you "
           f"draw the line. I used {thr:,} nautical miles, but there's genuinely no agreed "
           f"standard: the industry uses anywhere from about 2,200 to 2,600, and ICAO and "
           f"IATA both measure by flight time instead, and don't agree with each other "
           f"either. So the number moves quite a bit:")
    alt = r.get("share_at_alternative_thresholds") or {}
    ev = ["", "| If long haul means | Then the share is |", "|---|---|"]
    for k, v in alt.items():
        ev.append(f"| {k.replace('_', ' ')} or more | {_pct(v)} |")
    ev += ["", "| Segment | Departures | Share | Routes |", "|---|---|---|---|"]
    for k, v in r["distribution"].items():
        ev.append(f"| {k.replace('_', ' ')} | {_num(v['departures'])} | "
                  f"{_pct(v['share_of_departures'])} | {v['routes']} |")

    caveat = ("\nOne more thing that matters a lot at this particular airport: "
              + r["assumptions"]["cargo"])
    speech = (f"About {_spoken_pct(share)} of departures from {r['code']} are long haul, "
              f"using a {thr:,} nautical mile cutoff. There's no standard definition though, "
              f"so that number shifts if you move the line. Want me to try a different one?")
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _unmet(r: dict) -> tuple[str, str]:
    sp = r["spill"]
    name = r["name"].replace(" International Airport", "").replace(" Airport", "")
    lead = (f"Short answer: **{name} looks like it's turning away somewhere around "
            f"{_pct(sp['spill_rate'])} of the demand that wants to fly there** "
            f"— call it {_num(sp['spill_passengers'])} passengers a year.")

    measured = [d for d in r["drivers"] if d["type"] == "measured"]
    bits = [d["driver"].lower() for d in measured[:3]]
    why = ("Why that happens comes down to "
           + (", ".join(bits[:-1]) + " and " + bits[-1] if len(bits) > 1
              else (bits[0] if bits else "how full the aircraft are running"))
           + ". Let me take them in turn.")

    ev = [""]
    for d in r["drivers"]:
        tag = "we can measure this" if d["type"] == "measured" else "this one is an estimate"
        ev.append(f"- **{d['driver']}** ({tag}): {d['detail']}")

    ev += ["", "I want to be clear about which parts of that are solid and which aren't. "
               + r["epistemic_note"], "", "And here's what I genuinely can't tell you:"]
    for u in r["unknown"]:
        ev.append(f"- {u}")

    caveat = (f"\nWorth knowing about the estimate itself: {sp['note']}")
    speech = (f"{name} is turning away roughly {_spoken_pct(sp.get('spill_rate'))} of its "
              f"potential demand. Mostly that's "
              f"{' and '.join(bits[:2]) if bits else 'very full aircraft'}. "
              f"Want me to break that down?")
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _compare(r: dict) -> tuple[str, str]:
    codes = [a["code"] for a in r["airports"]]
    dc = next((row for row in r["comparison"] if row["metric"] == "dc_ratio"), None)
    leader = dc["more_congested"] if dc else codes[0]
    capped = [a for a in r["airports"] if a.get("passenger_cap") or a.get("curfew")]

    if capped:
        c = capped[0]
        lead = (f"On the raw numbers **{leader} is clearly the busier of the two**, but I'd "
                f"push back a little on the question. **{c['code']} isn't quiet because it "
                f"has room. It's quiet because it's legally not allowed to grow.**")
        why = (f"That distinction really matters if you're thinking about writing a cheque. "
               f"{c['code']} sits under a passenger cap"
               + (" and a night curfew" if c.get("curfew") else "")
               + f", so the low congestion reading is demand being held down, not demand that "
                 f"isn't there. {leader} is genuinely full. {c['code']} is genuinely capped. "
                 f"You can build your way out of the first problem; the second one is a "
                 f"negotiation, not a construction project.")
    else:
        lead = f"**{leader} is the busier of the two**, and it isn't especially close."
        why = (f"It runs nearer its capacity ceiling, sits in the queue longer before takeoff, "
               f"and misses its departure times more often. Here's the side by side.")

    ev = ["", "| Metric | " + " | ".join(codes) + " | Busier |",
          "|---|" + "|".join(["---"] * (len(codes) + 1)) + "|"]
    for row in r["comparison"]:
        disp = row.get("display") or {}
        vals = " | ".join(disp.get(c) or ("n/a" if row["values"].get(c) is None
                                          else str(row["values"][c])) for c in codes)
        ev.append(f"| {row['label']} | {vals} | {row['more_congested'] or 'n/a'} |")
    for a in r["airports"]:
        flags = []
        if a.get("slot_level"):
            flags.append(f"IATA Level {a['slot_level']}")
        if a.get("curfew"):
            flags.append("night curfew")
        if a.get("passenger_cap"):
            flags.append("passenger cap")
        if flags:
            ev.append(f"\n- **{a['code']}**: {', '.join(flags)}")
        if a.get("constraint"):
            ev.append(f"  {a['constraint']}")

    caveat = (f"\nThe trap to avoid here: {r['interpretation_warning']}")
    speech = (f"{leader} is busier on the raw numbers"
              + (f", but {capped[0]['code']} is capped by legal agreement rather than by "
                 f"capacity, which is a completely different problem." if capped else ".")
              + " Want the detail?")
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _explain(r: dict) -> tuple[str, str]:
    top = r["contributions"][0] if r["contributions"] else None
    lead = (f"**{r['code']} comes out at {r['score']}**, which puts it {_ordinal(r['rank_national'])} "
            f"out of {r['cohort_size']} airports nationally, in tier {r['tier']}.")
    why = (f"What's really costing it is **{top['pillar'].replace('_', ' ')}**, sitting at "
           f"{top['value']:.2f}. That single line accounts for about "
           f"{top['share_of_shortfall']:.0%} of the gap between this score and a perfect one."
           if top else "")
    ev = ["", "| What I looked at | Score | How much I weighted it | Share of the shortfall |",
          "|---|---|---|---|"]
    for c in r["contributions"]:
        ev.append(f"| {c['pillar'].replace('_', ' ')}{' (weak)' if c['drag'] else ''} | "
                  f"{c['value']:.2f} | {c['weight']:.0%} | {c['share_of_shortfall']:.0%} |")
    if r["dragging_pillars"]:
        ev.append(f"\nThe weak spots are **"
                  f"{', '.join(p.replace('_', ' ') for p in r['dragging_pillars'])}**. "
                  f"Because I multiply these together rather than average them, a weak area "
                  f"can't be papered over by a strong one. That's deliberate: an airport that "
                  f"physically can't expand isn't a good investment however busy it is.")
    caveat = f"\nOn reading the table: {r['how_to_read']}"
    speech = (f"{r['code']} scores {r['score']}, ranking {r['rank_national']} nationally. "
              f"The main thing holding it back is {top['pillar'].replace('_', ' ')}." if top else "")
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _sens(r: dict) -> tuple[str, str]:
    lead = f"**{r['headline']}**"
    why = (f"Here's what I did: I re-ran the whole ranking {r['n_draws']} times, nudging the "
           f"weights around each time. I'm not asking you to trust that I picked the right "
           f"weights. I'm showing you whether the answer would change much if I hadn't.")
    ev = ["", "| Airport | Median rank | 10th–90th pct | P(1st) | Stable |", "|---|---|---|---|---|"]
    for a in r["airports"][:12]:
        b = a["rank_band_p10_p90"]
        ev.append(f"| {a['code']} | {a['median_rank']:.0f} | {b[0]}–{b[1]} | "
                  f"{a['p_top1']:.0%} | {'yes' if a['stable'] else 'no'} |")
    caveat = f"\n**Caveat:** {r['assumptions']['sensitivity']}"
    return "\n\n".join([lead, why]) + "\n" + "\n".join(ev) + "\n" + caveat, r["headline"]


def _list(r: dict) -> tuple[str, str]:
    lead = f"**Found {r['count']} airports.**"
    ev = ["", "| Code | Name | City | Passengers |", "|---|---|---|---|"]
    for a in r["airports"][:20]:
        ev.append(f"| {a['code']} | {a['name'][:32]} | {a['city'] or '—'} | "
                  f"{_num(a['passengers'])} |")
    return lead + "\n" + "\n".join(ev), f"Found {r['count']} airports."


# ---------------------------------------------------------------- followups
def _programmes(r: dict) -> tuple[str, str]:
    name = r["name"].replace(" International Airport", "").replace(" Airport", "")
    findings = r.get("findings") or []

    if r.get("unavailable"):
        lead = (f"**I have no live web access configured, so I can't tell you what "
                f"{name} has announced recently.**")
        why = ("What I do have is the curated constraint note from when this database "
               "was built:" if r.get("curated_fallback") else
               "Set TAVILY_API_KEY or BRAVE_API_KEY and I can go and look.")
        ev = [f"\n> {r['curated_fallback']}"] if r.get("curated_fallback") else []
        if r.get("curated_source"):
            ev.append(f"\nSource: {r['curated_source']}")
        return "\n\n".join([lead, why] + ev), (
            f"I don't have web access configured, so I can't check what {name} "
            f"has announced.")

    lead = (f"**Here is what has been reported about {name}'s plans.** "
            f"This is third-party reporting, not something I can verify, and none "
            f"of it feeds the score.")
    ev = [""]
    for f in findings:
        when = f.get("published") or "date not reported"
        ev.append(f"- **{f.get('publisher')}** ({when}): {f.get('claim')}  \n  {f.get('url')}")
    caveat = ("\n" + r["assumptions"]["web"])
    speech = (f"There are {len(findings)} recent reports about {name}'s plans. "
              f"They are announcements, not delivered capacity.")
    return "\n\n".join([lead]) + "\n" + "\n".join(ev) + "\n" + caveat, speech


def _research(r: dict) -> tuple[str, str]:
    findings = r.get("findings") or []

    if r.get("unavailable"):
        lead = "**I have no live web access configured, so I could not look that up.**"
        why = ("Set `TAVILY_API_KEY` or `BRAVE_API_KEY` in `.env` and I will go and "
               "read the sources. What I hold locally is BTS T-100 and OurAirports, "
               "which does not cover this.")
        return f"{lead}\n\n{why}", ("I do not have web access configured, so I could "
                                     "not look that up.")
    if not findings:
        return (f"**I searched and found nothing usable on that.**\n\n"
                f"Query used: `{r.get('query_used')}`",
                "I searched and found nothing usable on that.")

    lead = ("**Here is what I found.** Third-party reporting, cited so you can check "
            "it, and none of it feeds any score.")
    ev = [""]
    for f in findings:
        when = f.get("published") or "date not reported"
        ev.append(f"- **{f.get('publisher')}** ({when}): {f.get('claim')}  \n  {f.get('url')}")
    speech = (f"I found {len(findings)} sources on that. They are third-party claims, "
              f"not our data.")
    return lead + "\n" + "\n".join(ev) + "\n\n" + r["assumptions"]["web"], speech


# ------------------------------------------------------------------- offers
# An offer is a sentence AND the action that satisfies it. These used to be
# hand-written strings with no action attached, so when the user answered "yes"
# there was nothing to run: the affirmative matched no handler and fell through
# to the out-of-scope refusal. Both now come from one list, so the words and
# the behaviour cannot drift apart. The first offer is the one "yes" runs, so
# it is always the one we can actually perform.

def _o_rank(r):
    rows = r.get("results") or []
    if len(rows) >= 2:
        return [{"label": f"explain why {rows[0]['code']} is ahead of {rows[1]['code']}",
                 "tool": "explain_score", "args": {"code": rows[0]["code"]}},
                {"label": "test how stable that ranking is",
                 "tool": "sensitivity_analysis",
                 "args": {"codes": [x["code"] for x in rows[:8]]}}]
    if rows:
        return [{"label": "break down how that score was built",
                 "tool": "explain_score", "args": {"code": rows[0]["code"]}}]
    return []


def _o_unmet(r):
    return [{"label": "break down which constraint matters most",
             "tool": "explain_score", "args": {"code": r["code"]}},
            {"label": f"compare {r['code']} against its regional peers"}]


def _o_mix(r):
    return [{"label": f"see {r['code']}'s top destinations",
             "tool": "flight_mix",
             "args": {"code": r["code"], "dimension": "destination"}},
            {"label": "change the long-haul threshold"}]


def _o_compare(r):
    codes = [a["code"] for a in r.get("airports") or []]
    if len(codes) < 2:
        return []
    return [{"label": f"score {' and '.join(codes)} on expansion upside rather "
                      f"than congestion",
             "tool": "rank_airports", "args": {"codes": codes}}]


def _o_profile(r):
    return [{"label": f"estimate unmet demand at {r['code']}",
             "tool": "unmet_demand", "args": {"code": r["code"]}},
            {"label": "compare it with a peer"}]


def _o_explain(r):
    # codes are filled from the conversation's last ranking at accept time.
    return [{"label": "test whether that ranking holds under different weights",
             "tool": "sensitivity_analysis", "args": {}}]


def _o_sens(r):
    return [{"label": "re-rank with growth weighted over congestion",
             "tool": "rank_airports",
             "args": {"weights": {"growth": 0.45}}}]


def _o_list(r):
    codes = [a["code"] for a in (r.get("airports") or [])][:12]
    if not codes:
        return []
    return [{"label": "rank these as investment candidates",
             "tool": "rank_airports", "args": {"codes": codes}}]


def _o_programmes(r):
    return [{"label": f"score {r['code']} on capacity",
             "tool": "airport_profile", "args": {"code": r["code"]}},
            {"label": "compare it with a peer"}]


def _o_research(r):
    if r.get("code"):
        return [{"label": f"put that next to {r['code']}'s capacity numbers",
                 "tool": "airport_profile", "args": {"code": r["code"]}}]
    return [{"label": "check that against the capacity data I hold"}]


def offer_sentence(offers) -> str | None:
    """The user-visible wording, derived from the offers themselves."""
    labels = [o["label"] for o in (offers or []) if o.get("label")]
    if not labels:
        return None
    if len(labels) == 1:
        return f"Want me to {labels[0]}?"
    return f"Want me to {labels[0]}, or {labels[1]}?"


_RENDERERS = {
    "capital_programmes": _programmes, "web_research": _research,
    "rank_airports": _rank, "airport_profile": _profile, "flight_mix": _mix,
    "unmet_demand": _unmet, "compare_airports": _compare, "explain_score": _explain,
    "sensitivity_analysis": _sens, "list_airports": _list,
}
_OFFERS = {
    "capital_programmes": _o_programmes, "web_research": _o_research,
    "rank_airports": _o_rank, "airport_profile": _o_profile, "flight_mix": _o_mix,
    "unmet_demand": _o_unmet, "compare_airports": _o_compare, "explain_score": _o_explain,
    "sensitivity_analysis": _o_sens, "list_airports": _o_list,
}
