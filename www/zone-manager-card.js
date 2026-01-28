/*
  Zone Manager Lovelace Card
  Version: 2.1.4
*/

const ZM_CARD_VERSION = "2.1.4";
console.info("[zone_manager-card] version", ZM_CARD_VERSION);

// Вместо `import ... from "lit"` берём LitElement/html/css из фронтенда Home Assistant.
// Зачем: HA не умеет резолвить "lit" как npm-модуль без сборки.
const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

const WS = {
  spacesList: "zone_manager/spaces_list",
  spaceGet: "zone_manager/space_get",
  spaceCreate: "zone_manager/space_create",
  spaceDelete: "zone_manager/space_delete",
  spaceSave: "zone_manager/space_save",
  areasList: "zone_manager/areas_list",
  entitiesForArea: "zone_manager/entities_for_area",
};

// Sentinel значения для UI (нельзя использовать пустую строку, иначе label не "флоатит" и накладывается на value)
const UI_ALL_AREAS = "__all__";
// Sentinel для "пустого выбора" в любых ha-select (иначе label может накладываться на value при value="")
const UI_NONE = "__none__";


class ZoneManagerCard extends LitElement {
  static get properties() {
    return {
      hass: {},
      _config: {},
      _spaces: { state: true },
      _selectedSpace: { state: true },
      _spaceDraft: { state: true },

      _areas: { state: true },
      _areaFilter: { state: true },

      _entitiesSensors: { state: true },
      _entitiesLights: { state: true },

      _addingSpace: { state: true },
      _newSpaceName: { state: true },

      _addingZone: { state: true },
      _newZoneSensor: { state: true },

      _busy: { state: true },

      // 2.1.0
      _dirty: { state: true },
      _errors: { state: true },

      // drag state
      _drag: { state: false },
    };
  }

  constructor() {
    super();

    this._spaces = [];
    this._selectedSpace = "";
    this._spaceDraft = null;

    this._areas = [];
    this._areaFilter = UI_ALL_AREAS;

    this._entitiesSensors = [];
    this._entitiesLights = [];

    this._addingSpace = false;
    this._newSpaceName = "";

    this._addingZone = false;
    this._newZoneSensor = "";

    this._busy = false;

    this._dirty = false;
    this._errors = [];

    this._drag = { zone: null, fromIndex: null };
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    const prev = this._hass;
    this._hass = hass;

    // Первый раз: загрузим данные
    if (!prev && hass) {
      this._log("First hass set -> initial load");
      this._initialLoad();
    }
  }

  get hass() {
    return this._hass;
  }

