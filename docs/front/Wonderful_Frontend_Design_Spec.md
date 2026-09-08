# Wonderful — Frontend Design Specification (MVP)

## 1. Product Concept

**Wonderful** is an AI-powered **Airport Investment Intelligence Agent** for investment analysts evaluating airport modernization opportunities in the United States.

The experience should feel less like a generic chatbot and more like **sitting across from a highly knowledgeable aviation investment analyst**.

The agent should:
- Speak naturally and clearly.
- Explain complex aviation data in normal human language.
- Give conclusions first, then explain the reasoning.
- Use public aviation/airport data and deterministic scoring logic.
- Show where the information came from.
- Clearly distinguish facts, estimates, assumptions, and uncertainty.
- Support conversational follow-up questions.

### Core UX principle

> **The AI should feel like an expert who happens to be conversational — not an LLM that happens to know data.**

Avoid huge walls of text, overly technical language, and robotic bullet-point dumps.

---

# 2. Visual Direction

The UI should be **minimal, calm, premium, and AI-first**.

Think:
- Apple-like simplicity
- Modern AI assistant
- Very generous whitespace
- Rounded surfaces
- Subtle borders
- Soft shadows
- Almost no visual clutter
- One recognizable AI visual: the Wonderful orb

The primary experience is **the conversation**, not a dashboard full of charts.

Charts, tables, maps, and rankings should appear **only when they help answer the question**.

---

# 3. Color & Theme

## Light Mode

- Background: `#FFFFFF`
- Surface: `#F8FAFC`
- Primary text: `#0B0F1A`
- Secondary text: `#475569`
- Muted text: `#94A3B8`
- Border: `#E2E8F0`
- Primary accent: `#3B82F6`
- Secondary accent: `#8B5CF6`
- Orb gradient: soft blue / purple / pink

## Dark Mode

- Background: `#090D14`
- Surface: `#111827`
- Primary text: `#F8FAFC`
- Secondary text: `#CBD5E1`
- Muted text: `#64748B`
- Border: `#1E293B`
- Accent: blue / purple
- Orb remains luminous against the dark background

The user must be able to switch between:

**Light / Dark / System**

---

# 4. Typography

Use **Inter** as the primary font.

Fallback:

`SF Pro → Helvetica Neue → Arial`

### Typography

| Element | Size | Weight |
|---|---:|---|
| H1 | 48px | 700 |
| H2 | 32px | 600 |
| H3 | 20px | 600 |
| Body | 16px | 400 |
| Small | 14px | 400 |
| Caption | 12–13px | 400 |

Keep typography clean and highly readable.

---

# 5. Main Application Layout

The application should have a simple two-part structure:

```text
┌──────────────────────────────────────────────────────┐
│ Wonderful                         Theme     Avatar   │
├───────────────┬──────────────────────────────────────┤
│               │                                      │
│   New Chat    │              AI CHAT                 │
│               │                                      │
│   Today       │                                      │
│   • New       │       User question                  │
│   England     │                                      │
│   • LAX/SNA   │       AI expert response             │
│   • SFO       │                                      │
│               │       Data / charts when useful      │
│               │                                      │
│               │                                      │
│               │   ┌──────────────────────────────┐   │
│               │   │ Ask a follow-up...       →   │   │
│               │   └──────────────────────────────┘   │
└───────────────┴──────────────────────────────────────┘
```

On the landing screen, the sidebar can be hidden so the experience feels even more minimal.

---

# 6. Landing / Welcome Screen

The first screen should feel like opening an AI expert rather than opening a traditional analytics platform.

Center the Wonderful orb near the upper-middle portion of the screen.

### Hero

**Your airport investment expert.**

Supporting text:

> Ask questions about airports, capacity, passenger demand, congestion, and expansion opportunities — and get clear, data-driven answers.

Below it, show 3–4 example questions.

### Example questions

- Which airports in New England are strong candidates for terminal expansion?
- Compare LA and Santa Ana airport congestion levels.
- What percentage of long-haul flights leave Anchorage?
- What is the unmet flight demand at SFO, and why?

At the bottom:

```text
[ + ]   Ask me anything about airports...                    [ → ]
```

---

# 7. The AI Orb

The supplied Wonderful orb is the central visual identity of the product.

Use the orb consistently throughout the experience.

It should not simply be a static image.

The orb represents the state of the agent.

## States

### Idle

Small, softly glowing orb.

No animation or only extremely subtle breathing.

### Listening

