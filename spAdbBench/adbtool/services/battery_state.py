from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


class BatterySimulationTracker:
    """Battery overrides written by this tool, grouped by device serial."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._states: dict[str, dict] = {}
        self.last_error = ""
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            logger.warning("读取电池模拟状态失败: %s", exc)
            return
        if isinstance(raw, dict):
            self._states = {
                str(serial): values
                for serial, values in raw.items()
                if isinstance(values, dict)
            }

    def state(self, serial: str) -> dict | None:
        values = self._states.get(serial)
        if values is None:
            return None
        return {
            key: value
            for key, value in values.items()
            if key != "updated_at"
        }

    def mark(self, serial: str, values: dict) -> dict:
        current = dict(self._states.get(serial) or {})
        current.update(values)
        current["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self._states[serial] = current
        self._save()
        return dict(current)

    def clear(self, serial: str) -> None:
        self._states.pop(serial, None)
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                json.dumps(self._states, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temp, self.path)
            self.last_error = ""
        except OSError as exc:
            self.last_error = str(exc)
            logger.warning("保存电池模拟状态失败: %s", exc)
