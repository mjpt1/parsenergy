// Translate via Django's JS catalog when available; fall back to the source string.
function T(s) { return (typeof window.gettext === 'function') ? window.gettext(s) : s; }

// One tile source for every map: our own server.
//
// Three services refused this site in turn — OpenStreetMap blocked the
// traffic, map.ir answers with an "unauthorized" watermark on this key's
// scope, and Esri returns 403 to Iranian addresses. Each refusal arrived as a
// perfectly valid image, so the map looked loaded and showed nothing useful.
//
// The browser now only ever talks to pars-tida.ir. The server fetches from
// whichever upstream it can still reach, caches the tile, and serves it. See
// apps/core/tiles.py.
// Always our own endpoint — the browser never talks to a tile service, so
// whichever of them blocks Iranian consumer networks this week stops being our
// problem. `theme` asks the server for a basemap that matches the UI; if that
// style is unreachable the server quietly falls back to a plain one.
function tileLayer() {
  const theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  const street = L.tileLayer('/core/tiles/{z}/{x}/{y}.png?theme=' + theme, {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  });
  // Every map that uses this layer also gets a "نقشه / ماهواره" switch.
  street.on('add', function (e) { addSatelliteSwitch(e.target._map, street); });
  return street;
}

function addSatelliteSwitch(map, street) {
  if (!map || map._satelliteSwitch) return;
  const satellite = L.tileLayer('/core/tiles/{z}/{x}/{y}.png?theme=satellite', {
    maxZoom: 19,
    attribution: 'تصاویر ماهواره‌ای © Google',
  });
  const layers = {};
  layers[T('نقشه')] = street;
  layers[T('ماهواره')] = satellite;
  map._satelliteSwitch = L.control.layers(layers, null, { position: 'topleft' }).addTo(map);
  // Customer wants satellite as the default view; the plain map stays one tap away.
  setTimeout(function () { map.removeLayer(street); satellite.addTo(map); }, 0);
}
window.tileLayer = tileLayer;