  static get styles() {
    return css`
      :host { display: block; }

      /* 2.1.3 UI polish: более читаемые границы и более заметные кнопки */
      :host {
        --zm-accent: #EFCC3C;           /* фирменные кнопки */
        --zm-accent-hover: #F3D45A;     /* чуть светлее */
        --zm-danger: var(--error-color, #db3a3a);

        --zm-border: rgba(var(--rgb-primary-text-color), 0.18);
        --zm-border-strong: rgba(var(--rgb-primary-text-color), 0.28);
        --zm-surface-2: var(--secondary-background-color);
      }

      ha-card {
        /* ВАЖНО: используем тему HA, чтобы dark/light корректно отображались */
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }

      /* FIX 2.1.2: Поля ввода/селекты должны быть читаемыми в тёмной теме.
         HA использует MWC/MDC переменные. Прокидываем их из темы HA. */
      ha-select,
      ha-textfield {
        --mdc-theme-surface: var(--card-background-color);
        --mdc-theme-on-surface: var(--primary-text-color);
        --mdc-theme-primary: var(--accent-color);

        /* Текст и лейблы */
        --mdc-select-ink-color: var(--primary-text-color);
        --mdc-select-label-ink-color: var(--secondary-text-color);

        --mdc-text-field-ink-color: var(--primary-text-color);
        --mdc-text-field-label-ink-color: var(--secondary-text-color);

        /* Фон инпута (в тёмной теме должен быть не белым) */
        --mdc-text-field-fill-color: var(--secondary-background-color);

        /* Линии/границы */
        --mdc-text-field-idle-line-color: var(--divider-color);
        --mdc-text-field-hover-line-color: var(--primary-text-color);
        --mdc-text-field-focused-line-color: var(--accent-color);
      }

      .header {
        background: #181923;
        color: #ffffff;
        padding: 12px 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }

      .header-title {
        font-weight: 700;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .header-title small {
        font-weight: 400;
        opacity: 0.9;
      }

      .header-actions {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      .btn {
        background: var(--zm-accent);
        color: #212120;
        border: 1px solid rgba(0,0,0,0.18);
        padding: 8px 12px;
        border-radius: 12px;
        cursor: pointer;
        font-weight: 700;
        box-shadow: 0 1px 0 rgba(0,0,0,0.10);
        transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
      }

      .btn:hover {
        background: var(--zm-accent-hover);
        box-shadow: 0 2px 0 rgba(0,0,0,0.12);
        transform: translateY(-1px);
      }

      .btn:active {
        transform: translateY(0px);
        box-shadow: 0 1px 0 rgba(0,0,0,0.10);
      }

      .btn[disabled] {
        opacity: 0.55;
        cursor: not-allowed;
        transform: none;
        box-shadow: none;
      }

      .content {
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .row {
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
      }

      .row > * { min-width: 220px; }

      .muted { opacity: 0.8; }

      .section {
        border: 1px solid var(--zm-border);
        border-radius: 14px;
        padding: 12px;
        background: rgba(var(--rgb-primary-text-color), 0.03);
      }



      .section-title {
        font-weight: 700;
        margin-bottom: 8px;
      }

      .zone {
        border: 1px solid var(--zm-border-strong);
        border-radius: 14px;
        padding: 12px;
        margin-top: 10px;
        background: rgba(var(--rgb-primary-text-color), 0.02);
        display: flex;
        flex-direction: column;
        gap: 10px;
      }



      .zone-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
      }

      .zone-header .key {
        font-weight: 700;
        word-break: break-all;
      }

      .mini-btn {
        background: var(--zm-surface-2);
        color: var(--primary-text-color);
        border: 1px solid var(--zm-border);
        padding: 7px 10px;
        border-radius: 12px;
        cursor: pointer;
        font-weight: 700;
        box-shadow: 0 1px 0 rgba(0,0,0,0.06);
        transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
      }

      .mini-btn:hover {
        border-color: var(--zm-border-strong);
        box-shadow: 0 2px 0 rgba(0,0,0,0.08);
        transform: translateY(-1px);
      }

      .mini-btn:active {
        transform: translateY(0px);
        box-shadow: 0 1px 0 rgba(0,0,0,0.06);
      }

      .mini-btn[disabled] {
        opacity: 0.55;
        cursor: not-allowed;
        transform: none;
        box-shadow: none;
      }

      /* Акцентные маленькие кнопки: + / Добавить */
      .mini-btn.primary {
        background: var(--zm-accent);
        color: #212120;
        border-color: rgba(0,0,0,0.18);
      }

      .mini-btn.primary:hover {
        background: var(--zm-accent-hover);
      }

      /* Опасные действия: удалить / X */
      .mini-btn.danger {
        background: rgba(var(--rgb-error-color), 0.12);
        border-color: rgba(var(--rgb-error-color), 0.35);
        color: var(--primary-text-color);
      }

      .mini-btn.danger:hover {
        background: rgba(var(--rgb-error-color), 0.18);
        border-color: rgba(var(--rgb-error-color), 0.50);
      }


      .hint { font-size: 12px; opacity: 0.75; }

      /* Errors */
      .errors {
        border: 1px solid rgba(var(--rgb-error-color), 0.45);
        background: rgba(var(--rgb-error-color), 0.10);
        border-radius: 12px;
        padding: 10px;
        color: var(--primary-text-color);
      }

      .errors-title {
        font-weight: 800;
        margin-bottom: 6px;
      }

      .errors ul {
        margin: 0;
        padding-left: 18px;
      }

      .field-error {
        outline: 2px solid rgba(255,0,0,0.35);
        border-radius: 10px;
        padding: 6px;
      }

      /* Pair rows */
      .pair-table {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .pair-row {
        padding: 8px;
        border-radius: 12px;
        border: 1px solid var(--zm-border);
        background: rgba(var(--rgb-primary-text-color), 0.02);
      }

      .pair-row:hover {
        border-color: var(--zm-border-strong);
      }

      .pair-row[draggable="true"] {
        cursor: grab;
      }

      .drag-handle {
        width: 24px;
        min-width: 24px;
        text-align: center;
        opacity: 0.75;
        user-select: none;
      }

      .pair-row ha-select {
        flex: 1;
        min-width: 220px;
      }

      .pair-row .xbtn {
        min-width: auto;
      }

      .small-note {
        font-size: 12px;
        opacity: 0.75;
      }
    `;
  }

