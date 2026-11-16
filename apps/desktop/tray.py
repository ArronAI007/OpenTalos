"""System tray integration for the OpenTalos desktop application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pystray
from PIL import Image, ImageDraw

from apps.desktop.config import DesktopConfig
from apps.desktop.controller import DesktopController


class DesktopTray:
    """Small tray controller with dynamic API and web health labels."""

    def __init__(self, config: DesktopConfig, controller: DesktopController) -> None:
        self.config = config
        self.controller = controller
        self._status = {"api": False, "gateway": False, "web": False}
        self._icon = pystray.Icon(
            "opentalos",
            _tray_image(config.resource_root),
            "OpenTalos",
            menu=self._menu(),
        )

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        self._icon.stop()

    def update_status(self, status: dict[str, bool]) -> None:
        self._status = status
        api = "ready" if status.get("api") else "offline"
        gateway = "ready" if status.get("gateway") else "offline"
        web = "ready" if status.get("web") else "offline"
        self._icon.title = f"OpenTalos\nAPI: {api}\nGateway: {gateway}\nWeb: {web}"
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open OpenTalos", self._open, default=True),
            pystray.MenuItem(self._api_label, None, enabled=False),
            pystray.MenuItem(self._gateway_label, None, enabled=False),
            pystray.MenuItem(self._web_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart services", self._restart),
            pystray.MenuItem("Quit", self._quit),
        )

    def _open(self, _icon: Any, _item: Any) -> None:
        self.controller.show_main()

    def _restart(self, _icon: Any, _item: Any) -> None:
        self.controller.restart_services()

    def _quit(self, _icon: Any, _item: Any) -> None:
        self.controller.request_quit()

    def _api_label(self, _item: Any) -> str:
        return f"API: {'ready' if self._status.get('api') else 'offline'}"

    def _web_label(self, _item: Any) -> str:
        return f"Web: {'ready' if self._status.get('web') else 'offline'}"

    def _gateway_label(self, _item: Any) -> str:
        return f"Gateway: {'ready' if self._status.get('gateway') else 'offline'}"


def _tray_image(root: Path) -> Image.Image:
    icon_path = root / "assets" / "icon" / "opentalos.png"
    try:
        return Image.open(icon_path).convert("RGBA")
    except Exception:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((7, 7, 57, 57), fill=(32, 32, 36, 255))
        draw.text((25, 18), "O", fill=(255, 255, 255, 255))
        return image
