"""Zone Manager интеграция для Home Assistant."""

import json
import logging
import voluptuous as vol
from pathlib import Path
from typing import Any, Dict, Optional

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType




# Schema для сервиса update_zone
# Зачем: Валидирует входные данные перед обработкой
UPDATE_ZONE_SCHEMA = vol.Schema({
    vol.Optional("space", default="space_1"): cv.string,
    vol.Required("sensor_id"): cv.string,
    vol.Required("zone_config"): dict,
})

# Schema для сервиса delete_zone
DELETE_ZONE_SCHEMA = vol.Schema({
    vol.Optional("space", default="space_1"): cv.string,
    vol.Required("sensor_id"): cv.string,
})

# Schema для сервиса get_zone
GET_ZONE_SCHEMA = vol.Schema({
    vol.Required("sensor_id"): cv.string,
})


from .const import (
    DOMAIN,
    ZONES_CONFIG_FILE,
    DEFAULT_ZONES_CONFIG,
    SERVICE_UPDATE_ZONE,
    SERVICE_DELETE_ZONE,
    SERVICE_GET_ZONE,
    KEY_ZONE_NAME,
    KEY_NEIGHBORS,
    KEY_LIGHT_GROUP,
    KEY_FAR_NEIGHBORS,
    KEY_NEIGHBOR_GROUPS,
    STORAGE_KEY_CARD,          # <--- добавлено
    STORAGE_VERSION_CARD,      # <--- добавлено
)


_LOGGER = logging.getLogger(__name__)

# ============================================
# Глобальный объект менеджера
# ============================================
zone_manager: Optional["ZoneManager"] = None


