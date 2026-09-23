# Decision Gate reliability contract

## Decision

The AI reliability wrapper must fail closed for any request that times out, raises an exception, or returns malformed data. In this system, the default outcome is `no trade`.

## Why this is required

The research graph can only produce valid decision traffic when the model output is both syntactically valid and semantically acceptable. Allowing a timeout, malformed JSON, or schema violation to continue downstream would create a false sense of certainty and could trigger execution against a weak or invalid analysis.

## Contract

1. Every AI call that is expected to return structured data is validated against a schema before the result is allowed to reach downstream nodes.
2. If the call fails, raises an exception, times out, or validates incorrectly, the wrapper retries only up to the configured cap.
3. After the retry cap is exhausted, the wrapper returns `None` and the surrounding gate treats that as a fail-closed `NO_TRADE` outcome.
4. A no-trade result is a real decision state, not a silent pass-through.
5. The wrapper is explicit and opt-in; existing agent fallback behavior remains unchanged elsewhere in the repo.

## Operational effect

This contract prevents the trading layer from acting on a malformed or partial AI output. It is intentionally stricter than a graceful free-text fallback and is designed for XAUUSD execution paths that must not guess under uncertainty.
