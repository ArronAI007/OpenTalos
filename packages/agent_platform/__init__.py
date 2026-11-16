"""Cross-agent discovery, configuration, bindings, and resource management."""

from .catalog import AgentDefinition, load_catalog
from .config import AgentConfigError, AgentConfigManager
from .discovery import AgentDiscovery
from .service import AgentPlatformService
from .store import AgentPlatformStore

__all__ = [
    "AgentConfigError",
    "AgentConfigManager",
    "AgentDefinition",
    "AgentDiscovery",
    "AgentPlatformService",
    "AgentPlatformStore",
    "load_catalog",
]