When voice input is active:

- Orb becomes slightly larger.
- Several thin rings appear around it.
- Rings gently expand outward.
- Small waveform/ripple effect.
- Text:

**Listening...**

### Thinking

This is the most important animation.

Make it feel similar to **Siri's active/thinking state**, while keeping Wonderful's visual identity.

Animation:

```text
       ◌
    ◌  ORB  ◌
       ◌
```

Use multiple translucent rings that continuously expand and fade.

The orb itself should very subtly:
- Scale up/down
- Shift its internal gradient
- Increase/decrease glow
- Pulse slowly

Text underneath:

**Analyzing airport data...**

Then show short, human-readable progress steps:

```text
✓ Fetching latest passenger data
✓ Checking airport capacity
✓ Comparing demand trends
○ Evaluating expansion potential
```

Do NOT show technical agent logs such as:

```text
Calling tool...
Executing function...
Running LLM...
Parsing JSON...
```

The user should feel that the expert is **thinking**, not that they are watching backend processes.

### Speaking

When voice output is playing:

- Orb gently pulses with the voice.
- Glow reacts to speech volume.
- Small circular waveform around the orb.

Text:

**Speaking...**

---

# 8. Voice Experience

Voice should be optional.

The microphone button is located inside the chat input.

When activated, the interface transitions into a focused voice state.

Example:

```text
             ✦
        [ Wonderful Orb ]

           Listening...

       ─── waveform ───

        Tap to stop
```

After the user stops speaking:

```text
Analyzing your question...
```

Then the orb enters the Thinking state.

When the response is ready:

```text
Speaking...
```

The user should be able to interrupt the agent.

---

# 9. Chat Experience

The chat is the main product.

Avoid the typical:

```text
User:
...

AI:
...
```

Instead, make the conversation feel like a real expert consultation.

### User message

Right aligned.

Use a subtle rounded bubble with a very light blue/purple tint.

Example:

> Which airports in New England are strong candidates for terminal expansion?

### AI message

Left aligned.

Show a small Wonderful orb next to the response.

The response should begin naturally:

> Based on the latest passenger data and our investment criteria, I'd start with Boston, Manchester, and Providence.

Then explain why.

---

# 10. Human-Like Answer Structure

The AI should generally follow this structure:

### 1. Direct answer

Tell the user what matters immediately.

### 2. Why

Explain the main factors in simple language.

### 3. Evidence

Show relevant numbers, charts, tables, or rankings.

### 4. Caveat

Mention assumptions or uncertainty when relevant.

### 5. Next question

Offer a useful follow-up.

Example:

> **I'd put Boston first, followed by Manchester and Providence.**
>
> Boston has the strongest combination of passenger volume, utilization, and international demand. Manchester is smaller, but its growth and available capacity make it interesting from a different investment angle.
>
> The ranking is based on passenger growth, capacity utilization, unmet demand, and strategic value.
>
> **One caveat:** airport capacity data isn't perfectly standardized across airports, so the score should be treated as a screening tool rather than a valuation.
>
> Want me to compare the three on **expansion upside vs. estimated investment risk**?

This should feel like an analyst talking to another person.

---

# 11. Deterministic Intelligence

The UI must make it clear that the answer is not generated purely by the LLM.

Use small source and methodology indicators.

Example:

```text
Investment Score

92 / 100

Passenger growth       25/25
Capacity pressure      23/25
Unmet demand            22/25
Strategic value         22/25
```

The LLM explains the result, but the underlying ranking comes from deterministic logic.

---

# 12. Data Visualization

Do not turn every response into a dashboard.

Only display visualizations when they improve understanding.

Possible components:

- Comparison table
- Bar chart
- Line chart
- Airport ranking
- Capacity vs. demand chart
- Small map
- KPI cards
- Score breakdown

Example:

```text
SFO — Unmet Demand

Estimated unmet demand
12–15%

Demand     ████████████████████
Capacity   ███████████████
```

Keep visualizations compact and embedded naturally inside the conversation.

---

# 13. Sources

Every meaningful data-driven response should show sources.

Use small pill-shaped source labels:

```text
Sources   FAA   BTS   OpenSky   IATA
```

Allow the user to expand them for details.

Example:

```text
Sources
FAA — Airport capacity
BTS — Passenger statistics
OpenSky — Flight activity
IATA — Route information
```

---

# 14. Assumptions & Uncertainty

The agent should never pretend estimates are exact.

Use subtle expandable sections:

