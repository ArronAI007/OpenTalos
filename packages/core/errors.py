class CoreError(Exception):
    pass


class SettingsError(CoreError):
    pass


class ModelError(CoreError):
    pass


class AgentRuntimeError(CoreError):
    pass
