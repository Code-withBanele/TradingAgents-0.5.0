# TradingAgents: XAUUSD Quant Research and Decision Architecture

This repository extends the TradingAgents multi-agent research framework with an **early, XAUUSD-focused deterministic quant research layer**. The original general-market AI application remains runnable; the quant engine is an additive research slice and is not yet wired into the graph as an autonomous strategy or execution system.

This is an engineering and research project, **not a finished autonomous trading bot**. It does not place broker orders or establish that any strategy is profitable.

Research / analysis != signal generation != decision making != risk enforcement != order execution.

These layers are intentionally separate. The existing graph can produce AI research and ratings. The quant engine can produce deterministic candidate setups. Quant signals are not connected to a decision gate, deterministic risk engine, execution engine, or broker.

## Current status

| Component | Status | Evidence |
| --- | --- | --- |
| TradingAgents foundation | Implemented | LangGraph workflow, agents, LLM clients, CLI |
| XAUUSD data layer | Partial | `XAUUSD_CONFIG` selects Massive; new async range method uses provider interface; legacy loader remains |
| Quant models/primitives | Partial, research | Shared models and deterministic candle functions; definitions remain heuristic |
| Strategy registry | Partial | Three registered v0.1 candidates |
| TradeSetup to QuantSignal | Partial | Mapper carries timeframe and strategy version; no graph consumer yet |
| JEV | Planned | No JEV module, adapter, or graph node found |
| Provider abstraction | Implemented foundation | Async protocol, capability method, mock and historical adapters |
| Massive Currencies | Adapter implemented; live smoke blocked by TLS in this environment | XAUUSD spot maps to C:XAUUSD; authentication and symbol access remain unverified |
| TradingView / broker | Stub | Provider classes raise NotImplementedError |
| Real XAUUSD verification | Not complete | No connected, independently labeled dataset or quant verification harness |
| Decision gate / risk engine | Planned / spec only | decision_gate_spec.md is a contract, not an integrated engine |
| Execution / live trading | Not implemented | No broker order lifecycle |
| UI | Not implemented | Interactive terminal CLI exists; no Strategy Checker web UI |
| CI | Implemented | GitHub Actions runs pytest, import smoke check, Ruff |

The latest full test run in this checkout was **1,062 passed, 5 skipped, 22 warnings, and 88 subtests passed**. Unit tests are not real-data validation or performance evidence.

## Architecture

This diagram shows intent and current status, not a claim that each box is wired or production-ready.

~~~mermaid
flowchart TD
    subgraph feeds[Market data]
      mock[Mock provider]
      files[CSV and JSON history]
      massive[Massive Currencies adapter, live access unverified]
      tv[TradingView stub]
      broker[Broker stub]
    end
    feeds --> normalize[Historical provider normalization]
    normalize --> candles[Candles and market state]
    candles --> quant[Quant primitives and candidate strategies]
    candles --> agents[Existing LangGraph research workflow]
    quant -. not yet integrated .-> signal[QuantSignal contract]
    agents --> rating[AI research and rating]
    signal -. no current connection .-> gate[Decision gate spec]
    rating --> backtest[Decision-quality grid evaluator]
    gate -. planned .-> risk[Risk engine]
    risk -. planned .-> execution[Paper or broker execution]
~~~

The graph's analysts call existing vendor-routed market, news, macro, sentiment, and technical tools. Separately, market-data providers normalize candles, which callers may pass to deterministic quant functions. There is no application service that automatically routes real XAUUSD data through strategy evaluation and into the graph.

## TradingAgents foundation

The existing framework remains useful and is tested:

