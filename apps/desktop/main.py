"""Entry point for the OpenTalos pywebview desktop application."""

from __future__ import annotations

import argparse
import sys
import threading

import webview

from apps.desktop.config import DesktopConfig, DesktopConfigError
from apps.desktop.controller import DesktopController
from apps.desktop.single_instance import ActivationListener, send_activation
from apps.desktop.supervisor import ServiceSupervisor
from apps.desktop.tray import DesktopTray


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
    args = parse_args(argv)
    try:
        config = DesktopConfig.from_env()
    except DesktopConfigError as error:
        print(f"OpenTalos configuration error: {error}", file=sys.stderr)
        return 1

    if send_activation(config.root):
        return 0

    controller_ref: list[DesktopController] = []
    pending_activations: list[str] = []

    def activate(message: str) -> None:
        if controller_ref:
            controller_ref[0].show_main()
        else:
            pending_activations.append(message)

    listener = ActivationListener(config.root)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