window.SolarOps = {
  getStoredTheme() {
    try {
      return localStorage.getItem('solarops-theme');
    } catch (e) {
      return null;
    }
  },

  setStoredTheme(theme) {
    try {
      localStorage.setItem('solarops-theme', theme);
    } catch (e) {
      // ignore storage errors
    }
  },

  applyTheme(theme, persist) {
    const root = document.documentElement;
    const body = document.body;
    const toggle = document.getElementById('themeToggle');
    const resolvedTheme = theme === 'dark' ? 'dark' : 'light';

    root.dataset.theme = resolvedTheme;
    if (body) {
      body.classList.toggle('theme-dark', resolvedTheme === 'dark');
      body.classList.toggle('theme-light', resolvedTheme === 'light');
    }

    const themeColor = resolvedTheme === 'dark' ? '#0b1218' : '#f4f7fb';
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', themeColor);
    if (toggle) {
      toggle.textContent = resolvedTheme === 'dark' ? T('حالت روز') : T('حالت شب');
    }

    // Only persist when the user explicitly chose a theme; otherwise the
    // automatic (clock-based) mode would freeze after the first page view.
    if (persist) this.setStoredTheme(resolvedTheme);
    this.refreshChartsTheme();
    this.refreshMapTiles();
    return resolvedTheme;
  },

  // Day = light (07:00–19:00), night = dark. Drives the automatic mode.
  timeBasedTheme() {
    const hour = new Date().getHours();
    return (hour >= 7 && hour < 19) ? 'light' : 'dark';
  },

  toggleTheme() {
    const currentTheme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    // A manual click pins the choice (persisted); auto mode steps aside.
    return this.applyTheme(currentTheme === 'dark' ? 'light' : 'dark', true);
  },

  initTheme() {
    const storedTheme = this.getStoredTheme();
    if (storedTheme === 'light' || storedTheme === 'dark') {
      this.applyTheme(storedTheme, false);  // honour the user's manual choice
      return;
    }
    // Automatic: follow the clock now and re-check every 5 minutes so it flips
    // at sunrise/sunset while the page stays open.
    this.applyTheme(this.timeBasedTheme(), false);
    if (!this._themeTimer) {
      this._themeTimer = setInterval(() => {
        if (!this.getStoredTheme()) this.applyTheme(this.timeBasedTheme(), false);
      }, 5 * 60 * 1000);
    }
  },

  formatNumber(value) {
    try {
      return new Intl.NumberFormat('fa-IR').format(value);
    } catch (e) {
      return String(value);
    }
  },

  getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  },

  getThemeColors() {
    const styles = getComputedStyle(document.documentElement);
    return {
      text: styles.getPropertyValue('--pe-text').trim() || '#0f172a',
      muted: styles.getPropertyValue('--pe-muted').trim() || '#475569',
      grid: styles.getPropertyValue('--pe-border').trim() || 'rgba(15, 23, 42, 0.1)',
      accent: styles.getPropertyValue('--pe-accent').trim() || '#22c55e',
      accentStrong: styles.getPropertyValue('--pe-accent-strong').trim() || '#16a34a',
    };
  },

  async fetchJson(url) {
    const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  },

  async refreshPanels() {
    await this.initAdminPanel();
    await this.initOwnerPanel();
    this.initRevenuePanels();
    this.initPlantMonitor();
    this.initPlantScreen();
    this.initAiAnalysis();
    this.initEvalWizard();
    this.initMoneyInputs();
    this.initPlantDashboard();
    this.initPlantCharts();
    this.initPvModuleGrid();
    this.initExecCharts();
    this.initAdminLocationMap();
    // Any form carrying #locationMap (request wizard, plant form, …) — the
    // helper no-ops when the element is absent or already initialised.
    this.initLocationMap();
  },

  // Smart conditional evaluation form: branch-aware step navigation +
  // province->city dependent dropdown. Steps/fields carry a `data-when`
  // attribute (space-separated tokens, OR-matched); inactive ones are hidden
  // AND their inputs disabled so they neither submit nor block validation.
  initEvalWizard() {
    const form = document.getElementById('evalForm');
    if (!form || form.dataset.wizardInit) return;
    const allSteps = Array.from(form.querySelectorAll('.wizard-step'));
    if (!allSteps.length) return;
    form.dataset.wizardInit = '1';
    this.initLocationMap();

    const label = document.getElementById('wizardLabel');
    const bar = document.getElementById('wizardBar');
    const prev = document.getElementById('wizardPrev');
    const next = document.getElementById('wizardNext');
    const submit = document.getElementById('wizardSubmit');

    // Current value of any named control. Radio/checkbox groups only count when
    // something is actually checked — falling back to the first input's value
    // would make an untouched group read as if its first option were selected.
    const fieldVal = (name) => {
      const el = form.querySelector('[name="' + name + '"]');
      if (!el) return '';
      if (el.type === 'radio' || el.type === 'checkbox') {
        const checked = form.querySelector('[name="' + name + '"]:checked');
        return checked ? checked.value : '';
      }
      return el.value;
    };
    // Conditions come from the admin-defined form builder as JSON: a list of
    // AND-groups OR'd together, e.g.
    //   [[{field:'request_type',value:'partnership'},
    //     {field:'partnership_type',value:'space'}]]
    // An empty/absent condition means "always shown".
    const parseWhen = (el) => {
      const raw = el.getAttribute('data-when');
      if (!raw) return [];
      try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    };
    const isActive = (el) => {
      const groups = parseWhen(el);
      if (!groups.length) return true;
      return groups.some((group) => (group || []).every(
        (cond) => fieldVal(cond.field) === cond.value));
    };
    // Every field any condition depends on, so we know what to re-render on.
    const conditionFields = () => {
      const names = new Set();
      form.querySelectorAll('[data-when]').forEach((el) => {
        parseWhen(el).forEach((group) => (group || []).forEach((c) => {
          if (c && c.field) names.add(c.field);
        }));
      });
      return names;
    };
    const setEnabled = (container, on) => {
      container.querySelectorAll('input, select, textarea').forEach((el) => { el.disabled = !on; });
    };

    let active = [];
    let cur = 0;

    const applyFieldConditions = (scope) => {
      scope.querySelectorAll('[data-when]').forEach((el) => {
        if (el.classList.contains('wizard-step')) return;
        const on = isActive(el);
        el.hidden = !on;
        setEnabled(el, on);
      });
    };

    const show = (i) => {
      // Recompute the active path (branch selectors may have changed).
      active = allSteps.filter(isActive);
      allSteps.forEach((s) => { if (active.indexOf(s) === -1) { s.hidden = true; setEnabled(s, false); } });
      if (i >= active.length) i = active.length - 1;
      if (i < 0) i = 0;
      cur = i;
      allSteps.forEach((s) => { s.hidden = true; });
      const step = active[cur];
      step.hidden = false;
      setEnabled(step, true);
      applyFieldConditions(step);
      if (label) label.textContent = (step.getAttribute('data-step-label') || '') + ' (' + (cur + 1) + '/' + active.length + ')';
      if (bar) bar.style.width = Math.round(((cur + 1) / active.length) * 100) + '%';
      if (prev) prev.hidden = cur === 0;
      if (next) next.hidden = cur === active.length - 1;
      if (submit) submit.hidden = cur !== active.length - 1;
      // Leaflet needs a re-measure once its (previously hidden) step is shown.
      // `show()` is a plain closure, so `this` is not SolarOps here — reach the
      // map through the object itself, or the re-measure silently never runs.
      if (SolarOps._locationMap && step.querySelector('#locationMap')) {
        setTimeout(() => SolarOps._locationMap.invalidateSize(), 60);
      }
    };

    const stepValid = () => {
      for (const el of active[cur].querySelectorAll('input, select, textarea')) {
        if (el.disabled) continue;
        if (!el.checkValidity()) { el.reportValidity(); return false; }
      }
      return true;
    };

    if (next) next.addEventListener('click', () => { if (stepValid()) show(cur + 1); });
    if (prev) prev.addEventListener('click', () => show(cur - 1));

    // Branch selectors can add/remove later steps — re-render in place.
    conditionFields().forEach((name) => {
      form.querySelectorAll('[name="' + name + '"]').forEach((el) => {
        el.addEventListener('change', () => show(cur));
      });
    });

    const dataEl = document.getElementById('cities-data');
    const province = document.getElementById('id_province');
    const city = document.getElementById('id_city');
    if (dataEl && province && city) {
      let cities = {};
      try { cities = JSON.parse(dataEl.textContent); } catch (e) { cities = {}; }
      const fill = (selected) => {
        const list = cities[province.value] || [];
        city.innerHTML = '<option value="">' + T('انتخاب کنید') + '</option>';
        list.forEach((name) => {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          if (name === selected) opt.selected = true;
          city.appendChild(opt);
        });
      };
      province.addEventListener('change', () => fill(''));
      if (province.value) fill(city.getAttribute('data-selected') || '');
    }

    show(0);
  },

  // Leaflet location picker on the request form: click/drag to set lat,lng.
  initLocationMap() {
    const el = document.getElementById('locationMap');
    if (!el || el.dataset.init || typeof L === 'undefined') return;
    el.dataset.init = '1';
    const latInput = document.getElementById('id_latitude');
    const lngInput = document.getElementById('id_longitude');
    const coords = document.getElementById('mapCoords');
    const hasInitial = latInput && latInput.value && lngInput && lngInput.value;
    const startLat = parseFloat(latInput && latInput.value) || 32.4279;  // Iran center
    const startLng = parseFloat(lngInput && lngInput.value) || 53.6880;

    const map = L.map(el).setView([startLat, startLng], hasInitial ? 13 : 5);
    // The wizard shows this step later; `show()` re-measures through this handle.
    // Without it Leaflet keeps the 0x0 size it had while the step was hidden and
    // only ever fetches a single tile, which is what made the map look dead.
    SolarOps._locationMap = map;
    tileLayer().addTo(map);

    let marker = null;
    // Ask our own endpoint for the street address; the map.ir key stays on the
    // server. A failed lookup is silent — the coordinates are the real answer.
    let lookupSeq = 0;
    const describe = (lat, lng) => {
      const seq = ++lookupSeq;
      fetch('/core/geocode/reverse/?lat=' + lat.toFixed(6) + '&lng=' + lng.toFixed(6),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((r) => r.json())
        .then((d) => {
          if (seq !== lookupSeq || !d.ok || !d.address || !coords) return;
          coords.textContent = d.address;
        })
        .catch(() => {});
    };

    const setCoords = (lat, lng) => {
      if (latInput) latInput.value = lat.toFixed(6);
      if (lngInput) lngInput.value = lng.toFixed(6);
      if (coords) coords.textContent = T('موقعیت انتخاب‌شده: ') + lat.toFixed(5) + '، ' + lng.toFixed(5);
      describe(lat, lng);
    };
    const place = (lat, lng) => {
      if (!marker) {
        marker = L.marker([lat, lng], { draggable: true }).addTo(map);
        marker.on('dragend', () => { const p = marker.getLatLng(); setCoords(p.lat, p.lng); });
      } else {
        marker.setLatLng([lat, lng]);
      }
      setCoords(lat, lng);
    };
    if (hasInitial) place(startLat, startLng);
    map.on('click', (e) => place(e.latlng.lat, e.latlng.lng));

    const btn = document.getElementById('useMyLocation');
    if (btn && navigator.geolocation) {
      btn.addEventListener('click', () => {
        navigator.geolocation.getCurrentPosition((pos) => {
          map.setView([pos.coords.latitude, pos.coords.longitude], 15);
          place(pos.coords.latitude, pos.coords.longitude);
        });
      });
    }
    setTimeout(() => map.invalidateSize(), 150);
  },

  // Read-only map on admin request detail (address/location for technical staff).
  initAdminLocationMap() {
    const el = document.getElementById('adminLocationMap');
    if (!el || el.dataset.init || typeof L === 'undefined') return;
    const lat = parseFloat(el.getAttribute('data-lat'));
    const lng = parseFloat(el.getAttribute('data-lng'));
    if (!isFinite(lat) || !isFinite(lng)) return;
    el.dataset.init = '1';
    const map = L.map(el).setView([lat, lng], 16);
    tileLayer().addTo(map);
    L.marker([lat, lng]).addTo(map);
    setTimeout(() => map.invalidateSize(), 150);
    this._adminLocationMap = map;  // so a theme switch can re-tile it
  },

  // Live thousands-separator formatting for amount inputs ([data-money]).
  // The server strips separators again, so the posted value stays clean.
  initMoneyInputs() {
    const toLatin = (s) => s
      .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
      .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
    document.querySelectorAll('input[data-money]').forEach((el) => {
      if (el.dataset.moneyInit) return;
      el.dataset.moneyInit = '1';
      const fmt = () => {
        const digits = toLatin(el.value).replace(/[^\d]/g, '');
        el.value = digits ? Number(digits).toLocaleString('en-US') : '';
      };
      el.addEventListener('input', fmt);
      fmt();
    });
  },

  // Executive dashboard: province mix and sales workload. Both read data the
  // context already carried but the old page never showed. Kept out of
  // refreshChartsTheme(), which assumes a cartesian chart and would throw on
  // the doughnut's missing `scales`; these redraw on theme change instead.
  initExecCharts() {
    const read = (id) => {
      const el = document.getElementById(id);
      if (!el) return null;
      try { return JSON.parse(el.textContent); } catch (e) { return null; }
    };
    const theme = this.getThemeColors();
    this._execCharts = this._execCharts || [];

    const province = document.getElementById('execProvinceChart');
    const provinceRows = read('exec-province-data');
    if (province && provinceRows && provinceRows.length && window.Chart && !province.dataset.init) {
      province.dataset.init = '1';
      // Provinces are separate places, not a ranked scale, so distinct hues
      // are right here. The ring is split by a border in the panel colour so
      // adjacent slices stay readable in both themes.
      const hues = ['#10b981', '#06b6d4', '#3b82f6', '#f59e0b', '#8b5cf6',
        '#ef4444', '#14b8a6', '#6366f1', '#f97316', '#64748b'];
      const panel = getComputedStyle(document.documentElement)
        .getPropertyValue('--pe-panel').trim() || '#ffffff';
      this._execCharts.push(new Chart(province, {
        type: 'doughnut',
        data: {
          labels: provinceRows.map((r) => r.province || T('نامشخص')),
          datasets: [{
            data: provinceRows.map((r) => r.n),
            backgroundColor: provinceRows.map((_, i) => hues[i % hues.length]),
            borderColor: panel,
            borderWidth: 2,
            hoverOffset: 6,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '70%',
          plugins: {
            legend: {
              position: 'bottom',
              labels: { color: theme.muted, boxWidth: 10, boxHeight: 10, padding: 10 },
            },
          },
        },
      }));
    }

    // Two bars per person: what they are carrying now, and what they have
    // actually closed. Either number alone is misleading — a big open load
    // might mean a busy quarter or a stalled one.
    const workload = document.getElementById('execWorkloadChart');
    const workloadRows = read('exec-workload-data');
    if (workload && workloadRows && workloadRows.length && window.Chart && !workload.dataset.init) {
      workload.dataset.init = '1';
      this._execCharts.push(new Chart(workload, {
        type: 'bar',
        data: {
          labels: workloadRows.map((r) => r.label),
          datasets: [
            {
              label: T('پرونده‌های فعال'),
              data: workloadRows.map((r) => r.active),
              backgroundColor: theme.accent,
              borderRadius: 5,
              maxBarThickness: 22,
            },
            {
              label: T('قراردادهای بسته‌شده'),
              data: workloadRows.map((r) => r.closed),
              backgroundColor: '#7c3aed',
              borderRadius: 5,
              maxBarThickness: 22,
            },
          ],
        },
        options: {
          indexAxis: 'y',  // names read better along the side than rotated
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'top',
              labels: { color: theme.muted, boxWidth: 10, boxHeight: 10, padding: 12 },
            },
          },
          scales: {
            x: { ticks: { color: theme.muted, precision: 0 }, grid: { color: theme.grid } },
            y: { ticks: { color: theme.muted }, grid: { display: false } },
          },
        },
      }));
    }
  },

  // Technical dashboard: plot every plant on a Leaflet map, coloured by health.
  initPlantDashboard() {
    const el = document.getElementById('plantDashboardMap') || document.getElementById('fleetMap');
    if (!el || el.dataset.init || typeof L === 'undefined') return;
    el.dataset.init = '1';
    let points = [];
    const dataEl = document.getElementById('plant-map-data') || document.getElementById('fleet-map-data');
    try { points = JSON.parse(dataEl.textContent); } catch (e) { points = []; }

    const map = L.map(el).setView([32.4279, 53.6880], 5);  // Iran
    tileLayer().addTo(map);

    const bounds = [];
    points.forEach((p) => {
      const color = p.alerts > 0 || (p.hot_cells || 0) > 0 ? '#dc2626' : (p.online ? '#16a34a' : '#9ca3af');
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 9, color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.9,
      }).addTo(map);
      marker.bindPopup(
        '<b>' + p.name + '</b><br>' + (p.location || '') +
        '<br>' + T('توان') + ': ' + p.power + ' kW' +
        '<br>' + T('ارورها') + ': ' + p.alerts +
        ((p.hot_cells != null) ? ('<br>' + T('پنل داغ') + ': ' + p.hot_cells) : '') +
        (p.id ? ('<br><a href="/plants/dashboard/?plant=' + p.id + '">' + T('جزئیات') + '</a>') : '')
      );
      bounds.push([p.lat, p.lng]);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    setTimeout(() => map.invalidateSize(), 80);
    this._plantMap = map;
  },

  // Interactive PV module / cell heat-map.
  initPvModuleGrid() {
    const grid = document.getElementById('pvModuleGrid');
    const dataEl = document.getElementById('pv-module-grid-data');
    const detail = document.getElementById('pvModuleDetail');
    if (!grid || !dataEl || grid.dataset.init) return;
    grid.dataset.init = '1';
    let payload = { rows: 8, cols: 12, cells: [], summary: {} };
    try { payload = JSON.parse(dataEl.textContent); } catch (e) { /* keep defaults */ }
    if (payload.sections) { this.renderPvSections(grid, detail, payload); return; }
    const cols = payload.cols || 12;
    grid.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
    const byKey = {};
    (payload.cells || []).forEach((c) => { byKey[c.row + '-' + c.col] = c; });
    const statusLabel = {
      ok: T('عادی'), warn: T('هشدار دما'), hot: T('داغ'),
      offline: T('آفلاین'), fault: 'Fault',
    };
    for (let r = 1; r <= (payload.rows || 8); r++) {
      for (let c = 1; c <= cols; c++) {
        const cell = byKey[r + '-' + c] || { row: r, col: c, status: 'offline', temp: 0, code: 'C-R' + r + '-C' + c, power_pct: 0, string: '', inverter: '' };
        const el = document.createElement('div');
        el.className = 'cell ' + (cell.status || 'ok');
        el.title = cell.code + ' · ' + cell.temp + '°C';
        el.addEventListener('click', () => {
          if (!detail) return;
          detail.innerHTML =
            '<div class="mini-stat"><span>' + T('شناسه') + '</span><strong>' + cell.code + '</strong></div>' +
            '<div class="mini-stat"><span>' + T('دما') + '</span><strong>' + cell.temp + '°C</strong></div>' +
            '<div class="mini-stat"><span>' + T('وضعیت') + '</span><strong>' + (statusLabel[cell.status] || cell.status) + '</strong></div>' +
            '<div class="mini-stat"><span>' + T('استرینگ') + '</span><strong>' + (cell.string || '—') + '</strong></div>' +
            '<div class="mini-stat"><span>' + T('اینورتر') + '</span><strong>' + (cell.inverter || '—') + '</strong></div>' +
            '<div class="mini-stat"><span>' + T('توان نسبی') + '</span><strong>' + (cell.power_pct || 0) + '%</strong></div>';
        });
        grid.appendChild(el);
      }
    }
  },

  // The layout as built: each roof with its real blocks. Panels have no sensors of
  // their own, so a roof's colour is the live state of the inverter it feeds.
  renderPvSections(grid, detail, payload) {
    const n = (v) => this.formatNumber(v);
    const make = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text !== undefined) el.textContent = text;
      return el;
    };
    const stat = (label, value) => {
      const box = make('div', 'mini-stat');
      box.append(make('span', '', label), make('strong', '', value));
      return box;
    };
    grid.className = 'pv-sections';
    grid.style.gridTemplateColumns = '';
    grid.replaceChildren();
    const legend = grid.parentElement && grid.parentElement.querySelector('.cell-legend');
    if (legend) {
      legend.replaceChildren();
      [['ok', T('در حال تولید')], ['idle', T('بدون تولید')], ['offline', T('بدون دادهٔ تازه')],
        ['fault', T('خطای اینورتر')], ['pending', T('به پایش وصل نشده')]].forEach(([cls, label]) => {
        const item = make('span');
        item.append(make('i', cls), label);
        legend.appendChild(item);
      });
    }
    grid.appendChild(make('div', 'footer-note',
      T('ظرفیت متصل به پایش') + ': ' + n(payload.connected_kw) + ' ' + T('از') + ' ' + n(payload.capacity_kw) + ' ' + T('کیلووات') +
      ' · ' + T('رنگ پنل‌ها وضعیت اینورتر متصل به آن‌هاست؛ پنل‌ها حسگر جداگانه ندارند.')));
    payload.sections.forEach((section) => {
      const box = make('div');
      const head = make('div', 'pv-section-head');
      const facts = [n(section.panels) + ' ' + T('پنل'), n(section.kwp) + ' kWp', section.status_label];
      if (section.tilt) facts.push(T('شیب') + ' ' + section.tilt);
      if (section.azimuth !== null) facts.push(T('جهت') + ' ' + n(section.azimuth) + '°');
      head.append(make('strong', '', section.name), make('small', '', facts.join(' · ')));
      box.appendChild(head);
      const blocks = make('div', 'pv-blocks');
      let number = 0;
      section.blocks.forEach((block, blockIndex) => {
        const cells = make('div', 'cell-grid' + (block.cols < 12 ? ' small-block' : ''));
        cells.style.gridTemplateColumns = block.cols < 12 ? 'repeat(' + block.cols + ', 18px)' : 'repeat(' + block.cols + ', 1fr)';
        for (let i = 0; i < block.cols * block.rows; i++) {
          number += 1;
          const panelNumber = number;
          const cell = make('div', 'cell ' + section.status);
          cell.title = section.name + ' · ' + T('پنل') + ' ' + n(panelNumber);
          cell.addEventListener('click', () => {
            if (!detail) return;
            detail.replaceChildren(
              stat(T('سوله'), section.name),
              stat(T('بلوک / پنل'), n(blockIndex + 1) + ' / ' + n(panelNumber)),
              stat(T('وضعیت'), section.status_label),
              stat(T('توان نامی پنل'), n(section.panel_watt) + ' W'),
              stat(T('میانگین توان هر پنل'), section.average_w === null ? '—' : n(section.average_w) + ' W'),
              stat(T('اینورتر'), section.inverter || '—'));
          });
          cells.appendChild(cell);
        }
        blocks.appendChild(cells);
      });
      box.appendChild(blocks);
      grid.appendChild(box);
    });
  },

  // Full plant monitor: figures, every reported field and charts, refreshed in place.
  initPlantScreen() {
    const root = document.querySelector('[data-screen-url]');
    if (!root || root.dataset.init) return;
    root.dataset.init = '1';
    const set = (name, value) => { const el = root.querySelector(`[data-s="${name}"]`); if (el) el.textContent = value; };
    const make = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
    const rows = (host, items) => host.replaceChildren(...items.map(([label, value]) => { const row = make('div'); row.append(make('span', label), make('b', value)); return row; }));
    const fa = (value) => Number(value).toLocaleString('fa-IR', { maximumFractionDigits: 1 });
    const axis = { color: '#a8bbb0', font: { family: 'inherit' } };
    const chartOptions = (unit) => ({
      responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { rtl: true, displayColors: false, callbacks: { label: (c) => `${fa(c.parsed.y)} ${unit()}` } } },
      scales: { x: { ticks: { ...axis, maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { ...axis, maxTicksLimit: 5, callback: (v) => fa(v) }, grid: { color: 'rgba(255,255,255,.07)' } } },
    });
    let data = null; let range = 'day'; let metric = 'kwh'; let powerChart = null; let energyChart = null;
    const unit = () => (metric === 'kwh' ? T('کیلووات‌ساعت') : T('تومان'));
    const drawEnergy = () => {
      const view = data.energy[range];
      const useMetric = metric === 'toman' && view.toman ? 'toman' : 'kwh';
      if (useMetric !== metric) metric = useMetric;
      root.querySelectorAll('[data-metric] button').forEach((b) => { b.classList.toggle('on', b.dataset.v === metric); if (b.dataset.v === 'toman') b.disabled = !view.toman; });
      root.querySelector('[data-energy-title]').textContent = metric === 'kwh' ? T('تولید انرژی (کیلووات‌ساعت)') : T('درآمد برآوردی (تومان)');
      const values = view[metric];
      if (window.Chart) {
        if (!energyChart) energyChart = new Chart(root.querySelector('[data-energy-chart]'), { type: 'bar', data: { labels: [], datasets: [{ data: [], backgroundColor: '#3ddc84', borderRadius: 4, maxBarThickness: 22 }] }, options: chartOptions(unit) });
        energyChart.data.labels = view.labels; energyChart.data.datasets[0].data = values; energyChart.update();
      }
      const table = make('table'); const body = make('tbody');
      view.labels.forEach((label, index) => { const tr = make('tr'); tr.append(make('td', label), make('td', `${fa(values[index])} ${unit()}`)); body.appendChild(tr); });
      table.appendChild(body); root.querySelector('[data-energy-table]').replaceChildren(table);
    };
    const render = (next) => {
      data = next;
      root.toggleAttribute('data-active', data.live.active);
      root.style.setProperty('--ps-speed', `${Math.max(0.55, 2.2 - data.live.percent / 55)}s`);
      root.querySelector('[data-state]').dataset.tone = data.status.tone;
      Object.entries({ name: data.plant.name, state: data.status.label, power: data.live.power, today_kwh: data.today.kwh, today_toman: data.today.toman,
        hours: data.today.hours, dc: data.live.dc, ac: data.live.power, grid: data.live.power, percent: `${fa(data.live.percent)}٪`, updated: data.status.updated || '—' }).forEach(([k, v]) => set(k, v));
      root.querySelector('[data-meter]').style.width = `${data.live.percent}%`;
      root.querySelector('[data-meter-label]').setAttribute('aria-label', `${fa(data.live.percent)}٪`);
      rows(root.querySelector('[data-info]'), [[T('قدرت قراردادی'), `${data.plant.contract} ${T('کیلووات')}`], [T('ظرفیت نصب‌شده'), `${data.plant.installed} ${T('کیلووات')}`], [T('متصل به پایش'), `${data.plant.connected} ${T('کیلووات')}`],
        [T('تولید کل اینورترها'), `${data.totals.lifetime} ${T('کیلووات‌ساعت')}`], [T('درآمد برآوردی از شروع پایش'), `${data.totals.income} ${T('تومان')}`], [T('نرخ فعلی هر کیلووات‌ساعت'), data.totals.rate ? `${data.totals.rate} ${T('تومان')}` : '—']]);
      rows(root.querySelector('[data-impact]'), data.impact.map((i) => [i.label, `${i.value} ${i.unit}`]));
      const units = data.inverters.map((inv) => {
        const card = make('div', undefined, 'ps-card'); const head = make('div', undefined, 'ps-unit-head'); const state = make('span', undefined, 'ps-state'); state.dataset.tone = inv.tone;
        state.append(make('i'), make('span', inv.state)); head.append(make('b', inv.name), state); const list = make('div', undefined, 'ps-list');
        rows(list, [[T('سریال'), inv.serial], [T('ظرفیت متصل'), `${inv.kwp} ${T('کیلووات')}`], [T('توان فعلی'), `${inv.power} ${T('کیلووات')}`], [T('تولید امروز'), `${inv.today} ${T('کیلووات‌ساعت')}`], [T('ساعت معادل'), inv.hours], [T('دما'), `${inv.temperature} ${T('درجه')}`]]);
        card.append(head, list); return card;
      });
      data.unmonitored.forEach((part) => { const card = make('div', undefined, 'ps-card ps-off'); const head = make('div', undefined, 'ps-unit-head'); head.append(make('b', part.name), make('small', T('به پایش وصل نشده'))); card.append(head, make('small', `${part.kwp} ${T('کیلووات')}`)); units.push(card); });
      root.querySelector('[data-units]').replaceChildren(...units);
      if (window.Chart) {
        if (!powerChart) powerChart = new Chart(root.querySelector('[data-power-chart]'), { type: 'line', data: { labels: [], datasets: [{ data: [], borderColor: '#3ddc84', backgroundColor: 'rgba(61,220,132,.14)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.25 }] }, options: chartOptions(() => T('کیلووات')) });
        powerChart.data.labels = data.power_curve.labels; powerChart.data.datasets[0].data = data.power_curve.kw; powerChart.update();
      }
      drawEnergy();
    };
    const pick = (selector, apply) => root.querySelector(selector).addEventListener('click', (event) => {
      const button = event.target.closest('button'); if (!button || !data) return;
      apply(button.dataset.v); root.querySelectorAll(`${selector} button`).forEach((b) => b.classList.toggle('on', b === button)); drawEnergy();
    });
    pick('[data-range]', (value) => { range = value; }); pick('[data-metric]', (value) => { metric = value; });
    root.querySelector('[data-full]').addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else if (root.requestFullscreen) root.requestFullscreen(); });
    const clock = root.querySelector('[data-clock]');
    const tick = () => { clock.textContent = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran' }).format(new Date()); };
    const load = () => fetch(root.dataset.screenUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); }).then(render)
      .catch(() => { root.querySelector('[data-state]').dataset.tone = 'warn'; set('state', T('دریافت اطلاعات ناموفق بود')); });
    tick(); load();
    const clockTimer = setInterval(tick, 30000);
    const dataTimer = setInterval(() => {
      if (!document.contains(root)) { clearInterval(dataTimer); clearInterval(clockTimer); if (powerChart) powerChart.destroy(); if (energyChart) energyChart.destroy(); return; }
      if (!document.hidden) load();
    }, 60000);
  },

  initPlantMonitor() {
    const root = document.querySelector('[data-monitor-url]');
    if (!root || root.dataset.init) return;
    root.dataset.init = '1';
    const body = root.querySelector('[data-monitor-body]');
    const colors = ['#22a35a', '#1aa9e8', '#f59e0b', '#8b5cf6', '#ef4444', '#14b8a6', '#ec4899', '#64748b'];
    const charts = new Map();
    let range = '1';
    let timer = null;
    const make = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text !== undefined) el.textContent = text;
      return el;
    };
    const cardGrid = (items) => {
      const grid = make('div', 'mon-cards');
      items.forEach((item) => {
        const card = make('div');
        const value = make('strong', '', item.value);
        card.append(make('span', '', item.label), value, ' ' + (item.unit || ''));
        grid.appendChild(card);
      });
      return grid;
    };
    const chartBox = (chart) => {
      const box = make('div', 'mon-chart');
      box.appendChild(make('h3', '', chart.title + (chart.unit ? ' (' + chart.unit + ')' : '')));
      const holder = make('div', 'box');
      const canvas = make('canvas');
      holder.appendChild(canvas);
      box.appendChild(holder);
      if (window.Chart) {
        const theme = this.getThemeColors();
        charts.set(chart.id, new Chart(canvas, {
          type: chart.type,
          data: {
            labels: chart.labels,
            datasets: chart.series.map((series, index) => ({
              label: series.name, data: series.data, borderColor: colors[index % colors.length],
              backgroundColor: colors[index % colors.length], borderWidth: 2, pointRadius: 0, spanGaps: true, tension: 0.25,
            })),
          },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: chart.series.length > 1, labels: { color: theme.muted, boxWidth: 12 } } },
            scales: {
              x: { ticks: { color: theme.muted, maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
              y: { ticks: { color: theme.muted }, grid: { color: theme.grid } },
            },
          },
        }));
      }
      return box;
    };
    const render = (data) => {
      charts.forEach((chart) => chart.destroy());
      charts.clear();
      const open = new Set(Array.from(body.querySelectorAll('details[open]')).map((el) => el.dataset.key));
      body.replaceChildren();
      data.inverters.forEach((inverter) => {
        const section = make('section', 'mb-4');
        section.appendChild(make('h2', 'h6 mb-1', inverter.name + ' · ' + inverter.rated + ' kW'));
        section.appendChild(make('div', 'footer-note', inverter.serial + ' · ' + inverter.status +
          (inverter.updated ? ' · ' + T('آخرین دریافت') + ': ' + inverter.updated : '')));
        section.appendChild(cardGrid(inverter.cards));
        const grid = make('div', 'mon-charts');
        inverter.charts.forEach((chart) => grid.appendChild(chartBox(chart)));
        section.appendChild(grid);
        if (inverter.fields.length) {
          const details = make('details', 'mon-fields');
          details.dataset.key = inverter.serial;
          details.open = open.has(inverter.serial);
          details.appendChild(make('summary', '', T('همهٔ داده‌های دریافتی از اینورتر')));
          inverter.fields.forEach((group) => {
            details.appendChild(make('h3', 'h6 mt-2', group.title));
            const list = make('div', 'mon-field-grid');
            group.items.forEach((item) => {
              const row = make('div');
              row.append(make('span', '', item.label), make('strong', '', item.value + (item.unit ? ' ' + item.unit : '')));
              list.appendChild(row);
            });
            details.appendChild(list);
          });
          section.appendChild(details);
        }
        body.appendChild(section);
      });
      const daily = make('section');
      daily.appendChild(make('h2', 'h6', T('تولید و درآمد روزانهٔ نیروگاه')));
      const grid = make('div', 'mon-charts');
      data.daily.forEach((chart) => grid.appendChild(chartBox(chart)));
      daily.appendChild(grid);
      body.appendChild(daily);
    };
    const load = async () => {
      if (!document.contains(root)) {
        clearInterval(timer);
        charts.forEach((chart) => chart.destroy());
        return;
      }
      if (document.hidden) return;
      try {
        render(await this.fetchJson(root.dataset.monitorUrl + '?range=' + range));
      } catch (error) {
        console.error(error);
      }
    };
    root.querySelectorAll('[data-monitor-range]').forEach((button) => {
      button.addEventListener('click', () => {
        range = button.dataset.monitorRange;
        root.querySelectorAll('[data-monitor-range]').forEach((b) => b.classList.toggle('active', b === button));
        load();
      });
    });
    load();
    timer = setInterval(load, 60000);
  },

  // Keeps every income panel on the page current without reloading it.
  initRevenuePanels() {
    if (this._revenueTimer || !document.querySelector('[data-revenue-url]')) return;
    const update = async () => {
      const panels = document.querySelectorAll('[data-revenue-url]');
      if (!panels.length) {
        clearInterval(this._revenueTimer);
        this._revenueTimer = null;
        return;
      }
      if (document.hidden) return;
      for (const panel of panels) {
        try {
          const data = await this.fetchJson(panel.dataset.revenueUrl);
          panel.querySelector('[data-rev="now"]').textContent = data.now_toman_text;
          panel.querySelector('[data-rev="note"]').textContent = data.now_note;
          data.periods.forEach((period) => {
            const card = panel.querySelector('[data-rev-period="' + period.key + '"]');
            if (!card) return;
            card.querySelector('[data-rev-part="toman"]').textContent = period.toman_text;
            card.querySelector('[data-rev-part="kwh"]').textContent = period.kwh_text;
          });
        } catch (error) {
          console.error(error);
        }
      }
    };
    this._revenueTimer = setInterval(update, 30000);
  },

  // Per-plant daily production bar charts on the technical dashboard.
  initPlantCharts() {
    const dataEl = document.getElementById('plant-charts-data');
    if (!dataEl) return;
    let data = [];
    try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const theme = this.getThemeColors();
    data.forEach((pc) => {
      const canvas = document.getElementById('plantChart-' + pc.id);
      if (!canvas || canvas.dataset.init || !pc.values || !pc.values.length) return;
      canvas.dataset.init = '1';
      if (typeof Chart !== 'undefined') {
        new Chart(canvas, {
          type: 'bar',
          data: { labels: pc.labels, datasets: [{ label: T('تولید روزانه (kWh)'), data: pc.values, backgroundColor: theme.accent, borderRadius: 4 }] },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: theme.muted, maxRotation: 0, autoSkip: true }, grid: { display: false } },
              y: { beginAtZero: true, ticks: { color: theme.muted }, grid: { color: theme.grid } },
            },
          },
        });
      } else {
        this.drawFallbackLineChart(canvas, pc.labels, [{ data: pc.values, color: theme.accent }]);
      }
    });
  },

  drawFallbackLineChart(canvas, labels, datasets) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const theme = this.getThemeColors();
    const width = canvas.clientWidth || 640;
    const height = canvas.clientHeight || 260;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = theme.text;
    ctx.font = '12px IRANSansX, sans-serif';
    ctx.fillText(T('نمودار (آفلاین)'), 10, 18);

    const padding = 30;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;
    ctx.strokeStyle = theme.grid;
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.stroke();

    const values = datasets.flatMap((set) => set.data || []);
    const maxVal = Math.max(1, ...values);
    datasets.forEach((dataset, index) => {
      const series = dataset.data || [];
      if (!series.length) return;
      ctx.strokeStyle = dataset.color || (index === 0 ? theme.accent : theme.accentStrong);
      ctx.beginPath();
      series.forEach((value, i) => {
        const x = padding + (plotW * i) / Math.max(1, series.length - 1);
        const y = height - padding - (plotH * value) / maxVal;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });
  },

  updateAdminChart(data) {
    const canvas = document.getElementById('adminMainChart');
    if (!canvas) return;
    const theme = this.getThemeColors();
    const chartData = {
      labels: data.labels || [],
      datasets: [
        {
          label: T('تولید انرژی'),
          data: data.production || [],
          borderColor: theme.accent,
          backgroundColor: 'rgba(34, 197, 94, 0.12)',
          tension: 0.35,
          fill: false,
        },
        {
          label: T('راندمان سیستم'),
          data: data.efficiency || [],
          borderColor: theme.accentStrong,
          backgroundColor: 'rgba(22, 163, 74, 0.08)',
          tension: 0.35,
          fill: false,
        },
      ],
    };

    if (!window.Chart) {
      this.drawFallbackLineChart(canvas, chartData.labels, [
        { data: chartData.datasets[0].data, color: theme.accent },
        { data: chartData.datasets[1].data, color: theme.accentStrong },
      ]);
      return;
    }

    if (this._adminChart) {
      this._adminChart.data = chartData;
      this.refreshChartsTheme();
      this._adminChart.update();
      return;
    }

    this._adminChart = new Chart(canvas, {
      type: 'line',
      data: chartData,
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: theme.text } } },
        scales: {
          x: { ticks: { color: theme.muted }, grid: { color: theme.grid } },
          y: { ticks: { color: theme.muted }, grid: { color: theme.grid } },
        },
      },
    });
  },

  renderAdminAlerts(alerts) {
    const table = document.getElementById('adminAlertsTable');
    if (!table) return;
    table.innerHTML = '';
    if (!alerts || !alerts.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 4;
      cell.textContent = T('رویدادی ثبت نشده است.');
      row.appendChild(cell);
      table.appendChild(row);
      return;
    }
    alerts.forEach((alert) => {
      const row = document.createElement('tr');
      const statusClass = alert.severity === 'high' ? 'danger' : alert.severity === 'medium' ? 'warning' : '';
      const statusLabel = alert.acknowledged ? 'OK' : T('در حال بررسی');

      const typeCell = document.createElement('td');
      typeCell.textContent = alert.type;
      const plantCell = document.createElement('td');
      plantCell.textContent = alert.plant;
      const messageCell = document.createElement('td');
      messageCell.textContent = alert.message;
      const statusCell = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = `badge ${statusClass}`.trim();
      badge.textContent = statusLabel;
      statusCell.appendChild(badge);

      row.appendChild(typeCell);
      row.appendChild(plantCell);
      row.appendChild(messageCell);
      row.appendChild(statusCell);
      table.appendChild(row);
    });
  },

  async initAdminPanel() {
    const panel = document.getElementById('panelContent');
    const target = panel || document.body;
    if (!target || target.dataset.dashboard !== 'admin') return;
    const endpoint = target.dataset.endpoint;
    if (!endpoint) return;
    if (this._adminPolling) return;
    this._adminPolling = true;

    const update = async () => {
      try {
        const data = await this.fetchJson(endpoint);
        const plantsNode = document.getElementById('adminPlantsCount');
        const equipmentNode = document.getElementById('adminEquipmentCount');
        const alertsNode = document.getElementById('adminAlertsCount');
        const healthNode = document.getElementById('adminHealthPercent');

        if (plantsNode) plantsNode.textContent = this.formatNumber(data.plants_count || 0);
        if (equipmentNode) equipmentNode.textContent = this.formatNumber(data.equipment_online_count || 0);
        if (alertsNode) alertsNode.textContent = this.formatNumber(data.alerts_count || 0);
        if (healthNode) {
          healthNode.textContent = data.system_health_percent === null ? '—' : `${data.system_health_percent}%`;
        }

        const cpuValue = document.getElementById('adminCpuValue');
        const cpuBar = document.getElementById('adminCpuBar');
        const ramValue = document.getElementById('adminRamValue');
        const ramBar = document.getElementById('adminRamBar');
        const diskValue = document.getElementById('adminDiskValue');
        const diskBar = document.getElementById('adminDiskBar');
        const queueValue = document.getElementById('adminQueueValue');
        const queueBar = document.getElementById('adminQueueBar');

        if (cpuValue) cpuValue.textContent = `${data.server_health.cpu}%`;
        if (cpuBar) cpuBar.style.width = `${data.server_health.cpu}%`;
        if (ramValue) ramValue.textContent = `${data.server_health.memory}%`;
        if (ramBar) ramBar.style.width = `${data.server_health.memory}%`;
        if (diskValue) diskValue.textContent = `${data.server_health.disk}%`;
        if (diskBar) diskBar.style.width = `${data.server_health.disk}%`;
        if (queueValue) queueValue.textContent = `${data.server_health.queue}`;
        if (queueBar) queueBar.style.width = `${Math.min(100, data.server_health.queue)}%`;

        this.updateAdminChart(data.chart || {});
        this.renderAdminAlerts(data.alerts || []);
      } catch (error) {
        console.error(error);
      }
    };

    await update();
    setInterval(update, 30000);
  },

  updateOwnerChart(data) {
    const canvas = document.getElementById('ownerPowerChart');
    if (!canvas) return;
    const theme = this.getThemeColors();
    const chartData = {
      labels: data.labels || [],
      datasets: [
        {
          label: T('تولید انرژی'),
          data: data.production || [],
          borderColor: theme.accent,
          backgroundColor: 'rgba(34, 197, 94, 0.12)',
          tension: 0.35,
          fill: false,
        },
      ],
    };

    if (!window.Chart) {
      this.drawFallbackLineChart(canvas, chartData.labels, [
        { data: chartData.datasets[0].data, color: theme.accent },
      ]);
      return;
    }

    if (this._ownerChart) {
      this._ownerChart.data = chartData;
      this.refreshChartsTheme();
      this._ownerChart.update();
      return;
    }

    this._ownerChart = new Chart(canvas, {
      type: 'line',
      data: chartData,
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: theme.text } } },
        scales: {
          x: { ticks: { color: theme.muted }, grid: { color: theme.grid } },
          y: { ticks: { color: theme.muted }, grid: { color: theme.grid } },
        },
      },
    });
  },

  renderOwnerInverters(inverters) {
    const table = document.getElementById('ownerInverterTable');
    if (!table) return;
    table.innerHTML = '';
    if (!inverters || !inverters.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 3;
      cell.textContent = T('تجهیز ثبت نشده است.');
      row.appendChild(cell);
      table.appendChild(row);
      return;
    }
    inverters.forEach((inv) => {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      nameCell.textContent = inv.name;
      const statusCell = document.createElement('td');
      statusCell.textContent = inv.status;
      statusCell.className = inv.status_level === 'bad' ? 'status-bad' : 'status-ok';
      const powerCell = document.createElement('td');
      powerCell.textContent = `${this.formatNumber(inv.power_kw)} kW`;

      row.appendChild(nameCell);
      row.appendChild(statusCell);
      row.appendChild(powerCell);
      table.appendChild(row);
    });
  },

  renderOwnerAlerts(alerts) {
    const table = document.getElementById('ownerAlertsTable');
    if (!table) return;
    table.innerHTML = '';
    if (!alerts || !alerts.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 3;
      cell.textContent = T('هشداری ثبت نشده است.');
      row.appendChild(cell);
      table.appendChild(row);
      return;
    }
    alerts.forEach((alert) => {
      const row = document.createElement('tr');
      const typeCell = document.createElement('td');
      typeCell.textContent = alert.type;
      const messageCell = document.createElement('td');
      messageCell.textContent = alert.message;
      const timeCell = document.createElement('td');
      timeCell.textContent = alert.time;

      row.appendChild(typeCell);
      row.appendChild(messageCell);
      row.appendChild(timeCell);
      table.appendChild(row);
    });
  },

  async initOwnerPanel() {
    const panel = document.getElementById('panelContent');
    const target = panel || document.body;
    if (!target || target.dataset.dashboard !== 'owner') return;
    const endpoint = target.dataset.endpoint;
    if (!endpoint) return;
    if (this._ownerPolling) return;
    this._ownerPolling = true;

    const update = async () => {
      try {
        const data = await this.fetchJson(endpoint);
        const powerNode = document.getElementById('ownerRealtimePower');
        const energyNode = document.getElementById('ownerTodayEnergy');
        const efficiencyNode = document.getElementById('ownerEfficiency');
        const revenueNode = document.getElementById('ownerTodayRevenue');

        // Units sit under each number in the page, so only the number changes here.
        const round1 = (v) => Math.round((Number(v) || 0) * 10) / 10;
        const monthNode = document.getElementById('ownerMonthEnergy');
        const savingNode = document.getElementById('ownerTodaySaving');
        if (powerNode) powerNode.textContent = this.formatNumber(round1(data.latest_power_kw));
        if (energyNode) energyNode.textContent = this.formatNumber(round1(data.today_energy_kwh));
        if (monthNode) monthNode.textContent = this.formatNumber(data.month_energy_kwh || 0);
        if (savingNode) savingNode.textContent = data.today_saving_toman == null ? '—' : this.formatNumber(data.today_saving_toman);
        if (efficiencyNode) efficiencyNode.textContent = `${this.formatNumber(round1(data.efficiency))}٪`;
        if (revenueNode) revenueNode.textContent = `${this.formatNumber(data.today_revenue || 0)} ریال`;

        this.updateOwnerChart(data.chart || {});
        this.renderOwnerInverters(data.inverters || []);
        this.renderOwnerAlerts(data.alerts || []);
      } catch (error) {
        console.error(error);
      }
    };

    await update();
    setInterval(update, 30000);
  },

  // Swap every open map onto the basemap for the current theme. Leaflet keeps
  // the view and the markers; only the tile layer is replaced.
  refreshMapTiles() {
    [this._plantMap, this._locationMap, this._adminLocationMap].forEach((map) => {
      if (!map || typeof map.eachLayer !== 'function') return;
      try {
        map.eachLayer((layer) => {
          if (layer instanceof L.TileLayer) map.removeLayer(layer);
        });
        tileLayer().addTo(map);
      } catch (e) { /* a map mid-teardown is not worth a thrown error */ }
    });
  },

  refreshChartsTheme() {
    const theme = this.getThemeColors();
    const updateChart = (chart) => {
      if (!chart) return;
      chart.options.plugins.legend.labels.color = theme.text;
      chart.options.scales.x.ticks.color = theme.muted;
      chart.options.scales.y.ticks.color = theme.muted;
      chart.options.scales.x.grid.color = theme.grid;
      chart.options.scales.y.grid.color = theme.grid;
      if (chart.data && chart.data.datasets && chart.data.datasets.length) {
        chart.data.datasets.forEach((dataset, index) => {
          dataset.borderColor = index === 0 ? theme.accent : theme.accentStrong;
        });
      }
      chart.update();
    };
    updateChart(this._adminChart);
    updateChart(this._ownerChart);

    // The executive charts are a doughnut and a horizontal bar: one has no
    // `scales` at all, so only recolour what each actually has.
    (this._execCharts || []).forEach((chart) => {
      if (!chart || !chart.options) return;
      const legend = chart.options.plugins && chart.options.plugins.legend;
      if (legend && legend.labels) legend.labels.color = theme.muted;
      const scales = chart.options.scales || {};
      Object.keys(scales).forEach((axis) => {
        if (scales[axis].ticks) scales[axis].ticks.color = theme.muted;
        if (scales[axis].grid && scales[axis].grid.color) scales[axis].grid.color = theme.grid;
      });
      chart.update();
    });
  },

  initAiAnalysis() {
    const container = document.getElementById('aiAnalytics');
    const button = document.getElementById('aiAnalyzeButton');
    const output = document.getElementById('aiAnalysisOutput');
    if (!container || !button || !output) return;
    if (button.dataset.bound) return;
    button.dataset.bound = 'true';
    const endpoint = container.dataset.aiEndpoint;
    if (!endpoint) return;
    button.addEventListener('click', async () => {
      button.disabled = true;
      output.textContent = T('در حال تحلیل...');
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': this.getCookie('csrftoken'),
          },
          body: JSON.stringify({}),
        });
        const data = await response.json();
        if (!response.ok) {
          output.textContent = data.error || T('خطا در دریافت تحلیل.');
        } else {
          output.textContent = data.analysis || T('پاسخی دریافت نشد.');
        }
      } catch (error) {
        output.textContent = T('خطا در ارتباط با سرویس تحلیل.');
      } finally {
        button.disabled = false;
      }
    });
  }
};

