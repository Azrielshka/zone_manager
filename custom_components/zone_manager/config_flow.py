"""Config Flow для Zone Manager интеграции.

Зачем: Позволяет пользователям добавлять интеграцию через 
Home Assistant UI (Settings → Devices & Services) вместо 
редактирования YAML вручную.

Это создает красивую форму конфигурации в интерфейсе.
"""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ZoneManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow для Zone Manager.
    
    Этот класс обрабатывает процесс добавления интеграции
    через UI Home Assistant.
    """

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    # ============================================
    # Шаг 1: Инициализация (первый экран)
    # ============================================
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Первый шаг конфигурации (когда пользователь нажимает "Create Config").
        
        Зачем: Home Assistant вызывает эту функцию первой.
        Нам нужно собрать базовые данные и создать запись.
        
        Args:
            user_input: Данные из формы (если пользователь заполнил и нажал Next)
                        None если это первый вызов (показываем пустую форму).
                        
        Returns:
            FlowResult: Либо форма для заполнения, либо CreateEntry если все ОК.
        """
        
        # Если данные уже есть для этого домена, не позволяем создать еще одну
        # (обычно интеграция должна быть только одна)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        
        # ============ Если это первый вызов (форма пуста) ============
        if user_input is None:
            # Возвращаем форму с полями для заполнения
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    # Поле: "Имя конфигурации" (optional)
                    vol.Required(
                        "name",
                        default="Zone Manager"
                    ): str,
                }),
                description_placeholders={
                    "info": "Zone Manager помогает управлять зонами и их связями",
                },
                errors={},
            )
        
        # ============ Если данные уже заполнены ============
        # Валидируем данные
        errors = await self._validate_input(user_input)
        
        if errors:
            # Есть ошибки — показываем форму снова с ошибками
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(
                        "name",
                        default=user_input.get("name", "Zone Manager")
                    ): str,
                }),
                errors=errors,
            )
        
        # ============ Все хорошо — создаем запись конфигурации ============
        # Эта запись будет сохранена в Home Assistant и использована
        # при инициализации интеграции
        return self.async_create_entry(
            title=user_input["name"],
            data={}  # Пока пустые данные (все хранится в zones_config.json)
        )

    # ============================================
    # Шаг 2: Опции (редактирование)
    # ============================================
    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Создать OptionsFlow для редактирования опций.
        
        Зачем: Позволяет пользователю отредактировать конфигурацию
        после первого добавления интеграции.
        """
        return ZoneManagerOptionsFlow(config_entry)

    # ============================================
    # Валидация входных данных
    # ============================================
    async def _validate_input(
        self, user_input: Dict[str, Any]
    ) -> Dict[str, str]:
        """Проверить корректность введенных данных.
        
        Зачем: Перед сохранением конфигурации нужно убедиться,
        что пользователь ввел корректные значения (не пустые поля и т.д.).
        
        Args:
            user_input: Данные из формы
            
        Returns:
            Словарь ошибок (пустой если все ОК)
            Формат: {"field_name": "error_code"}
            Например: {"name": "invalid_name"}
        """
        errors = {}
        
        # Проверяем, что имя не пустое
        name = user_input.get("name", "").strip()
        if not name:
            errors["name"] = "invalid_name"  # Код ошибки
            _LOGGER.error("❌ Имя конфигурации не может быть пустым")
        
        # Здесь можно добавить другие проверки (подключение к API и т.д.)
        
        return errors


class ZoneManagerOptionsFlow(config_entries.OptionsFlow):
    """Options Flow для редактирования конфигурации.
    
    Это то, что видит пользователь когда нажимает "Options"
    на странице конфигурации интеграции.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Инициализация OptionsFlow.
        
        Args:
            config_entry: Запись конфигурации которую редактируем.
        """
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Первый (и обычно единственный) шаг опций.
        
        Зачем: Показываем форму с опциями которые можно менять после
        первого добавления интеграции.
        
        Args:
            user_input: Данные из формы (если заполнена)
            
        Returns:
            FlowResult: Форма или результат.
        """
        
        # ============ Если это первый вызов (форма пуста) ============
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({
                    # Опция: Включить отладку
                    vol.Required(
                        "debug_mode",
                        default=self.config_entry.options.get("debug_mode", False)
                    ): bool,
                    
                    # Опция: Интервал сохранения (сек)
                    vol.Required(
                        "save_interval",
                        default=self.config_entry.options.get("save_interval", 60)
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                }),
                description_placeholders={
                    "info": "Опции Zone Manager",
                },
            )
        
        # ============ Данные заполнены — сохраняем ============
        # Home Assistant автоматически сохранит user_input в config_entry.options
        return self.async_abort(reason="reconfigure_successful")
