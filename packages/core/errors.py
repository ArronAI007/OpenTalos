class CoreError(Exception):
    pass


class SettingsError(CoreError):
    pass


class ModelError(CoreError):
    pass


class EmptyModelResponse(ModelError):
    """模型既没返回可见文本，也没请求工具——运行"成功"却没有任何答案时显式报错。"""


class AgentRuntimeError(CoreError):
    pass


class OutputLimitError(AgentRuntimeError):
    """模型撞上 max_tokens/上下文上限被截断，返回的文本不是完整答案（finish_reason 为 length 系）。"""


class OperationCancelled(AgentRuntimeError):
    pass
