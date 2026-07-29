from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "ctld-launcher"

DEFAULT_RIG_PORT = 4532
DEFAULT_ROTATOR_PORT = 4533


class ProfileKind(StrEnum):
    RIG = "rig"
    ROTATOR = "rotator"


@dataclass
class Profile:
    """One rigctld/rotctld configuration (model, serial port, listen address, etc.)."""

    name: str
    kind: ProfileKind
    model_id: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    port: str = ""
    serial_speed: int | None = None
    data_bits: int | None = None
    stop_bits: int | None = None
    serial_parity: str | None = None
    serial_handshake: str | None = None
    civ_address: str | None = None
    listen_address: str = "127.0.0.1"
    listen_port: int = DEFAULT_RIG_PORT
    debug_level: int = 0
    log_file: str | None = None
    extra_args: list[str] = field(default_factory=list)
    auto_start: bool = False
    usb_hotplug: bool = False
    usb_vid: int | None = None
    usb_pid: int | None = None
    usb_serial_number: str | None = None

    @classmethod
    def new_rig(
        cls,
        name: str,
        model_id: int,
        port: str = "",
        serial_speed: int | None = None,
        civ_address: str | None = None,
        listen_address: str = "127.0.0.1",
        listen_port: int = DEFAULT_RIG_PORT,
        debug_level: int = 0,
        log_file: str | None = None,
        extra_args: list[str] | None = None,
        auto_start: bool = False,
    ) -> Profile:
        return cls(
            name=name,
            kind=ProfileKind.RIG,
            model_id=model_id,
            port=port,
            serial_speed=serial_speed,
            civ_address=civ_address,
            listen_address=listen_address,
            listen_port=listen_port,
            debug_level=debug_level,
            log_file=log_file,
            extra_args=extra_args or [],
            auto_start=auto_start,
        )

    @classmethod
    def new_rotator(
        cls,
        name: str,
        model_id: int,
        port: str = "",
        serial_speed: int | None = None,
        listen_address: str = "127.0.0.1",
        listen_port: int = DEFAULT_ROTATOR_PORT,
        debug_level: int = 0,
        log_file: str | None = None,
        extra_args: list[str] | None = None,
        auto_start: bool = False,
    ) -> Profile:
        return cls(
            name=name,
            kind=ProfileKind.ROTATOR,
            model_id=model_id,
            port=port,
            serial_speed=serial_speed,
            listen_address=listen_address,
            listen_port=listen_port,
            debug_level=debug_level,
            log_file=log_file,
            extra_args=extra_args or [],
            auto_start=auto_start,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        kwargs = dict(data)
        kwargs["kind"] = ProfileKind(kwargs["kind"])
        return cls(**kwargs)


def default_profiles_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "profiles.json"


class ProfileStore:
    """Loads/saves the list of rig/rotator profiles as JSON in the user config dir."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_profiles_path()

    def load(self) -> list[Profile]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [Profile.from_dict(item) for item in raw]

    def save(self, profiles: list[Profile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in profiles]
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
