"""Константы для Zone Manager интеграции."""

DOMAIN = "zone_manager"
ZONES_CONFIG_FILE = "zones_config.json"  # Имя JSON файла в /config
DEFAULT_ZONES_CONFIG = {
    "space_1": {},  # Пустая структура по умолчанию
}

# Ключи в JSON
KEY_ZONE_NAME = "zone_name"
KEY_NEIGHBORS = "neighbors"
KEY_LIGHT_GROUP = "light_group"
KEY_FAR_NEIGHBORS = "far_neighbors"
KEY_NEIGHBOR_GROUPS = "neighbor_groups"

# Сервисы
SERVICE_UPDATE_ZONE = "update_zone"
SERVICE_DELETE_ZONE = "delete_zone"
SERVICE_GET_ZONE = "get_zone"

# -------- Новое: параметры хранилища .storage для карточек --------
STORAGE_KEY_CARD = "zone_manager_card_config"  # имя файла в .storage
STORAGE_VERSION_CARD = 1                      # версия формата

