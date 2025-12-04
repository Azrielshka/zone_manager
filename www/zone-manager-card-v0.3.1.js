// ============================================================================
// Zone Manager Card v0.3.0
// Карточка управления зонами освещения для одного пространства.
// Работает ТОЛЬКО через WebSocket API интеграции zone_manager:
//  - zone_manager/get_space_config
//  - zone_manager/save_space_config
//
// Никаких чтений entity, никакого браузерного кэша.
// ============================================================================

class ZoneManagerCard extends HTMLElement {
  constructor() {
    super();

    // Текущая конфигурация Lovelace
    this._config = null;

    // Ссылка на hass (объект Home Assistant на фронте)
    this._hass = null;

    // Имя пространства, за которое отвечает карточка
    this._spaceName = "space_1";

    // Текущие данные зон пространства:
    // {
    //   "sensor.xxx": {...},
    //   "sensor.yyy": {...}
    // }
    this._zones = {};

    // Кеш списков сущностей (датчики / свет)
    this._sensors = [];
    this._lights = [];

    // Флаг загрузки (пока ждём ответ из WebSocket)
    this._loading = false;

    // Флаг, что мы уже пытались загрузить конфиг для этого пространства
    this._initialized = false;
  }

  // --------------------------------------------------------------------------
  // Конфигурация карточки (Lovelace)
  // --------------------------------------------------------------------------
  setConfig(config) {
    // config ожидается вида:
    // type: custom:zone-manager-card
    // space: "MMMM"
    if (!config) {
      throw new Error("Конфигурация карточки zone-manager-card пуста");
    }

    if (!config.space) {
      throw new Error(
        'В конфигурации zone-manager-card нужно указать "space"'
      );
    }

    this._config = config;
    this._spaceName = config.space;
  }

  // --------------------------------------------------------------------------
  // Подписка на hass: при первом появлении сразу запрашиваем зоны
  // --------------------------------------------------------------------------
set hass(hass) {
  const firstRun = !this._hass;
  this._hass = hass;

  // Первый вызов: один раз собираем списки и грузим конфиг
  if (firstRun) {
    this._refreshEntityLists();

    if (!this._initialized) {
      this._initialized = true;
      // _loadSpaceConfig сам вызовет _render() с "loading" и потом с зоной
      this._loadSpaceConfig();
    } else {
      this._render();
    }
  }

  // На последующих вызовах мы НИЧЕГО не перерисовываем.
  // _hass нужен только чтобы работать с callWS и states.
}

  // --------------------------------------------------------------------------
  // Обновление списков доступных сущностей
  // --------------------------------------------------------------------------
  _refreshEntityLists() {
    if (!this._hass) return;

    const sensors = [];
    const lights = [];

    Object.keys(this._hass.states).forEach((entityId) => {
      if (entityId.startsWith("sensor.")) {
        sensors.push(entityId);
      } else if (entityId.startsWith("light.")) {
        lights.push(entityId);
      }
    });

    this._sensors = sensors.sort();
    this._lights = lights.sort();
  }

  // --------------------------------------------------------------------------
  // Загрузка конфигурации пространства через WebSocket
  // --------------------------------------------------------------------------
async _loadSpaceConfig() {
  if (!this._hass) return;

  // Обновить списки сенсоров/света именно в момент загрузки
  this._refreshEntityLists();

  this._loading = true;
  this._render();

  console.log(
    "[ZoneManagerCard v0.3.0] Запрос конфигурации пространства через WS:",
    this._spaceName
  );

  try {
    const result = await this._hass.callWS({
      type: "zone_manager/get_space_config",
      space: this._spaceName,
    });

    const zones = (result && result.zones) || {};

    console.log(
      "[ZoneManagerCard v0.3.0] Конфигурация пространства получена:",
      { space: this._spaceName, zones }
    );

    this._zones = zones;
  } catch (err) {
    console.error(
      "[ZoneManagerCard v0.3.0] Ошибка при загрузке конфигурации пространства:",
      err
    );
    this._zones = {};
  } finally {
    this._loading = false;
    this._render();
  }
}