window.SolarOps.initPanelNavigation = function initPanelNavigation() {
  if (this._ajaxNavInitialized) return;
  this._ajaxNavInitialized = true;
  document.addEventListener('click', async (event) => {
    const link = event.target.closest('a[data-ajax="true"]');
    if (!link) return;
    if (link.hasAttribute('data-no-ajax') || link.hasAttribute('download') || link.getAttribute('target')) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const panel = document.getElementById('panelContent');
    if (!panel) {
      window.location.href = link.href;
      return;
    }
    const url = link.getAttribute('href');
    if (!url) return;
    try {
      const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (!response.ok) {
        window.location.href = url;
        return;
      }
      const html = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const nextPanel = doc.getElementById('panelContent');
      if (!nextPanel) {
        window.location.href = url;
        return;
      }
      panel.replaceWith(nextPanel);
      window.history.pushState({}, '', url);
      // Only #panelContent is swapped, so the document title would otherwise
      // keep naming whatever page you opened first.
      const nextTitle = doc.querySelector('title');
      if (nextTitle && nextTitle.textContent.trim()) document.title = nextTitle.textContent.trim();
      document.querySelectorAll('a[data-ajax="true"]').forEach((item) => item.classList.remove('active'));
      link.classList.add('active');
      // Keep the group holding the new page open — otherwise following a
      // sub-item collapses the group you just navigated from.
      const group = link.closest('.nav-group');
      if (group) group.classList.add('open');
      window.SolarOps.refreshPanels();
      if (window.LocationSelect) window.LocationSelect.boot();
    } catch (error) {
      console.error(error);
      window.location.href = url;
    }
  });
};

