# AI call budget for a realistic XAUUSD backtest

## Assumptions

This budget assumes a 180-day research backtest with one decision cycle per trading day after the session close, using the current three-node analyst-stage estimate:

- Technical / market analyst
- News + macro analyst (combined node for this estimate)
- Sentiment analyst

This gives a 3-node analyst stage, with the analyst calls running in parallel because they all consume the same market context and do not depend on each other. No separate market regime analyst node exists in the current codebase. When a regime analyst is built in a later phase, revise these totals and estimates again to include it.

## Arithmetic behind the call split

### Parallel analyst stage

- 3 analyst nodes per cycle
- 180 cycles
- Total parallel analyst calls = 3 x 180 = 540

This is the part of the run that can be batched or fan-out in parallel because each analyst reads the same market context and generates a separate view.

### Sequential debate / synthesis stage

The model does not issue a single monolithic call per day. The architecture continues as a structured chain:

- Bull researcher: 1 x 180 = 180
- Bear researcher: 1 x 180 = 180
- Research manager: 1 x 180 = 180
- Risk perspective: Aggressive / Neutral / Conservative = 3 x 180 = 540
- Final portfolio / JEV-style synthesis: 1 x 180 = 180

This yields:

- 180 + 180 + 180 + 540 + 180 = 1,260 sequential-stage calls

The arithmetic is intentionally conservative rather than optimistic. It assumes one full debate pass and one risk-scenario pass per decision day, with no extra retry loops counted in the base estimate. If the provider retries after a timeout or malformed response, the real total rises above 1,980.

## Total AI budget

Total estimated AI calls for the 180-day backtest = 540 + 1,260 = 1,800 calls.

## Estimated wall-clock latency

A wall-clock estimate depends on the per-call latency, but a realistic planning range is:

- Fast model, cached or short prompt: ~1-3 seconds per call
- Typical research model with tool/schema overhead: ~5-12 seconds per call
- Slow/reasoning model or network jitter: ~15-30 seconds per call

Using a midpoint estimate of ~6 seconds per call for the full workflow:

- 1,800 calls x 6 seconds = ~10,800 seconds
- ~180 minutes = ~3 hours for the end-to-end run, using the same per-call midpoint and assuming the parallel analyst stage is effectively batched and the sequential chain is serviced in order

In practice, the run will usually be slower than this idealized lower bound because:

- each cycle waits for the previous stage to finish
- some models retry after malformed output or timeouts
- network/caching variability introduces jitter
- the sequential research and risk stages cannot be compressed into a single parallel fan-out

A proportionally adjusted planning range for a serious historical replay is therefore roughly 3.6-9 hours, with a significantly longer run if retries or reasoning models are used at scale. Revise this range again when the regime analyst is built.

## Rough dollar-cost estimate

The rough cost is driven by token usage, which depends on prompt length, debate output, and temperature/response size. A useful planning approximation is:

- Small/open model: ~$0.50-$2.00 per 1M input tokens and ~$1.00-$5.00 per 1M output tokens
- Mid-tier reasoning model: ~$2.00-$10.00 per 1M input tokens and ~$8.00-$30.00 per 1M output tokens
- Premium reasoning model: ~$10.00-$30.00 per 1M input tokens and ~$30.00-$100.00 per 1M output tokens

For a backtest of this size, the practical planning assumption is that each call runs on a prompt that is not enormous but still includes context, research notes, and a structured schema. A rough median assumption is:

- ~2,000 input tokens per call
- ~1,000 output tokens per call
- effective blended cost around ~$0.01-$0.05 per call for a mid-tier provider

That gives a ballpark:

- 1,800 calls x $0.02/call = ~$36.00
- 1,800 calls x $0.05/call = ~$90.00

A more expensive reasoning model can push the run into roughly the $136-$364 range, depending on whether the backtest uses the full debate stack, multiple risk scenarios, and repeated retries. These estimates must be revised when the regime analyst is built. This is why budgets must include retries, caching, and a strict ceiling before Phase 2 execution work begins.

## Why this is a realistic budget

- It matches the repo's architecture, where the analysts are independent of each other and the debate/synthesis chain depends on their output.
- It is large enough to reflect a meaningful backtest range without pretending the model can be called on every 1m bar in a full historical replay.
- It gives the project a concrete ceiling for planning, caching, and budget management before Phase 2 execution work begins.
- It frames the run in terms of worker fan-out, stage dependencies, and provider cost rather than raw call counts alone.

## Important guardrails

- The analyst stage is parallel; the bull/bear/research manager and risk-debate stages are sequential and must not be treated as independent fan-out.
- Cache keying must include model version + strategy version + canonicalized prompt inputs so identical decisions across a historical run can be replayed without changing results.
- Retry loops and malformed-output fallbacks must be treated as budget multipliers rather than rounding noise.
- This budget is a planning estimate, not a promise of profitability or a target for generating favorable backtests.
