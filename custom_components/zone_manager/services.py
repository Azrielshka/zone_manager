"""Services for Zone Manager (v0.2).
v0.2: добавлен сервис get_sensor_config с response data + нормализация списков + light_group_single.
Зачем:
- reload: перечитать файл вручную
- export: принудительно записать текущие данные в файл
- get_sensor_config: получить конфиг зоны по trigger sensor entity_id (для автоматизаций через response_variable)

services.yaml обязателен по стандарту. :contentReference[oaicite:3]{index=3}
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, ServiceResponse
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, ZONE_FIELDS_LISTS
from .storage import ZoneManagerStorage

_LOGGER = logging.getLogger(__name__)


def _find_zone_by_entity_id(data: dict[str, Any], entity_id: str) -> tuple[str | None, dict[str, Any] | None]:
    """Ищем зону по ключу entity_id в структуре:
    data["spaces"][<space_name>]["zones"][<entity_id>]

    Возвращает:
    - space_name (или None)
    - zone_obj (или None)
    """
    spaces = (data or {}).get("spaces") or {}
    if not isinstance(spaces, dict):
        return None, None

    for space_name, space_obj in spaces.items():
        zones = (space_obj or {}).get("zones") or {}
        if isinstance(zones, dict) and entity_id in zones:
            zone = zones.get(entity_id)
            if isinstance(zone, dict):
                return str(space_name), zone
            return str(space_name), None

    return None, None


def _as_list(value: Any) -> list[str]:
    """Нормализуем значение к list[str].

    Поддерживаем:
    - list[str] -> list[str]
    - "a, b" -> ["a","b"]
    - "a" -> ["a"]
    - None/прочее -> []
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, str):
        v = value.strip()
        if not v:
            return []
        if "," in v:
            return [x.strip() for x in v.split(",") if x.strip()]
        return [v]

    # Непредвиденный тип — безопасно игнорируем
    return []


async def async_register_services(hass: HomeAssistant, storage: ZoneManagerStorage) -> None:
    """Register services once."""
    _LOGGER.debug("Registering services")

    # ---------------------------
    # reload
    # ---------------------------
    async def handle_reload(call: ServiceCall) -> None:
        _LOGGER.info("Service reload called")
        await storage.async_reload()

    if not hass.services.has_service(DOMAIN, "reload"):
        hass.services.async_register(DOMAIN, "reload", handle_reload)
    else:
        _LOGGER.debug("Service reload already registered")

    # ---------------------------
    # export
    # ---------------------------
    async def handle_export(call: ServiceCall) -> None:
        _LOGGER.info("Service export called")
        await storage.async_save()

    if not hass.services.has_service(DOMAIN, "export"):
        hass.services.async_register(DOMAIN, "export", handle_export)
    else:
        _LOGGER.debug("Service export already registered")

    # ---------------------------
    # get_sensor_config
    # ---------------------------
    async def handle_get_sensor_config(call: ServiceCall) -> ServiceResponse | None:
        """Вернуть конфиг зоны по entity_id.

        Зачем:
        - Автоматизация не читает JSON-файл напрямую
        - Получаем конфиг из storage.data (в памяти)
        - Возвращаем через response_variable
        """
        entity_id: str = call.data["entity_id"]
        do_reload: bool = bool(call.data.get("reload", False))

        _LOGGER.debug("Service get_sensor_config called entity_id=%s reload=%s", entity_id, do_reload)

        if do_reload:
            _LOGGER.info("get_sensor_config: reloading storage before lookup (entity_id=%s)", entity_id)
            await storage.async_reload()

        data = storage.data
        space_name, zone = _find_zone_by_entity_id(data, entity_id)

        # Базовый ответ (всегда одинаковая форма)
        response: dict[str, Any] = {
            "found": False,
            "entity_id": entity_id,
            "space": None,
            "zone": None,
            "neighbors": [],
            "far_neighbors": [],
            "neighbor_groups": [],
            "light_group": [],
            # Удобный “одиночный” вариант для текущих off-скриптов,
            # где light_group используется как строка в is_state(...).
            "light_group_single": "",
        }

        if zone is None:
            _LOGGER.warning("get_sensor_config: not found entity_id=%s", entity_id)
            if call.return_response:
                return response
            return None

        # Нормализуем ожидаемые поля зоны (на всякий случай, даже если storage уже нормализовал)
        normalized: dict[str, Any] = {}
        for field in ZONE_FIELDS_LISTS:
            normalized[field] = _as_list(zone.get(field))

        light_group_list = normalized.get("light_group", [])
        light_group_single = light_group_list[0] if len(light_group_list) == 1 else ""

        response.update(
            {
                "found": True,
                "space": space_name,
                "zone": zone,  # сырой объект (как в JSON), полезно для диагностики
                "neighbors": normalized.get("neighbors", []),
                "far_neighbors": normalized.get("far_neighbors", []),
                "neighbor_groups": normalized.get("neighbor_groups", []),
                "light_group": light_group_list,
                "light_group_single": light_group_single,
            }
        )

        _LOGGER.info(
            "get_sensor_config: found entity_id=%s space=%s neighbors=%d far=%d groups=%d light_group=%s",
            entity_id,
            space_name,
            len(response["neighbors"]),
            len(response["far_neighbors"]),
            len(response["neighbor_groups"]),
            response["light_group"],
        )

        if call.return_response:
            return response

        return None

    schema_get_sensor_config = vol.Schema(
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("reload", default=False): cv.boolean,
        }
    )

    if not hass.services.has_service(DOMAIN, "get_sensor_config"):
        hass.services.async_register(
            DOMAIN,
            "get_sensor_config",
            handle_get_sensor_config,
            schema=schema_get_sensor_config,
            supports_response=SupportsResponse.OPTIONAL,
        )
    else:
        _LOGGER.debug("Service get_sensor_config already registered")

    _LOGGER.info("Services registered")