// Collapsible sidebar (hamburger) + accordion nav groups. Uses delegated
// listeners so it keeps working after AJAX panel swaps; state is persisted.
// Mark the nav link for the page actually being shown, and open the group it
// lives in. Without this the highlight only ever followed a click: after a
// hard reload (or a bookmark, or an F5 on the settings page) "داشبورد" stayed
// lit and every group stayed shut, whatever you were looking at.
window.SolarOps.markActiveNav = function markActiveNav() {
  const here = window.location.pathname;
  let best = null;
  let bestLen = 0;
  document.querySelectorAll('.sidebar a[href]').forEach((link) => {
    const href = link.getAttribute('href') || '';
    if (!href.startsWith('/')) return;
    // Longest matching prefix wins, so /plants/inverters/ beats /plants/.
    if (here === href || (href.length > 1 && here.startsWith(href))) {
      if (href.length > bestLen) { best = link; bestLen = href.length; }
    }
  });
  if (!best) return;
  document.querySelectorAll('.sidebar a.active').forEach((a) => a.classList.remove('active'));
  best.classList.add('active');
  const group = best.closest('.nav-group');
  if (group) group.classList.add('open');
};

window.SolarOps.restoreNavGroups = function restoreNavGroups() {
  let openKeys = [];
  try {
    const raw = localStorage.getItem('solarops-nav-open') || '';
    openKeys = raw ? raw.split(',') : [];
  } catch (e) { /* ignore */ }
  document.querySelectorAll('.nav-group').forEach((group) => {
    const key = group.getAttribute('data-nav-group') || '';
    const hasActive = group.querySelector('.nav-subitems a.active');
    if (openKeys.indexOf(key) !== -1 || hasActive) {
      group.classList.add('open');
    }
  });
  this.markActiveNav();
};

