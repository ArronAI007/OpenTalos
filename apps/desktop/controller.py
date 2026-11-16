"""Desktop window, tray, and service lifecycle coordination."""

from __future__ import annotations

from typing import Protocol

from apps.desktop.config import DesktopConfig


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

    def attach_window(self, window: WindowLike) -> None:
        self.window = window
        self.refresh_status()

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
        if self.tray is not None:
            self.tray.stop()
        if self.window is not None:
            self.window.destroy()
        if self.supervisor is not None:
            self.supervisor.stop()

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.stop()
        if self.supervisor is not None:
            self.supervisor.stop()
