import time
from pathlib import Path

from apps.desktop.single_instance import (
    ActivationListener,
    instance_paths,
    send_activation,
)


def test_instance_paths_are_stable_and_path_specific(tmp_path: Path) -> None:
    first = instance_paths(tmp_path)
    second = instance_paths(tmp_path)
    other = instance_paths(tmp_path / "other")

    assert first == second
    assert first != other
    assert first[0].name == "desktop-instance.lock"
    assert first[1].name == "desktop-activate"


def test_activation_listener_receives_existing_instance_message(tmp_path: Path) -> None:
    received: list[str] = []
    listener = ActivationListener(tmp_path)
    assert listener.start(received.append)

    try:
        assert send_activation(tmp_path, "activate")
        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
        assert received == ["activate"]
    finally:
        listener.stop()


def test_second_listener_cannot_claim_the_same_lock(tmp_path: Path) -> None:
    first = ActivationListener(tmp_path)
    second = ActivationListener(tmp_path)
    assert first.start(lambda _message: None)
    try:
        assert not second.start(lambda _message: None)
    finally:
        second.stop()
        first.stop()