window.SolarOps.initSidebar = function initSidebar() {
  this.restoreNavGroups();
  if (this._sidebarInitialized) return;
  this._sidebarInitialized = true;

  try {
    if (localStorage.getItem('solarops-nav-collapsed') === '1') {
      const app = document.querySelector('.app');
      if (app) app.classList.add('nav-collapsed');
    }
  } catch (e) { /* ignore */ }

  const MOBILE_BP = 900;   // matches the drawer breakpoint in responsive.css
  document.addEventListener('click', (event) => {
    const app = document.querySelector('.app');
    if (event.target.closest('#sidebarToggle')) {
      if (app) {
        if (window.innerWidth <= MOBILE_BP) {
          // Mobile: the hamburger opens/closes the off-canvas drawer.
          app.classList.toggle('nav-open');
        } else {
          // Desktop: it collapses the fixed sidebar for more space.
          const collapsed = app.classList.toggle('nav-collapsed');
          try { localStorage.setItem('solarops-nav-collapsed', collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
        }
      }
      return;
    }
    // Mobile drawer: close it when tapping the backdrop or following a nav link.
    if (app && app.classList.contains('nav-open') && window.innerWidth <= MOBILE_BP) {
      if (event.target.closest('.sidebar a')) {
        app.classList.remove('nav-open');
      } else if (!event.target.closest('.sidebar')) {
        app.classList.remove('nav-open');
        return;
      }
    }
    const groupToggle = event.target.closest('.nav-group-toggle');
    if (groupToggle) {
      const group = groupToggle.closest('.nav-group');
      if (!group) return;
      const open = group.classList.toggle('open');
      const key = group.getAttribute('data-nav-group') || '';
      try {
        const raw = localStorage.getItem('solarops-nav-open') || '';
        const set = new Set(raw ? raw.split(',') : []);
        if (open) set.add(key); else set.delete(key);
        localStorage.setItem('solarops-nav-open', Array.from(set).filter(Boolean).join(','));
      } catch (e) { /* ignore */ }
    }
  });

  // Growing past the mobile breakpoint must drop the drawer state so the
  // sidebar returns to its docked desktop position cleanly.
  let _resizeRaf = null;
  window.addEventListener('resize', () => {
    if (_resizeRaf) return;
    _resizeRaf = requestAnimationFrame(() => {
      _resizeRaf = null;
      const app = document.querySelector('.app');
      if (app && window.innerWidth > 1100) app.classList.remove('nav-open');
    });
  });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (window.SolarOps && typeof window.SolarOps.initTheme === 'function') {
      window.SolarOps.initTheme();
    }
    if (window.SolarOps) {
      window.SolarOps.initAdminPanel();
      window.SolarOps.initOwnerPanel();
      window.SolarOps.initRevenuePanels(); window.SolarOps.initPlantMonitor(); window.SolarOps.initPlantScreen();
      window.SolarOps.initAiAnalysis();
      window.SolarOps.initPanelNavigation();
      window.SolarOps.initSidebar();
      window.SolarOps.initEvalWizard();
      window.SolarOps.initMoneyInputs();
      window.SolarOps.initPlantDashboard();
      window.SolarOps.initPlantCharts();
      window.SolarOps.initPvModuleGrid();
      window.SolarOps.initExecCharts();
      window.SolarOps.initAdminLocationMap();
      window.SolarOps.initLocationMap();
    }
  });
} else if (window.SolarOps && typeof window.SolarOps.initTheme === 'function') {
  window.SolarOps.initTheme();
  window.SolarOps.initAdminPanel();
  window.SolarOps.initOwnerPanel();
  window.SolarOps.initRevenuePanels(); window.SolarOps.initPlantMonitor(); window.SolarOps.initPlantScreen();
  window.SolarOps.initAiAnalysis();
  window.SolarOps.initPanelNavigation();
  window.SolarOps.initSidebar();
  window.SolarOps.initEvalWizard();
  window.SolarOps.initMoneyInputs();
  window.SolarOps.initPlantDashboard();
  window.SolarOps.initPlantCharts();
  window.SolarOps.initPvModuleGrid();
  window.SolarOps.initExecCharts();
  window.SolarOps.initAdminLocationMap();
  window.SolarOps.initLocationMap();
}