- tradingagents/llm_clients: model factory, provider clients, model capabilities, API-key mapping, validation, retries, and reliability helpers.
- tradingagents/graph: LangGraph orchestration, state routing, analyst execution, checkpointing, reflection, and graph-facing signal/rating parsing.
- tradingagents/agents: market/news/fundamental/sentiment analysts, Bull/Bear researchers, research manager, trader, risk-discussion agents, and portfolio manager.
- tradingagents/agents/utils/memory.py and graph/reflection.py: persistent decision notes and outcome reflection.
- cli/: Typer/Rich/Questionary terminal application and decision-grid command.
- tests/: coverage for reliability, point-in-time rules, provider contracts, graph behavior, CLI, and quant primitives.

These modules support AI-assisted research and decision workflows. “Risk” discussion agents are not a deterministic risk-enforcement engine.

## Deterministic Quant Engine

Shared enums and dataclasses are in tradingagents/quant/models.py. Detector implementations remain in tradingagents/dataflows/market_structure.py for compatibility. Results are deterministic for fixed input and parameters, but domain definitions are not all validated against hand-labeled XAUUSD charts.

| Feature | Purpose and implementation | Input -> output | Limitations |
| --- | --- | --- | --- |
| Swings | Strict local high/low; optional right-side confirmation | Candles + lookback -> indexed SwingPoint | Confirmed swings use later candles; usable only at confirmation time |
| Market structure | Higher-low/higher-high and lower-high/lower-low sequence heuristic | Candles -> MarketStructureState | Not a complete protected-swing state machine |
| BOS / CHoCH / MSS | Close across confirmed swing; same-direction BOS, reversal CHoCH; MSS requires protected swing and 1.5x prior ATR body | Candles -> BreakOfStructure | Research definition and unvalidated threshold |
| CISD | Versioned cisd-v1: body closes through latest opposing candle open, then later close accepts beyond candidate close | Candles -> CISDEvent | Chosen operational meaning; not universal ICT definition |
| Liquidity sweep | Wick reaches structural level; next candle close reclaims it | Candles -> LiquiditySweep | Nearest-level heuristic |
| Liquidity pools | Two or more confirmed equal swing highs/lows within absolute tolerance; subsequent wick and reclaim can sweep | Candles -> LiquidityPool list | No separate run classification |
| FVG | Three-candle gap with created, active, partial/full mitigated, and invalidated states | Candles -> FairValueGap list | State reflects all candles passed to the call |
| iFVG | Original FVG closes beyond far boundary, then later close accepts beyond | Candles -> InverseFairValueGap list | Explicit rule, research-only |
| Order blocks | Prior candle range associated with directional displacement; ATR or absolute threshold | Candles -> candidate OrderBlock list | Candidate heuristic, not validated institutional-origin model |
| Breaker blocks | Order-block candidate closes beyond far zone edge | Candles -> BreakerBlock list | No full structural role-reversal validation |
| Displacement | Measures absolute move, ATR multiple, body ratio, direction, and structure-break flag | Candles + threshold -> DisplacementEvent | Versioned but heuristic thresholds |
| Premium / discount | Equilibrium and zones from explicit structural, session, or custom range | Candles + range source -> PremiumDiscountState | Caller selects range; limited context |
| Sessions | London/New York local-time classification with DST-aware windows and active-window range | Candles -> SessionContext | Fixed windows, not an exchange calendar |
| Previous day/week | Latest completed available local calendar day and ISO week | Candles + timezone -> PDH/PDL/PWH/PWL | Missing periods are not synthesized |
| AMD / manipulation BOS | Walks break, sweep extreme, failed pullback, reclaim, invalidation | Candles -> ManipulationConfirmedBOS | Research sequencing; not chart-validated |
| ATR | Simple mean of trailing true range | Candles + period -> volatility result | Requires sufficient history |
| Stochastic | Trailing %K and simple %D | Candles + periods -> oscillator state | Indicator context only |
| VWAP | Typical price weighted by supplied candle volume; optional date/session reset | Candles -> VWAPResult | Source volume semantics are preserved, not reconciled |
| Fibonacci / dedicated support-resistance / volume profile | No dedicated quant implementations found | — | Do not infer these from generic LLM reports |

