"""Release metadata, migration, update, and safe-uninstall primitives."""

from .installer import InstallError, apply_install_request, install_request_path
from .migrations import DowngradeBlockedError, ReleaseMetadataStore
from .uninstaller import SafeUninstaller
from .updater import UpdateError, UpdateManager

__all__ = [
    "InstallError",
    "DowngradeBlockedError",
    "ReleaseMetadataStore",
    "SafeUninstaller",
    "UpdateError",
    "UpdateManager",
    "apply_install_request",
    "install_request_path",
]
