# 08 — Frontend spec

> **Superseded by `docs/front/Wonderful_Frontend_Design_Spec.md`**, which is the
> design direction actually implemented: light-first, orb-centred, conversational,
> with human-readable progress steps instead of technical tool logs. Keep this file
> as the earlier analyst-terminal concept; see the Wonderful spec for what shipped.


## Layout — two panes, and the right pane is the point

```
┌───────────────────────────────┬────────────────────────────────┐
│  CHAT                         │  EVIDENCE                      │
│                               │                                │
│  user: Which New England      │  ┌──────────────────────────┐  │
│  airports are candidates      │  │ Profile: terminal        │  │
│  for terminal expansion?      │  │ Vintage: T-100 → 2026-05 │  │
│                               │  │ Confidence: ●●○ Medium   │  │
│  🔧 list_airports    (18ms)   │  └──────────────────────────┘  │
│  🔧 rank_airports    (44ms)   │  Rank  Apt  Score  Tier        │
│                               │   1    BOS   78    A           │
│  assistant: Three stand out…  │   2    BDL   64    B           │
│                               │   3    PVD   61    B           │
│  [🎤]  Ask a follow-up…  [↵]  │  ── BOS pillar breakdown ──    │
│                               │  Saturation  ████████░░ 0.82   │
│                               │  Unmet dem.  ██████░░░░ 0.61   │
│                               │  Growth      █████░░░░░ 0.53   │
│                               │  Feasibility ███░░░░░░░ 0.31 ⚠ │
│                               │  ▸ Assumptions (3)             │
└───────────────────────────────┴────────────────────────────────┘
```

The evidence pane is not decoration — it is how you demonstrate "deterministic scoring" and "explains its reasoning" **visually, in one glance**, without the reviewer reading your code. Build it.

## Components
| Component | Role |
|---|---|
| `ChatPane` | messages, streaming tokens, mic button, voice-mode toggle |
| `ToolTrace` | collapsed one-liner per tool call: name, duration, expandable args/results |
| `RankTable` | ranked rows, tier badges (A red / B amber / C blue / D grey), click → drill in |
| `PillarBars` | five horizontal bars, weight shown, ⚠ on any pillar dragging the geometric mean |
| `AssumptionsPanel` | collapsible; every assumption **editable** where it's a parameter |
| `ConfidenceBadge` | High/Med/Low + hover explaining what's missing |
| `SensitivityChart` | rank band (10th–90th pct) per airport under weight perturbation |
| `MapView` *(optional)* | react-simple-maps dots sized by score. Nice, not necessary. |

## Interaction details that earn credit
- **Stream tool calls as they happen.** Watching `rank_airports (44ms)` appear before the prose is the clearest possible proof the model isn't making numbers up.
- **Make assumptions clickable.** Long-haul threshold as an editable field that re-runs the query is a 15-minute feature that directly demonstrates "clearly communicate assumptions."
- **Suggested follow-up chips** under each answer ("Why is BDL ahead?", "Is this stable?") — makes conversational depth discoverable in a demo where the reviewer doesn't know what to ask.
- **Mic button states:** idle → listening (pulsing) → transcribing → thinking → speaking. Show the transcript *and any airport-code corrections* before sending, so a mis-hear is visibly caught rather than silently wrong.
- **Empty state** listing the four sample questions as one-click buttons. The reviewer's first 10 seconds should require no typing.

## Styling
Tailwind, dark, dense, analyst-tool feel — think Bloomberg terminal, not consumer chatbot. Tabular numerals (`font-variant-numeric: tabular-nums`) so columns align. Colour carries meaning only alongside a label (tier badges say "A", not just red).

## State
```ts
type AppState = {
  messages: Message[];
  evidence: Evidence | null;       // latest tool output for the right pane
  conversationState: {             // mirrors the backend state object
    lastAirports: string[]; lastProfile: string;
    lastWeights: Record<string, number>; lastRegion?: string;
  };
  voiceMode: boolean; listening: boolean; speaking: boolean;
};
```
Plain `useState` + `useReducer`. No Redux/Zustand for one screen.

## Cut list, in order
Drop these first if time runs short: MapView → SensitivityChart → editable assumptions → suggested chips. **Never cut:** tool trace, rank table, assumptions panel. Those three *are* the assignment's stated requirements rendered on screen.
