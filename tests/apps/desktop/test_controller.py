from pathlib import Path

from apps.desktop.config import DesktopConfig
from apps.desktop.controller import DesktopController


class FakeWindow:
    def __init__(self) -> None:
        self.shown = 0
        self.hidden = 0
        self.destroyed = 0

    def show(self) -> None:
        self.shown += 1

    def hide(self) -> None:
        self.hidden += 1

    def destroy(self) -> None:
        self.destroyed += 1


class FakeTray:
    def __init__(self) -> None:
        self.statuses: list[dict[str, bool]] = []
        self.stopped = False

    def update_status(self, status: dict[str, bool]) -> None:
        self.statuses.append(status)

    def stop(self) -> None:
        self.stopped = True


class FakeSupervisor:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def status(self) -> dict[str, bool]:
        return {"api": True, "web": False}


def _config(tmp_path: Path) -> DesktopConfig:
    return DesktopConfig.from_env(
        root=tmp_path,
        env={"OPENTALOS_DESKTOP_WEB_MODE": "dev"},
    )


def test_controller_hides_window_when_tray_is_active(tmp_path: Path) -> None:
    supervisor = FakeSupervisor()
    controller = DesktopController(
        _config(tmp_path),
        supervisor=supervisor,
        tray=FakeTray(),
    )
    window = FakeWindow()
    controller.attach_window(window)

    assert controller.on_closing() is False
    assert window.hidden == 1
    assert window.destroyed == 0


def test_controller_restarts_services_and_refreshes_tray(tmp_path: Path) -> None:
    supervisor = FakeSupervisor()
    tray = FakeTray()
    controller = DesktopController(
        _config(tmp_path),
        supervisor=supervisor,
        tray=tray,
    )
    controller.attach_window(FakeWindow())

    controller.restart_services()

    assert supervisor.stop_calls == 1
    assert supervisor.start_calls == 1
    assert tray.statuses[-1] == {"api": True, "web": False}


def test_controller_quits_window_tray_and_services(tmp_path: Path) -> None:
    supervisor = FakeSupervisor()
    tray = FakeTray()
    controller = DesktopController(
        _config(tmp_path),
        supervisor=supervisor,
        tray=tray,
    )
    window = FakeWindow()
    controller.attach_window(window)

    controller.request_quit()

    assert window.destroyed == 1
    assert tray.stopped
    assert supervisor.stop_calls == 1