class ZoneManager:
    """Класс для управления зонами и их конфигурацией.
    
    Этот класс отвечает за:
    - Загрузку конфигурации зон из JSON файла
    - Сохранение изменений обратно в файл
    - Быстрый поиск зоны по ID датчика
    - Добавление/удаление зон
    """
    
    def __init__(self, hass: HomeAssistant):
        """Инициализация менеджера зон.
        
        Args:
            hass: Экземпляр Home Assistant
            
        Зачем: Сохраняем ссылку на HA и определяем путь к JSON файлу,
        который будет храниться в /config/zones_config.json
        """
        self.hass = hass
        self.config_path = Path(hass.config.path(ZONES_CONFIG_FILE))
        self.zones_data: Dict[str, Any] = {}
        
        # Store для хранения конфигурации карточек в .storage
        # Файл будет выглядеть как .storage/zone_manager_card_config
        self._card_store: Store = Store(
            hass,
            STORAGE_VERSION_CARD,
            STORAGE_KEY_CARD,
        )   
     
    async def load_config(self) -> None:
        """Загрузить конфигурацию из JSON файла.
        
        Зачем: При старте интеграции нужно прочитать все сохраненные зоны.
        Если файл не существует, создаст пустой с дефолтной структурой.
        Если JSON повреждена, логирует ошибку и использует дефолт.
        """
        try:
            if self.config_path.exists():
                # Файл существует — загружаем его
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    self.zones_data = loaded_data
                _LOGGER.info(
                    f"✅ Конфигурация зон загружена из {self.config_path}"
                )
            else:
                # Файл не существует — создаем новый
                self.zones_data = DEFAULT_ZONES_CONFIG
                await self.save_config()
                _LOGGER.info(
                    f"📝 Создан новый файл конфигурации: {self.config_path}"
                )
        except json.JSONDecodeError as err:
            # JSON повреждена — логируем ошибку и используем дефолт
            _LOGGER.error(
                f"❌ JSON файл повреждена: {err}. "
                f"Используется дефолтная конфигурация."
            )
            self.zones_data = DEFAULT_ZONES_CONFIG

        except Exception as err:
            # Другие ошибки (прав доступа, диск и т.д.)
            _LOGGER.error(
                f"❌ Ошибка при загрузке конфигурации: {err}"
            )
            self.zones_data = DEFAULT_ZONES_CONFIG

        # --- Новое: синхронизируем .storage с текущей zones_data ---
        try:
            await self._card_store.async_save(self.zones_data)
            _LOGGER.debug(
                "💾 Конфигурация зон из JSON синхронизирована в .storage "
                "(zone_manager_card_config)"
            )
        except Exception as err:
            _LOGGER.error(
                "❌ Не удалось сохранить конфигурацию карточек в .storage: %s",
                err,
            )

    async def save_config(self) -> None:
        """Сохранить конфигурацию в JSON файл.
        
        Зачем: После каждого изменения (добавление/удаление/изменение зоны)
        нужно записать обновленные данные на диск. Без этого данные теряются
        при перезагрузке Home Assistant.
        """
        try:
            # Создаем/перезаписываем файл с текущими данными
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(
                    self.zones_data,
                    f,
                    indent=2,
                    ensure_ascii=False  # Чтобы кириллица сохранялась корректно
                )
            _LOGGER.debug("💾 Конфигурация зон сохранена на диск")

            # Дополнительно: поддерживаем зеркало в .storage для карточек
            try:
                await self._card_store.async_save(self.zones_data)
                _LOGGER.debug(
                    "💾 Конфигурация зон сохранена в .storage "
                    "(zone_manager_card_config)"
                )
            except Exception as err:
                _LOGGER.error(
                    "❌ Ошибка при сохранении конфигурации карточек в .storage: %s",
                    err,
                )

        except Exception as err:
            _LOGGER.error(
                f"❌ Ошибка при сохранении конфигурации: {err}"
            )

    def get_zone_by_sensor(
        self, sensor_entity_id: str
    ) -> Optional[Dict[str, Any]]:
        """Получить данные зоны по ID датчика (ключу).
        
        Зачем: Это нужно автоматизациям — когда срабатывает датчик,
        нужно быстро найти его в конфиге и получить соседей, группы и т.д.
        
        Поиск работает за O(1) благодаря структуре словаря (хеш-таблица).
        
        Args:
            sensor_entity_id: Например, "sensor.ms_5_1_4_11_state"
            
        Returns:
            Словарь с данными зоны, например:
            {
                "zone_name": "Зона 1",
                "neighbors": ["sensor.ms_5_1_3_8_state", ...],
                "light_group": "light.koridor_510_0",
                "far_neighbors": [...],
                "neighbor_groups": [...]
            }
            Или None если зона не найдена.
        """
        # Перебираем все пространства (space_1, space_2, ...)
        for space, zones in self.zones_data.items():
            # Проверяем, есть ли датчик в этом пространстве
            if sensor_entity_id in zones:
                return zones[sensor_entity_id]
        
        # Датчик не найден ни в одном пространстве
        _LOGGER.warning(
            f"⚠️ Датчик {sensor_entity_id} не найден в конфигурации"
        )
        return None

    def add_or_update_zone(
        self,
        space: str,
        sensor_entity_id: str,
        zone_config: Dict[str, Any]
    ) -> bool:
        """Добавить или обновить зону.
        
        Зачем: Карточка вызывает этот метод через сервис,
        чтобы добавить новую зону или обновить существующую.
        
        Args:
            space: Название пространства (например, "space_1")
            sensor_entity_id: ID датчика (ключ), например "sensor.ms_5_1_4_11_state"
            zone_config: Словарь с параметрами зоны
                {
                    "zone_name": "Зона 1",
                    "neighbors": ["sensor.ms_5_1_3_8_state", ...],
                    "light_group": "light.koridor_510_0",
                    "far_neighbors": [...],
                    "neighbor_groups": [...]
                }
                
        Returns:
            True если успешно, False если ошибка валидации.
        """
        # ============ Валидация входных данных ============
        if not space or not isinstance(space, str):
            _LOGGER.error(f"❌ Невалидное имя пространства: {space}")
            return False
        
        if not sensor_entity_id or not isinstance(sensor_entity_id, str):
            _LOGGER.error(f"❌ Невалидный ID датчика: {sensor_entity_id}")
            return False
        
        if not zone_config or not isinstance(zone_config, dict):
            _LOGGER.error(f"❌ Невалидная конфигурация зоны: {zone_config}")
            return False
        
        # ============ Добавление или обновление ============
        # Если пространства нет — создать его
        if space not in self.zones_data:
            self.zones_data[space] = {}
            _LOGGER.debug(f"📁 Создано новое пространство: {space}")
        
        # Добавить или обновить зону
        self.zones_data[space][sensor_entity_id] = zone_config
        _LOGGER.info(
            f"✅ Зона обновлена: {space}/{sensor_entity_id} "
            f"(имя: {zone_config.get('zone_name', 'N/A')})"
        )
        return True

    def delete_zone(self, space: str, sensor_entity_id: str) -> bool:
        """Удалить зону.
        
        Зачем: Если пользователь хочет удалить зону из интерфейса.
        
        Args:
            space: Название пространства
            sensor_entity_id: ID датчика
            
        Returns:
            True если успешно удалена, False если такой зоны не было.
        """
        if space not in self.zones_data:
            _LOGGER.warning(
                f"⚠️ Пространство не найдено: {space}"
            )
            return False
        
        if sensor_entity_id not in self.zones_data[space]:
            _LOGGER.warning(
                f"⚠️ Зона не найдена: {space}/{sensor_entity_id}"
            )
            return False
        
        # Удаляем зону
        zone_name = self.zones_data[space][sensor_entity_id].get(
            "zone_name", "Unknown"
        )
        del self.zones_data[space][sensor_entity_id]
        
        _LOGGER.info(
            f"✅ Зона удалена: {space}/{sensor_entity_id} (имя: {zone_name})"
        )
        return True

    def get_all_zones(self, space: Optional[str] = None) -> Dict[str, Any]:
        """Получить все зоны для пространства или всех пространств.
        
        Зачем: Для отладки, логирования или экспорта данных.
        
        Args:
            space: Если указано, вернуть только для этого пространства.
                   Если None, вернуть все.
        
        Returns:
            Словарь с данными.
        """
        if space:
            return self.zones_data.get(space, {})
        return self.zones_data

