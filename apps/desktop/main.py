"""Entry point for the OpenTalos pywebview desktop application."""

from __future__ import annotations

import argparse
import importlib
import sys
import threading
from pathlib import Path

from apps.desktop.config import DesktopConfig, DesktopConfigError
from apps.desktop.controller import DesktopController
from apps.desktop.single_instance import ActivationListener, send_activation
from apps.desktop.supervisor import ServiceSupervisor
from apps.desktop.tray import DesktopTray
from apps.runtime_paths import resource_root
from release_platform.installer import (
    InstallError,
    apply_install_request,
    install_request_path,
)
from release_platform.migrations import DowngradeBlockedError, ReleaseMetadataStore
from release_platform.uninstaller import SafeUninstaller
from release_platform.version import CURRENT_DATA_SCHEMA_VERSION, app_version


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenTalos desktop")
    parser.add_argument("--no-services", action="store_true", help="use services already running")
    parser.add_argument("--no-tray", action="store_true", help="do not create a tray icon")
    parser.add_argument("--tray-only", action="store_true", help="start with the window hidden")
    parser.add_argument("--smoke-test", action="store_true", help="exit after creating the window")
    parser.add_argument("--debug", action="store_true", help="enable pywebview developer tools")
    parser.add_argument("--url", help="override the desktop web URL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args[:1] == ["--internal-service"]:
        return _run_internal_service(raw_args[1:])
    if "--version" in raw_args:
        print(app_version())
        return 0
    if "--uninstall" in raw_args:
        return _run_uninstaller(raw_args)
    import webview

    args = parse_args(argv)
    try:
        config = DesktopConfig.from_env()
    except DesktopConfigError as error:
        print(f"OpenTalos configuration error: {error}", file=sys.stderr)
        return 1

    try:
        ReleaseMetadataStore(config.data_dir).prepare(
            app_version=app_version(),
            schema_version=CURRENT_DATA_SCHEMA_VERSION,
            platform_name=sys.platform,
        )
    except (DowngradeBlockedError, RuntimeError) as error:
        print(f"OpenTalos data migration error: {error}", file=sys.stderr)
        return 1

    if send_activation(config.root, data_dir=config.data_dir):
        return 0

    controller_ref: list[DesktopController] = []
    pending_activations: list[str] = []

    def activate(message: str) -> None:
        if controller_ref:
            controller_ref[0].show_main()
        else:
            pending_activations.append(message)

    listener = ActivationListener(config.root, data_dir=config.data_dir)
    if not listener.start(activate):
        return 0

    supervisor = None if args.no_services else ServiceSupervisor(config)
    if supervisor is not None:
        try:
            supervisor.start()
        except Exception as error:
            print(f"OpenTalos startup error: {error}", file=sys.stderr)
            supervisor.stop()
            listener.stop()
            return 1

    controller: DesktopController | None = None
    try:
        target_url = args.url or config.web_url
        window = webview.create_window(
            "OpenTalos",
            target_url,
            width=1280,
            height=840,
            min_size=(900, 600),
            hidden=args.tray_only,
            confirm_close=False,
            background_color="#f4f4f6",
        )
        controller = DesktopController(config, supervisor=supervisor, tray=None)
        controller_ref.append(controller)
        controller.attach_window(window)
        controller.start_update_watcher()
        window.events.closing += controller.on_closing

        if not args.no_tray:
            tray = DesktopTray(config, controller)
            try:
                tray.start()
            except Exception as error:
                print(f"OpenTalos tray unavailable: {error}", file=sys.stderr)
            else:
                controller.tray = tray
                controller.refresh_status()

        if args.tray_only and controller.tray is None:
            controller.show_main()
        elif not args.tray_only and not args.smoke_test:
            controller.show_main()
        if pending_activations:
            controller.show_main()

        if args.smoke_test:
            threading.Timer(1.0, window.destroy).start()
        webview.start(debug=args.debug, private_mode=False)
    finally:
        listener.stop()
        if controller is not None:
            controller.shutdown()
        elif supervisor is not None:
            supervisor.stop()
    if install_request_path(config.data_dir).is_file():
        try:
            apply_install_request(
                data_dir=config.data_dir,
                app_dir=_installed_app_dir(),
            )
        except InstallError as error:
            print(f"OpenTalos update error: {error}", file=sys.stderr)
            return 1
    return 0


def _run_internal_service(args: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("service", choices=("api", "gateway"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parsed = parser.parse_args(args)
    import uvicorn

    service_dir = resource_root() / "apps" / parsed.service
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))
    module = importlib.import_module(
        "apps.api.main" if parsed.service == "api" else "apps.gateway.main"
    )
    uvicorn.run(
        module.app,
        host=parsed.host,
        port=parsed.port,
        log_level="info",
    )
    return 0


def _run_uninstaller(args: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Uninstall OpenTalos")
    parser.add_argument("--uninstall", action="store_true", required=True)
    data_group = parser.add_mutually_exclusive_group()
    data_group.add_argument("--keep-data", action="store_true")
    data_group.add_argument("--purge", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parsed = parser.parse_args(args)
    config = DesktopConfig.from_env()
    keep_data = not parsed.purge
    if not parsed.yes:
        action = "keep user data" if keep_data else "delete all OpenTalos user data"
        answer = input(f"Uninstall OpenTalos and {action}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    try:
        result = SafeUninstaller(
            data_dir=config.data_dir,
            app_dir=_installed_app_dir(),
            resource_root=config.resource_root,
        ).run(keep_data=keep_data)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"OpenTalos uninstall error: {error}", file=sys.stderr)
        return 1
    print(
        f"OpenTalos agent state restored; user data "
        f"{'removed' if result['data_removed'] else 'kept at ' + result['data_dir']}"
    )
    return 0


def _installed_app_dir() -> Path:
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return executable.parent


if __name__ == "__main__":
    raise SystemExit(main())
