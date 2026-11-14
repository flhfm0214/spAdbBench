from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingsEntry:
    serial: str
    table: str
    key: str
    value: str
    write_command: str
    updated_at: str

    @classmethod
    def from_dict(cls, raw: dict) -> "SettingsEntry | None":
        try:
            return cls(
                serial=str(raw["serial"]),
                table=str(raw["table"]),
                key=str(raw["key"]),
                value=str(raw["value"]),
                write_command=str(raw["write_command"]),
                updated_at=str(raw.get("updated_at", "")),
            )
        except (KeyError, TypeError):
            return None


class SettingsHistoryStore:
    """Settings values written by this tool, grouped by device serial."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._entries: list[SettingsEntry] = []
        self.last_error = ""
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            logger.warning("读取设置历史失败: %s", exc)
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if isinstance(item, dict):
                entry = SettingsEntry.from_dict(item)
                if entry is not None:
                    self._entries.append(entry)

    def entries(self, serial: str) -> list[SettingsEntry]:
        return [entry for entry in self._entries if entry.serial == serial]

    def record(
        self,
        serial: str,
        table: str,
        key: str,
        value: str,
        write_command: str,
    ) -> SettingsEntry:
        entry = SettingsEntry(
            serial=serial,
            table=table,
            key=key,
            value=value,
            write_command=write_command,
            updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._entries = [
            existing
            for existing in self._entries
            if not (
                existing.serial == serial
                and existing.table == table
                and existing.key == key
            )
        ]
        self._entries.append(entry)
        self._save()
        return entry

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(
                    [asdict(entry) for entry in self._entries],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
            self.last_error = ""
        except OSError as exc:
            self.last_error = str(exc)
            logger.warning("保存设置历史失败: %s", exc)