// --- PWA install prompt: reveal an in-app "نصب اپلیکیشن" button when the
// browser offers installation, instead of relying on a hidden browser menu. ---
(function () {
  let deferredPrompt = null;
  const reveal = () => {
    const btn = document.getElementById('pwaInstallBtn');
    if (btn && deferredPrompt) btn.hidden = false;
  };
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    reveal();
  });
  document.addEventListener('click', async (event) => {
    const btn = event.target.closest && event.target.closest('#pwaInstallBtn');
    if (!btn || !deferredPrompt) return;
    btn.hidden = true;
    deferredPrompt.prompt();
    try { await deferredPrompt.userChoice; } catch (e) { /* ignore */ }
    deferredPrompt = null;
  });
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    const btn = document.getElementById('pwaInstallBtn');
    if (btn) btn.hidden = true;
  });
  document.addEventListener('DOMContentLoaded', reveal);
})();

// One tap, one submission. The lead and request forms do slow work on submit
// (identity check, SMS), and people tap again while waiting — each tap used to
// create another request. Lock POST forms after the first submit.
(() => {
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    if ((form.method || '').toLowerCase() !== 'post') return;
    if (form.dataset.submitting === '1') { event.preventDefault(); return; }
    form.dataset.submitting = '1';
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((b) => {
      b.disabled = true;
      b.setAttribute('aria-busy', 'true');
    });
    // Unlock if the browser restores the page from history (back button).
    window.addEventListener('pageshow', () => {
      form.dataset.submitting = '';
      form.querySelectorAll('[aria-busy]').forEach((b) => { b.disabled = false; b.removeAttribute('aria-busy'); });
    }, { once: true });
  });
})();

