"""File-lock single-instance coordination for the desktop application."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path


def instance_paths(root: Path) -> tuple[Path, Path]:
    """Return the stable lock and activation paths for one checkout."""

    data = root.resolve() / ".data"
    return data / "desktop-instance.lock", data / "desktop-activate"


def send_activation(root: Path, message: str = "activate") -> bool:
    """Notify a running instance, returning false when no lock holder exists."""

    lock_path, activation_path = instance_paths(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if _lock(handle):
            _unlock(handle)
            return False
    activation_path.write_text(message, encoding="utf-8")
    return True


class ActivationListener:
    """Own the single-instance lock and watch for activation requests."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock_path, self.activation_path = instance_paths(root)
        self._lock_file = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def start(self, callback: Callable[[str], None]) -> bool:
        if self._lock_file is not None:
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        if not _lock(handle):
            handle.close()
            return False

        self._lock_file = handle
        self.activation_path.unlink(missing_ok=True)
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._serve,
            args=(callback,),
            name="opentalos-activation",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        if self._lock_file is not None:
            _unlock(self._lock_file)
            self._lock_file.close()
            self._lock_file = None
        self.activation_path.unlink(missing_ok=True)

    def _serve(self, callback: Callable[[str], None]) -> None:
        while not self._stopped.is_set():
            try:
                message = self.activation_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._stopped.wait(0.1)
                continue
            except OSError:
                self._stopped.wait(0.1)
                continue
            self.activation_path.unlink(missing_ok=True)
            callback(message or "activate")


def _lock(handle) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
