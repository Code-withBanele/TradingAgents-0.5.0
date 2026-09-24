# Market structure and setup evaluation specification

This document defines the observable behavior required of
`tradingagents.dataflows.market_structure`. It is an independent contract for
implementation and review. It describes deterministic candidate generation;
it does not establish that the concepts are profitable or validated against
real XAUUSD charts.

## Input and time rules

- Inputs are chronological `Candle` objects. `None` is treated as empty; any
  non-`Candle` member raises `TypeError`.
- Naive timestamps are interpreted as UTC. A `Z` suffix and explicit offsets
  are accepted and normalized to UTC for comparisons.
- Session classification uses London and New York local clocks (`Europe/London`
  and `America/New_York`) so daylight saving transitions follow each region's
  calendar. Each market window is 08:00 inclusive through 17:00 exclusive.
  When both windows are open the label is `LONDON_NEW_YORK_OVERLAP`. Asia is
  the configured UTC window 00:00–08:00. Other times are outside configured
  sessions. `session_open`, `session_high`, and `session_low` use UTC-calendar-
  day grouping, not the local session window used to choose the `session`
  label; they summarize that UTC date's candles rather than session-window-only
  extrema.

## Structural event rules

- A swing high/low is a strict local extreme within the configured lookback;
  equal prices do not form swings. `require_confirmation=True` emits a point
  only when the full right-side window exists and supplies its
  `confirmation_index`. Unconfirmed left-context candidates have no
  confirmation index and must not be used as confirmed liquidity.
- A break of structure is a close crossing the nearest preceding swing high
  or low after the prior close was on the other side. Its reference swing must
  already be confirmed, and the event records the break candle index.
- A liquidity sweep requires a current wick that actually reaches through a
  prior support/resistance level and the next candle close to reclaim that
  level. Bullish and bearish reach tests are symmetric (`low <= support`,
  `high >= resistance`). No hidden price percentage tolerance is applied. The
  swept candle and reclaim-confirmation indices are recorded separately.
- A fair value gap is a three-candle non-overlap between the first candle's
  extreme and the third candle's opposing extreme, optionally widened by the
  configured tolerance. The returned bounds are ordered low to high; the
  middle candle's index and third-candle availability index are recorded
  separately.
- An order block candidate is the prior candle's range associated with a
  directional close displacement. By default displacement must be at least
  `min_atr_multiple` times ATR computed from bars preceding the impulse. The
  explicit `min_displacement` argument opts into an absolute price threshold
  and permits a candidate at index 1 because it does not require ATR history.
  Source and impulse-confirmation indices are recorded. This detector remains
  a candidate heuristic, not a labeled institutional order-block classifier.
- A breaker block is an order-block candidate followed by a close beyond its
  far edge. Iterable input must be consumed once and reused for both steps.

## Registered strategies

`LIQUIDITY_SWEEP_FVG_REVERSAL` requires a confirmed sweep and a FVG with the
same direction. `LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL` requires a confirmed
sweep, same-direction order block, and same-direction structure break. Every
listed confirmation rule is mandatory; unrelated features cannot substitute
for a missing required feature.

For either setup, entry is the midpoint of its matching FVG or order-block
zone. The stop is beyond both the swept level and the zone's far edge. A
candidate is invalid if the latest close has crossed its stop. The target is
the nearest prior opposing swing beyond entry. A candidate is `VALID` only
when every required feature and confirmation is present, no invalidation has
occurred, and a structural target exists. Otherwise it is `INVALID`; absent
levels are returned as `None`. These are candidate levels, not execution
instructions or evidence of positive expectancy.

Unknown strategy IDs fail closed with `INVALID` status and version `unknown`.

## Verification boundary

Unit tests can verify determinism, symmetry, iterable handling, DST-aware
classification, registry-specific requirements, and structural level
relationships. They cannot verify that swing, sweep, FVG, or block labels
match a trader's intended reading of XAUUSD. That requires independent
hand-labeled charts with instrument, timeframe, timezone, and label rationale
recorded alongside each example.
