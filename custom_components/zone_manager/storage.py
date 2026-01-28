"""File storage for Zone Manager (v0.1).

Зачем:
- Хранить источник истины в /config/zone_manager.json (как вы хотите).
- Делать атомарную запись (tmp -> replace), логировать операции.
- Давать удобные методы для CRUD на пространства.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import async_timeout
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CONFIG_PATH,
    DATA_VERSION,
    ZONE_FIELDS_LISTS,
    DEFAULT_CONFIG_FILENAME,  # <-- добавить
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZoneManagerStorage:
    """Storage wrapper for file-based JSON config."""

    hass: HomeAssistant
    entry: ConfigEntry

    _data: dict[str, Any] | None = None
    _lock: Any = None  # asyncio.Lock (инициализируем в async_load)

    @property
    def config_path(self) -> str:
        """Абсолютный путь к JSON файлу.

        Зачем: на случай старых/битых ConfigEntry без config_path — используем дефолт /config/zone_manager.json
        и пишем предупреждение в лог.
        """
        path = self.entry.data.get(CONF_CONFIG_PATH)
        if not path or not str(path).strip():
            fallback = self.hass.config.path(DEFAULT_CONFIG_FILENAME)
            _LOGGER.warning("config_path missing in entry.data, using fallback: %s", fallback)
            return fallback
        return path

    @property
    def data(self) -> dict[str, Any]:
        """Текущее состояние данных в памяти."""
        return self._data if self._data is not None else self._new_empty()

    async def async_load(self) -> None:
        """Загрузить JSON из файла в память (с таймаутом, чтобы не подвесить HA)."""
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()

        needs_save = False
        path = self.config_path

        async with self._lock:
            _LOGGER.info("Loading Zone Manager config from %s", path)

            try:
                # Предохранитель: не даём зависнуть на чтении файла
                async with async_timeout.timeout(10):
                    _LOGGER.debug("Reading JSON file (executor) start: %s", path)
                    raw = await self.hass.async_add_executor_job(_read_json_file, path)
                    _LOGGER.debug("Reading JSON file (executor) done: %s", path)
            except TimeoutError:
                _LOGGER.error("Timeout while reading JSON file: %s. Using empty config.", path)
                raw = None
            except Exception as err:
                _LOGGER.exception("Unexpected error while reading JSON file %s: %s", path, err)
                raw = None

            if raw is None:
                _LOGGER.warning("Config file not found or invalid, will create new at %s", path)
                self._data = self._new_empty()
                needs_save = True
            else:
                normalized = _normalize_and_validate(raw)
                self._data = normalized

                _LOGGER.info(
                    "Loaded Zone Manager config: spaces=%d",
                    len(self._data.get("spaces", {})),
                )

        # ВАЖНО: сохраняем уже ПОСЛЕ выхода из lock (иначе дедлок)
        if needs_save:
            await self.async_save()


    async def async_save(self) -> None:
        """Сохранить текущие данные в файл (атомарно, с таймаутом)."""
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            path = self.config_path
            payload = _normalize_and_validate(self.data)

            _LOGGER.info("Saving Zone Manager config to %s", path)

            try:
                # Предохранитель: не даём зависнуть на записи
                async with async_timeout.timeout(10):
                    _LOGGER.debug("Writing JSON file (executor) start: %s", path)
                    await self.hass.async_add_executor_job(_write_json_atomic_with_backup, path, payload)
                    _LOGGER.debug("Writing JSON file (executor) done: %s", path)
            except TimeoutError:
                _LOGGER.error("Timeout while writing JSON file: %s", path)
                # Не падаем — чтобы интеграция не блокировала HA
                return
            except Exception as err:
                _LOGGER.exception("Failed to write JSON file %s: %s", path, err)
                return

            self._data = payload
            _LOGGER.debug("Save completed (spaces=%d)", len(payload.get("spaces", {})))


    async def async_reload(self) -> None:
        """Перечитать файл с диска (по сервису reload)."""
        _LOGGER.info("Reload requested")
        await self.async_load()

    async def async_close(self) -> None:
        """На будущее: закрытие/очистка ресурсов."""
        _LOGGER.debug("Storage close called")

    # ---------------------------
    # CRUD для пространств
    # ---------------------------
    def list_spaces(self) -> list[dict[str, Any]]:
        """Вернуть список пространств (для селекта)."""
        spaces: dict[str, Any] = self.data.get("spaces", {})
        out: list[dict[str, Any]] = []
        for name, space_obj in spaces.items():
            zones = (space_obj or {}).get("zones", {}) or {}
            out.append({"name": name, "zones_count": len(zones)})
        out.sort(key=lambda x: x["name"].lower())
        return out

    def get_space(self, space_name: str) -> dict[str, Any] | None:
        """Вернуть пространство целиком."""
        spaces: dict[str, Any] = self.data.get("spaces", {})
        return spaces.get(space_name)

    def create_space(self, space_name: str) -> None:
        """Создать пространство, если не существует."""
        data = self.data
        spaces: dict[str, Any] = data.setdefault("spaces", {})
        if space_name in spaces:
            raise ValueError("space_exists")
        spaces[space_name] = {"zones": {}}
        _LOGGER.debug("Space created: %s", space_name)

    def delete_space(self, space_name: str) -> None:
        """Удалить пространство."""
        data = self.data
        spaces: dict[str, Any] = data.setdefault("spaces", {})
        if space_name not in spaces:
            raise ValueError("space_not_found")
        spaces.pop(space_name)
        _LOGGER.debug("Space deleted: %s", space_name)

    def save_space(self, space_name: str, space_obj: dict[str, Any]) -> None:
        """Сохранить пространство целиком (перезапись)."""
        data = self.data
        spaces: dict[str, Any] = data.setdefault("spaces", {})
        spaces[space_name] = _normalize_space(space_obj)
        _LOGGER.debug("Space saved: %s (zones=%d)", space_name, len(spaces[space_name]["zones"]))

    # ---------------------------
    # Helpers
    # ---------------------------
    @staticmethod
    def _new_empty() -> dict[str, Any]:
        """Пустой шаблон данных."""
        return {"version": DATA_VERSION, "spaces": {}}


# ---------------------------
# Низкоуровневые операции с файлами
# ---------------------------

def _read_json_file(path: str) -> dict[str, Any] | None:
    """Прочитать JSON из файла. Возвращает None при ошибке/отсутствии."""
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as err:
        _LOGGER.exception("Failed to read JSON file %s: %s", path, err)
        return None


def _write_json_atomic_with_backup(path: str, data: dict[str, Any]) -> None:
    """Атомарная запись JSON + backup (.bak)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Backup (если файл уже есть)
        if os.path.exists(path):
            bak_path = f"{path}.bak"
            try:
                shutil.copy2(path, bak_path)
                _LOGGER.debug("Backup created: %s", bak_path)
            except Exception as err:
                _LOGGER.warning("Failed to create backup for %s: %s", path, err)

        # Пишем во временный файл
        fd, tmp_path = tempfile.mkstemp(prefix="zone_manager_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())

            # replace атомарно
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    except Exception as err:
        _LOGGER.exception("Failed to write JSON file %s: %s", path, err)
        raise


# ---------------------------
# Валидация/нормализация данных (мягкая для v0.1)
# ---------------------------

def _normalize_and_validate(raw: dict[str, Any]) -> dict[str, Any]:
    """Привести к ожидаемой структуре и отбросить мусор (мягко)."""
    if not isinstance(raw, dict):
        _LOGGER.warning("Invalid root type, resetting to empty")
        return {"version": DATA_VERSION, "spaces": {}}

    version = raw.get("version") or DATA_VERSION
    spaces = raw.get("spaces")
    if not isinstance(spaces, dict):
        spaces = {}

    out_spaces: dict[str, Any] = {}
    for space_name, space_obj in spaces.items():
        if not isinstance(space_name, str) or not space_name.strip():
            continue
        out_spaces[space_name] = _normalize_space(space_obj)

    return {"version": str(version), "spaces": out_spaces}


def _normalize_space(space_obj: Any) -> dict[str, Any]:
    """Нормализовать объект пространства."""
    if not isinstance(space_obj, dict):
        return {"zones": {}}

    zones = space_obj.get("zones")
    if not isinstance(zones, dict):
        zones = {}

    out_zones: dict[str, Any] = {}
    for zone_key, zone_obj in zones.items():
        if not isinstance(zone_key, str) or not zone_key.strip():
            continue
        out_zones[zone_key] = _normalize_zone(zone_obj)

    return {"zones": out_zones}


def _normalize_zone(zone_obj: Any) -> dict[str, Any]:
    """Нормализовать объект зоны под вашу схему."""
    if not isinstance(zone_obj, dict):
        zone_obj = {}

    out: dict[str, Any] = {}
    for field in ZONE_FIELDS_LISTS:
        val = zone_obj.get(field, [])
        if isinstance(val, list):
            out[field] = [x for x in val if isinstance(x, str) and x.strip()]
        else:
            out[field] = []

    return out
