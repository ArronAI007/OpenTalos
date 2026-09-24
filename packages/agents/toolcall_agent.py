from core.agent import Agent, AssemblyConfig, OutputTrimmer, RuntimeSettings
from core.agent_loop import run_tool_turn, seed_messages
from core.protocol import ChatMessage
from core.model import ModelClient
from tool.registry import ToolRegistry

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


class ToolCallingAgent(Agent):
    """单轮问答 Agent：有 tool_registry 就走 function-calling 循环，没有就直接问答。"""

    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_iterations: int = 3,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
        trace_dir: str | None = None,
        compaction_token_limit: int | None = None,
        output_trimmer: OutputTrimmer | None = None,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_SYSTEM_PROMPT,
            settings,
            context_config,
            min_retain_turns,
            trace_dir,
            compaction_token_limit,
            output_trimmer,
        )
        self.tool_registry = tool_registry
        self.max_tool_iterations = max_tool_iterations

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        messages = seed_messages(self.system_prompt, self.history_snapshot(), input_text)
        answer = await run_tool_turn(
            self.model_client,
            messages,
            self.tool_registry,
            self.max_tool_iterations,
            self.recorder,
            trimmer=self.output_trimmer,
            on_tool_result=self.record_tool_result,
            **kwargs,
        )

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=answer, role="assistant"))
        await self.maybe_compress_history()
        return answer