// Table rows marked .row-link open their record when clicked anywhere, through
// the row's own link so AJAX panel navigation still applies. Delegated from
// document because panel navigation does not run page scripts.
document.addEventListener('click', (e) => {
  const row = e.target.closest && e.target.closest('tr.row-link');
  if (!row || e.target.closest('a,button,input,label,select,textarea')) return;
  const link = row.querySelector('a[data-ajax][href]') || row.querySelector('a[href]');
  if (link) link.click();
});

// Phones keep the request filters folded behind one button.
document.addEventListener('click', (e) => {
  const button = e.target.closest && e.target.closest('[data-filter-toggle]');
  if (!button) return;
  const open = button.closest('form').classList.toggle('open');
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
});

// In-page links (#new-offer, #next-actions): the panel scrolls inside its own
// container, so the browser's default jump to an anchor does nothing there.
document.addEventListener('click', (e) => {
  const link = e.target.closest && e.target.closest('a[href^="#"]');
  if (!link || link.getAttribute('href').length < 2) return;
  const target = document.getElementById(link.getAttribute('href').slice(1));
  if (!target) return;
  e.preventDefault();
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const field = target.querySelector('input:not([type=hidden]),select,textarea');
  if (field) setTimeout(() => field.focus({ preventScroll: true }), 400);
});