@callback
def _update_zones_entity(hass: HomeAssistant, manager: "ZoneManager") -> None:
    """Создать/обновить entity zone_manager.zones_data в HA.

    Зачем:
    - Карточка и шаблоны читают данные только через entity.
    - Здесь мы один раз собираем zones_data из менеджера и
      публикуем его как атрибут в состоянии Home Assistant.
    """
    try:
        hass.states.async_set(
            "zone_manager.zones_data",  # entity_id
            "ready",                    # произвольное состояние
            {
                "zones_data": manager.get_all_zones()
            },
        )
        _LOGGER.debug(
            "📡 Entity zone_manager.zones_data обновлена, всего пространств: %d",
            len(manager.get_all_zones()),
        )
    except Exception as err:
        _LOGGER.error("❌ Не удалось обновить entity zones_data: %s", err)

def _register_websocket_handlers(
    hass: HomeAssistant,
    update_entity_cb,
) -> None:
    """Регистрация WebSocket-команд для работы карточки.

    Карточка использует только эти команды, НЕ читая entity напрямую.
    """

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "zone_manager/get_space_config",
            vol.Required("space"): cv.string,
        }
    )
    @websocket_api.async_response
    async def websocket_get_space_config(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: Dict[str, Any],
    ) -> None:
        """Вернуть конфигурацию зон для одного пространства."""
        space = msg["space"]
        manager: ZoneManager = hass.data[DOMAIN]["manager"]
        zones = manager.get_all_zones(space)

        _LOGGER.debug(
            "🌐 WS get_space_config: space=%s, zones=%d",
            space,
            len(zones),
        )

        connection.send_result(
            msg["id"],
            {
                "space": space,
                "zones": zones,
            },
        )

    websocket_api.async_register_command(hass, websocket_get_space_config)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "zone_manager/save_space_config",
            vol.Required("space"): cv.string,
            vol.Required("zones"): dict,
        }
    )
    @websocket_api.async_response
    async def websocket_save_space_config(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: Dict[str, Any],
    ) -> None:
        """Сохранить полную конфигурацию зон для одного пространства.

        Карточка передаёт полный словарь:
        {
          "sensor.xxx": {...},
          "sensor.yyy": {...}
        }
        """
        space: str = msg["space"]
        zones: Dict[str, Any] = msg["zones"]

        manager: ZoneManager = hass.data[DOMAIN]["manager"]

        # Полностью заменяем пространство новыми данными
        manager.zones_data[space] = zones

        await manager.save_config()
        update_entity_cb()

        _LOGGER.info(
            "🌐 WS save_space_config: пространство %s обновлено, зон: %d",
            space,
            len(zones),
        )

        connection.send_result(
            msg["id"],
            {
                "success": True,
                "space": space,
                "zones": manager.get_all_zones(space),
            },
        )

    websocket_api.async_register_command(hass, websocket_save_space_config)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Инициализация интеграции при старте Home Assistant (YAML)."""
    global zone_manager

    hass.data.setdefault(DOMAIN, {})

    _LOGGER.info("🚀 Инициализация Zone Manager (YAML)...")
    zone_manager = ZoneManager(hass)
    await zone_manager.load_config()
    hass.data[DOMAIN]["manager"] = zone_manager

    # Колбэк для обновления entity zones_data
    @callback
    def update_entity_cb() -> None:
        _update_zones_entity(hass, zone_manager)

    hass.data[DOMAIN]["update_entity"] = update_entity_cb

    # WebSocket-команды для карточки
    _register_websocket_handlers(hass, update_entity_cb)

    # Первый прогон: публикуем то, что загрузили из JSON
    update_entity_cb()

    _LOGGER.info("✅ Zone Manager инициализирован (YAML)")

    # ============ Сервис: update_zone ============
    async def handle_update_zone(call: ServiceCall) -> None:
        """Обработчик сервиса update_zone."""
        space = call.data.get("space", "space_1")
        sensor_id = call.data.get("sensor_id")
        zone_config = call.data.get("zone_config", {})

        if not sensor_id:
            _LOGGER.error("❌ Сервис update_zone: отсутствует sensor_id")
            return

        success = zone_manager.add_or_update_zone(space, sensor_id, zone_config)

        if success:
            await zone_manager.save_config()
            _LOGGER.info(
                "🔄 Сервис update_zone выполнен: %s/%s", space, sensor_id
            )
            # 🔁 ОБНОВЛЯЕМ ENTITY
            update_entity_cb()
        else:
            _LOGGER.error(
                "❌ Сервис update_zone: ошибка валидации %s/%s",
                space,
                sensor_id,
            )

    # ============ Сервис: delete_zone ============
    async def handle_delete_zone(call: ServiceCall) -> None:
        """Обработчик сервиса delete_zone."""
        space = call.data.get("space", "space_1")
        sensor_id = call.data.get("sensor_id")

        if not sensor_id:
            _LOGGER.error("❌ Сервис delete_zone: отсутствует sensor_id")
            return

        success = zone_manager.delete_zone(space, sensor_id)

        if success:
            await zone_manager.save_config()
            _LOGGER.info(
                "🔄 Сервис delete_zone выполнен: %s/%s", space, sensor_id
            )
            # 🔁 ОБНОВЛЯЕМ ENTITY ПОСЛЕ УДАЛЕНИЯ
            update_entity_cb()
        else:
            _LOGGER.error(
                "❌ Сервис delete_zone: зона не найдена %s/%s",
                space,
                sensor_id,
            )

    # ============ Сервис: get_zone ============
    async def handle_get_zone(call: ServiceCall) -> None:
        """Обработчик сервиса get_zone."""
        sensor_id = call.data.get("sensor_id")

        if not sensor_id:
            _LOGGER.error("❌ Сервис get_zone: отсутствует sensor_id")
            return

        zone_data = zone_manager.get_zone_by_sensor(sensor_id)

        if zone_data:
            _LOGGER.debug("✅ Сервис get_zone: найдена %s", sensor_id)
        else:
            _LOGGER.warning("⚠️ Сервис get_zone: %s не найдена", sensor_id)

    # ============ Регистрация сервисов ============
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_ZONE,
        handle_update_zone,
        schema=UPDATE_ZONE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_ZONE,
        handle_delete_zone,
        schema=DELETE_ZONE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ZONE,
        handle_get_zone,
        schema=GET_ZONE_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Инициализация интеграции через Config Flow (UI)."""
    global zone_manager

    hass.data.setdefault(DOMAIN, {})

    if zone_manager is None:
        _LOGGER.info("🚀 Инициализация Zone Manager (Config Entry)...")
        zone_manager = ZoneManager(hass)
        await zone_manager.load_config()
        hass.data[DOMAIN]["manager"] = zone_manager

        @callback
        def update_entity_cb() -> None:
            _update_zones_entity(hass, zone_manager)

        hass.data[DOMAIN]["update_entity"] = update_entity_cb

        # Первый прогон entity
        update_entity_cb()

        # WebSocket-команды для карточки (Config Flow)
        _register_websocket_handlers(hass, update_entity_cb)

    _LOGGER.info(
        "✅ Zone Manager Config Entry инициализирован: %s", entry.title
    )
    return True