```text
ⓘ Assumptions & uncertainty
```

When opened:

```text
Capacity estimates are based on publicly available
airport and aviation data. Airport capacity is not
reported using one universal methodology, so results
should be treated as directional.
```

This is especially important for investment decisions.

---

# 15. Conversation Sidebar

The sidebar should remain very minimal.

Top:

```text
+ New chat
```

Then:

```text
Today

New England expansion
LA vs Santa Ana
Long-haul flights — ANC
Unmet demand — SFO
```

No complicated folders or dashboard navigation in the MVP.

---

# 16. Example Response Screen

For:

**"Which airports in New England are strong candidates for terminal expansion?"**

The AI could respond:

```text
Based on the latest data, I'd start with:

1. Boston Logan (BOS)
2. Manchester-Boston (MHT)
3. Providence (PVD)

Boston is the strongest candidate overall because of its
scale, high utilization, and international demand.

Manchester is interesting for a different reason: it combines
strong growth with more room for additional capacity.

Providence is a smaller opportunity, but its growth and
regional demand make it worth investigating.
```

Then show a compact ranking card:

| Airport | Growth | Utilization | Unmet Demand | Score |
|---|---:|---:|---:|---:|
| BOS | +18% | 92% | High | 92 |
| MHT | +20% | 76% | Medium | 78 |
| PVD | +16% | 71% | Medium | 65 |

Then:

```text
Sources   FAA   BTS   OpenSky   IATA

ⓘ Assumptions & uncertainty
```

And finally:

> Want me to compare these airports based on **investment upside versus expansion risk**?

---

# 17. Follow-Up Questions

The agent must maintain conversational context.

Example:

User:

> Which airports in New England are strong candidates?

Agent:

> Boston, Manchester, and Providence.

User:

> What about Hartford?

The agent should understand that **Hartford / BDL** is being added to the previous comparison.

The user should not need to repeat context.

---

# 18. Dark Mode

Dark mode should not simply invert the colors.

It should feel intentionally designed.

Use:

- Deep navy/black background
- Slightly lighter chat surfaces
- White typography
- Soft blue/purple orb glow
- Subtle borders
- Minimal shadows

The orb should become the primary visual source of color.

---

# 19. Settings

Keep settings simple.

```text
Settings

Appearance
○ Light
● Dark
○ System

Voice
[ On ]

Voice
Siri-style / Natural

Response style
Balanced

Data sources
FAA
BTS
OpenSky
IATA
```

The settings panel should use a clean modal or side sheet.

---

# 20. Microinteractions

Use subtle animation throughout.

Examples:

- Buttons slightly lift on hover.
- Chat bubbles fade/slide in.
- Source pills appear after the answer.
- Charts animate when entering the screen.
- Orb transitions smoothly between states.
- Thinking rings continuously expand and fade.
- Voice waveform responds to audio.

Animations should feel **calm and premium**, never flashy.

---

# 21. Responsive Design

## Desktop

Primary experience:

```text
Sidebar + Chat
```

## Tablet

Reduce sidebar width and content width.

## Mobile

Hide the sidebar behind a menu.

The chat should occupy almost the entire screen.

The input should remain fixed at the bottom.

The orb should scale down appropriately.

---

# 22. Footer

Minimal footer:

```text
Privacy Policy     Security     Vulnerability Disclosure

                         Built with Wonderful
```

---

# 23. Product Personality

The AI should sound:

- Intelligent
- Calm
- Confident
- Conversational
- Analytical
- Honest about uncertainty
- Helpful without being overly enthusiastic

Avoid:

- "As an AI language model..."
- "I have analyzed the data and..."
- Excessive emojis
- Corporate jargon
- Overly long introductions
- Repeating the question
- Robotic tool descriptions

Preferred:

> "I'd start with Boston."

Instead of:

> "According to my analysis, Boston Logan International Airport appears to be the optimal candidate based on the available data."

---

# 24. MVP Screens

The frontend should initially implement these screens/states:

1. **Welcome / Empty Chat**
2. **User Asking a Question**
3. **AI Thinking — Orb Animation**
4. **AI Answer — Text Only**
5. **AI Answer — With Ranking/Table**
6. **AI Answer — With Chart**
7. **Voice Listening**
8. **Voice Speaking**
9. **Dark Mode**
10. **Settings**

The product should always prioritize the feeling of:

> **"I'm talking to an expert who can actually work with the data."**

rather than:

> **"I'm using another AI chatbot."**
