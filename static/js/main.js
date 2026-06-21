// Translate via Django's JS catalog when available; fall back to the source string.
function T(s) { return (typeof window.gettext === 'function') ? window.gettext(s) : s; }

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

  applyTheme(theme) {
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

    this.setStoredTheme(resolvedTheme);
    this.refreshChartsTheme();
    return resolvedTheme;
  },

  toggleTheme() {
    const currentTheme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    return this.applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
  },

  initTheme() {
    const storedTheme = this.getStoredTheme();
    const preferredTheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    this.applyTheme(storedTheme || document.documentElement.dataset.theme || preferredTheme);
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
    this.initAiAnalysis();
    this.initEvalWizard();
  },

  // 3-step evaluation form: step navigation + province->city dependent dropdown.
  initEvalWizard() {
    const form = document.getElementById('evalForm');
    if (!form || form.dataset.wizardInit) return;
    const steps = Array.from(form.querySelectorAll('.wizard-step'));
    if (!steps.length) return;
    form.dataset.wizardInit = '1';

    const label = document.getElementById('wizardLabel');
    const bar = document.getElementById('wizardBar');
    const prev = document.getElementById('wizardPrev');
    const next = document.getElementById('wizardNext');
    const submit = document.getElementById('wizardSubmit');
    let cur = 0;

    const show = (i) => {
      steps.forEach((step, idx) => { step.hidden = idx !== i; });
      if (label) label.textContent = steps[i].getAttribute('data-step-label') || '';
      if (bar) bar.style.width = Math.round(((i + 1) / steps.length) * 100) + '%';
      if (prev) prev.hidden = i === 0;
      if (next) next.hidden = i === steps.length - 1;
      if (submit) submit.hidden = i !== steps.length - 1;
      cur = i;
    };

    const stepValid = (i) => {
      for (const el of steps[i].querySelectorAll('input, select, textarea')) {
        if (!el.checkValidity()) { el.reportValidity(); return false; }
      }
      return true;
    };

    if (next) next.addEventListener('click', () => { if (stepValid(cur)) show(Math.min(cur + 1, steps.length - 1)); });
    if (prev) prev.addEventListener('click', () => show(Math.max(cur - 1, 0)));

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
    ctx.font = '12px Vazirmatn, sans-serif';
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

        if (powerNode) powerNode.textContent = `${this.formatNumber(data.latest_power_kw || 0)} kW`;
        if (energyNode) energyNode.textContent = `${this.formatNumber(data.today_energy_kwh || 0)} kWh`;
        if (efficiencyNode) efficiencyNode.textContent = `${this.formatNumber(data.efficiency || 0)}%`;
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
      document.querySelectorAll('a[data-ajax="true"]').forEach((item) => item.classList.remove('active'));
      link.classList.add('active');
      window.SolarOps.refreshPanels();
    } catch (error) {
      console.error(error);
      window.location.href = url;
    }
  });
};

// Collapsible sidebar (hamburger) + accordion nav groups. Uses delegated
// listeners so it keeps working after AJAX panel swaps; state is persisted.
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

  document.addEventListener('click', (event) => {
    if (event.target.closest('#sidebarToggle')) {
      const app = document.querySelector('.app');
      if (app) {
        const collapsed = app.classList.toggle('nav-collapsed');
        try { localStorage.setItem('solarops-nav-collapsed', collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
      }
      return;
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
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (window.SolarOps && typeof window.SolarOps.initTheme === 'function') {
      window.SolarOps.initTheme();
    }
    if (window.SolarOps) {
      window.SolarOps.initAdminPanel();
      window.SolarOps.initOwnerPanel();
      window.SolarOps.initAiAnalysis();
      window.SolarOps.initPanelNavigation();
      window.SolarOps.initSidebar();
      window.SolarOps.initEvalWizard();
    }
  });
} else if (window.SolarOps && typeof window.SolarOps.initTheme === 'function') {
  window.SolarOps.initTheme();
  window.SolarOps.initAdminPanel();
  window.SolarOps.initOwnerPanel();
  window.SolarOps.initAiAnalysis();
  window.SolarOps.initPanelNavigation();
  window.SolarOps.initSidebar();
  window.SolarOps.initEvalWizard();
}