  // --------------------------------------------------------------------------
  // Сохранение конфигурации пространства через WebSocket
  // --------------------------------------------------------------------------
  async _saveSpaceConfig() {
    if (!this._hass) return;

    // Собираем данные из UI в свежую структуру зон
    const zonesPayload = this._collectZonesFromUI();

    console.log(
      "[ZoneManagerCard v0.3.0] Попытка сохранить конфигурацию пространства:",
      {
        space: this._spaceName,
        zones: zonesPayload,
      }
    );

    this._loading = true;
    this._render();

    try {
      const result = await this._hass.callWS({
        type: "zone_manager/save_space_config",
        space: this._spaceName,
        zones: zonesPayload,
      });

      console.log(
        "[ZoneManagerCard v0.3.0] Конфигурация пространства сохранена:",
        result
      );

      // Обновляем локальный кеш тем, что вернул сервер
      this._zones = (result && result.zones) || zonesPayload;

      alert(
        `✅ Пространство "${this._spaceName}" сохранено.\nДанные записаны в zones_config.json и .storage.`
      );
    } catch (err) {
      console.error(
        "[ZoneManagerCard v0.3.0] Ошибка при сохранении конфигурации:",
        err
      );
      alert(`❌ Ошибка при сохранении: ${err.message || err}`);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  // --------------------------------------------------------------------------
  // Сбор всех зон из DOM
  // --------------------------------------------------------------------------
  _collectZonesFromUI() {
    const zones = {};
    const root = this.shadowRoot;
    if (!root) return zones;

    const zoneBlocks = root.querySelectorAll(".zm-zone-block");

    zoneBlocks.forEach((block) => {
      const sensorInput = block.querySelector(
        'input[data-role="sensor-id-input"]'
      );
      const nameInput = block.querySelector(
        'input[data-role="zone-name-input"]'
      );

      const sensorId = sensorInput ? sensorInput.value.trim() : "";
      const zoneName = nameInput ? nameInput.value.trim() : "";

      if (!sensorId) {
        return;
      }

      // Собираем динамические поля
      const neighbors = this._collectDynamic(block, "neighbors");
      const farNeighbors = this._collectDynamic(block, "far-neighbors");
      const lightGroupArr = this._collectDynamic(block, "light-group");
      const neighborGroups = this._collectDynamic(block, "neighbor-groups");

      const lightGroup = lightGroupArr[0] || null;

      zones[sensorId] = {
        zone_name: zoneName || sensorId,
        neighbors,
        far_neighbors: farNeighbors,
        light_group: lightGroup,
        neighbor_groups: neighborGroups,
      };
    });

    return zones;
  }

  // Helper для динамических полей (массив значений селектов)
  _collectDynamic(block, key) {
    const container = block.querySelector(
      `[data-role="${key}-container"]`
    );
    if (!container) return [];
    const selects = container.querySelectorAll(`.${key}-select`);
    return Array.from(selects)
      .map((s) => s.value)
      .filter((v) => v);
  }

  // --------------------------------------------------------------------------
  // Добавление новой зоны в UI (без записи на сервер до нажатия "Сохранить")
  // --------------------------------------------------------------------------
  _addZoneBlock() {
    const root = this.shadowRoot;
    if (!root) return;

    const zonesContainer = root.querySelector("#zones-container");
    if (!zonesContainer) return;

    const block = this._createZoneBlock(null, null);
    zonesContainer.appendChild(block);

    console.log(
      "[ZoneManagerCard v0.3.0] Добавлен новый блок зоны в UI",
      block
    );
  }

  // --------------------------------------------------------------------------
  // Удаление блока зоны из UI (без немедленного вызова backend)
  // --------------------------------------------------------------------------
  _deleteZoneBlock(blockElement) {
    if (!blockElement) return;

    if (
      !confirm(
        "⚠️ Удалить эту зону из конфигурации?\nИз файла zones_config.json она будет удалена только после сохранения."
      )
    ) {
      return;
    }

    try {
      if (blockElement.parentElement) {
        blockElement.parentElement.removeChild(blockElement);
      }
    } catch (err) {
      console.error(
        "[ZoneManagerCard v0.3.0] Ошибка при удалении блока зоны из UI:",
        err
      );
    }
  }

  // --------------------------------------------------------------------------
  // Основной рендер карточки
  // --------------------------------------------------------------------------
  _render() {
    if (!this._config || !this._hass) {
      return;
    }

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    const root = this.shadowRoot;

    // Очистка
    while (root.firstChild) {
      root.removeChild(root.firstChild);
    }

    // Корневая карточка
    const card = document.createElement("ha-card");
    card.style.padding = "0";
    card.style.background = "#FFFFFF";
    card.style.color = "#212120";
    card.style.boxShadow = "0 2px 6px rgba(0,0,0,0.4)";
    card.style.borderRadius = "12px";
    card.style.overflow = "hidden";

    // ---------- Шапка ----------
    const header = document.createElement("div");
    header.style.background = "#181923";
    header.style.color = "#FFFFFF";
    header.style.padding = "8px 12px";
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.justifyContent = "space-between";

    const title = document.createElement("div");
    title.textContent = `Zone Manager – пространство: ${this._spaceName}`;
    title.style.fontWeight = "600";
    title.style.fontSize = "14px";

    const headerButtons = document.createElement("div");

    // Кнопка "Обновить" (перечитать с бэкенда)
    const reloadBtn = document.createElement("button");
    reloadBtn.textContent = "⟳ Обновить";
    reloadBtn.style.marginRight = "8px";
    reloadBtn.style.border = "none";
    reloadBtn.style.borderRadius = "8px";
    reloadBtn.style.padding = "4px 10px";
    reloadBtn.style.cursor = "pointer";
    reloadBtn.style.background = "#EFCC3C";
    reloadBtn.style.color = "#212120";
    reloadBtn.style.fontWeight = "600";
    reloadBtn.style.fontSize = "12px";
    reloadBtn.addEventListener("click", () => this._loadSpaceConfig());

    // Кнопка "Сохранить"
    const saveBtn = document.createElement("button");
    saveBtn.textContent = "💾 Сохранить";
    saveBtn.style.border = "none";
    saveBtn.style.borderRadius = "8px";
    saveBtn.style.padding = "4px 10px";
    saveBtn.style.cursor = "pointer";
    saveBtn.style.background = "#EFCC3C";
    saveBtn.style.color = "#212120";
    saveBtn.style.fontWeight = "600";
    saveBtn.style.fontSize = "12px";
    saveBtn.addEventListener("click", () => this._saveSpaceConfig());

    headerButtons.appendChild(reloadBtn);
    headerButtons.appendChild(saveBtn);

    header.appendChild(title);
    header.appendChild(headerButtons);

    // ---------- Тело карточки ----------
    const body = document.createElement("div");
    body.style.padding = "10px 12px";
    body.style.background = "#FFFFFF";
    body.style.color = "#212120";

    if (this._loading) {
      const loadingEl = document.createElement("div");
      loadingEl.textContent = "Загрузка конфигурации пространства…";
      loadingEl.style.fontSize = "13px";
      body.appendChild(loadingEl);

      card.appendChild(header);
      card.appendChild(body);
      root.appendChild(card);
      return;
    }

    // Краткая инфа
    const info = document.createElement("div");
    info.style.fontSize = "12px";
    info.style.marginBottom = "8px";
    info.textContent =
      "Каждый блок ниже — это одна зона, привязанная к датчику. " +
      "Изменения применяются только после нажатия «Сохранить».";
    body.appendChild(info);

    // Контейнер зон
    const zonesContainer = document.createElement("div");
    zonesContainer.id = "zones-container";
    body.appendChild(zonesContainer);

    const spaceZones = this._zones || {};
    const sensorIds = Object.keys(spaceZones);

    if (sensorIds.length === 0) {
      const emptyEl = document.createElement("div");
      emptyEl.style.fontSize = "12px";
      emptyEl.style.opacity = "0.7";
      emptyEl.style.marginBottom = "6px";
      emptyEl.textContent =
        "В этом пространстве пока нет ни одной зоны. Добавьте первую с помощью кнопки ниже.";
      body.appendChild(emptyEl);
    }

    sensorIds.forEach((sensorId) => {
      const zoneData = spaceZones[sensorId];
      const block = this._createZoneBlock(sensorId, zoneData);
      zonesContainer.appendChild(block);
    });

    // Кнопка "Добавить зону"
    const addBtn = document.createElement("button");
    addBtn.textContent = "➕ Добавить зону";
    addBtn.style.marginTop = "8px";
    addBtn.style.border = "none";
    addBtn.style.borderRadius = "8px";
    addBtn.style.padding = "6px 12px";
    addBtn.style.cursor = "pointer";
    addBtn.style.background = "#181923";
    addBtn.style.color = "#EFCC3C";
    addBtn.style.fontWeight = "600";
    addBtn.style.fontSize = "12px";
    addBtn.addEventListener("click", () => this._addZoneBlock());
    body.appendChild(addBtn);

    card.appendChild(header);
    card.appendChild(body);
    root.appendChild(card);
  }

  // --------------------------------------------------------------------------
  // Создание одного блока зоны (новой или существующей)
  // --------------------------------------------------------------------------
  _createZoneBlock(sensorId, zoneData) {
    const block = document.createElement("div");
    block.classList.add("zm-zone-block");
    block.style.border = "1px solid rgba(0,0,0,0.1)";
    block.style.borderRadius = "10px";
    block.style.padding = "8px";
    block.style.marginBottom = "8px";
    block.style.background = "#F7F7F7";

    // Верхняя строка: sensor_id + имя зоны + кнопка удаления
    const topRow = document.createElement("div");
    topRow.style.display = "flex";
    topRow.style.alignItems = "center";
    topRow.style.marginBottom = "6px";

    const sensorInput = document.createElement("input");
    sensorInput.type = "text";
    sensorInput.placeholder = "sensor.имя_датчика";
    sensorInput.value = sensorId || "";
    sensorInput.dataset.role = "sensor-id-input";
    sensorInput.style.flex = "0 0 40%";
    sensorInput.style.marginRight = "6px";
    sensorInput.style.fontSize = "12px";

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "Имя зоны (опционально)";
    nameInput.value = (zoneData && zoneData.zone_name) || "";
    nameInput.dataset.role = "zone-name-input";
    nameInput.style.flex = "1 1 auto";
    nameInput.style.marginRight = "6px";
    nameInput.style.fontSize = "12px";

    const delBtn = document.createElement("button");
    delBtn.textContent = "🗑";
    delBtn.title = "Удалить зону из конфигурации";
    delBtn.style.border = "none";
    delBtn.style.borderRadius = "6px";
    delBtn.style.padding = "4px 8px";
    delBtn.style.cursor = "pointer";
    delBtn.style.background = "#EFCC3C";
    delBtn.style.color = "#212120";
    delBtn.style.fontSize = "12px";
    delBtn.addEventListener("click", () => this._deleteZoneBlock(block));

    topRow.appendChild(sensorInput);
    topRow.appendChild(nameInput);
    topRow.appendChild(delBtn);

    block.appendChild(topRow);

    // Нормализуем массивы (на случай, если в JSON пришла строка вместо списка)
    const neighborsValues = this._normalizeToArray(
      zoneData && zoneData.neighbors
    );
    const farNeighborsValues = this._normalizeToArray(
      zoneData && zoneData.far_neighbors
    );
    const lightGroupValues = this._normalizeToArray(
      zoneData && zoneData.light_group
    );
    const neighborGroupsValues = this._normalizeToArray(
      zoneData && zoneData.neighbor_groups
    );

    // Соседние датчики
    block.appendChild(
      this._createDynamicField(
        "Соседние датчики *",
        "Список sensor.* соседних зон",
        "neighbors",
        this._sensors,
        neighborsValues
      )
    );

    // Дальние соседи
    block.appendChild(
      this._createDynamicField(
        "Дальние соседи *",
        "Список sensor.* дальних зон",
        "far-neighbors",
        this._sensors,
        farNeighborsValues
      )
    );

    // Основная группа светильников (1 селект, но формат всё равно массив)
    block.appendChild(
      this._createDynamicField(
        "Группа светильников *",
        "Основная группа light.*",
        "light-group",
        this._lights,
        lightGroupValues,
        true
      )
    );

    // Соседние группы светильников
    block.appendChild(
      this._createDynamicField(
        "Группы соседних светильников *",
        "Соседние light.*",
        "neighbor-groups",
        this._lights,
        neighborGroupsValues
      )
    );

    return block;
  }

  // --------------------------------------------------------------------------
  // Универсальный блок с динамическими селектами
  // --------------------------------------------------------------------------
  _createDynamicField(
    labelText,
    description,
    key,
    options,
    initialValues,
    single = false
  ) {
    const wrapper = document.createElement("div");
    wrapper.style.marginBottom = "6px";

    const label = document.createElement("div");
    label.textContent = labelText;
    label.style.fontSize = "11px";
    label.style.fontWeight = "600";
    label.style.color = "#181923";
    label.style.marginBottom = "2px";

    const desc = document.createElement("div");
    desc.textContent = description;
    desc.style.fontSize = "10px";
    desc.style.color = "#666666";
    desc.style.marginBottom = "4px";

    wrapper.appendChild(label);
    wrapper.appendChild(desc);

    const container = document.createElement("div");
    container.dataset.role = `${key}-container`;

    const values = initialValues && initialValues.length ? initialValues : [""];

    values.forEach((val) => {
      const row = this._createSelectRow(key, options, val);
      container.appendChild(row);
    });

    // Кнопка "Добавить" (если допускается несколько)
    if (!single) {
      const addBtn = document.createElement("button");
      addBtn.textContent = "Добавить";
      addBtn.type = "button";
      addBtn.style.border = "none";
      addBtn.style.borderRadius = "6px";
      addBtn.style.padding = "2px 8px";
      addBtn.style.marginTop = "4px";
      addBtn.style.cursor = "pointer";
      addBtn.style.background = "#EFCC3C";
      addBtn.style.color = "#212120";
      addBtn.style.fontSize = "10px";
      addBtn.addEventListener("click", () => {
        const row = this._createSelectRow(key, options, "");
        container.appendChild(row);
      });
      wrapper.appendChild(addBtn);
    }

    wrapper.appendChild(container);
    return wrapper;
  }

  // Одна строка с селектом и кнопкой удаления
  _createSelectRow(key, options, value) {
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.marginBottom = "4px";

    const select = document.createElement("select");
    select.classList.add(`${key}-select`);
    select.style.flex = "1 1 auto";
    select.style.fontSize = "11px";
    select.style.marginRight = "4px";

    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "-- не выбрано --";
    select.appendChild(emptyOpt);

    options.forEach((opt) => {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      select.appendChild(o);
    });

    select.value = value || "";

    const delBtn = document.createElement("button");
    delBtn.textContent = "✕";
    delBtn.type = "button";
    delBtn.style.border = "none";
    delBtn.style.borderRadius = "6px";
    delBtn.style.padding = "2px 6px";
    delBtn.style.cursor = "pointer";
    delBtn.style.background = "#181923";
    delBtn.style.color = "#EFCC3C";
    delBtn.style.fontSize = "10px";
    delBtn.addEventListener("click", () => {
      if (row.parentElement) {
        row.parentElement.removeChild(row);
      }
    });

    row.appendChild(select);
    row.appendChild(delBtn);
    return row;
  }

  // Нормализация: строка → [строка], null → [], список → как есть
  _normalizeToArray(value) {
    if (Array.isArray(value)) return value;
    if (value === null || value === undefined || value === "") return [];
    return [value];
  }

  // --------------------------------------------------------------------------
  // Lovelace metadata
  // --------------------------------------------------------------------------
  static getConfigElement() {
    // Пока собственного редактора конфигурации нет
    return null;
  }

  static getStubConfig() {
    return {
      type: "custom:zone-manager-card",
      space: "space_1",
    };
  }
}

// Регистрация Web Component для Lovelace
customElements.define("zone-manager-card", ZoneManagerCard);
// Регистрация карточки в UI Lovelace (Card Picker)
window.customCards = window.customCards || [];
window.customCards.push({
  type: "zone-manager-card",
  name: "Zone Manager Card",
  description: "Управление зонами освещения для одного пространства",
  preview: false, // можно true, если захочешь предпросмотр
});
