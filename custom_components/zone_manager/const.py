"""Constants for Zone Manager integration (v0.1)."""

DOMAIN = "zone_manager"

CONF_CONFIG_PATH = "config_path"

DEFAULT_CONFIG_FILENAME = "zone_manager.json"

# Версия внутреннего формата JSON (для будущих миграций)
DATA_VERSION = "v0.1"

# Поля зоны (минимум под вашу схему)
ZONE_FIELDS_LISTS = (
    "neighbors",
    "far_neighbors",
    "neighbor_groups",
    "light_group",
)