  render() {
    const spaceName = this._selectedSpace || "—";
    return html`
      <ha-card>
        <div class="header">
          <div class="header-title">
            <div>Zone Manager</div>
            <small>
              Space: ${spaceName}
              ${this._dirty ? html` • <span style="color:#EFCC3C;">Несохранённые изменения</span>` : html``}
            </small>
          </div>

          <div class="header-actions">
            <button class="btn" ?disabled=${this._busy || !this._dirty} @click=${this._onSave}>Сохранить</button>
            <button class="btn" ?disabled=${this._busy} @click=${this._onRefresh}>Обновить</button>
          </div>
        </div>

        <div class="content">
          ${this._renderErrors()}
          ${this._renderSpaceControls()}
          ${this._renderAreaFilter()}
          ${this._renderSpaceEditor()}
        </div>
      </ha-card>
    `;
  }

  _renderErrors() {
    if (!Array.isArray(this._errors) || this._errors.length === 0) return html``;

    return html`
      <div class="errors">
        <div class="errors-title">Ошибки валидации (${this._errors.length})</div>
        <ul>
          ${this._errors.map((e) => html`<li>${this._formatError(e)}</li>`)}
        </ul>
      </div>
    `;
  }

  _formatError(e) {
    const zone = e?.zone || "";
    const field = e?.field || "";
    const idx = Number.isInteger(e?.index) ? `[${e.index}]` : "";

    const fieldRuMap = {
      zone_key: "Ключ зоны (zone_key)",
      neighbors: "Соседи (neighbors)",
      far_neighbors: "Дальние соседи (far_neighbors)",
      neighbor_groups: "Группы соседнего света (neighbor_groups)",
      light_group: "Основная группа света (light_group)",
      space: "Пространство (space)",
      save: "Сохранение (save)",
      refresh: "Обновление (refresh)",
      filter: "Фильтр (filter)",
    };

    const code = e?.code || "";
    let text = "";

    if (code === "self_reference") {
      text = "Ключ зоны не может присутствовать в этом списке";
    } else if (code === "duplicate") {
      text = "Дубликат значения в списке";
    } else if (code === "length_mismatch") {
      text = "Длина списка должна совпадать с длиной neighbors";
    } else if (code === "exists") {
      text = "Зона с таким ключом уже существует";
    } else if (code === "create_failed") {
      text = "Не удалось создать пространство";
    } else if (code === "delete_failed") {
      text = "Не удалось удалить пространство";
    } else if (code === "load_failed") {
      text = "Не удалось загрузить пространство";
    } else if (code === "entities_failed") {
      text = "Не удалось загрузить список сущностей";
    } else if (code === "save_failed") {
      text = "Не удалось сохранить (ошибка WebSocket)";
    } else if (code === "refresh_failed") {
      text = "Не удалось обновить данные";
    } else if (code === "validation_failed") {
      text = "Валидация не пройдена";
    } else if (e?.text) {
      // fallback на текст backend (entity_id не трогаем)
      text = e.text;
    } else {
      text = "Ошибка";
    }

    const extra =
      code === "length_mismatch"
        ? ` (ожидалось ${e.expected}, фактически ${e.actual})`
        : "";

    const fieldRu = fieldRuMap[field] || field;

    return `${zone} → ${fieldRu}${idx}: ${text}${extra}`;
  }


