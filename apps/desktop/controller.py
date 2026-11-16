"""Desktop window, tray, and service lifecycle coordination."""

from __future__ import annotations

import threading
from typing import Protocol

from apps.desktop.config import DesktopConfig
from release_platform.installer import install_request_path


class WindowLike(Protocol):
    def show(self) -> None: ...

    def hide(self) -> None: ...

    def destroy(self) -> None: ...


class TrayLike(Protocol):
    def update_status(self, status: dict[str, bool]) -> None: ...

    def stop(self) -> None: ...


class SupervisorLike(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def status(self) -> dict[str, bool]: ...


class DesktopController:
    """Keep the UI responsive while coordinating non-visual desktop state."""

    def __init__(
        self,
        config: DesktopConfig,
        *,
        supervisor: SupervisorLike | None,
        tray: TrayLike | None,
    ) -> None:
        self.config = config
        self.supervisor = supervisor
        self.tray = tray
        self.window: WindowLike | None = None
        self._quitting = False
        self._update_watcher_stop = threading.Event()
        self._update_watcher: threading.Thread | None = None

    def attach_window(self, window: WindowLike) -> None:
        self.window = window
        self.refresh_status()

    def start_update_watcher(self, interval: float = 1.0) -> None:
        if self._update_watcher is not None:
            return
        marker = install_request_path(self.config.data_dir)

        def watch() -> None:
            while not self._update_watcher_stop.wait(interval):
                if marker.is_file() and not self._quitting:
                    self.request_quit()
                    return

        self._update_watcher = threading.Thread(
            target=watch,
            name="opentalos-update-watcher",
            daemon=True,
        )
        self._update_watcher.start()

    def show_main(self) -> None:
        if not self._quitting and self.window is not None:
            self.window.show()

    def on_closing(self) -> bool:
        if self._quitting or self.tray is None:
            return True
        self.window.hide()
        return False

    def refresh_status(self) -> None:
        if self.tray is None:
            return
        status = self.supervisor.status() if self.supervisor is not None else {
            "api": False,
            "gateway": False,
            "web": False,
        }
        self.tray.update_status(status)

    def restart_services(self) -> None:
        if self.supervisor is None:
            return
        self.supervisor.stop()
        self.supervisor.start()
        self.refresh_status()

    def request_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._update_watcher_stop.set()
        if self.tray is not None:
            self.tray.stop()
        if self.window is not None:
            self.window.destroy()
        if self.supervisor is not None:
            self.supervisor.stop()

    def shutdown(self) -> None:
        self._update_watcher_stop.set()
        if self.tray is not None:
            self.tray.stop()
        if self.supervisor is not None:
            self.supervisor.stop()
