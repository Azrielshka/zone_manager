"""Services for Zone Manager (v0.1).

Зачем:
- reload: перечитать файл вручную
- export: принудительно записать текущие данные в файл
services.yaml обязателен по стандарту. :contentReference[oaicite:8]{index=8}
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .storage import ZoneManagerStorage

_LOGGER = logging.getLogger(__name__)


async def async_register_services(hass: HomeAssistant, storage: ZoneManagerStorage) -> None:
    """Register services once."""
    _LOGGER.debug("Registering services")

    async def handle_reload(call: ServiceCall) -> None:
        _LOGGER.info("Service reload called")
        await storage.async_reload()

    async def handle_export(call: ServiceCall) -> None:
        _LOGGER.info("Service export called")
        await storage.async_save()

    hass.services.async_register(DOMAIN, "reload", handle_reload)
    hass.services.async_register(DOMAIN, "export", handle_export)

    _LOGGER.info("Services registered")