  _renderSpaceControls() {
    return html`
      <div class="section">
        <div class="section-title">Пространства</div>

        <div class="row">
          <ha-select
            .label=${"Выбор пространства"}
            .value=${this._selectedSpace || UI_NONE}
            @selected=${this._onSelectSpace}
          >
            <mwc-list-item .value=${UI_NONE}>—</mwc-list-item>
            ${this._spaces.map(
              (s) => html`<mwc-list-item .value=${s.name}>${s.name} (${s.zones_count})</mwc-list-item>`
            )}
          </ha-select>

          <button class="mini-btn primary" ?disabled=${this._busy} @click=${this._toggleAddSpace}>
            ${this._addingSpace ? "Отмена" : "Добавить пространство"}
          </button>

          ${this._selectedSpace
            ? html`<button class="mini-btn danger" ?disabled=${this._busy} @click=${this._onDeleteSpace}>Удалить пространство</button>`
            : html``}
        </div>

        ${this._addingSpace
          ? html`
              <div class="row" style="margin-top:10px;">
                <ha-textfield
                  .label=${"Имя пространства"}
                  .value=${this._newSpaceName}
                  @input=${(e) => (this._newSpaceName = e.target.value)}
                ></ha-textfield>
                <button class="btn" ?disabled=${this._busy || !this._newSpaceName.trim()} @click=${this._onCreateSpace}>
                  Создать
                </button>
              </div>
            `
          : html``}
      </div>
    `;
  }

  _renderAreaFilter() {
    return html`
      <div class="section">
        <div class="section-title">Фильтр</div>
        <div class="row">
          <ha-select
            .label=${"Area (фильтр UI)"}
            .value=${this._areaFilter}
            @selected=${this._onSelectArea}
          >
            <mwc-list-item .value=${UI_ALL_AREAS}>Все area</mwc-list-item>
            ${this._areas.map(
              (a) => html`<mwc-list-item .value=${a.id}>${a.name}</mwc-list-item>`
            )}
          </ha-select>

          <div class="hint">
            Area фильтрует списки сущностей ниже, но не сохраняется в JSON.
          </div>
        </div>
      </div>
    `;
  }