/* Persian calendar for date boxes; typing a date by hand keeps working. */
(() => {
  const SELECTOR = 'input[data-jalali],input[name=date_from],input[name=date_to],input[name=updated_from],'
    + 'input[name=updated_to],input[name=valid_until],input[name=valid_from],input[name=from],input[name=to],'
    + 'input[name=period_start],input[name=period_end]';
  const MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
  const DAYS = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];
  const fa = (v) => String(v).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const pad = (v) => String(v).padStart(2, '0');
  const BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
  const div = (a, b) => Math.trunc(a / b);
  const mod = (a, b) => a - Math.trunc(a / b) * b;
  const march = (jy) => {
    const gy = jy + 621; let leapJ = -14; let jp = BREAKS[0]; let jump = 0;
    for (let i = 1; i < BREAKS.length; i += 1) {
      jump = BREAKS[i] - jp;
      if (jy < BREAKS[i]) break;
      leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
      jp = BREAKS[i];
    }
    const n = jy - jp;
    leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
    if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
    return [gy, 20 + leapJ - (div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150)];
  };
  const g2d = (gy, gm, gd) => div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408
    - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
  const d2g = (jdn) => {
    let j = 4 * jdn + 139361631;
    j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
    const i = div(mod(j, 1461), 4) * 5 + 308;
    const gm = mod(div(i, 153), 12) + 1;
    return [div(j, 1461) - 100100 + div(8 - gm, 6), gm, div(mod(i, 153), 5) + 1];
  };
  const j2d = (jy, jm, jd) => {
    const m = march(jy);
    return g2d(m[0], 3, m[1]) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
  };
  const j2g = (jy, jm, jd) => d2g(j2d(jy, jm, jd));
  const g2j = (gy, gm, gd) => {
    const jdn = g2d(gy, gm, gd);
    let jy = gy - 621;
    let k = jdn - j2d(jy, 1, 1);
    if (k >= 0 && k <= 185) return [jy, 1 + div(k, 31), mod(k, 31) + 1];
    if (k >= 0) k -= 186; else { jy -= 1; k = jdn - j2d(jy, 7, 1); }
    return [jy, 7 + div(k, 30), mod(k, 30) + 1];
  };
  const stamp = (y, m, d) => { const g = j2g(y, m, d); return Date.UTC(g[0], g[1] - 1, g[2]); };
  const monthDays = (y, m) => (m < 7 ? 31 : m < 12 ? 30 : (stamp(y + 1, 1, 1) - stamp(y, 12, 1)) / 86400000);
  const todayJ = () => { const n = new Date(); return g2j(n.getFullYear(), n.getMonth() + 1, n.getDate()); };
  const parse = (text) => {
    const p = String(text || '').replace(/[۰-۹]/g, (c) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(c)).split(/[/\-.\s]+/).map(Number);
    return p.length === 3 && p[0] > 1200 && p[0] < 1700 && p[1] >= 1 && p[1] <= 12 && p[2] >= 1 ? p : null;
  };

  let box = null; let input = null; let year = 0; let month = 0;
  const close = () => { if (box) box.remove(); box = null; input = null; };
  const place = () => {
    if (!box || !input) return;
    const r = input.getBoundingClientRect();
    const width = box.offsetWidth; const height = box.offsetHeight;
    box.style.left = `${Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8))}px`;
    box.style.top = `${r.bottom + height + 6 > window.innerHeight ? Math.max(8, r.top - height - 6) : r.bottom + 6}px`;
  };
  const pick = (y, m, d) => {
    input.value = d ? fa(`${y}/${pad(m)}/${pad(d)}`) : '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    close();
  };
  const draw = () => {
    const chosen = parse(input.value); const now = todayJ();
    const g = j2g(year, month, 1);
    const lead = (new Date(Date.UTC(g[0], g[1] - 1, g[2])).getUTCDay() + 1) % 7;
    let cells = DAYS.map((d) => `<b>${d}</b>`).join('') + '<span></span>'.repeat(lead);
    for (let d = 1; d <= monthDays(year, month); d += 1) {
      const on = chosen && chosen[0] === year && chosen[1] === month && chosen[2] === d;
      const today = now[0] === year && now[1] === month && now[2] === d;
      cells += `<button type="button" data-day="${d}" class="${on ? 'on' : ''}${today ? ' today' : ''}">${fa(d)}</button>`;
    }
    box.innerHTML = `<div class="jp-head"><button type="button" data-move="-1" aria-label="ماه قبل">›</button>`
      + `<strong>${MONTHS[month - 1]} ${fa(year)}</strong><button type="button" data-move="1" aria-label="ماه بعد">‹</button></div>`
      + `<div class="jp-grid">${cells}</div><div class="jp-foot"><button type="button" data-today="1">امروز</button>`
      + '<button type="button" data-clear="1">پاک کردن</button></div>';
    place();
  };
  const open = (el) => {
    if (input === el) return;
    close();
    if (!document.getElementById('jpStyle')) {
      const style = document.createElement('style'); style.id = 'jpStyle';
      style.textContent = '.jp{position:fixed;z-index:3000;width:276px;max-width:calc(100vw - 16px);direction:rtl;background:#fff;color:#1f2937;'
        + 'border:1px solid #d7dde5;border-radius:12px;padding:10px;box-shadow:0 14px 34px rgba(15,23,42,.2);font-size:14px}'
        + '.jp button{border:0;background:none;color:inherit;font:inherit;border-radius:8px;cursor:pointer}.jp button:hover{background:#eef3ec}'
        + '.jp-head,.jp-foot{display:flex;justify-content:space-between;align-items:center}.jp-head button{width:34px;height:32px;font-size:20px}'
        + '.jp-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;margin:8px 0;text-align:center}.jp-grid b{font-size:12px;color:#6b7280;padding:4px 0}'
        + '.jp-grid button{height:34px}.jp-grid .today{box-shadow:inset 0 0 0 1px #4b773c}.jp .jp-grid .on{background:#4b773c;color:#fff}'
        + '.jp-foot button{padding:5px 10px;color:#4b773c}';
      document.head.appendChild(style);
    }
    input = el;
    const start = parse(el.value) || todayJ();
    year = start[0]; month = start[1];
    box = document.createElement('div'); box.className = 'jp';
    box.addEventListener('mousedown', (e) => e.preventDefault());
    box.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.move) {
        month += Number(b.dataset.move);
        if (month < 1) { month = 12; year -= 1; } else if (month > 12) { month = 1; year += 1; }
        draw();
      } else if (b.dataset.day) pick(year, month, Number(b.dataset.day));
      else if (b.dataset.today) { const t = todayJ(); pick(t[0], t[1], t[2]); } else if (b.dataset.clear) pick(0, 0, 0);
    });
    document.body.appendChild(box);
    draw();
  };
  document.addEventListener('focusin', (e) => {
    const el = e.target.closest && e.target.closest(SELECTOR);
    if (el && !el.readOnly && !el.disabled) open(el); else if (!(box && box.contains(e.target))) close();
  });
  document.addEventListener('click', (e) => {
    const el = e.target.closest && e.target.closest(SELECTOR);
    if (el) open(el); else if (box && !box.contains(e.target)) close();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  window.addEventListener('resize', place);
  window.addEventListener('scroll', place, true);
})();