### Causality

find_swing_points with require_confirmation=False uses only supplied candles. With require_confirmation=True, it waits for a complete right-side window. Historical labels using future bars must not be treated as information available at the pivot time. A complete 1m-trigger / 5m-context availability-time service is not implemented.

### Strategy registry

Only these strategy IDs are registered, each at v0.1:

| Strategy ID | Conditions | Setup semantics | Verified on real XAUUSD? |
| --- | --- | --- | --- |
| LIQUIDITY_SWEEP_FVG_REVERSAL | Confirmed sweep and same-direction FVG | Midpoint entry; stop beyond swept level and zone edge; nearest prior opposing swing target; close through stop invalidates | No |
| LIQUIDITY_SWEEP_ORDER_BLOCK_REVERSAL | Confirmed sweep, matching OB candidate, matching structure break | Midpoint entry; structural stop and nearest opposing swing target | No |
| MANIPULATION_CONFIRMED_BOS | Initial break swept, failed pullback formed, reclaim closed | Reclaim-candle midpoint entry; manipulation extreme stop; nearest eligible untouched opposing swing target | No |

VALID means programmed conditions and levels passed. Confidence is a deterministic passed-condition fraction, **not win probability**.

## TradeSetup and QuantSignal

TradeSetup stores strategy ID/version, direction, confidence, entry, stop, target, validity, conditions, required features, timestamp, and timeframe. QuantSignal stores symbol, timeframe, direction, setup type, strength, reasons, validity, strategy ID/version, entry, stop, target, and timestamp.

to_quant_signal returns None for invalid setups and preserves setup timeframe and strategy version. It maps to the existing generic CONFIRMED_REVERSAL type and is not connected to graph routing, decision gate, risk, or execution.

## AI research and JEV

The existing analyst graph summarizes available data, debates Bull/Bear cases, and produces portfolio ratings. Model output can vary; it is not a guaranteed prediction.

JEV is **not implemented**: no JEV class, adapter, or graph node exists. The existing AI graph is not deterministic quant logic. decision_gate_spec.md is a reliability specification, not an integrated decision gate.

## Market-data architecture

MarketDataProvider is an async protocol for historical candles, latest candle, subscriptions, and capabilities(). HistoricalDataAdapter is a synchronous row adapter. FreeHistoricalDataProvider normalizes adapter/preloaded rows into UTC Candle objects and records dataset metadata. Check provider.capabilities() rather than assuming ticks, spreads, or intervals.

| Provider | Status | Data / credentials | Limitations |
| --- | --- | --- | --- |
| MockDataProvider | Implemented mock | Synthetic deterministic OHLCV; no credentials | Not market evidence; useful for tests, CI, debugging |
| CsvHistoricalAdapter | Implemented | Local CSV OHLCV; no API key | User supplies data provenance and metadata |
| JsonHistoricalAdapter | Implemented | Local JSON OHLCV; no API key | Same source-quality responsibilities |
| MassiveDataProvider | Primary real XAUUSD development provider | Massive Currencies aggregates, `C:XAUUSD`, 1m/5m; `MASSIVE_API_KEY` | Access depends on account subscription; local historical cache and bounded retry |
| FreeHistoricalDataProvider | Implemented importer | Adapter or already-loaded data | Does not discover arbitrary public feeds itself |
| TradingViewDataProvider | Stub | None | Methods raise NotImplementedError |
| BrokerDataProvider | Stub | None | Methods raise NotImplementedError |
| Yahoo-backed general data tools | Used by existing app | yfinance, generally no key | XAUUSD alias maps to GC=F futures, not broker spot/CFD candles |
| Alpha Vantage tools | Existing general data vendor | ALPHA_VANTAGE_API_KEY | Not wired as the quant candle provider |