  _renderSpaceEditor() {
    if (!this._spaceDraft || !this._selectedSpace) {
      return html`<div class="muted">Выберите пространство для редактирования.</div>`;
    }

    const zones = (this._spaceDraft.zones || {});
    const zoneKeys = Object.keys(zones);

    return html`
      <div class="section">
        <div class="section-title">Зоны</div>

        <div class="row">
          <button class="mini-btn primary" ?disabled=${this._busy} @click=${this._toggleAddZone}>
            ${this._addingZone ? "Отмена" : "Добавить зону"}
          </button>

          ${this._addingZone
            ? html`
                <ha-select
                  .label=${"Sensor entity_id (ключ зоны)"}
                  .value=${this._newZoneSensor || UI_NONE}
                  @selected=${(e) => (this._newZoneSensor = (e.target.value === UI_NONE ? "" : e.target.value))}
                >
                  <mwc-list-item .value=${UI_NONE}>Выберите датчик...</mwc-list-item>
                  ${this._entitiesSensors.map(
                    (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
                  )}
                </ha-select>

                <button class="btn" ?disabled=${this._busy || !this._newZoneSensor} @click=${this._onAddZone}>
                  Добавить
                </button>
              `
            : html``}
        </div>

        ${zoneKeys.length === 0
          ? html`<div class="muted">Зоны отсутствуют.</div>`
          : zoneKeys.map((zk) => this._renderZone(zk, zones[zk]))}
      </div>
    `;
  }

  _renderZone(zoneKey, zoneObj) {
    const z = zoneObj || {};

    const hasErrNeighbors = this._hasFieldError(zoneKey, "neighbors");
    const hasErrFar = this._hasFieldError(zoneKey, "far_neighbors");
    const hasErrGroups = this._hasFieldError(zoneKey, "neighbor_groups");

    return html`
      <div class="zone">
        <div class="zone-header">
          <div class="key">${zoneKey}</div>
          <button class="mini-btn danger" ?disabled=${this._busy} @click=${() => this._onDeleteZone(zoneKey)}>Удалить зону</button>
        </div>

        <div class="row">
          <ha-select
            .label=${"Датчик зоны (ключ)"}
            .value=${zoneKey}
            @selected=${(e) => this._onRenameZoneKey(zoneKey, e.target.value)}
          >
            ${this._entitiesSensors.map(
              (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
            )}
          </ha-select>
          <div class="small-note">
            Порядок строк важен: пары обрабатываются по индексу.
          </div>
        </div>

        <div class=${this._cx({
          "field-error": (hasErrNeighbors || hasErrFar || hasErrGroups),
        })}>
          <div class="section-title">Pairs: neighbors ↔ far_neighbors ↔ neighbor_groups</div>
          ${this._renderPairRows(zoneKey, z)}
        </div>

        <div class=${this._cx({ "field-error": this._hasFieldError(zoneKey, "light_group") })}>
          ${this._renderSingleList(
            "Основная группа света (light)",
            z.light_group,
            this._entitiesLights,
            (newArr) => this._setZoneField(zoneKey, "light_group", newArr)
          )}
        </div>
      </div>
    `;
  }

  _renderPairRows(zoneKey, z) {
    const neighbors = Array.isArray(z.neighbors) ? [...z.neighbors] : [];
    const far = Array.isArray(z.far_neighbors) ? [...z.far_neighbors] : [];
    const groups = Array.isArray(z.neighbor_groups) ? [...z.neighbor_groups] : [];

    // Приводим массивы к одинаковой длине UI-образом (ориентир neighbors)
    // Backend всё равно валидирует, но UI не должен мешать.
    const len = neighbors.length;
    while (far.length < len) far.push("");
    while (groups.length < len) groups.push("");
    if (far.length > len) far.length = len;
    if (groups.length > len) groups.length = len;

    const setRow = (idx, field, value) => {
      if (field === "neighbors") neighbors[idx] = value;
      if (field === "far_neighbors") far[idx] = value;
      if (field === "neighbor_groups") groups[idx] = value;

      this._applyPairs(zoneKey, neighbors, far, groups);
    };

    const addRow = () => {
      neighbors.push("");
      far.push("");
      groups.push("");
      this._applyPairs(zoneKey, neighbors, far, groups);
    };

    const removeRow = (idx) => {
      neighbors.splice(idx, 1);
      far.splice(idx, 1);
      groups.splice(idx, 1);
      this._applyPairs(zoneKey, neighbors, far, groups);
    };

    const onDragStart = (idx) => {
      this._drag = { zone: zoneKey, fromIndex: idx };
    };

    const onDrop = (toIndex) => {
      if (this._drag.zone !== zoneKey) return;
      const fromIndex = this._drag.fromIndex;
      if (fromIndex === null || fromIndex === undefined) return;
      if (fromIndex === toIndex) return;

      const move = (arr) => {
        const item = arr.splice(fromIndex, 1)[0];
        arr.splice(toIndex, 0, item);
      };

      move(neighbors);
      move(far);
      move(groups);

      this._drag = { zone: null, fromIndex: null };
      this._applyPairs(zoneKey, neighbors, far, groups);
    };

    const allowDrop = (ev) => {
      ev.preventDefault();
    };

    const rowHasError = (idx) => {
      return this._errors.some((e) => e?.zone === zoneKey && Number.isInteger(e?.index) && e.index === idx);
    };

    return html`
      <div class="pair-table">
        ${neighbors.map((_, idx) => html`
          <div
            class=${this._cx({ "pair-row": true, "field-error": rowHasError(idx) })}
            draggable="true"
            @dragstart=${() => onDragStart(idx)}
            @dragover=${allowDrop}
            @drop=${() => onDrop(idx)}
          >
            <div class="drag-handle">☰</div>

            <ha-select
              .label=${"Сосед (sensor)"}
              .value=${neighbors[idx] || UI_NONE}
              @selected=${(e) => setRow(idx, "neighbors", (e.target.value === UI_NONE ? "" : e.target.value))}
            >
              <mwc-list-item .value=${UI_NONE}>Выберите...</mwc-list-item>
              ${this._entitiesSensors.map(
                (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
              )}
            </ha-select>

            <ha-select
              .label=${"Дальний сосед (sensor)"}
              .value=${far[idx] || UI_NONE}
              @selected=${(e) => setRow(idx, "far_neighbors", (e.target.value === UI_NONE ? "" : e.target.value))}
            >
              <mwc-list-item .value=${UI_NONE}>Выберите...</mwc-list-item>
              ${this._entitiesSensors.map(
                (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
              )}
            </ha-select>

            <ha-select
              .label=${"Группа соседнего света (light)"}
              .value=${groups[idx] || UI_NONE}
              @selected=${(e) => setRow(idx, "neighbor_groups", (e.target.value === UI_NONE ? "" : e.target.value))}
            >
              <mwc-list-item .value=${UI_NONE}>Выберите...</mwc-list-item>
              ${this._entitiesLights.map(
                (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
              )}
            </ha-select>

            <button class="mini-btn danger xbtn" ?disabled=${this._busy} @click=${() => removeRow(idx)}>X</button>
          </div>
        `)}

        <button class="mini-btn primary" ?disabled=${this._busy} @click=${addRow}>+</button>
      </div>
    `;
  }

  _applyPairs(zoneKey, neighbors, far, groups) {
    const zones = { ...(this._spaceDraft.zones || {}) };
    const zone = { ...(zones[zoneKey] || {}) };

    zone.neighbors = Array.isArray(neighbors) ? neighbors : [];
    zone.far_neighbors = Array.isArray(far) ? far : [];
    zone.neighbor_groups = Array.isArray(groups) ? groups : [];

    zones[zoneKey] = zone;
    this._spaceDraft = { ...this._spaceDraft, zones };

    this._markDirty();
  }

  _renderSingleList(label, arr, options, onChange) {
    const list = Array.isArray(arr) ? [...arr] : [];

    const addRow = () => {
      list.push("");
      onChange(list);
    };

    const setAt = (idx, val) => {
      list[idx] = val;
      onChange(list);
    };

    const removeAt = (idx) => {
      list.splice(idx, 1);
      onChange(list);
    };

    return html`
      <div>
        <div class="section-title">${label}</div>
        <div style="display:flex; flex-direction:column; gap:8px;">
          ${list.map(
            (val, idx) => html`
              <div style="display:flex; gap:8px; align-items:center;">
                <ha-select
                  .label=${label}
                  .value=${val || UI_NONE}
                  @selected=${(e) => setAt(idx, (e.target.value === UI_NONE ? "" : e.target.value))}
                >
                  <mwc-list-item .value=${UI_NONE}>Выберите...</mwc-list-item>
                  ${options.map(
                    (en) => html`<mwc-list-item .value=${en.entity_id}>${en.entity_id}</mwc-list-item>`
                  )}
                </ha-select>
                <button class="mini-btn danger" ?disabled=${this._busy} @click=${() => removeAt(idx)}>X</button>
              </div>
            `
          )}
          <button class="mini-btn primary" ?disabled=${this._busy} @click=${addRow}>+</button>
        </div>
      </div>
    `;
  }

  // -----------------------
  // Data operations
  // -----------------------

  async _initialLoad() {
    try {
      this._busy = true;
      await this._loadSpaces();
      await this._loadAreas();
      await this._loadEntitiesForArea(""); // all
    } finally {
      this._busy = false;
    }
  }

  async _loadSpaces() {
    const res = await this.hass.callWS({ type: WS.spacesList });
    this._spaces = res.spaces || [];
    this._log("Spaces loaded:", this._spaces);
  }

  async _loadAreas() {
    const res = await this.hass.callWS({ type: WS.areasList });
    this._areas = res.areas || [];
    this._log("Areas loaded:", this._areas.length);
  }

  async _loadEntitiesForArea(areaId) {
    const msg = { type: WS.entitiesForArea, area_id: areaId || null, domains: ["sensor", "light"] };
    const res = await this.hass.callWS(msg);
    const entities = res.entities || [];

    this._entitiesSensors = entities.filter((e) => e.domain === "sensor");
    this._entitiesLights = entities.filter((e) => e.domain === "light");

    this._log("Entities loaded:", { sensors: this._entitiesSensors.length, lights: this._entitiesLights.length });
  }

  async _loadSpace(spaceName) {
    const res = await this.hass.callWS({ type: WS.spaceGet, space: spaceName });
    this._spaceDraft = res.data || { zones: {} };

    // Сбрасываем состояния UI
    this._dirty = false;
    this._errors = [];
  }

  // -----------------------
  // Handlers
  // -----------------------

  _toggleAddSpace() {
    this._addingSpace = !this._addingSpace;
    this._newSpaceName = "";
  }

  async _onCreateSpace() {
    const name = (this._newSpaceName || "").trim();
    if (!name) return;

    try {
      this._busy = true;
      await this.hass.callWS({ type: WS.spaceCreate, space: name });
      await this._loadSpaces();
      this._selectedSpace = name;
      await this._loadSpace(name);
      this._addingSpace = false;
      this._newSpaceName = "";
    } catch (e) {
      this._log("Create space error:", e);
      this._errors = [{ zone: "", field: "space", code: "create_failed", text: "Failed to create space" }];
    } finally {
      this._busy = false;
    }
  }

  async _onDeleteSpace() {
    if (!this._selectedSpace) return;
    const ok = confirm(`Удалить пространство "${this._selectedSpace}"?`);
    if (!ok) return;

    try {
      this._busy = true;
      await this.hass.callWS({ type: WS.spaceDelete, space: this._selectedSpace });
      this._selectedSpace = "";
      this._spaceDraft = null;
      this._dirty = false;
      this._errors = [];
      await this._loadSpaces();
    } catch (e) {
      this._log("Delete space error:", e);
      this._errors = [{ zone: "", field: "space", code: "delete_failed", text: "Failed to delete space" }];
    } finally {
      this._busy = false;
    }
  }

  async _onSelectSpace(e) {
    const space = e.target.value;
    if (!space || space === UI_NONE)  {
    // Сброс выбора
    this._selectedSpace = "";
    this._spaceDraft = null;
    this._dirty = false;
    this._errors = [];
    return;
    }

    try {
      this._busy = true;
      this._selectedSpace = space;
      await this._loadSpace(space);
    } catch (err) {
      this._log("Select space error:", err);
      this._errors = [{ zone: "", field: "space", code: "load_failed", text: "Failed to load space" }];
    } finally {
      this._busy = false;
    }
  }

  async _onSelectArea(e) {
    const areaId = e.target.value || UI_ALL_AREAS;
    // UI хранит выбранное значение как есть (включая sentinel)
    this._areaFilter = areaId;

    // Для backend: sentinel трактуем как "нет фильтра"
    const backendAreaId = (areaId === UI_ALL_AREAS) ? "" : areaId;

    try {
      this._busy = true;
      await this._loadEntitiesForArea(backendAreaId);
    } catch (err) {
      this._log("Select area error:", err);
      this._errors = [{ zone: "", field: "filter", code: "entities_failed", text: "Failed to load entities" }];
    } finally {
      this._busy = false;
    }
  }

  _toggleAddZone() {
    this._addingZone = !this._addingZone;
    this._newZoneSensor = "";
  }

  _onAddZone() {
    const sensorId = this._newZoneSensor;
    if (!sensorId) return;

    const zones = this._spaceDraft?.zones || {};
    if (zones[sensorId]) {
      this._errors = [{ zone: sensorId, field: "zone_key", code: "exists", text: "Zone with this key already exists" }];
      return;
    }

    zones[sensorId] = {
      neighbors: [],
      far_neighbors: [],
      neighbor_groups: [],
      light_group: [],
    };

    this._spaceDraft = { ...this._spaceDraft, zones: { ...zones } };
    this._addingZone = false;
    this._newZoneSensor = "";
    this._markDirty();
  }

  _onDeleteZone(zoneKey) {
    const zones = { ...(this._spaceDraft.zones || {}) };
    delete zones[zoneKey];
    this._spaceDraft = { ...this._spaceDraft, zones };
    this._markDirty();
  }

  _onRenameZoneKey(oldKey, newKey) {
    if (!newKey || oldKey === newKey) return;

    const zones = { ...(this._spaceDraft.zones || {}) };
    if (zones[newKey]) {
      this._errors = [{ zone: oldKey, field: "zone_key", code: "exists", text: "Zone with this key already exists" }];
      return;
    }

    const payload = zones[oldKey];
    delete zones[oldKey];
    zones[newKey] = payload;

    this._spaceDraft = { ...this._spaceDraft, zones };
    this._markDirty();
  }

  _setZoneField(zoneKey, field, newArr) {
    const zones = { ...(this._spaceDraft.zones || {}) };
    const zone = { ...(zones[zoneKey] || {}) };

    zone[field] = Array.isArray(newArr) ? newArr : [];
    zones[zoneKey] = zone;

    this._spaceDraft = { ...this._spaceDraft, zones };
    this._markDirty();
  }

  _markDirty() {
    this._dirty = true;
    // при правках убираем старые ошибки, чтобы не “залипали”
    this._errors = [];
  }

  async _onSave() {
    if (!this._selectedSpace || !this._spaceDraft) return;

    try {
      this._busy = true;

      const res = await this.hass.callWS({
        type: WS.spaceSave,
        space: this._selectedSpace,
        data: this._spaceDraft,
      });

      if (res?.ok === false) {
        // Ошибки валидации от backend
        this._errors = Array.isArray(res.errors) ? res.errors : [{ zone: "", field: "save", code: "validation_failed", text: "Validation failed" }];
        return;
      }

      // ok: true
      await this._loadSpaces();
      this._dirty = false;
      this._errors = [];

    } catch (err) {
      this._log("Save error:", err);
      this._errors = [{ zone: "", field: "save", code: "save_failed", text: "Failed to save (WS error)" }];
    } finally {
      this._busy = false;
    }
  }

  async _onRefresh() {
    if (!this._selectedSpace) return;

    try {
      this._busy = true;
      await this._loadSpace(this._selectedSpace); // overwrite draft
      // без alert
    } catch (err) {
      this._log("Refresh error:", err);
      this._errors = [{ zone: "", field: "refresh", code: "refresh_failed", text: "Failed to refresh" }];
    } finally {
      this._busy = false;
    }
  }

  _hasFieldError(zoneKey, field) {
    return Array.isArray(this._errors) && this._errors.some((e) => e?.zone === zoneKey && e?.field === field);
  }

  _cx(obj) {
    return Object.entries(obj)
      .filter(([_, v]) => !!v)
      .map(([k]) => k)
      .join(" ");
  }

  _log(...args) {
    // eslint-disable-next-line no-console
    console.debug("[zone_manager-card]", ...args);
  }

  // Card Picker metadata
  static getStubConfig() {
    return { type: "custom:zone-manager-card" };
  }
}

customElements.define("zone-manager-card", ZoneManagerCard);

// Регистрация в Card Picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "zone-manager-card",
  name: "Zone Manager",
  description: "Редактор пространств и зон (zone_manager) — 2.1.4",
});
