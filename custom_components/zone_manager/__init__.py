"""Zone Manager integration (v0.1).

Зачем нужен этот файл:
- Точка входа интеграции.
- Инициализирует хранилище, WebSocket API, сервисы и статический путь для frontend.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_CONFIG_PATH, DEFAULT_CONFIG_FILENAME
from .storage import ZoneManagerStorage
from .websocket_api import async_register_ws
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Базовая подготовка (редко используется)."""
    _LOGGER.debug("async_setup called")
    hass.data.setdefault(DOMAIN, {})
    return True



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Основная точка инициализации логики интеграции."""
    _LOGGER.info("Setting up Zone Manager entry_id=%s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})
    # --- FIX v0.1: миграция/страховка на случай старых/битых entry без config_path ---
    # Зачем: старые записи могли создаться без data[config_path], чтобы не падать с KeyError.
    data = dict(entry.data)
    if CONF_CONFIG_PATH not in data or not str(data.get(CONF_CONFIG_PATH, "")).strip():
        default_path = hass.config.path(DEFAULT_CONFIG_FILENAME)
        _LOGGER.warning(
            "Config entry missing '%s'. Defaulting to %s and updating entry.",
            CONF_CONFIG_PATH,
            default_path,
        )
        data[CONF_CONFIG_PATH] = default_path
        hass.config_entries.async_update_entry(entry, data=data)
    # --- /FIX ---
    storage = ZoneManagerStorage(hass=hass, entry=entry)
    await storage.async_load()  # важно: await на async функции :contentReference[oaicite:2]{index=2}

    # Сохраняем storage в hass.data
    hass.data[DOMAIN][entry.entry_id] = storage

    # Регистрируем WebSocket команды ЯВНО :contentReference[oaicite:3]{index=3}
    await async_register_ws(hass, storage)

    # Регистрируем сервисы (services.yaml обязателен) :contentReference[oaicite:4]{index=4}
    await async_register_services(hass, storage)

    _LOGGER.info("Zone Manager setup complete (entry_id=%s)", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка интеграции."""
    _LOGGER.info("Unloading Zone Manager entry_id=%s", entry.entry_id)

    storage: ZoneManagerStorage | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if storage is not None:
        await storage.async_close()

    return True
