"""WebSocket API for Zone Manager (v0.1).

Зачем:
- Lovelace карточка общается с backend через WS.
- По стандарту команды регистрируем ЯВНО через async_register_command. :contentReference[oaicite:5]{index=5}
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.components import websocket_api
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .storage import ZoneManagerStorage, _normalize_space


_LOGGER = logging.getLogger(__name__)


async def async_register_ws(hass: HomeAssistant, storage: ZoneManagerStorage) -> None:
    """Register all WS commands explicitly."""
    _LOGGER.debug("Registering WebSocket commands")

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/spaces_list",
        }
    )
    @websocket_api.async_response
    async def ws_spaces_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        _LOGGER.debug("WS spaces_list called")
        connection.send_result(msg["id"], {"spaces": storage.list_spaces()})

    websocket_api.async_register_command(hass, ws_spaces_list)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/space_get",
            vol.Required("space"): str,
        }
    )
    @websocket_api.async_response
    async def ws_space_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        space = msg["space"]
        _LOGGER.debug("WS space_get called space=%s", space)
        obj = storage.get_space(space)
        if obj is None:
            connection.send_error(msg["id"], "space_not_found", f"Space '{space}' not found")
            return
        connection.send_result(msg["id"], {"space": space, "data": obj})

    websocket_api.async_register_command(hass, ws_space_get)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/space_create",
            vol.Required("space"): str,
        }
    )
    @websocket_api.async_response
    async def ws_space_create(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        space = msg["space"].strip()
        _LOGGER.info("WS space_create space=%s", space)
        try:
            storage.create_space(space)
            await storage.async_save()
            connection.send_result(msg["id"], {"ok": True})
        except ValueError as err:
            connection.send_error(msg["id"], str(err), str(err))
        except Exception as err:
            _LOGGER.exception("space_create failed: %s", err)
            connection.send_error(msg["id"], "unknown_error", "Failed to create space")

    websocket_api.async_register_command(hass, ws_space_create)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/space_delete",
            vol.Required("space"): str,
        }
    )
    @websocket_api.async_response
    async def ws_space_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        space = msg["space"].strip()
        _LOGGER.info("WS space_delete space=%s", space)
        try:
            storage.delete_space(space)
            await storage.async_save()
            connection.send_result(msg["id"], {"ok": True})
        except ValueError as err:
            connection.send_error(msg["id"], str(err), str(err))
        except Exception as err:
            _LOGGER.exception("space_delete failed: %s", err)
            connection.send_error(msg["id"], "unknown_error", "Failed to delete space")

    websocket_api.async_register_command(hass, ws_space_delete)

    def _validate_space_for_save(space_obj: dict[str, Any]) -> list[dict[str, Any]]:
        """Серверная валидация данных space перед сохранением.

        Возвращает список ошибок для UI.
        Формат ошибки:
          { zone, field, index?, code, text, expected?, actual? }
        """
        errors: list[dict[str, Any]] = []

        zones = (space_obj or {}).get("zones", {}) or {}
        if not isinstance(zones, dict):
            return [{"zone": "", "field": "zones", "code": "invalid_type", "text": "zones must be an object"}]

        for zone_key, zone_obj in zones.items():
            if not isinstance(zone_key, str) or not zone_key.strip():
                continue

            z = zone_obj if isinstance(zone_obj, dict) else {}
            neighbors = z.get("neighbors") if isinstance(z.get("neighbors"), list) else []
            far_neighbors = z.get("far_neighbors") if isinstance(z.get("far_neighbors"), list) else []
            neighbor_groups = z.get("neighbor_groups") if isinstance(z.get("neighbor_groups"), list) else []

            # 1) zone_key не может быть в neighbors / far_neighbors
            for idx, v in enumerate(neighbors):
                if v == zone_key:
                    errors.append({
                        "zone": zone_key,
                        "field": "neighbors",
                        "index": idx,
                        "code": "self_reference",
                        "text": "Zone sensor (key) cannot be in neighbors",
                    })
            for idx, v in enumerate(far_neighbors):
                if v == zone_key:
                    errors.append({
                        "zone": zone_key,
                        "field": "far_neighbors",
                        "index": idx,
                        "code": "self_reference",
                        "text": "Zone sensor (key) cannot be in far neighbors",
                    })

            # 2) Дубли в neighbors (внутри одной зоны)
            seen: dict[str, int] = {}
            for idx, v in enumerate(neighbors):
                if not isinstance(v, str) or not v.strip():
                    continue
                if v in seen:
                    errors.append({
                        "zone": zone_key,
                        "field": "neighbors",
                        "index": idx,
                        "code": "duplicate",
                        "text": "Duplicate value in neighbors",
                    })
                else:
                    seen[v] = idx

            # 3) Дубли в far_neighbors (внутри одной зоны)
            seen = {}
            for idx, v in enumerate(far_neighbors):
                if not isinstance(v, str) or not v.strip():
                    continue
                if v in seen:
                    errors.append({
                        "zone": zone_key,
                        "field": "far_neighbors",
                        "index": idx,
                        "code": "duplicate",
                        "text": "Duplicate value in far neighbors",
                    })
                else:
                    seen[v] = idx

            # 4) far_neighbors может повторять neighbors — НИЧЕГО НЕ ДЕЛАЕМ (разрешено)

            # 5) Длины списков должны совпадать, ориентир = neighbors
            exp = len(neighbors)
            if len(far_neighbors) != exp:
                errors.append({
                    "zone": zone_key,
                    "field": "far_neighbors",
                    "code": "length_mismatch",
                    "text": "far_neighbors length must match neighbors length",
                    "expected": exp,
                    "actual": len(far_neighbors),
                })
            if len(neighbor_groups) != exp:
                errors.append({
                    "zone": zone_key,
                    "field": "neighbor_groups",
                    "code": "length_mismatch",
                    "text": "neighbor_groups length must match neighbors length",
                    "expected": exp,
                    "actual": len(neighbor_groups),
                })

        return errors

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/space_save",
            vol.Required("space"): str,
            vol.Required("data"): dict,
        }
    )
    @websocket_api.async_response
    async def ws_space_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        space = msg["space"].strip()
        data = msg["data"]
        _LOGGER.info("WS space_save space=%s", space)

        try:
            # Нормализуем вход (чтобы валидатор работал на чистой структуре)
            normalized_space = _normalize_space(data)

            errors = _validate_space_for_save(normalized_space)
            if errors:
                _LOGGER.warning("Validation failed for space=%s errors=%d", space, len(errors))
                connection.send_result(msg["id"], {"ok": False, "errors": errors})
                return

            storage.save_space(space, normalized_space)
            await storage.async_save()
            connection.send_result(msg["id"], {"ok": True})

        except Exception as err:
            _LOGGER.exception("space_save failed: %s", err)
            connection.send_error(msg["id"], "unknown_error", "Failed to save space")

    websocket_api.async_register_command(hass, ws_space_save)

    # ----- areas_list -----
    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/areas_list",
        }
    )
    @websocket_api.async_response
    async def ws_areas_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        _LOGGER.debug("WS areas_list called")
        reg = ar.async_get(hass)
        areas = [{"id": a.id, "name": a.name} for a in reg.async_list_areas()]
        areas.sort(key=lambda x: x["name"].lower())
        connection.send_result(msg["id"], {"areas": areas})

    websocket_api.async_register_command(hass, ws_areas_list)

    # ----- entities_for_area -----
    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/entities_for_area",
            # area_id пустой/None = все
            vol.Optional("area_id"): vol.Any(None, str),
            vol.Optional("domains", default=["sensor", "light"]): [str],
        }
    )
    @websocket_api.async_response
    async def ws_entities_for_area(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        area_id = msg.get("area_id")
        domains = msg.get("domains", ["sensor", "light"])
        _LOGGER.debug("WS entities_for_area area_id=%s domains=%s", area_id, domains)

        entities = await _async_entities_for_area(hass, area_id, set(domains))
        connection.send_result(msg["id"], {"entities": entities})

    websocket_api.async_register_command(hass, ws_entities_for_area)

    _LOGGER.info("WebSocket commands registered")


async def _async_entities_for_area(hass: HomeAssistant, area_id: str | None, domains: set[str]) -> list[dict[str, Any]]:
    """Собрать сущности по area через Entity/Device Registry (правильно по стандарту). :contentReference[oaicite:6]{index=6}"""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    out: list[dict[str, Any]] = []

    # Берём именно registry, т.к. area_id — метаданные, не state.attributes :contentReference[oaicite:7]{index=7}
    for entry in ent_reg.entities.values():
        entity_id = entry.entity_id
        domain = entity_id.split(".", 1)[0]
        if domain not in domains:
            continue

        resolved_area = entry.area_id
        if resolved_area is None and entry.device_id is not None:
            dev = dev_reg.devices.get(entry.device_id)
            if dev is not None:
                resolved_area = dev.area_id

        if area_id and resolved_area != area_id:
            continue

        # friendly_name (если есть state)
        st = hass.states.get(entity_id)
        name = None
        if st is not None:
            name = st.attributes.get("friendly_name")
        if not name:
            name = entry.original_name or entity_id

        out.append(
            {
                "entity_id": entity_id,
                "name": name,
                "domain": domain,
            }
        )

    out.sort(key=lambda x: (x["domain"], x["name"].lower(), x["entity_id"]))
    return out
