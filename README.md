# OpenTalos

An experimental agent framework in Python: a small, dependency-clean core runtime plus
building blocks for tool calling, context engineering, sandboxed script execution, four
reusable agent reasoning patterns, and execution tracing — with a Gradio chat console on top
to actually use it.

Managed as a single `uv` project (not a workspace); `packages/*` are added to `sys.path`
rather than installed, and imported as top-level modules (`from core.agent import Agent`,
`from tool.registry import ToolRegistry`, etc.).

## Architecture

`packages/tool`, `packages/context`, `packages/sandbox`, and `packages/observability` are
leaf packages — none of them import each other or anything else in this repo:

| Package | Responsibility |
|---|---|
| `packages/tool` | `Tool`/`ToolParameter` abstract interface, `ToolOutcome`, `ToolRegistry` (registration, function-schema export, per-tool `CircuitBreaker`). |
| `packages/context` | Context engineering: `TokenBudget` (cached token estimation), `TranscriptStore` (turn-based history with summary compression), `ContextAssembler` (Gather-Select-Structure-Compress pipeline, with MMR-based diverse selection), `OutputTrimmer` (head/tail truncation of large tool output). |
| `packages/sandbox` | Docker-based sandboxed execution of a single script (`run_sandboxed_script`), with path-traversal-safe script resolution. |
| `packages/observability` | `RunRecorder`: records a run's events as streaming JSONL plus an incrementally-rendered HTML report, with secret redaction and summary stats. |

`packages/core` builds on the leaves above — its `Agent` base class composes a
`TranscriptStore`/`ContextAssembler` pair unconditionally, and a `RunRecorder` when
constructed with `trace_dir`:

| Package | Responsibility |
|---|---|
| `packages/core` | `Agent` (abstract base: history, context assembly, tracing, phase callbacks), `ModelClient` (async, provider-agnostic: Anthropic / OpenAI-compatible / mock), `ChatMessage`, `Completion`/`ToolCompletion` types. |
| `packages/skill` | FastAPI service exposing the `skills/` directory over HTTP (`GET /skills`, `GET /skills/{name}`, `POST /skills/{name}/run-script`), running scripts through `packages/sandbox`. |

`packages/agents` sits on top, depending only on `core` and `tool`:

| Package | Responsibility |
|---|---|
| `packages/agents` | Four `core.Agent` implementations sharing one tool-calling loop (`dialogue.run_tool_turn`): `ToolCallingAgent` (single-turn, optional tool calling), `ReActAgent` (step-budgeted reason+act loop with an explicit `finish` tool), `ReflectionAgent` (draft → critique → revise), `PlanExecuteAgent` (plan into steps via a forced function call, then execute each with accumulating context). Plus `build_agent`/`default_subagent_builder` to construct one by type name. |

And `apps/` is what you actually run:

| App | Responsibility |
|---|---|
| `apps/chat_console` | Gradio UI: chat with any of the four agent types (with a demo calculator tool for tool-calling patterns), and a live Trace tab showing that agent's `RunRecorder` events/stats as the conversation happens. |

## Repository Layout

```
opentalos/
├── packages/         # core, tool, context, sandbox, observability, skill, agents
├── apps/             # chat_console (Gradio)
├── skills/           # skill content served by packages/skill (SKILL.md + scripts)
├── tests/            # pytest, mirrors packages/ and apps/
└── scripts/          # start.sh
```

## Quick Start

Requires Python ≥3.12 and [`uv`](https://docs.astral.sh/uv/). Docker is only needed for
`packages/sandbox`/`packages/skill` (and their tests).

```bash
uv sync
cp .env.example .env   # fill in MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME, or leave
                        # MODEL_PROVIDER=mock to run without a real model

uv run pytest tests/

./scripts/start.sh chat    # Gradio chat console at http://127.0.0.1:7860
./scripts/start.sh skill   # skill FastAPI service (needs Docker running)
```

`scripts/start.sh --help` for details. Nothing needs `--env-file` — `packages/core/model_client.py`
loads `.env` itself (see next section) the moment it's imported.

## Key Environment Variables

Read by `packages/core/model_client.py` (`ModelClient()` with no constructor args), which
loads `.env` from the repo root automatically; values already in the process environment take
precedence over it.

| Variable | Default | Notes |
|---|---|---|
| `MODEL_PROVIDER` | *(required)* | `anthropic` \| `openai-compatible` \| `mock`. `mock` needs no key/network access. |
| `MODEL_API_KEY` | *(required except `mock`)* | |
| `MODEL_NAME` | *(required except `mock`)* | |
| `MODEL_BASE_URL` | provider default | Required for `openai-compatible` against a non-OpenAI endpoint (DeepSeek, Kimi/Moonshot, etc.). |
| `MODEL_TIMEOUT` | `60` | Request timeout, seconds. |
| `MODEL_TEMPERATURE` | *(not sent)* | Left unset, the request carries no `temperature` and the provider's own default applies — required for models that only accept a fixed value (o-series, kimi-k3). Set a number to pin it. |

## Testing

```bash
uv run pytest tests/
```

Every `packages/*` and `apps/*` directory has a matching `tests/` counterpart. Docker-backed
sandbox tests hit a real container, not a mock — same principle applies wherever it's
practical (`ModelClient` tests use a scripted fake backend since real LLM calls aren't
reproducible, but nothing here mocks its own package's collaborators).
