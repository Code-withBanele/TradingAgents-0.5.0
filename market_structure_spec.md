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
  sessions. Session range fields are aggregated from candles belonging to the
  current configured session window, not the full UTC calendar day.

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

## Phase 3C deterministic extensions

- A swing is the strict local extreme defined above. Confirmed swings require
  the complete right-side lookback; indices are zero-based candle indices and
  timestamps are copied from the source candle. No detector backdates an event
  timestamp to a candle that was not available when it confirmed.
- Market direction continues to use the existing higher-low / lower-high / then
  higher-high / lower-low ordering in `compute_market_structure`. The protected
  swing is the latest confirmed low in a bullish state or high in a bearish
  state. A close crossing the nearest confirmed swing in the current direction
  is BOS. An opposing close crossing is CHoCH. It is labeled MSS only when it
  crosses the protected swing and its body is at least 1.5 times the prior ATR.
  ATR is calculated on bars before the break. Neutral or unknown context yields
  BOS because reversal cannot be established from absent directional state.
- CISD uses the isolated `cisd-v1` definition: a directional candle body must
  close through the open of the latest opposing candle and meet the configured
  body-ratio floor. A later close beyond the candidate close confirms it; a
  close through the candidate extreme invalidates it first. A wick alone never
  qualifies. Displacement is optional and disabled by default. This definition
  is versioned because the term has multiple methodology-specific meanings.
- FVG status is evaluated over the candles supplied in the current snapshot:
  ACTIVE until later trading enters the gap, PARTIALLY_MITIGATED on first entry,
  FULLY_MITIGATED on a trade to the far boundary, and INVALIDATED on a close
  beyond that boundary. Formation and confirmation indices remain explicit.
  Historical callers must pass only data available at their as-of time.
- Premium/discount requires an explicit structural, session, or custom range.
  Custom ranges must be provided. Structural range uses the latest confirmed
  high and low; session range uses the active configured session window.
- Previous levels aggregate the most recent completed available local calendar
  day and ISO week, excluding the current local day/week. Missing observations
  are not synthesized; if no prior period is present, levels are `None`.
- Session ranges include only candles inside the active timezone-aware session
  window up through the latest candle. Classification and range aggregation are
  separate; outside-session snapshots have no current session range.
- XAUUSD precision is caller configuration. `InstrumentConfig` defaults retain
  generic FX-compatible pip/decimal settings for compatibility; callers should
  explicitly supply gold settings (commonly 0.01 pip/tick and two decimals).
  Provider precision can override the configured decimals when supplied by the
  caller. No symbol-based inference is performed.
