# OpenTalos

An experimental agent framework in Python: a small, dependency-clean core runtime plus
building blocks for tool calling, context engineering, script-execution skills, four
reusable agent reasoning patterns, and execution tracing — with a Gradio chat console on top
to actually use it.

Managed as a single `uv` project (not a workspace); `packages/*` are added to `sys.path`
rather than installed, and imported as top-level modules (`from core.agent import Agent`,
`from tool.registry import ToolRegistry`, etc.).

## Architecture

`packages/tool`, `packages/context`, and `packages/observability` are
leaf packages — none of them import each other or anything else in this repo:

| Package | Responsibility |
|---|---|
| `packages/tool` | `Tool`/`ToolParameter` abstract interface, `ToolOutcome`, `ToolRegistry` (registration, function-schema export, per-tool `CircuitBreaker`). |
| `packages/context` | Context engineering: `TokenBudget` (cached token estimation), `TranscriptStore` (turn-based history with summary compression), `ContextAssembler` (Gather-Select-Structure-Compress pipeline, with MMR-based diverse selection), `OutputTrimmer` (head/tail truncation of large tool output). |
| `packages/observability` | `RunRecorder`: records a run's events as streaming JSONL plus an incrementally-rendered HTML report, with secret redaction and summary stats. |

`packages/core` and `packages/skill` build on the leaves above — `core`'s `Agent` base class
composes a `TranscriptStore`/`ContextAssembler` pair unconditionally, and a `RunRecorder` when
constructed with `trace_dir`; `skill`'s agent-facing tools implement the `tool.Tool` interface:

| Package | Responsibility |
|---|---|
| `packages/core` | `Agent` (abstract base: history, context assembly, tracing, phase callbacks), `ModelClient` (async, provider-agnostic: Anthropic / OpenAI-compatible / mock), `ChatMessage`, `Completion`/`ToolCompletion` types. |
| `packages/skill` | FastAPI service exposing the `skills/` directory over HTTP (`GET /skills`, `GET /skills/{name}`, `POST /skills/{name}/run-script`), running scripts as local subprocesses with path-traversal-safe script resolution (a proper sandbox will be reintroduced separately). Plus the agent-facing side: `SkillClient` (async HTTP client), `read_skill`/`run_skill_script` tools for any `ToolRegistry`, and `format_skills_for_system_prompt` (pi-style `<available_skills>` prompt section). |

`packages/agents` sits on top, depending only on `core` and `tool`:

| Package | Responsibility |
|---|---|
| `packages/agents` | Four `core.Agent` implementations sharing one tool-calling loop (`dialogue.run_tool_turn`): `ToolCallingAgent` (single-turn, optional tool calling), `ReActAgent` (step-budgeted reason+act loop with an explicit `finish` tool), `ReflectionAgent` (draft → critique → revise), `PlanExecuteAgent` (plan into steps via a forced function call, then execute each with accumulating context). Plus `build_agent`/`default_subagent_builder` to construct one by type name. |

And `apps/` is what you actually run:

| App | Responsibility |
|---|---|
| `apps/chat_console` | Gradio UI: chat with any of the four agent types (with a demo calculator tool for tool-calling patterns, and an opt-in skills toggle that wires the skill service's `read_skill`/`run_skill_script` tools plus an `<available_skills>` prompt section), and a live Trace tab showing that agent's `RunRecorder` events/stats as the conversation happens. |

## Repository Layout

```
opentalos/
├── packages/         # core, tool, context, observability, skill, agents
├── apps/             # chat_console (Gradio)
├── skills/           # skill content served by packages/skill (SKILL.md + scripts)
├── tests/            # pytest, mirrors packages/ and apps/
└── scripts/          # start.sh
```

## Quick Start

Requires Python ≥3.12 and [`uv`](https://docs.astral.sh/uv/). Node.js is only needed to run
JS skills (`skills/text-to-table`).

```bash
uv sync
cp .env.example .env   # fill in MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME, or leave
                        # MODEL_PROVIDER=mock to run without a real model

uv run pytest tests/

./scripts/start.sh chat    # Gradio chat console at http://127.0.0.1:7860
./scripts/start.sh skill   # skill FastAPI service
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

Read by `apps/chat_console/app.py` directly:

| Variable | Default | Notes |
|---|---|---|
| `SKILL_SERVICE_URL` | `http://localhost:8000` | Where the chat console reaches the skill service when the skills toggle is on. |

## Testing

```bash
uv run pytest tests/
```

Every `packages/*` and `apps/*` directory has a matching `tests/` counterpart. Skill
execution tests run real subprocesses, not mocks — same principle applies wherever it's
practical (`ModelClient` tests use a scripted fake backend since real LLM calls aren't
reproducible, but nothing here mocks its own package's collaborators).