`XAUUSDDataLayer()` uses the provider named by `XAUUSD_CONFIG` (Massive by default). Inject `MockDataProvider()` to run the same interface offline. No provider selector UI exists yet. To add another provider, implement `MarketDataProvider` or a synchronous `HistoricalDataAdapter` for import-only sources, report only implemented capabilities, register its name in `create_market_data_provider`, and add mocked normalization/error tests. Strategy functions continue to consume canonical `Candle` objects.

Massive's Currencies API exposes historical custom OHLC aggregates. The adapter maps canonical `XAUUSD` to Massive's `C:XAUUSD` symbol. Massive describes forex aggregates as quote-derived, not executed trades. Its free Currencies Basic plan currently lists five API calls per minute and two years of history, so use this as a development/testing source and keep local caching enabled. Confirm current limits and terms in the [Currencies docs](https://massive.com/docs/rest/forex/overview) and [pricing](https://massive.com/pricing?product=currencies). This adapter does not implement ticks, quotes, live subscriptions, or market depth; separate futures products are not used.

~~~python
from datetime import datetime, timezone
import asyncio
from tradingagents.dataflows.intraday_types import Timeframe
from tradingagents.dataflows.market_data_provider import MassiveDataProvider

provider = MassiveDataProvider()  # reads MASSIVE_API_KEY from .env / process environment
candles = asyncio.run(provider.get_historical_candles(
    "XAUUSD", Timeframe.M5,
    datetime(2025, 1, 1, tzinfo=timezone.utc),
    datetime(2025, 1, 3, tzinfo=timezone.utc),
))
print(provider.get_dataset_metadata(timeframe=Timeframe.M5)["data_quality"])
~~~

Run a structured connection probe with `asyncio.run(provider.test_connection(timeframe=Timeframe.M5))`. Results distinguish configuration/authentication errors, provider unavailability, rate limits, symbol unavailability, and capability errors. It requires an authenticated recent range with returned candles. Unit tests mock HTTP; live access must be smoke-tested against the caller's subscription.

The provider-to-quant path can be exercised from Python after setting a key:

~~~python
import asyncio
from datetime import datetime, timedelta, timezone
from tradingagents.dataflows.intraday_types import Timeframe
from tradingagents.dataflows.market_data_provider import MassiveDataProvider
from tradingagents.dataflows.market_structure import compute_market_structure, evaluate_strategy
from tradingagents.quant.models import InstrumentConfig

async def run():
    provider = MassiveDataProvider()
    end = datetime.now(timezone.utc)
    candles = await provider.get_historical_candles(
        "XAUUSD", Timeframe.M5, end - timedelta(days=3), end,
    )
    structure = compute_market_structure(candles)
    setup = evaluate_strategy(
        candles, strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL",
        instrument=InstrumentConfig.xauusd(),
    )
    return candles, structure, setup

candles, structure, setup = asyncio.run(run())
print(len(candles), structure.direction, setup.strategy_id, setup.strategy_version, setup.timeframe, setup.status)
~~~

A strategy may return an `INVALID` TradeSetup if historical candles do not meet its rules. This pipeline validates connectivity and deterministic execution; it is not an outcome or profitability test.

### XAUUSD and instrument caveats

- Candle and MarketTick are canonical Pydantic models; Timeframe declares 1m and 5m.
- XAUUSDDataLayer retains legacy `load_candles`; its async `get_historical_candles(start, end)` method uses the provider selected by XAUUSD_CONFIG (Massive by default). Pass MockDataProvider explicitly for offline development/tests.
- XAUUSD_CONFIG says paper mode but is metadata, not a paper broker.
- InstrumentConfig.xauusd() supplies explicit common 0.01 pip/tick and two-decimal defaults. Actual increment, quote convention, spread and volume semantics must follow the provider.
- No symbol-based precision inference occurs. Massive is configured as the XAUUSD development provider but is not selected automatically by the graph or CLI.
- OANDA, broker feeds, TradingView, Alpha Vantage, and other vendors remain separate integration categories unless a connected adapter and its capabilities are verified.

## Backtest and historical verification

tradingagents/backtest.py and the CLI backtest command run the AI graph over a ticker/date grid, settle outcomes later, and summarize directional hit rate and alpha versus benchmark. Cells are independent; an optional portfolio is constant per cell.

This is **decision-quality evaluation**, not a quant trade simulator. It does not model fills, spread, slippage, commissions, position sizing, cash evolution, broker order state, or execution P&L. Model outputs and text feeds are not archived for exact replay.

No dedicated quant historical runner fetches labeled XAUUSD and reports walk-forward strategy outcomes. Unit fixtures verify code rules, not profitability. Real verification needs a selected source, credentials or dataset, and explicit outcome/label rules.
## Timeframes and instrument configuration

The candle schema carries symbol, timestamp, OHLCV, and 1m/5m timeframe. Instrument precision is explicitly configured. TradeSetup and QuantSignal retain the originating timeframe; strategy evaluation remains caller-driven.

A future 5m-context / 1m-trigger flow must align availability timestamps; no multi-timeframe service currently prevents later 5m information leaking into an earlier 1m decision.

## Setup

### Requirements

- Python 3.10 or newer (pyproject declares >=3.10; CI covers 3.10-3.13).
- Git and network access for installation and whichever model/data providers you select.
- No Node.js or web frontend is present.

### Clone and install

~~~bash
git clone https://github.com/Code-withBanele/TradingAgents-0.5.0.git
cd TradingAgents-0.5.0
python -m venv .venv
~~~

Activate in PowerShell with .\.venv\Scripts\Activate.ps1 or on macOS/Linux with source .venv/bin/activate.

~~~bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
~~~

requirements.txt contains a single dot; pyproject.toml is authoritative. For optional Bedrock support use python -m pip install -e ".[bedrock]".

### Environment

Copy .env.example to .env, replace the `MASSIVE_API_KEY` placeholder with the key from your [Massive dashboard](https://massive.com/docs/rest/quickstart#authenticate-your-request), and set only credentials you need. `.env` is ignored by Git. Never commit real keys. LLM provider keys are resolved through tradingagents/llm_clients/api_key_env.py; the CLI may prompt. Massive credentials use the HTTPS Authorization header and are not added to request URLs.

| Variable(s) | Required? | Purpose |
| --- | --- | --- |
| OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY | One for selected hosted LLM | Native model authentication |
| XAI_API_KEY, DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, DASHSCOPE_CN_API_KEY, ZHIPU_API_KEY, ZHIPU_CN_API_KEY, MINIMAX_API_KEY, MINIMAX_CN_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY, MOONSHOT_API_KEY, GROQ_API_KEY, NVIDIA_API_KEY | One for selected compatible LLM | Hosted compatible provider credentials |
| AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME, OPENAI_API_VERSION | Azure only | Key, endpoint URL, deployment and API version |
| OPENAI_COMPATIBLE_API_KEY, TRADINGAGENTS_LLM_BACKEND_URL | Custom endpoint only | Optional key and endpoint URL |
| OLLAMA_BASE_URL | Optional | Ollama URL; defaults to local server |
| AWS_BEARER_TOKEN_BEDROCK, AWS_DEFAULT_REGION, AWS_PROFILE | Bedrock only | Bearer token or AWS credential chain/profile and region |
| FRED_API_KEY | Optional | FRED macro data |
| ALPHA_VANTAGE_API_KEY | Optional | Alpha Vantage data tools |
| MASSIVE_API_KEY | Optional | Massive Currencies historical XAUUSD spot aggregates (`C:XAUUSD`) |
| SEC_EDGAR_USER_AGENT | Recommended for SEC | Contact text, e.g. Research App user@example.org |
| TRADINGAGENTS_LLM_PROVIDER | Optional | Provider ID such as openai, anthropic, google, nvidia, ollama |
| TRADINGAGENTS_DEEP_THINK_LLM, TRADINGAGENTS_QUICK_THINK_LLM | Optional | Model IDs |
| TRADINGAGENTS_LLM_BACKEND_URL | Optional | Model endpoint override |
| TRADINGAGENTS_OUTPUT_LANGUAGE | Optional | Analyst/final response language |
| TRADINGAGENTS_MAX_DEBATE_ROUNDS, TRADINGAGENTS_MAX_RISK_ROUNDS | Optional | Integer discussion limits |
| TRADINGAGENTS_CHECKPOINT_ENABLED | Optional | Boolean graph checkpoint setting |
| TRADINGAGENTS_BENCHMARK_TICKER | Optional | Reflection/backtest benchmark |
| TRADINGAGENTS_TEMPERATURE, TRADINGAGENTS_LLM_MAX_RETRIES, TRADINGAGENTS_MAX_TOKENS | Optional | Numeric model controls |
| TRADINGAGENTS_GOOGLE_THINKING_LEVEL, TRADINGAGENTS_OPENAI_REASONING_EFFORT, TRADINGAGENTS_ANTHROPIC_EFFORT | Optional | Provider reasoning controls |
| TRADINGAGENTS_RESULTS_DIR, TRADINGAGENTS_CACHE_DIR, TRADINGAGENTS_MEMORY_LOG_PATH | Optional | Output/cache/memory paths |

China-region provider variables use separate accounts/endpoints. Ollama and Bedrock can use non-key authentication. Do not set every key to run tests.

## How to run

### Interactive research CLI

~~~bash
python -m cli.main
~~~

This runs the current terminal workflow using the AI research graph and existing vendor tools. It does not automatically run deterministic quant strategies. A selected hosted model generally requires credentials and network access. The installed console script is tradingagents; pyproject defines it as the same Typer app.

### Decision-grid backtest

~~~bash
python -m cli.main backtest NVDA,AAPL --start 2025-01-01 --end 2025-02-01 --every 7
~~~

This invokes AI decision-quality evaluation and may make many external model/data calls. It is not a quant-candle trade backtest.

### Quant engine

There is no standalone quant CLI. Call the functions from Python:

~~~python
from tradingagents.dataflows.market_structure import evaluate_strategy
from tradingagents.quant.models import InstrumentConfig

# candles must be chronological Candle objects supplied by the caller
setup = evaluate_strategy(
    candles,
    strategy_id="LIQUIDITY_SWEEP_FVG_REVERSAL",
    instrument=InstrumentConfig.xauusd(),
)
print(setup.status, setup.strategy_id, setup.entry, setup.stop, setup.target)
~~~

MockDataProvider is for deterministic development, not market evidence. A real provider needs an explicit adapter/key as shown above.

### Tests and CI

~~~bash
python -m pytest -q
python -m pytest tests/test_market_structure.py tests/test_quant_hardening.py tests/test_quant_signal.py -q
python -m pytest tests/test_market_data_provider.py tests/test_massive_adapter.py tests/test_dataset_metadata.py -q
~~~

Tests include provider contracts, synthetic provider determinism, Massive response/error/cache handling, market structure, signal validation, CLI/graph, and lookahead protections. Massive tests mock HTTP; they do not contact the vendor.

.github/workflows/ci.yml runs pytest on Python 3.10-3.13, a Python 3.12 clean-install import smoke check, and Ruff on Python 3.12. Reproduce locally:

~~~bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m pip install .
python -c "import tradingagents, cli.main; print('clean-install import OK')"
~~~

At audit time, the full test suite and import path passed. Scoped Ruff checks for the changed provider/quant files passed; repository-wide Ruff reports 12 findings in existing unrelated files. CI has no formatter, type-check, coverage threshold, or live provider test.
## Why these files still exist

| Path | Purpose |
| --- | --- |
| tradingagents/agents/ | Analyst, researcher, manager, trader and risk-discussion graph nodes |
| tradingagents/graph/ | LangGraph orchestration, state routing, checkpointing, reflection and signal/rating boundary |
| tradingagents/llm_clients/ | Model factory, provider abstraction, API keys, capabilities, validation and reliability |
| tradingagents/dataflows/ | Vendor tools, point-in-time filtering, provider contracts, candle models, XAUUSD compatibility and detector implementations |
| tradingagents/quant/models.py | Shared typed quant structures; detector implementations remain in the compatibility dataflows module |
| tradingagents/graph/signal_processing.py | Validated QuantSignal schema and legacy rating parser |
| tradingagents/backtest.py | Ticker/date-grid decision evaluation and later outcome summary, not a trade simulator |
| tradingagents/default_config.py | Defaults and typed TRADINGAGENTS_* overrides |
| tradingagents/xauusd_config.py | XAUUSD paper-mode metadata, not a paper broker |
| cli/ and main.py | Interactive CLI, backtest command, and legacy direct graph entry point |
| market_structure_spec.md | Deterministic market-structure behavior specification |
| decision_gate_spec.md | Decision-gate reliability contract; spec only until integrated |

## Security and data integrity

- .env is ignored by Git; .env.example contains a placeholder only. Store credentials locally, never in source control or this README.
- Massive credentials are sent in the HTTPS Authorization header; sanitized errors omit credentials and request URLs.
- No credential vault or broker credential-management UI exists.
- Volume semantics vary by source. Synthetic, tick, futures, and exchange volume are not interchangeable.
- Historical labels confirmed by later candles must not be presented as known at the pivot time.
- Timestamps, provider symbol, session, licensing, and data quality must be verified for each dataset.

## Current roadmap

These phase labels are development direction, not claims that phases are complete.

| Phase | Focus | Current status |
| --- | --- | --- |
| 0 — Inspection | Repository audit | Ongoing |
| 1 — Foundation / AI reliability | Existing agent and LLM system | Substantially present |
| 2 — Data layer / state reconciliation | Providers and normalized data | Partial; XAUUSD wiring incomplete |
| 3 — Quant Engine | Deterministic primitives and candidates | Partial, heuristic, unit-tested but not market-validated |
| 3C — Quant hardening / historical verification / provider UI | Definitions, real data checks, control UI | In progress; real dataset and UI pending |
| 4 — Analyst & research | Connect quant context to existing research | Quant integration unfinished |
| 5 — JEV / risk / decision gate | Context synthesis and deterministic controls | Planned; JEV/gate/risk engine absent |
| 6 — Execution / backtesting / observability | Trade simulator and broker lifecycle | Planned; current backtest scores AI decisions |
| 7 — Control UI / autonomous research | Strategy Checker and research loop | Planned; no web UI or quant loop |

## Important limitations

- Massive Currencies XAUUSD history is implemented; the live smoke request in this environment stopped at TLS verification (`SSLError`), before authentication or symbol access could be verified. Aggregates are quote-derived and can contain gaps.
- No tick, bid/ask, spread, or live subscription feed exists in the XAUUSD quant adapter.
- Yahoo's XAUUSD symbol alias is GC=F futures, not a broker spot/CFD quote.
- Quant strategies are heuristic; no labeled chart corpus, walk-forward outcome report, or profitability evidence exists.
- The QuantSignal bridge preserves timeframe and strategy version but remains disconnected from graph routing.
- Quant output is not wired into the AI graph, JEV, gate, deterministic risk controls, execution, or broker.
- TradingView and broker providers are stubs. The CLI is not a quant Strategy Checker UI.
- backtest.py scores AI decisions against later market outcomes; it does not simulate trades.

For current contracts, see market_structure_spec.md, pyproject.toml, and component tests.
