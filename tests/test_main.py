from __future__ import annotations

from ctld_launcher.core.autostart import MINIMIZED_FLAG
from ctld_launcher.main import should_show_on_startup


def test_should_show_on_startup_true_for_manual_launch() -> None:
    assert should_show_on_startup(["ctld-launcher"]) is True


def test_should_show_on_startup_false_when_launched_via_autostart() -> None:
    assert should_show_on_startup(["ctld-launcher", MINIMIZED_FLAG]) is False
