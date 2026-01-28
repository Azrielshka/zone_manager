"""Config Flow for Zone Manager (v0.1).

Зачем:
- Чтобы интеграция ставилась/настраивалась через UI HA.
- В v0.1 настраиваем только путь JSON (по умолчанию zone_manager.json в /config).
"""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_CONFIG_PATH, DEFAULT_CONFIG_FILENAME

_LOGGER = logging.getLogger(__name__)


def _default_config_path(hass: HomeAssistant) -> str:
    """Формируем дефолтный путь в /config."""
    return hass.config.path(DEFAULT_CONFIG_FILENAME)


class ZoneManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Zone Manager config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Шаг добавления интеграции пользователем."""
        errors: dict[str, str] = {}

        if user_input is not None:
            config_path = user_input[CONF_CONFIG_PATH].strip()
            if not config_path:
                errors["base"] = "invalid_config_path"
            else:
                # В v0.1 допускаем только один инстанс интеграции
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                _LOGGER.info("Creating config entry with config_path=%s", config_path)
                return self.async_create_entry(
                    title="Zone Manager",
                    data={CONF_CONFIG_PATH: config_path},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_CONFIG_PATH, default=_default_config_path(self.hass)): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
