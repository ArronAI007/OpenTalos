class OpenTalosError(Exception):
    pass


class ConfigError(OpenTalosError):
    pass


class LLMError(OpenTalosError):
    pass


class AgentError(OpenTalosError):
    pass
