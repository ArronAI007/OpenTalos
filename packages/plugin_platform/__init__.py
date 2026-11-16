"""Integrity-checked local plugin discovery, providers, middleware, and UI metadata."""

from .manifest import PluginManifest, PluginValidationError, validate_manifest
from .middleware import PluginMiddleware
from .provider import PluginCommandRunner, PluginProviderUpstream
from .store import PluginIntegrityError, PluginStore

__all__ = [
    "PluginCommandRunner",
    "PluginIntegrityError",
    "PluginManifest",
    "PluginMiddleware",
    "PluginProviderUpstream",
    "PluginStore",
    "PluginValidationError",
    "validate_manifest",
]
