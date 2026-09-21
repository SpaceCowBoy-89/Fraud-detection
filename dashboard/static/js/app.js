/* Fraud Detection Dashboard — Client JS */
/* ═══════════════════════════════════════════════════════════
   FRAUD DETECTION DASHBOARD — CLIENT
   ═══════════════════════════════════════════════════════════ */

// ─── State ───
let currentTab = 'overview';
let autoRefresh = false;
let refreshTimer = null;
let sortState = {};
let filterState = {};
let rawDataCache = {};  // Store unfiltered data for search/filter
let currentDrillAffiliate = null;

// ─── Theme ───
function initTheme() {
  const saved = localStorage.getItem('fd-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  updateThemeUI(saved);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('fd-theme', next);
  updateThemeUI(next);
  refreshApexChartsTheme();
  replotAll();
}
function updateThemeUI(theme) {
  document.getElementById('themeIcon').textContent = theme === 'dark' ? '☀' : '☽';
  document.getElementById('themeLabel').textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
}
// ═══════════════════════════════════════════════════════════
// APEXCHARTS HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════

// Store chart instances for later updates
const chartInstances = {};
const chartTypes = {}; // Store current type for each chart

function getApexTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  return {
    mode: isDark ? 'dark' : 'light',
    palette: 'palette1'
  };
}

function getApexBaseOptions(extra = {}) {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const darkLabelColor = '#aab6cf';
  const darkGridColor = '#2a3550';
  const {
    chart: xChart = {},
    xaxis: xAxis = {},
    yaxis: yAxis = {},
    grid: xGrid = {},
    tooltip: xTooltip = {},
    legend: xLegend = {},
    colors: xColors,
    showDataLabels: xShowDl,
    dataLabels: xDataLabels = {},
    ...passThrough
  } = extra;
  return {
    chart: {
      fontFamily: 'Outfit, system-ui, sans-serif',
      toolbar: {
        show: true,
        tools: {
          download: true,
          selection: false,
          zoom: false,
          zoomin: false,
          zoomout: false,
          pan: false,
          reset: false
        }
      },
      background: 'transparent',
      animations: {
        enabled: true,
        speed: 400,
        animateGradually: { enabled: true, delay: 150 }
      },
      ...xChart
    },
    theme: getApexTheme(),
    colors: xColors || ['#3b82f6', '#dc2626', '#d97706', '#059669', '#6366f1', '#8b5cf6'],
    dataLabels: {
      enabled: xShowDl !== undefined ? xShowDl : false,
      ...xDataLabels
    },
    grid: {
      borderColor: isDark ? darkGridColor : '#e5e7eb',
      strokeDashArray: 4,
      ...xGrid
    },
    xaxis: {
      labels: {
        style: { colors: isDark ? darkLabelColor : '#6b7280' },
        trim: true,
        rotate: -45,
        rotateAlways: false
      },
      ...xAxis
    },
    yaxis: {
      labels: { style: { colors: isDark ? darkLabelColor : '#6b7280' } },
      ...yAxis
    },
    tooltip: {
      theme: isDark ? 'dark' : 'light',
      ...xTooltip
    },
    legend: {
      labels: { colors: isDark ? darkLabelColor : '#6b7280' },
      position: 'top',
      horizontalAlign: 'left',
      ...xLegend
    },
    ...passThrough
  };
}

function renderApexChart(elementId, type, data, options = {}) {
  const el = document.getElementById(elementId);
  if (!el) {
    console.warn(`Chart element not found: ${elementId}`);
    return null;
  }
  
  // Destroy existing chart if it exists
  if (chartInstances[elementId]) {
    chartInstances[elementId].destroy();
  }
  
  // Store chart type
  chartTypes[elementId] = type;
  
  // Build chart options
  const chartOptions = getApexBaseOptions({
    chart: { type: type, height: options.height || 320, id: elementId },
    ...options
  });
  
  // Add data based on chart type
  if (type === 'pie' || type === 'donut') {
    chartOptions.series = data.values || data.series;
    chartOptions.labels = data.labels;
  } else if (type === 'radialBar') {
    chartOptions.series = data.values || data.series;
    chartOptions.labels = data.labels;
  } else {
    chartOptions.series = data.series;
    if (data.categories) {
      chartOptions.xaxis = { ...chartOptions.xaxis, categories: data.categories };
    }
  }
  
  // Create and render chart
  try {
    const chart = new ApexCharts(el, chartOptions);
    chart.render();
    chartInstances[elementId] = chart;
    return chart;
  } catch (error) {
    console.error(`Failed to render chart ${elementId}:`, error);
    el.innerHTML = `<div style="padding:20px;text-align:center;color:#ef4444;">Failed to render chart</div>`;
    return null;
  }
}

function downloadChart(chartId) {
  const chart = chartInstances[chartId];
  if (chart) {
    chart.dataURI().then(({ imgURI }) => {
      const link = document.createElement('a');
      link.href = imgURI;
      link.download = `${chartId}_${new Date().getTime()}.png`;
      link.click();
      showToast('Chart downloaded!');
    });
  }
}

function downloadChartData(chartId) {
  const chart = chartInstances[chartId];
  if (!chart) return;
  
  const series = chart.w.config.series;
  const categories = chart.w.config.xaxis?.categories || chart.w.config.labels || [];
  
  let csv = '';
  if (chart.w.config.chart.type === 'pie' || chart.w.config.chart.type === 'donut') {
    csv = 'Label,Value\n';
    categories.forEach((cat, idx) => {
      csv += `${cat},${series[idx]}\n`;
    });
  } else {
    csv = 'Category,' + series.map(s => s.name).join(',') + '\n';
    categories.forEach((cat, idx) => {
      csv += cat + ',' + series.map(s => s.data[idx] || 0).join(',') + '\n';
    });
  }
  
  const blob = new Blob([csv], { type: 'text/csv' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${chartId}_data_${new Date().getTime()}.csv`;
  const blobUrl = link.href;
  link.click();
  URL.revokeObjectURL(blobUrl);
  showToast('Chart data exported!');
}

function addChartControls(chartId, availableTypes = ['bar', 'line', 'area']) {
  const chartEl = document.getElementById(chartId);
  if (!chartEl) return;
  
  const parent = chartEl.parentElement;
  const controlsId = `${chartId}-controls`;
  
  // Remove existing controls
  const existing = document.getElementById(controlsId);
  if (existing) existing.remove();
  
  const currentType = chartTypes[chartId] || 'bar';
  
  const controls = document.createElement('div');
  controls.id = controlsId;
  controls.className = 'chart-controls';
  controls.innerHTML = `
    <label>Chart Type:</label>
    <select onchange="changeChartType('${chartId}', this.value)">
      ${availableTypes.map(t => `<option value="${t}" ${t === currentType ? 'selected' : ''}>${t.charAt(0).toUpperCase() + t.slice(1)}</option>`).join('')}
    </select>
    <button onclick="downloadChart('${chartId}')">📥 PNG</button>
    <button onclick="downloadChartData('${chartId}')">📊 CSV</button>
  `;
  
  parent.insertBefore(controls, chartEl);
}

function changeChartType(chartId, newType) {
  const chart = chartInstances[chartId];
  if (!chart) return;
  
  chart.updateOptions({
    chart: { type: newType }
  });
  chartTypes[chartId] = newType;
  showToast(`Chart type changed to ${newType}`);
}

/** Update theme-related options on all live ApexCharts instances (no refetch). */
function refreshApexChartsTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const labelColor = isDark ? '#aab6cf' : '#6b7280';
  const gridColor = isDark ? '#2a3550' : '#e5e7eb';
  Object.values(chartInstances).forEach(chart => {
    if (!chart || typeof chart.updateOptions !== 'function') return;
    try {
      chart.updateOptions({
        theme: getApexTheme(),
        grid: { borderColor: gridColor },
        xaxis: { labels: { style: { colors: labelColor } } },
        yaxis: { labels: { style: { colors: labelColor } } },
        tooltip: { theme: isDark ? 'dark' : 'light' },
        legend: { labels: { colors: labelColor } }
      }, false, true);
    } catch (e) {
      console.warn('ApexCharts theme refresh skipped:', e);
    }
  });
}

// ─── Navigation ───
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => switchTab(item.dataset.tab));
});

// Embed mode top nav tabs
document.querySelectorAll('.embed-tab').forEach(item => {
  item.addEventListener('click', () => switchTab(item.dataset.tab));
});

const tabTitles = {
  overview:  'Overview',
  review:    'Review Queue',
  reports:   'All Accounts',
  flags:     'Flags',
  affiliates:'Affiliates',
  campaigns: 'Campaigns',
  clusters:  'Clusters',
  temporal:  'Trends',
  anomaly:   'Analysis',
  eda:       'Data Explorer',
  settings:  'Settings'
};

function switchTab(tab) {
  currentTab = tab;
  // Sidebar items
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.tab === tab));
  // Embed top nav tabs
  document.querySelectorAll('.embed-tab').forEach(n => n.classList.toggle('active', n.dataset.tab === tab));
  // Panels
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tab));
  document.getElementById('pageTitle').textContent = tabTitles[tab] || tab;
  // Update search placeholder to match context
  const searchEl = document.getElementById('globalSearchInput');
  if (searchEl) {
    if (tab === 'affiliates') {
      searchEl.placeholder = 'Search affiliates... (Press /)';
    } else if (tab === 'campaigns') {
      searchEl.placeholder = 'Search campaigns... (Press /)';
    } else {
      searchEl.placeholder = 'Search emails, DUIDs... (Press /)';
    }
  }
  loadTabData(tab);
}

// ═══════════════════════════════════════════════════════════
// EMBED MODE
// ═══════════════════════════════════════════════════════════

/**
 * Enable embed mode — strips the sidebar, shows a compact top tab bar.
 * Call this from your platform:
 *   window.fraudDashboard.enableEmbedMode()
 * Or add ?embed=1 to the URL.
 */
function enableEmbedMode() {
  document.body.classList.add('embed-mode');
  localStorage.setItem('fraudDashboard_embedMode', '1');
}

function disableEmbedMode() {
  document.body.classList.remove('embed-mode');
  localStorage.removeItem('fraudDashboard_embedMode');
}

// Auto-detect embed mode from URL param or localStorage
(function() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('embed') === '1' || localStorage.getItem('fraudDashboard_embedMode') === '1') {
    document.body.classList.add('embed-mode');
  }
})();

// ═══════════════════════════════════════════════════════════
// ADMIN2 SESSION LOGIN (per user, not config file)
// ═══════════════════════════════════════════════════════════

function showAdmin2LoginOverlay(show) {
  const el = document.getElementById('admin2LoginOverlay');
  if (el) el.style.display = show ? 'flex' : 'none';
}

function setAdmin2LoginError(msg) {
  const el = document.getElementById('admin2LoginError');
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.style.display = 'block';
  } else {
    el.textContent = '';
    el.style.display = 'none';
  }
}

async function submitAdmin2Login(fromSettings) {
  const userEl = fromSettings
    ? document.getElementById('settingAdminUser')
    : document.getElementById('admin2LoginUser');
  const passEl = fromSettings
    ? document.getElementById('settingAdminPass')
    : document.getElementById('admin2LoginPass');
  const username = (userEl?.value || '').trim();
  const password = passEl?.value || '';
  if (!username || !password) {
    const msg = 'Username and password are required';
    if (fromSettings) showToast(msg, 'error');
    else setAdmin2LoginError(msg);
    return false;
  }
  setAdmin2LoginError('');
  try {
    const res = await fetch('/api/auth/admin2/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      const msg = data.error || 'Sign-in failed';
      if (fromSettings) showToast(msg, 'error');
      else setAdmin2LoginError(msg);
      return false;
    }
    if (passEl) passEl.value = '';
    showAdmin2LoginOverlay(false);
    showToast(`Signed in to admin2 (${data.username_preview || 'ok'})`, 'success');
    if (typeof loadSettings === 'function') loadSettings();
    return true;
  } catch (e) {
    const msg = 'Sign-in request failed: ' + e.message;
    if (fromSettings) showToast(msg, 'error');
    else setAdmin2LoginError(msg);
    return false;
  }
}

async function signOutAdmin2() {
  await fetch('/api/auth/admin2/logout', { method: 'POST', credentials: 'same-origin' });
  showToast('Signed out of admin2', 'info');
  if (typeof loadSettings === 'function') loadSettings();
  await ensureAdmin2Session();
}

function signInAdmin2FromSettings() {
  void submitAdmin2Login(true);
}

async function ensureAdmin2Session() {
  try {
    const res = await fetch('/api/auth/admin2/status', { credentials: 'same-origin' });
    const st = await res.json();
    if (st.login_required && !st.authenticated) {
      showAdmin2LoginOverlay(true);
    } else {
      showAdmin2LoginOverlay(false);
    }
    return st;
  } catch (_e) {
    showAdmin2LoginOverlay(false);
    return null;
  }
}

function bindAdmin2LoginUi() {
  document.getElementById('admin2LoginSubmit')?.addEventListener('click', () => {
    void submitAdmin2Login(false);
  });
  document.getElementById('admin2LoginPass')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void submitAdmin2Login(false);
  });
}

// Expose to parent window for iframe integration
window.fraudDashboard = {
  enableEmbedMode,
  disableEmbedMode,
  switchTab,
  version: '2.0.0'
};

// ═══════════════════════════════════════════════════════════
// ACCOUNT FRAUD WIDGET
// ═══════════════════════════════════════════════════════════

/**
 * Renders a compact fraud risk panel for a single account.
 * Use this on account detail pages in your internal platform.
 *
 * Usage:
 *   <div id="fraud-widget"></div>
 *   <script>
 *     initFraudWidget('384046981', document.getElementById('fraud-widget'));
 *   </script>
 */
async function initFraudWidget(duid, container) {
  if (!container) {
    container = document.getElementById('fraud-widget');
  }
  if (!container) return;
  
  container.innerHTML = `<div class="fraud-widget"><div class="fraud-widget-loading">Loading fraud data…</div></div>`;
  
  try {
    const res = await fetch(`/api/account/${duid}`);
    const data = await res.json();
    
    if (data.error || !data.duid) {
      container.innerHTML = `
        <div class="fraud-widget">
          <div class="fraud-widget-empty">No fraud data for this account yet.<br>
            <a href="#" onclick="switchTab('settings');return false;" style="color:var(--accent);font-size:12px;">Run Analysis →</a>
          </div>
        </div>`;
      return;
    }
    
    const score    = data.risk_score || 0;
    const level    = score >= 50 ? 'high' : score >= 25 ? 'medium' : 'low';
    const levelLbl = score >= 50 ? 'High Risk' : score >= 25 ? 'Medium Risk' : 'Low Risk';
    const flags    = data.flags ? data.flags.split('|').filter(Boolean) : [];
    
    container.innerHTML = `
      <div class="fraud-widget">
        <div class="fraud-widget-header">
          <span class="fraud-widget-title">Fraud Risk</span>
          <div class="fraud-widget-score">
            <span class="score-number" style="color:var(--risk-${level})">${score}</span>
            <span class="score-label ${level}">${levelLbl}</span>
          </div>
        </div>
        <div class="fraud-widget-body">
          <!-- Score bar -->
          <div class="score-bar-track">
            <div class="score-bar-fill ${level}" style="width:${score}%"></div>
          </div>
          
          <!-- Flags -->
          ${flags.length ? `
          <div class="fraud-widget-flags" style="margin-top:12px;">
            ${flags.slice(0,5).map(f => `<span class="flag-pill ${f.includes('POV') || f.includes('DOMAIN') ? 'medium' : ''}">${f.replace(/_/g,' ')}</span>`).join('')}
            ${flags.length > 5 ? `<span class="flag-pill">+${flags.length - 5} more</span>` : ''}
          </div>` : ''}
          
          <!-- Meta info -->
          <div class="fraud-widget-meta">
            <div class="meta-item">
              <span class="meta-label">DUID</span>
              <span class="meta-value">${data.duid}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Analyzed</span>
              <span class="meta-value">${data.analyzed_at ? new Date(data.analyzed_at).toLocaleDateString() : '—'}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Affiliate</span>
              <span class="meta-value">${data.webmaster_code || '—'}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Payout</span>
              <span class="meta-value">${data.payout_amount ? '$' + Number(data.payout_amount).toFixed(2) : '—'}</span>
            </div>
          </div>
          
          <!-- Actions -->
          <div class="fraud-widget-actions">
            <button class="w-btn primary" onclick="openHighRiskModal('${data.duid}')">View Details</button>
            <button class="w-btn" onclick="recordOutcome('${data.duid}','false_positive')">False Positive</button>
            <button class="w-btn danger" onclick="recordOutcome('${data.duid}','confirmed_fraud')">Confirm Fraud</button>
          </div>
        </div>
      </div>`;
      
  } catch (err) {
    container.innerHTML = `<div class="fraud-widget"><div class="fraud-widget-empty">Failed to load fraud data.</div></div>`;
    console.error('Fraud widget error:', err);
  }
}

// Convenience: auto-init any [data-fraud-duid] elements on the page
document.querySelectorAll('[data-fraud-duid]').forEach(el => {
  initFraudWidget(el.dataset.fraudDuid, el);
});

// ─── Sub-tabs (billing clusters only — scoped so other UI is unaffected) ───
document.querySelectorAll('.billing-subtab-host .sub-tab').forEach(st => {
  st.addEventListener('click', () => {
    const host = st.closest('.billing-subtab-host');
    if (!host) return;
    host.querySelectorAll('.sub-tab').forEach(s => s.classList.toggle('active', s === st));
    const sid = st.dataset.sub;
    host.querySelectorAll('.sub-panel').forEach(p => p.classList.toggle('active', p.id === 'sub-' + sid));
  });
});

function initMajorTabs(containerId, onSwitch) {
  const root = document.getElementById(containerId);
  if (!root) return;
  root.querySelectorAll('.major-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const panelId = btn.dataset.major;
      if (!panelId) return;
      root.querySelectorAll('.major-tab').forEach(b => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
      });
      root.querySelectorAll('.major-tab-panel').forEach(p => {
        const on = p.id === panelId;
        p.classList.toggle('active', on);
        p.style.display = on ? '' : 'none';
      });
      if (typeof onSwitch === 'function') onSwitch(panelId);
    });
  });
}

/** Reflow ApexCharts after a hidden major-tab panel becomes visible. */
function resizeAllCharts() {
  Object.values(chartInstances).forEach(chart => {
    try { chart?.resize?.(); } catch (_) { /* ignore */ }
  });
  ['_spikeChart', '_volumeAnomalyChart'].forEach(key => {
    try { window[key]?.resize?.(); } catch (_) { /* ignore */ }
  });
}

// ─── Auto-refresh ───
function toggleAutoRefresh() {
  autoRefresh = !autoRefresh;
  document.getElementById('autoRefreshBtn').classList.toggle('active', autoRefresh);
  clearInterval(refreshTimer);
  refreshTimer = null;
  if (autoRefresh) {
    refreshTimer = setInterval(() => {
      clearApiCache();
      loadTabData(currentTab);
    }, 30000);
  }
}

document.getElementById('autoRefreshBtn').addEventListener('click', toggleAutoRefresh);

document.getElementById('themeToggle').addEventListener('click', toggleTheme);

// ─── Helpers ───
function fmt(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtCur(n) { return n == null ? '—' : '$' + Number(n).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 }); }
function fmtPct(n) { return n == null ? 'N/A' : (n * 100).toFixed(1) + '%'; }
function riskBadge(score) {
  if (score >= 50) return `<span class="risk-badge high">${score}</span>`;
  if (score >= 25) return `<span class="risk-badge medium">${score}</span>`;
  return `<span class="risk-badge low">${score}</span>`;
}
function velocityBadge(change) {
  if (change === null || change === undefined) return '';
  const isUp = change > 0;
  const isDown = change < 0;
  const arrow = isUp ? '↑' : isDown ? '↓' : '→';
  const color = isUp ? 'var(--risk-high)' : isDown ? 'var(--risk-low)' : 'var(--text-muted)';
  const absChange = Math.abs(change);
  return `<span class="velocity-badge" style="color:${color}" title="vs previous 7 days">${arrow}${absChange}%</span>`;
}
function emptyState(icon, title, desc) {
  return `<div class="empty-state"><div class="empty-icon">${icon}</div><h3>${title}</h3><p>${desc}</p></div>`;
}
function errorState(title, desc, retry) {
  return `<div class="error-state"><div class="error-icon">⚠</div><h3>${title}</h3><p>${desc}</p>${retry ? `<button class="btn btn-primary" onclick="${retry}">Retry</button>` : ''}</div>`;
}
function loading() { return '<div class="loading-spinner">Loading data…</div>'; }
function truncate(s, n) { return s && s.length > n ? s.slice(0, n) + '…' : (s || '—'); }
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const CLUSTER_MODAL_PREVIEW_LIMIT = 25;

function parseAccountFlags(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v.map(f => String(f).trim()).filter(Boolean);
  return String(v).replace(/[\[\]']/g, '').split(',').map(f => f.trim()).filter(Boolean);
}

function renderClusterEmail(v) {
  const email = v || '—';
  return `<span class="cluster-email-cell" title="${escapeHtml(email)}">${escapeHtml(truncate(email, 42))}</span>`;
}

function renderClusterFlags(v) {
  const flags = parseAccountFlags(v);
  if (!flags.length) return '—';
  const labels = flags.map(f => f.toLowerCase().replace(/_/g, ' '));
  const title = labels.join(', ');
  const extra = flags.length > 1
    ? `<span class="flag-count-badge" title="${escapeHtml(title)}">+${flags.length - 1}</span>`
    : '';
  return `<span class="cluster-flag-cell"><span class="cluster-flag-primary" title="${escapeHtml(title)}">${escapeHtml(labels[0])}</span>${extra}</span>`;
}

function setClusterModalMode(active, title) {
  const dialog = document.querySelector('#accountModal .modal.account-modal');
  if (dialog) dialog.classList.toggle('cluster-mode', !!active);
  const titleEl = document.getElementById('accountModalTitle');
  if (titleEl) titleEl.textContent = title || (active ? 'Cluster Preview' : 'Account Details');
}

/** Small (?) next to table headers; stops sort when clicked. */
function thColumnHint(text) {
  return `<span class="th-info" onclick="event.stopPropagation()" data-tip="${escapeHtml(text)}" tabindex="0" role="img" aria-label="${escapeHtml(text)}">?</span>`;
}

// ─── Global floating tooltip (escapes overflow containers) ───
(function () {
  const TIP_ID = '_fd_tip';
  let tipEl = null;
  let hideTimer = null;

  function getTip() {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.id = TIP_ID;
      tipEl.style.cssText = [
        'position:fixed',
        'z-index:99999',
        'max-width:340px',
        'padding:7px 10px',
        'background:#1e293b',
        'color:#e2e8f0',
        'font-size:12px',
        'font-weight:400',
        'font-family:var(--font-sans,sans-serif)',
        'line-height:1.5',
        'border-radius:6px',
        'border:1px solid rgba(255,255,255,0.1)',
        'box-shadow:0 4px 12px rgba(0,0,0,0.4)',
        'pointer-events:none',
        'opacity:0',
        'transition:opacity 0.12s ease',
        'white-space:normal',
        'word-break:break-word',
      ].join(';');
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }

  function showTip(text, rect) {
    clearTimeout(hideTimer);
    const tip = getTip();
    tip.textContent = text;
    tip.style.opacity = '0';
    tip.style.display = 'block';

    // Position above the element; flip below if too close to top
    const GAP = 8;
    const tipH = tip.offsetHeight || 60;
    let top = rect.top - tipH - GAP;
    if (top < 6) top = rect.bottom + GAP;   // flip below
    let left = rect.left + rect.width / 2 - (tip.offsetWidth || 160) / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - (tip.offsetWidth || 160) - 8));
    tip.style.top = `${Math.round(top)}px`;
    tip.style.left = `${Math.round(left)}px`;
    tip.style.opacity = '1';
  }

  function hideTip() {
    hideTimer = setTimeout(() => {
      if (tipEl) tipEl.style.opacity = '0';
    }, 80);
  }

  document.addEventListener('mouseover', (e) => {
    const target = e.target.closest('[data-tip]');
    if (!target) return;
    showTip(target.dataset.tip, target.getBoundingClientRect());
  }, true);

  document.addEventListener('mouseout', (e) => {
    const target = e.target.closest('[data-tip]');
    if (!target) return;
    hideTip();
  }, true);

  document.addEventListener('scroll', hideTip, true);
}());

/** Short-lived GET response cache (tab switching); cleared on mutations and auto-refresh tick. */
const _apiResponseCache = new Map();
const API_CACHE_TTL_MS = 30000;

function clearApiCache() {
  _apiResponseCache.clear();
}

function _cloneForCache(data) {
  if (data == null || typeof data !== 'object') return data;
  try {
    return typeof structuredClone === 'function' ? structuredClone(data) : JSON.parse(JSON.stringify(data));
  } catch {
    return data;
  }
}

/**
 * @param {string} path
 * @param {RequestInit & { skipCache?: boolean }} [options] fetch options; set skipCache to bypass GET cache
 */
async function api(path, options = {}) {
  const skipCache = options.skipCache === true;
  const fetchOptions = { ...options };
  delete fetchOptions.skipCache;
  const method = (fetchOptions.method || 'GET').toUpperCase();

  if (method === 'GET' && !skipCache) {
    const hit = _apiResponseCache.get(path);
    if (hit && hit.expiresAt > Date.now()) {
      return { data: _cloneForCache(hit.data), error: null };
    }
  }

  try {
    const r = await fetch(path, { credentials: 'same-origin', ...fetchOptions });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      if (r.status === 401 && err.code === 'admin2_auth_required') {
        showAdmin2LoginOverlay(true);
      }
      throw new Error(err.error || `HTTP ${r.status}`);
    }
    const ct = r.headers.get('content-type') || '';
    const data = ct.includes('application/json') ? await r.json() : await r.text();
    if (method === 'GET' && !skipCache && typeof data === 'object' && data != null) {
      _apiResponseCache.set(path, { data: _cloneForCache(data), expiresAt: Date.now() + API_CACHE_TTL_MS });
    }
    return { data, error: null };
  } catch (e) {
    console.error(`API error ${path}:`, e);
    return { data: null, error: e.message };
  }
}

// ─── Keyboard Shortcuts ───
function toggleShortcuts() {
  document.getElementById('shortcutsPanel').classList.toggle('open');
}

document.addEventListener('keydown', e => {
  // Ignore if typing in input/textarea
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  
  // Close modals/panels on Escape
  if (e.key === 'Escape') {
    closeModal();
    closeAccountModal();
    closeDrilldown();
    hideSearchResults();
    closeCommandPalette();
    closeFabMenu();
    document.getElementById('shortcutsPanel').classList.remove('open');
    return;
  }
  
  // Number keys for tabs (use 0 for 10+)
  const tabMap = {
    '1': 'overview',  '2': 'reports',    '3': 'flags',
    '4': 'affiliates','5': 'campaigns',  '6': 'clusters',
    '7': 'temporal',  '8': 'anomaly',    '9': 'eda',    '0': 'settings'
  };
  if (tabMap[e.key]) {
    switchTab(tabMap[e.key]);
    return;
  }
  
  // Other shortcuts
  switch (e.key.toLowerCase()) {
    case 't':
      toggleTheme();
      break;
    case 'r':
      document.getElementById('autoRefreshBtn').click();
      break;
    case '/':
      e.preventDefault();
      focusCurrentSearch();
      break;
    case '?':
      toggleShortcuts();
      break;
  }
});

function focusCurrentSearch() {
  // Always focus global search with /
  const globalSearch = document.getElementById('globalSearchInput');
  if (globalSearch) {
    globalSearch.focus();
    return;
  }
  
  // Fallback to tab-specific search
  const searchIds = {
    review: 'searchHighRisk',
    affiliates: 'searchAffiliates',
    billing: 'searchBilling'
  };
  const id = searchIds[currentTab];
  if (id) {
    const el = document.getElementById(id);
    if (el) el.focus();
  }
}

// ─── Export Functions ───
function exportData(type, params = {}) {
  let url = `/api/export/${type}`;
  const queryParams = new URLSearchParams(params).toString();
  if (queryParams) url += '?' + queryParams;
  
  // Create hidden link and click
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  
  showToast('Download started...');
}

function exportAffiliate(code) {
  exportData(`affiliate/${encodeURIComponent(code)}`);
}

function exportHighRisk() {
  exportData('fraud-results', { min_risk: 50 });
}

async function downloadFlagReference(format) {
  const fmt = String(format || 'csv').toLowerCase();
  const ext = fmt === 'md' ? 'md' : fmt === 'json' ? 'json' : 'csv';
  const url = `/api/export/flag-reference?format=${encodeURIComponent(fmt)}`;
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) {
      let msg = `Export failed (${res.status})`;
      try {
        const j = await res.json();
        if (j && j.error) msg = j.error;
      } catch (_) { /* blob body */ }
      showToast(msg, 'error');
      return;
    }
    const blob = await res.blob();
    const stamp = new Date().toISOString().slice(0, 10);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `fraud_flags_reference_${stamp}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    showToast('Flag reference downloaded', 'success');
  } catch (e) {
    showToast('Download failed: ' + (e.message || e), 'error');
  }
}

// ─── Search & Filter ───
const filterDebounceTimers = {};
const TABLE_PAGE_SIZE = 50;
const tablePageState = {};
const PAGINATED_TABLE_IDS = new Set(['hr', 'aff', 'camp', 'campDrill', 'pend']);

function resetTablePage(tableId) {
  tablePageState[tableId] = 1;
}

function getTablePageSlice(tableId, rows, pageSize = TABLE_PAGE_SIZE) {
  const totalRows = rows.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  let page = tablePageState[tableId] || 1;
  page = Math.max(1, Math.min(page, totalPages));
  tablePageState[tableId] = page;
  const start = (page - 1) * pageSize;
  return { pageRows: rows.slice(start, start + pageSize), page, totalPages, totalRows, pageSize };
}

function updateTablePagination(tableId, page, totalPages, totalRows, pageSize = TABLE_PAGE_SIZE) {
  const el = document.getElementById(`${tableId}Pagination`);
  if (!el) return;
  if (totalRows <= pageSize) {
    el.style.display = 'none';
    return;
  }
  el.style.display = 'block';
  const info = document.getElementById(`${tableId}PageInfo`);
  if (info) info.textContent = `Page ${page} of ${totalPages} (${fmt(totalRows)} rows)`;
  const prev = document.getElementById(`${tableId}PrevPage`);
  const next = document.getElementById(`${tableId}NextPage`);
  if (prev) prev.disabled = page <= 1;
  if (next) next.disabled = page >= totalPages;
}

function goTablePage(tableId, page) {
  tablePageState[tableId] = page;
  const searchMap = {
    hr: 'searchHighRisk',
    aff: 'searchAffiliates',
    camp: 'searchCampaigns',
    campDrill: 'searchCampDrill',
  };
  const searchEl = searchMap[tableId] ? document.getElementById(searchMap[tableId]) : null;
  if (tableId === 'pend') {
    renderPendingTable();
    return;
  }
  filterTable(tableId, searchEl?.value || '', { resetPage: false });
}

function goTablePrevPage(tableId) {
  goTablePage(tableId, (tablePageState[tableId] || 1) - 1);
}

function goTableNextPage(tableId) {
  goTablePage(tableId, (tablePageState[tableId] || 1) + 1);
}

function filterTableDebounced(tableId, searchText) {
  clearTimeout(filterDebounceTimers[tableId]);
  filterDebounceTimers[tableId] = setTimeout(() => filterTable(tableId, searchText), 200);
}

function filterTable(tableId, searchText, opts = {}) {
  const rawData = rawDataCache[tableId];
  if (!rawData || !rawData.length) return;
  if (opts.resetPage !== false) resetTablePage(tableId);
  
  // Get current search text
  searchText = searchText ?? '';
  const searchLower = searchText.toLowerCase().trim();
  
  // Get filter values based on table
  let filterFn = () => true;
  
  if (tableId === 'hr') {
    const typeFilter = document.getElementById('filterHighRiskType')?.value;
    const houseFilter = document.getElementById('filterHighRiskHouse')?.value || 'external';
    const flagFilter = document.getElementById('filterHighRiskFlag')?.value || '';
    const hideActioned = document.getElementById('filterHighRiskHideActioned')?.checked;
    const houseLower = new Set(houseAffiliates.map(h => h.toLowerCase()));
    const externalExclude = externalOnlyExcludeLower();
    
    filterFn = row => {
      // Type filter
      if (typeFilter && row.data_type !== typeFilter) return false;
      
      // House filter
      const code = (row.webmaster_code || '').toLowerCase();
      const isHouse = houseLower.has(code);
      if (houseFilter === 'external' && externalExclude.has(code)) return false;
      if (houseFilter === 'house' && !isHouse) return false;

      if (hideActioned) {
        const act = affiliateActionsByCode[code];
        if (act && act.action_status === 'actioned') return false;
      }
      
      // Flag filter
      if (flagFilter && row.flags) {
        const flags = String(row.flags).toUpperCase();
        if (!flags.includes(flagFilter)) return false;
      } else if (flagFilter && !row.flags) {
        return false;
      }
      
      return true;
    };
  } else if (tableId === 'aff') {
    const riskFilter = document.getElementById('filterAffRisk')?.value;
    const houseFilter = document.getElementById('filterAffHouse')?.value || 'external';
    const hideActioned = document.getElementById('filterAffHideActioned')?.checked;
    const houseLower = new Set(houseAffiliates.map(h => h.toLowerCase()));
    const externalExclude = externalOnlyExcludeLower();
    
    filterFn = row => {
      const code = (row.webmaster_code || '').toLowerCase();
      const isHouse = houseLower.has(code);
      
      // House filter
      if (houseFilter === 'external' && externalExclude.has(code)) return false;
      if (houseFilter === 'house' && !isHouse) return false;

      if (hideActioned) {
        const act = affiliateActionsByCode[code];
        if (act && act.action_status === 'actioned') return false;
      }
      
      // Risk filter
      if (riskFilter === 'high' && (row.high_risk_count || 0) === 0) return false;
      if (riskFilter === 'clean' && (row.high_risk_count || 0) > 0) return false;
      return true;
    };
  } else if (tableId === 'drill') {
    const riskFilter = document.getElementById('filterDrillRisk')?.value;
    filterFn = row => {
      if (riskFilter && (row.risk_score || 0) < parseInt(riskFilter)) return false;
      return true;
    };
  } else if (tableId === 'camp') {
    const riskFilter = document.getElementById('filterCampRisk')?.value;
    filterFn = row => {
      if (riskFilter === 'high' && (row.high_risk_pct || 0) < 30) return false;
      if (riskFilter === 'medium' && ((row.high_risk_pct || 0) < 15 || (row.high_risk_pct || 0) >= 30)) return false;
      return true;
    };
  } else if (tableId === 'campDrill') {
    const riskFilter = document.getElementById('filterCampDrillRisk')?.value;
    filterFn = row => {
      if (riskFilter === 'high' && (row.risk_score || 0) < 50) return false;
      return true;
    };
  }

  // Apply search and filter
  const filtered = rawData.filter(row => {
    if (!filterFn(row)) return false;
    if (!searchLower) return true;
    
    // Search across relevant fields
    const searchFields = ['email', 'flags', 'webmaster_code', 'campaign', 'duid', 'review_outcome'];
    return searchFields.some(field => {
      const val = row[field];
      return val && String(val).toLowerCase().includes(searchLower);
    });
  });
  
  // Update count display
  const countEl = document.getElementById(`${tableId}SearchCount`);
  if (countEl) {
    if (searchLower || filtered.length !== rawData.length) {
      countEl.textContent = `${filtered.length} of ${rawData.length}`;
    } else {
      countEl.textContent = '';
    }
  }
  
  // Update main count for specific tables
  if (tableId === 'hr') {
    const hrc = document.getElementById('highRiskCount');
    if (hrc) hrc.textContent = `${filtered.length} accounts`;
  } else if (tableId === 'aff') {
    document.getElementById('affCount').textContent = `${filtered.length} affiliates`;
  } else if (tableId === 'camp') {
    document.getElementById('campaignCount').textContent = `${filtered.length} campaigns`;
  } else if (tableId === 'campDrill') {
    const el = document.getElementById('campDrillCount');
    if (el) el.textContent = `${filtered.length} accounts`;
  }
  
  // Re-render table with filtered data
  renderFilteredTable(tableId, filtered);
}

function renderFilteredTable(tableId, data) {
  const configs = {
    hr: {
      wrap: 'highRiskTableWrap',
      columns: [
        { key: 'duid', label: '☐', render: (v, row) => `<input type="checkbox" class="bulk-checkbox" data-duid="${v}" onclick="event.stopPropagation();toggleBulkSelect('${v}', this)" ${_bulkSelected.has(v) ? 'checked' : ''}>` },
        { key: 'email', label: 'Email', hint: 'Email address on the analyzed record.' },
        { key: 'risk_score', label: 'Risk', numeric: true, right: true, hint: 'Fraud model score from 0–100. 50+ is treated as high risk (you can change the cutoff in Settings).', render: v => riskBadge(v) },
        { key: 'payout_amount', label: 'Payout', numeric: true, right: true, hint: 'Payout tied to this row when the source file includes it.', render: v => fmtCur(v) },
        { key: 'webmaster_code', label: 'Affiliate', muted: true, hint: 'Affiliate / webmaster code for this account.', render: (v, row) => {
          const code = v || (row && row.webmaster_code) || '';
          if (!code) return '—';
          const pill = affiliateActionPillHtml(code);
          if (!pill) return code;
          return `<span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;"><span>${code}</span>${pill}</span>`;
        } },
        { key: 'flags', label: 'Flags', muted: true, hint: 'Short labels for rules that added risk (hover the … on a flag chip in other views for the full reason).', render: v => truncate(String(v), 40) }
      ],
      opts: { clickable: true, onClick: 'openHighRiskModalByDuid', onClickKey: 'duid', emptyIcon: '⊘', emptyTitle: 'No matching accounts' }
    },
    aff: {
      wrap: 'affiliatesTableWrap',
      columns: [
        { key: 'webmaster_code', label: 'Affiliate', hint: 'Affiliate code; click row to drill into accounts.', render: v => `
          <span style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-family:var(--mono);font-size:12px;">${v}</span>
            ${affiliateActionPillHtml(v)}
            <a href="/affiliate/${encodeURIComponent(v)}" target="_blank"
               onclick="event.stopPropagation()"
               style="font-size:10px;color:var(--accent);text-decoration:none;opacity:0.7;padding:2px 5px;border:1px solid var(--border);border-radius:3px;white-space:nowrap;transition:opacity 0.1s;"
               onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'"
               title="Open affiliate detail page">↗</a>
          </span>` },
        { key: 'total_accounts', label: 'Total', numeric: true, right: true, hint: 'Rows in fraud_results for this affiliate (all risk levels).', render: v => fmt(v) },
        { key: 'high_risk_count', label: 'High', numeric: true, right: true, hint: 'Count with risk score ≥ high-risk threshold (typically 50).', render: v => `<span style="color:var(--risk-high)">${fmt(v)}</span>` },
        { key: 'medium_risk_count', label: 'Med', numeric: true, right: true, hint: 'Count with score in the medium band (e.g. 25–49), per config.', render: v => `<span style="color:var(--risk-medium)">${fmt(v)}</span>` },
        { key: 'high_risk_pct', label: 'High %', numeric: true, right: true, hint: 'High-risk count ÷ total accounts × 100.', render: v => (v != null ? v.toFixed(1) + '%' : '—') },
        { key: 'avg_risk_score', label: 'Avg Risk', numeric: true, right: true, hint: 'Mean risk_score across all accounts for this affiliate.', render: v => v != null ? v.toFixed(0) : '—' },
        { key: 'high_risk_payout', label: 'HR Payout', numeric: true, right: true, hint: 'Sum of payout_amount for high-risk accounts only.', render: v => fmtCur(v) },
        { key: 'confirmed_fraud_count', label: 'CF #', numeric: true, right: true, hint: 'Accounts with a review outcome of confirmed fraud.', render: v => `<span style="color:var(--risk-high)">${fmt(v || 0)}</span>` },
        { key: 'confirmed_fraud_payout', label: 'CF $', numeric: true, right: true, hint: 'Financial total for confirmed fraud.', render: v => fmtCur(v || 0) },
        { key: 'webmaster_code', label: '7-Day', hint: 'Mini chart: high-risk count per day for the last 7 days.', render: (code) => buildSparkline(_sparklines[code] || []) + spikeChipForAffiliate(code) }
      ],
      opts: { clickable: true, onClick: 'drillAffiliateByCode', onClickKey: 'webmaster_code', emptyIcon: '⊞', emptyTitle: 'No matching affiliates' }
    },
    drill: {
      wrap: 'drillTableWrap',
      columns: [
        { key: 'email', label: 'Email', render: v => truncate(v, 36) },
        { key: 'risk_score', label: 'Risk', numeric: true, right: true, hint: 'Model risk score at last analysis.', render: v => riskBadge(v) },
        { key: 'payout_amount', label: 'Payout', numeric: true, right: true, hint: 'Payout on the source record.', render: v => fmtCur(v) },
        { key: 'review_outcome', label: 'Review', muted: true, hint: 'Manual review outcome. Extra $ shows confirmed-fraud payout when stored.', render: (v, row) => {
          if (!v) return '—';
          const m = { confirmed_fraud: 'Fraud', false_positive: 'FP', under_review: 'Review', legitimate: 'OK' };
          const lbl = m[v] || String(v);
          const cf = row && row.confirmed_fraud_payout;
          const extra = (v === 'confirmed_fraud' && cf != null && Number(cf) > 0) ? ` ${fmtCur(cf)}` : '';
          return lbl + extra;
        } },
        { key: 'campaign', label: 'Campaign', muted: true },
        { key: 'flags', label: 'Flags', muted: true, hint: 'Rules that flagged this account.', render: v => truncate(String(v), 40) }
      ],
      opts: { clickable: true, onClick: 'openDrillModal', emptyIcon: '⊘', emptyTitle: 'No matching accounts' }
    },
    camp: {
      wrap: 'campaignsTableWrap',
      columns: [
        { key: 'campaign', label: 'Campaign', hint: 'Campaign name on analyzed records.', render: v => truncate(v, 30) },
        { key: 'total_accounts', label: 'Total', numeric: true, right: true, hint: 'All accounts in this campaign in fraud_results.', render: v => fmt(v) },
        { key: 'high_risk_count', label: 'High', numeric: true, right: true, hint: 'Count with risk ≥ high-risk threshold.', render: v => `<span style="color:var(--risk-high)">${fmt(v)}</span>` },
        { key: 'high_risk_pct', label: 'High %', numeric: true, right: true, hint: 'High-risk ÷ total × 100. Color bands: ~15% / 30% UI thresholds.', render: v => {
          const color = v >= 30 ? 'var(--risk-high)' : v >= 15 ? 'var(--risk-medium)' : 'var(--risk-low)';
          return `<span style="color:${color}">${v}%</span>`;
        }},
        { key: 'avg_risk_score', label: 'Avg Risk', numeric: true, right: true, hint: 'Mean risk_score for the campaign.', render: v => v?.toFixed(0) || '—' },
        { key: 'high_risk_payout', label: 'HR Payout', numeric: true, right: true, hint: 'Sum of payout for high-risk rows only.', render: v => fmtCur(v) },
        { key: 'affiliate_count', label: 'Affiliates', numeric: true, right: true, hint: 'Distinct webmaster codes seen on this campaign.' }
      ],
      opts: { clickable: true, onClick: 'drillCampaign', emptyIcon: '📣', emptyTitle: 'No matching campaigns' }
    },
    campDrill: {
      wrap: 'campDrillTableWrap',
      columns: [
        { key: 'email', label: 'Email', render: v => truncate(v, 36) },
        { key: 'risk_score', label: 'Risk', numeric: true, right: true, hint: 'Model risk score.', render: v => riskBadge(v) },
        { key: 'webmaster_code', label: 'Affiliate', muted: true },
        { key: 'payout_amount', label: 'Payout', numeric: true, right: true, hint: 'Payout on record.', render: v => fmtCur(v) },
        { key: 'flags', label: 'Flags', muted: true, hint: 'Detection flags fired.', render: v => truncate(String(v), 40) }
      ],
      opts: { clickable: true, onClick: 'openCampDrillModalByDuid', onClickKey: 'duid', emptyIcon: '⊘', emptyTitle: 'No accounts' }
    }
  };

  const config = configs[tableId];
  if (!config) return;

  // Need to update the data reference for click handlers
  if (tableId === 'hr') _highRiskData = data;
  else if (tableId === 'aff') affiliatesData = data;
  else if (tableId === 'drill') _drillData = data;
  else if (tableId === 'camp') _campaignsData = data;
  else if (tableId === 'campDrill') _campDrillData = data;

  let rows = data;
  let pageMeta = null;
  if (PAGINATED_TABLE_IDS.has(tableId)) {
    pageMeta = getTablePageSlice(tableId, data);
    rows = pageMeta.pageRows;
  }

  document.getElementById(config.wrap).innerHTML = buildTable(tableId, config.columns, rows, config.opts);
  if (pageMeta) {
    updateTablePagination(tableId, pageMeta.page, pageMeta.totalPages, pageMeta.totalRows, pageMeta.pageSize);
  }
}

// ─── Toast ───
function showToast(msg, type = 'success') {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3000);
}

// ─── Outcome Modal ───
let _modalDuid = null;
function openOutcomeModal(duid, email) {
  _modalDuid = duid;
  document.getElementById('modalDuid').textContent = duid || '—';
  document.getElementById('modalEmail').textContent = email || '—';
  document.getElementById('outcomeNotes').value = '';
  document.querySelectorAll('#outcomeOptions input').forEach(r => r.checked = false);
  document.querySelectorAll('.outcome-opt').forEach(o => o.classList.remove('selected'));
  document.getElementById('outcomeSubmit').disabled = true;
  document.getElementById('outcomeModal').classList.add('open');
}
function closeModal() {
  document.getElementById('outcomeModal').classList.remove('open');
  _modalDuid = null;
}
document.querySelectorAll('#outcomeOptions .outcome-opt').forEach(opt => {
  opt.addEventListener('click', () => {
    opt.querySelector('input').checked = true;
    document.querySelectorAll('.outcome-opt').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected');
    document.getElementById('outcomeSubmit').disabled = false;
  });
});
document.getElementById('outcomeModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});
async function submitOutcome() {
  const outcome = document.querySelector('#outcomeOptions input:checked')?.value;
  if (!outcome || !_modalDuid) return;
  const notes = document.getElementById('outcomeNotes').value.trim();
  document.getElementById('outcomeSubmit').disabled = true;
  try {
    const r = await fetch('/api/outcomes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duid: _modalDuid, outcome, notes })
    });
    const data = await r.json();
    if (r.ok) {
      showToast('Outcome recorded for ' + _modalDuid);
      closeModal();
      clearApiCache();
      loadTabData(currentTab);
    } else {
      showToast(data.error || 'Failed to record outcome', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
  document.getElementById('outcomeSubmit').disabled = false;
}

// ─── Pending review inline actions ───
let _pendingData = [];
async function pendingAction(idx, outcome) {
  const row = _pendingData[idx];
  if (!row) return;
  try {
    const r = await fetch('/api/outcomes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duid: row.duid, outcome, notes: '' })
    });
    const data = await r.json();
    if (r.ok) {
      showToast('Marked ' + row.duid + ' as ' + outcome.replace('_', ' '));
      clearApiCache();
      loadTabData(currentTab);
    } else {
      showToast(data.error || 'Failed', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
}

// ─── Sortable Table Builder ───
function buildTable(id, columns, rows, opts = {}) {
  if (!rows || rows.length === 0) {
    return emptyState(opts.emptyIcon || '◌', opts.emptyTitle || 'No data', opts.emptyDesc || 'No records available yet.');
  }

  if (!sortState[id]) sortState[id] = { col: null, dir: 'desc' };

  const state = sortState[id];
  if (state.col !== null) {
    const col = columns[state.col];
    rows = [...rows].sort((a, b) => {
      let va = a[col.key], vb = b[col.key];
      if (col.numeric) { va = Number(va) || 0; vb = Number(vb) || 0; }
      else { va = String(va || '').toLowerCase(); vb = String(vb || '').toLowerCase(); }
      if (va < vb) return state.dir === 'asc' ? -1 : 1;
      if (va > vb) return state.dir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  let html = `<table class="data-table${opts.noSort ? ' no-sort' : ''}"><thead><tr>`;
  columns.forEach((col, i) => {
    const cls = [col.right ? 'right' : '', state.col === i ? (state.dir === 'asc' ? 'sorted-asc' : 'sorted-desc') : ''].filter(Boolean).join(' ');
    const hint = col.hint ? thColumnHint(col.hint) : '';
    html += `<th class="${cls}" data-table-id="${id}" data-col="${i}">${col.label}${hint}</th>`;
  });
  html += '</tr></thead><tbody>';
  rows.forEach((row, ri) => {
    const cls = opts.clickable ? 'clickable' : '';
    let click = '';
    if (opts.clickable) {
      if (opts.onClickKey) {
        const keyVal = row[opts.onClickKey];
        click = `onclick="${opts.onClick}('${encodeURIComponent(String(keyVal != null ? keyVal : ''))}')"`;
      } else {
        click = `onclick="${opts.onClick}(${ri})"`;
      }
    }
    html += `<tr class="${cls}" ${click}>`;
    columns.forEach(col => {
      const val = col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—');
      html += `<td class="${col.right ? 'right' : ''} ${col.muted ? 'muted' : ''}">${val}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  return html;
}

// Global sort handler
document.addEventListener('click', e => {
  if (e.target.closest('.th-info')) return;
  const th = e.target.closest('th[data-table-id]');
  if (!th) return;
  if (th.closest('.data-table.no-sort')) return;
  const id = th.dataset.tableId;
  const col = parseInt(th.dataset.col);
  if (!sortState[id]) sortState[id] = { col: null, dir: 'desc' };
  if (sortState[id].col === col) {
    sortState[id].dir = sortState[id].dir === 'asc' ? 'desc' : 'asc';
  } else {
    sortState[id].col = col;
    sortState[id].dir = 'desc';
  }
  loadTabData(currentTab);
});

// ─── Data cache for drill-down ───
let affiliatesData = [];
let _drillData = [];

function replotAll() {
  loadTabData(currentTab);
}

// ═══════════════════════════════════════════════════════════
// TAB DATA LOADERS
// ═══════════════════════════════════════════════════════════

async function loadTabData(tab) {
  document.getElementById('lastUpdated').textContent = new Date().toLocaleTimeString();

  switch (tab) {
    case 'overview':   return loadOverview();
    case 'review':     return loadReviewQueue();
    case 'affiliates': return loadAffiliates();
    case 'campaigns':  return loadCampaigns();
    case 'reports':    return loadReports();
    case 'flags':      return loadFlagsTab();
    case 'temporal':   return loadTemporal();
    // Merged tabs — call all constituent loaders
    case 'clusters':
      loadClusters();
      return loadBilling();
    case 'anomaly':
      return loadAnalysisSubTab(getActiveAnalysisSubTab());
    case 'eda':
      initEDAAffiliateList();
      return loadExplore();
    case 'settings':
      loadSchedulerStatus();
      loadSchedulerHistory();
      loadSettings();
      return loadActionsTab();
  }
}

// ═══════════════════════════════════════════════════════════
// GLOBAL SEARCH
// ═══════════════════════════════════════════════════════════

let searchTimeout = null;
let searchResultsVisible = false;

function handleGlobalSearch(event) {
  const query = event.target.value.trim();
  
  // Clear previous timeout
  if (searchTimeout) clearTimeout(searchTimeout);
  
  // Handle enter key
  if (event.key === 'Enter' && query.length >= 2) {
    performSearch(query);
    return;
  }
  
  // Debounce search
  if (query.length >= 2) {
    searchTimeout = setTimeout(() => performSearch(query), 300);
  } else {
    hideSearchResults();
  }
}

async function performSearch(query) {
  const resultsEl = document.getElementById('globalSearchResults');
  resultsEl.classList.add('active');
  resultsEl.innerHTML = '<div class="search-loading">Searching...</div>';

  // Scope search by active tab
  const scopeMap = {
    affiliates: 'affiliates',
    campaigns:  'campaigns',
  };
  const accountTabs = new Set(['overview', 'review', 'reports', 'flags', 'clusters', 'temporal', 'anomaly', 'eda', 'billing', 'settings']);
  const scope = scopeMap[currentTab] || (accountTabs.has(currentTab) ? 'accounts' : 'accounts');

  const res = await api(`/api/search?q=${encodeURIComponent(query)}&limit=20&scope=${scope}`);
  
  if (res.error) {
    resultsEl.innerHTML = `<div class="search-no-results">Error: ${res.error}</div>`;
    return;
  }
  
  const results = res.data?.results || [];
  
  if (results.length === 0) {
    resultsEl.innerHTML = '<div class="search-no-results">No results found</div>';
    return;
  }
  
  resultsEl.innerHTML = results.map((r) => {
    if (r.type === 'affiliate') {
      const fraudPct = r.total_accounts > 0 ? Math.round(100 * r.high_risk_count / r.total_accounts) : 0;
      return `
        <div class="search-result-item" onclick="hideSearchResults();window.location.href='/affiliate/${encodeURIComponent(r.webmaster_code)}'" title="Open affiliate detail">
          <div class="search-result-email">${r.webmaster_code}</div>
          <div class="search-result-meta">
            <span class="search-result-risk ${fraudPct >= 50 ? '' : fraudPct >= 25 ? 'medium' : 'low'}">Fraud: ${fraudPct}%</span>
            <span>${r.total_accounts.toLocaleString()} accounts</span>
            <span>$${r.total_payout?.toFixed(2) ?? '—'} payout</span>
            <span style="opacity:0.5">affiliate</span>
          </div>
        </div>`;
    }
    if (r.type === 'campaign') {
      const fraudPct = r.total_accounts > 0 ? Math.round(100 * r.high_risk_count / r.total_accounts) : 0;
      return `
        <div class="search-result-item" onclick="openCampaignFromSearch(${JSON.stringify(r.campaign || '')})" title="View campaign accounts">
          <div class="search-result-email">${escapeHtml(r.campaign)}</div>
          <div class="search-result-meta">
            <span class="search-result-risk ${fraudPct >= 50 ? '' : fraudPct >= 25 ? 'medium' : 'low'}">Fraud: ${fraudPct}%</span>
            <span>${r.total_accounts.toLocaleString()} accounts</span>
            <span>$${r.total_payout?.toFixed(2) ?? '—'} payout</span>
            <span style="opacity:0.5">campaign</span>
          </div>
        </div>`;
    }
    // Account result (default)
    return `
      <div class="search-result-item" onclick="openAccountDetail('${r.duid}')" title="Click to view account detail">
        <div class="search-result-email">${r.email || 'No email'}</div>
        <div class="search-result-meta">
          <span class="search-result-risk ${r.risk_score >= 50 ? '' : r.risk_score >= 25 ? 'medium' : 'low'}">
            ${r.risk_score != null ? `Risk: ${r.risk_score}` : 'Not analyzed'}
          </span>
          ${r.webmaster_code
            ? `<span class="search-aff-link" onclick="event.stopPropagation();hideSearchResults();window.location.href='/affiliate/${encodeURIComponent(r.webmaster_code)}'" title="Open affiliate detail page">${r.webmaster_code} ↗</span>`
            : '<span>—</span>'}
          <span>${r.data_type || '—'}</span>
          <span style="opacity:0.5">${r.match_type}</span>
        </div>
      </div>`;
  }).join('');
}

function showSearchResults() {
  const query = document.getElementById('globalSearchInput').value.trim();
  if (query.length >= 2) {
    document.getElementById('globalSearchResults').classList.add('active');
  }
}

function hideSearchResults() {
  document.getElementById('globalSearchResults').classList.remove('active');
}

function hideSearchResultsDelayed() {
  setTimeout(hideSearchResults, 200);
}

// ═══════════════════════════════════════════════════════════
// ACCOUNT DETAIL MODAL
// ═══════════════════════════════════════════════════════════

async function openAccountDetail(duid) {
  const modal = document.getElementById('accountModal');
  const body = document.getElementById('accountModalBody');

  setClusterModalMode(false, 'Account Details');
  modal.classList.add('open');
  body.innerHTML = '<div class="loading-spinner">Loading account details...</div>';
  
  // Hide search results
  hideSearchResults();
  document.getElementById('globalSearchInput').value = '';
  
  const res = await api(`/api/account/${encodeURIComponent(duid)}`);
  
  if (res.error) {
    body.innerHTML = `<div class="error-state"><p>Error loading account: ${res.error}</p></div>`;
    return;
  }
  
  const data = res.data;
  const account = data.account || {};
  const outcomes = data.outcomes || [];
  const relatedByEmail = data.related_by_email || [];
  const relatedByIp = data.related_by_ip || [];
  
  const riskScore = account.risk_score || 0;
  const riskClass = riskScore >= 50 ? 'high' : riskScore >= 25 ? 'medium' : 'low';
  
  // Parse flags
  let flags = [];
  try {
    const flagsStr = account.flags || '[]';
    flags = JSON.parse(flagsStr.replace(/'/g, '"'));
  } catch { 
    if (account.flags) flags = [account.flags];
  }
  
  body.innerHTML = `
    <div class="account-header">
      <div>
        <div class="account-email">${account.email || 'No email'}</div>
        <div style="font-family:var(--mono);font-size:11px;color:var(--text-muted);margin-top:4px;">
          DUID: ${account.duid || '—'}
        </div>
      </div>
      <div class="account-risk-badge ${riskClass}">
        ${account.risk_score != null ? `Risk: ${account.risk_score}` : 'Not Analyzed'}
      </div>
    </div>
    
    <div class="account-grid">
      <div class="account-field">
        <div class="account-field-label">Affiliate</div>
        <div class="account-field-value">${account.webmaster_code || '—'}</div>
      </div>
      <div class="account-field">
        <div class="account-field-label">Campaign</div>
        <div class="account-field-value">${account.campaign || '—'}</div>
      </div>
      <div class="account-field">
        <div class="account-field-label">Payout</div>
        <div class="account-field-value">${fmtCur(account.payout_amount)}</div>
      </div>
      <div class="account-field">
        <div class="account-field-label">Data Type</div>
        <div class="account-field-value">${account.data_type || '—'}</div>
      </div>
      <div class="account-field">
        <div class="account-field-label">IP Address</div>
        <div class="account-field-value">${account.ip || '—'}</div>
      </div>
      <div class="account-field">
        <div class="account-field-label">Analyzed</div>
        <div class="account-field-value">${account.analyzed_at ? new Date(account.analyzed_at).toLocaleString() : '—'}</div>
      </div>
    </div>
    
    ${flags.length > 0 ? `
      <div class="account-section">
        <div class="account-section-title">🚩 Fraud Flags</div>
        <div class="account-flags">
          ${flags.map(f => `<span class="account-flag">${String(f).replace(/_/g, ' ')}</span>`).join('')}
        </div>
      </div>
    ` : ''}
    
    ${outcomes.length > 0 ? `
      <div class="account-section">
        <div class="account-section-title">📋 Outcome History</div>
        <div class="account-related-list">
          ${outcomes.map(o => `
            <div class="account-related-item" style="cursor:default;">
              <div>
                <strong>${o.outcome}</strong>
                ${o.notes ? `<span style="opacity:0.7;margin-left:8px;">${o.notes}</span>` : ''}
              </div>
              <span style="font-size:10px;opacity:0.5;">${o.recorded_at ? new Date(o.recorded_at).toLocaleDateString() : ''}</span>
            </div>
          `).join('')}
        </div>
      </div>
    ` : ''}
    
    ${relatedByEmail.length > 0 ? `
      <div class="account-section">
        <div class="account-section-title">📧 Related by Email Pattern (${relatedByEmail.length})</div>
        <div class="account-related-list">
          ${relatedByEmail.map(r => `
            <div class="account-related-item" onclick="openAccountDetail('${r.duid}')">
              <div>
                <span>${r.email}</span>
                <span style="margin-left:8px;opacity:0.5;">${r.webmaster_code || ''}</span>
              </div>
              <span class="search-result-risk ${r.risk_score >= 50 ? '' : r.risk_score >= 25 ? 'medium' : 'low'}">
                ${r.risk_score}
              </span>
            </div>
          `).join('')}
        </div>
      </div>
    ` : ''}
    
    ${relatedByIp.length > 0 ? `
      <div class="account-section">
        <div class="account-section-title">🌐 Related by IP Address (${relatedByIp.length})</div>
        <div class="account-related-list">
          ${relatedByIp.map(r => `
            <div class="account-related-item" onclick="openAccountDetail('${r.duid}')">
              <div>
                <span>${r.email}</span>
                <span style="margin-left:8px;opacity:0.5;">${r.webmaster_code || ''}</span>
              </div>
              <span class="search-result-risk ${r.risk_score >= 50 ? '' : r.risk_score >= 25 ? 'medium' : 'low'}">
                ${r.risk_score}
              </span>
            </div>
          `).join('')}
        </div>
      </div>
    ` : ''}
    
    <div class="account-actions">
      <button class="btn btn-fraud" onclick="recordAccountOutcome('${account.duid}', 'confirmed_fraud')">
        Mark as Fraud
      </button>
      <button class="btn btn-fp" onclick="recordAccountOutcome('${account.duid}', 'false_positive')">
        False Positive
      </button>
      <button class="btn btn-review" onclick="recordAccountOutcome('${account.duid}', 'under_review')">
        Under Review
      </button>
      <a href="/account/${encodeURIComponent(account.duid)}" target="_blank"
         class="btn btn-sm" style="margin-left:auto;" title="Open dedicated page for this account">
        Open Full Page ↗
      </a>
      <button class="btn btn-cancel" onclick="closeAccountModal()">
        Close
      </button>
    </div>
  `;
}

function closeAccountModal() {
  document.getElementById('accountModal').classList.remove('open');
  setClusterModalMode(false, 'Account Details');
}

async function recordAccountOutcome(duid, outcome) {
  const notes = prompt('Add notes (optional):');
  
  const res = await api('/api/outcomes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duid, outcome, notes: notes || '' })
  });
  
  if (res.error) {
    showToast('Failed to record outcome: ' + res.error, 'error');
    return;
  }
  
  showToast(`Recorded: ${outcome}`, 'success');
  closeAccountModal();
  clearApiCache();
  loadTabData(currentTab);
}

// ═══════════════════════════════════════════════════════════
// CROSS-TAB SPIKE CACHE
// ═══════════════════════════════════════════════════════════

async function loadRecentSpikes() {
  if (_recentSpikes) return _recentSpikes;   // already loaded
  const res = await api('/api/recent-spikes');
  if (!res.error && res.data) {
    _recentSpikes = res.data;
  }
  return _recentSpikes;
}

/**
 * Returns a clickable spike chip HTML string for an affiliate code,
 * or '' if no recent spike.
 */
function spikeChipForAffiliate(code) {
  if (!_recentSpikes?.aff_map) return '';
  const s = _recentSpikes.aff_map[code];
  if (!s) return '';
  const lvl = s.z_score >= 3 ? 'severe' : 'spike';
  const pct = s.pct_above != null ? `+${Math.round(s.pct_above)}%` : `${s.z_score}σ`;
  return `<span class="spike-chip ${lvl}" title="Spike on ${s.spike_date}: ${s.count} signups (${pct} above avg)" onclick="event.stopPropagation();showTab('temporal');setTimeout(()=>drillSpike('${s.spike_date}'),400)">⚡ ${pct}</span>`;
}

/**
 * Returns a clickable spike chip for a campaign, or ''.
 */
function spikeChipForCampaign(campaign) {
  if (!_recentSpikes?.camp_map) return '';
  const s = _recentSpikes.camp_map[campaign];
  if (!s) return '';
  const lvl = s.z_score >= 3 ? 'severe' : 'spike';
  const pct = s.pct_above != null ? `+${Math.round(s.pct_above)}%` : `${s.z_score}σ`;
  return `<span class="spike-chip ${lvl}" title="Spike on ${s.spike_date}: ${s.count} signups (${pct} above avg)" onclick="event.stopPropagation();showTab('temporal');setTimeout(()=>drillSpike('${s.spike_date}'),400)">⚡ ${pct}</span>`;
}

/**
 * Renders the spike context banner inside the affiliate drill-down panel.
 * Called from drillAffiliate / drillAffiliateByCode after loading.
 */
function renderDrillSpikeBanner(affCode) {
  const banner = document.getElementById('drillSpikeBanner');
  if (!banner) return;
  if (!_recentSpikes?.aff_map) { banner.style.display = 'none'; return; }
  const s = _recentSpikes.aff_map[affCode];
  if (!s) { banner.style.display = 'none'; return; }

  const pct  = s.pct_above != null ? `+${Math.round(s.pct_above)}% above baseline` : `z-score ${s.z_score}σ`;
  const lvl  = s.z_score >= 3 ? 'severe' : 'spike';
  banner.style.display = '';
  banner.innerHTML = `<div class="aff-spike-banner">
    <span style="font-size:16px">⚡</span>
    <div>
      <strong>Spike detected for this affiliate</strong> on <strong>${s.spike_date}</strong> —
      ${fmt(s.count)} signups (${pct}, ${s.z_score}σ above avg).
      ${s.high_risk > 0 ? `<strong style="color:var(--risk-high)">${fmt(s.high_risk)} high-risk</strong> on that day.` : ''}
    </div>
    <button class="asb-btn" onclick="showTab('temporal');setTimeout(()=>drillSpike('${s.spike_date}'),400)">
      Full spike analysis →
    </button>
  </div>`;
}

// ═══════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════
// BA FEATURE: TODAY'S DIGEST + BACKLOG SLA
// ═══════════════════════════════════════════════════════════

async function loadDigest() {
  const res = await api('/api/overview/digest');
  if (res.error || !res.data) return;
  const d = res.data;

  const fmtDelta = (val, invert = false) => {
    if (val == null) return '';
    const up = invert ? val < 0 : val > 0;
    const cls = Math.abs(val) < 2 ? 'flat' : (up ? 'up' : 'down');
    const arrow = val > 0 ? '▲' : '▼';
    return `<span class="d-delta ${cls}">${arrow} ${Math.abs(val)}% vs yesterday</span>`;
  };

  const set = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  const setH = (id, val) => { const e = document.getElementById(id); if (e) e.innerHTML = val; };

  set('dg-analyzed',    fmt(d.today?.analyzed));
  set('dg-high',        fmt(d.today?.high_risk));
  set('dg-revenue',     fmtCur(d.today?.revenue));
  set('dg-confirmed',   fmt(d.today?.confirmed));
  set('dg-backlog',     fmt(d.backlog?.total_pending));

  setH('dg-analyzed-delta', fmtDelta(d.deltas?.analyzed_vs_yesterday, false));
  setH('dg-high-delta',     fmtDelta(d.deltas?.high_vs_yesterday, true));
  setH('dg-revenue-delta',  fmtDelta(d.deltas?.revenue_vs_yesterday, true));
  setH('dg-reviewed-delta', `<span class="d-delta flat">${fmt(d.today?.false_positives)} FP today</span>`);
  setH('dg-backlog-payout', `<span class="d-delta ${d.backlog?.over_72h > 0 ? 'up' : 'flat'}">${fmtCur(d.backlog?.pending_payout)} at risk</span>`);

  // Backlog SLA buckets
  const bl = d.backlog || {};
  set('bl-72h',   bl.over_72h   || 0);
  set('bl-48h',   bl.over_48h   || 0);
  set('bl-24h',   bl.over_24h   || 0);
  set('bl-fresh', bl.under_24h  || 0);
}

// ═══════════════════════════════════════════════════════════
// BA FEATURE: RULE PERFORMANCE TABLE
// ═══════════════════════════════════════════════════════════

async function loadRulePerformance() {
  const wrap = document.getElementById('rulePerformanceWrap');
  if (!wrap) return;

  const res = await api('/api/rule-performance' + analysisFilterParams());
  if (res.error) { wrap.innerHTML = errorState('Failed to load rule performance', res.error, 'loadRulePerformance()'); return; }

  const rules = res.data?.rules || [];
  if (rules.length === 0) {
    wrap.innerHTML = emptyState('📋', 'No reviewed accounts yet', 'Rule precision is calculated from confirmed fraud and false positive outcomes. Review some accounts to see stats here.');
    return;
  }

  const rows = rules.map(r => {
    const precBar = r.precision != null
      ? `<div class="precision-bar-wrap"><div class="precision-bar-fill" style="width:${r.precision}%;background:${r.precision >= 80 ? 'var(--risk-low)' : r.precision >= 60 ? 'var(--risk-medium)' : 'var(--risk-high)'}"></div></div>`
      : '';
    const precLabel = r.precision != null ? `${r.precision}%` : '<span style="color:var(--text-muted)">No reviews</span>';
    const fpLabel   = r.fp_rate   != null ? `${r.fp_rate}%`   : '—';
    const dot = `<span class="rule-status-dot ${r.status}"></span>`;
    const confLabel = r.confidence ? r.confidence.replace(/_/g, ' ') : '—';
    return `<tr>
      <td>${dot}<strong>${r.rule.replace(/_/g,' ')}</strong></td>
      <td style="text-align:right">${fmt(r.flagged)}</td>
      <td style="text-align:right">${fmt(r.reviewed)}</td>
      <td style="text-align:right">${fmt(r.confirmed)}</td>
      <td style="text-align:right;color:var(--text-muted)">${fmt(r.unreviewed || 0)}</td>
      <td class="precision-bar-cell">${precLabel}${precBar}</td>
      <td style="text-align:right;color:${r.fp_rate != null && r.fp_rate > 30 ? 'var(--risk-high)' : 'inherit'}">${fpLabel}</td>
      <td><span class="conf-badge conf-${r.confidence || 'neutral'}">${confLabel}</span></td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `
    <table class="data-table no-sort">
      <thead><tr>
        <th>Rule</th>
        <th style="text-align:right">Flagged${thColumnHint('Accounts that had this rule fire (high-risk cohort or all flagged, per API).')}</th>
        <th style="text-align:right">Reviewed${thColumnHint('Subset of flagged that received a fraud or false-positive outcome.')}</th>
        <th style="text-align:right">Confirmed${thColumnHint('Reviewed accounts where outcome is confirmed fraud and this rule contributed.')}</th>
        <th style="text-align:right">Unreviewed${thColumnHint('Flagged accounts with no outcome yet.')}</th>
        <th>Precision${thColumnHint('Confirmed fraud ÷ reviewed × 100 for this rule.')}</th>
        <th style="text-align:right">FP Rate${thColumnHint('False positives ÷ reviewed × 100.')}</th>
        <th>Confidence${thColumnHint('strong (n≥30), directional (n≥10), or too little data.')}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="padding:10px 16px;font-size:11px;color:var(--text-muted)">
      <span class="rule-status-dot good" style="display:inline-block"></span> ≥80% precision &nbsp;
      <span class="rule-status-dot caution" style="display:inline-block"></span> &lt;60% precision &nbsp;
      <span class="rule-status-dot neutral" style="display:inline-block"></span> unreviewed / moderate
    </div>`;
}

// ═══════════════════════════════════════════════════════════
// BA FEATURE: CAMPAIGN FRAUD RATE RANKING
// ═══════════════════════════════════════════════════════════

async function loadCampaignRanking() {
  const wrap = document.getElementById('campaignRankingWrap');
  if (!wrap) return;

  // Ensure spike cache is warm
  if (!_recentSpikes) await loadRecentSpikes();

  const res = await api('/api/campaign-ranking');
  if (res.error) { wrap.innerHTML = errorState('Failed to load campaign ranking', res.error, 'loadCampaignRanking()'); return; }

  const campaigns = res.data?.campaigns || [];
  if (campaigns.length === 0) {
    wrap.innerHTML = emptyState('📣', 'No campaign data', 'Run analysis on data with campaign information.');
    return;
  }

  const maxRate = Math.max(...campaigns.map(c => c.fraud_rate || 0), 1);

  const rows = campaigns.map((c, i) => {
    const rank = i + 1;
    const rankBadge = `<span class="rank-badge ${rank <= 3 ? 'rank-' + rank : ''}">${rank}</span>`;
    const barW = Math.round((c.fraud_rate / maxRate) * 80);
    const barColor = c.fraud_rate >= 50 ? 'var(--risk-high)' : c.fraud_rate >= 25 ? 'var(--risk-medium)' : 'var(--risk-low)';
    const fraudRateCell = `${c.fraud_rate}%<span class="fraud-rate-bar" style="width:${barW}px;background:${barColor}"></span>`;
    const wowStr = c.wow_delta == null ? '—'
      : `<span style="color:${c.wow_delta > 0 ? 'var(--risk-high)' : 'var(--risk-low)'}">${c.wow_delta > 0 ? '▲' : '▼'}${Math.abs(c.wow_delta)}%</span>`;
    const spikeChip = spikeChipForCampaign(c.campaign || '');
    return `<tr>
      <td>${rankBadge}${c.campaign || '—'}${spikeChip}</td>
      <td style="text-align:right">${fmt(c.total)}</td>
      <td style="text-align:right">${fmt(c.high_risk)}</td>
      <td style="text-align:right">${fraudRateCell}</td>
      <td style="text-align:right">${fmtCur(c.payout_at_risk)}</td>
      <td style="text-align:right">${wowStr}</td>
      <td style="text-align:right">${c.affiliate_count}</td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `
    <table class="data-table no-sort">
      <thead><tr>
        <th>Campaign</th>
        <th style="text-align:right">Total${thColumnHint('Accounts in fraud_results for this campaign.')}</th>
        <th style="text-align:right">High Risk${thColumnHint('Count with risk ≥ high-risk threshold.')}</th>
        <th style="text-align:right">Fraud Rate${thColumnHint('High risk ÷ total × 100 for this campaign.')}</th>
        <th style="text-align:right">Payout at Risk${thColumnHint('Sum of payout for high-risk rows in this campaign.')}</th>
        <th style="text-align:right">WoW${thColumnHint('Week-over-week change in high-risk count (recent 7d vs prior 7d).')}</th>
        <th style="text-align:right">Affiliates${thColumnHint('Distinct affiliate codes on this campaign.')}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ═══════════════════════════════════════════════════════════
// ITEM 5: DETECTION FUNNEL
// ═══════════════════════════════════════════════════════════

function detectionFunnelDateParams() {
  const df = document.getElementById('detectionFunnelDateFrom')?.value?.trim() || '';
  const dt = document.getElementById('detectionFunnelDateTo')?.value?.trim() || '';
  const q = new URLSearchParams();
  if (df) q.set('date_from', df);
  if (dt) q.set('date_to', dt);
  return q;
}

function syncReportAnalyzedDatesFromFunnel() {
  const df = document.getElementById('detectionFunnelDateFrom')?.value?.trim() || '';
  const dt = document.getElementById('detectionFunnelDateTo')?.value?.trim() || '';
  const a = document.getElementById('reportAnalyzedFrom');
  const b = document.getElementById('reportAnalyzedTo');
  if (a) a.value = df;
  if (b) b.value = dt;
}

function clearDetectionFunnelDates() {
  const a = document.getElementById('detectionFunnelDateFrom');
  const b = document.getElementById('detectionFunnelDateTo');
  if (a) a.value = '';
  if (b) b.value = '';
  loadDetectionFunnel();
}

/** Jump to Reports with filters matching a funnel stage (uses Overview date pickers → analyzed_at window). */
function drillDetectionFunnel(stage) {
  syncReportAnalyzedDatesFromFunnel();
  const risk = document.getElementById('reportRiskFilter');
  const out = document.getElementById('reportOutcomeFilter');
  const maxH = document.getElementById('reportMaxRisk');
  if (maxH) maxH.value = '';

  const setRisk = (v) => { if (risk) risk.value = v; };
  const setOut = (v) => { if (out) out.value = v; };

  switch (stage) {
    case 'total':
      setRisk('0'); setOut(''); break;
    case 'medium':
      setRisk('25'); setOut(''); if (maxH) maxH.value = '50'; break;
    case 'high':
      setRisk('50'); setOut(''); break;
    case 'reviewed':
      setRisk('50'); setOut('any'); break;
    case 'confirmed':
      setRisk('50'); setOut('confirmed_fraud'); break;
    case 'false_positive':
      setRisk('50'); setOut('false_positive'); break;
    case 'under_review':
      setRisk('50'); setOut('under_review'); break;
    case 'pending':
      setRisk('50'); setOut('__unreviewed__'); break;
    default:
      return;
  }
  switchTab('reports');
  setTimeout(() => loadReports(), 120);
}

function drillFiFunnelStage(stageId) {
  const m = { analyzed: 'total', flagged_high: 'high', reviewed: 'reviewed', confirmed: 'confirmed' };
  const stage = m[stageId];
  if (stage) drillDetectionFunnel(stage);
}

async function loadDetectionFunnel() {
  const wrap = document.getElementById('detectionFunnelWrap');
  if (!wrap) return;

  const qs = detectionFunnelDateParams().toString();
  const res = await api('/api/detection-funnel' + (qs ? `?${qs}` : ''));
  if (res.error) { wrap.innerHTML = errorState('Failed to load funnel', res.error, 'loadDetectionFunnel()'); return; }

  const d = res.data || {};
  if (!d.total_analyzed) {
    wrap.innerHTML = emptyState('⧖', 'No data yet', 'Run fraud analysis to see the detection funnel.');
    return;
  }

  const precTxt = d.precision  != null ? `${d.precision}% precision` : 'No reviews yet';
  const fpTxt   = d.fp_rate    != null ? `${d.fp_rate}% FP rate` : '';
  const foot = d.reviewed_scope_note
    ? `<p class="fi-hint" style="margin-top:10px;padding:0 4px;font-size:11px;">${escapeHtml(d.reviewed_scope_note)}</p>`
    : '';

  wrap.innerHTML = `
    <div class="funnel-wrap">
      <div class="funnel-step">
        <div class="funnel-bar funnel-drill-target" style="background:#3b82f6" role="button" tabindex="0" title="Open Reports · all analyzed in this window" onclick="drillDetectionFunnel('total')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('total')">
          <span class="funnel-label">Total analyzed</span>
          <span class="funnel-count">${fmt(d.total_analyzed)}</span>
        </div>
      </div>
      <div class="funnel-connector"></div>

      <div class="funnel-leaf-row">
        <div class="funnel-leaf funnel-drill-target" style="background:#f59e0b" role="button" tabindex="0" title="Reports · medium risk (25–49)" onclick="drillDetectionFunnel('medium')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('medium')">
          <span class="funnel-label">Medium risk</span>
          <span class="funnel-count">${fmt(d.medium_risk)} <span class="funnel-pct">${((d.medium_risk||0)/d.total_analyzed*100).toFixed(1)}%</span></span>
        </div>
        <div class="funnel-leaf funnel-drill-target" style="background:#ef4444" role="button" tabindex="0" title="Reports · high risk (50+)" onclick="drillDetectionFunnel('high')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('high')">
          <span class="funnel-label">High risk</span>
          <span class="funnel-count">${fmt(d.high_risk)} <span class="funnel-pct">${d.high_risk_pct}%</span></span>
        </div>
      </div>
      <div class="funnel-connector"></div>

      <div class="funnel-step">
        <div class="funnel-bar funnel-drill-target" style="background:#8b5cf6;width:${Math.max(30, d.review_rate)}%" role="button" tabindex="0" title="Reports · high-risk accounts with any review outcome" onclick="drillDetectionFunnel('reviewed')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('reviewed')">
          <span class="funnel-label">Reviewed (high-risk)</span>
          <span class="funnel-count">${fmt(d.reviewed)} <span class="funnel-pct">${d.review_rate}% of high risk</span></span>
        </div>
      </div>
      <div class="funnel-connector"></div>

      <div class="funnel-leaf-row">
        <div class="funnel-leaf funnel-drill-target" style="background:#22c55e" role="button" tabindex="0" title="Reports · confirmed fraud" onclick="drillDetectionFunnel('confirmed')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('confirmed')">
          <span class="funnel-label">Confirmed fraud</span>
          <span class="funnel-count">${fmt(d.confirmed)} <span class="funnel-pct">${precTxt}</span></span>
        </div>
        <div class="funnel-leaf funnel-drill-target" style="background:#64748b" role="button" tabindex="0" title="Reports · false positive" onclick="drillDetectionFunnel('false_positive')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('false_positive')">
          <span class="funnel-label">False positive</span>
          <span class="funnel-count">${fmt(d.false_positives)} <span class="funnel-pct">${fpTxt}</span></span>
        </div>
        <div class="funnel-leaf funnel-drill-target" style="background:#f59e0b" role="button" tabindex="0" title="Reports · under review" onclick="drillDetectionFunnel('under_review')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('under_review')">
          <span class="funnel-label">Under review</span>
          <span class="funnel-count">${fmt(d.under_review)}</span>
        </div>
      </div>
      <div class="funnel-connector"></div>

      <div class="funnel-step">
        <div class="funnel-bar funnel-drill-target" style="background:#dc2626" role="button" tabindex="0" title="Reports · high risk, not reviewed yet" onclick="drillDetectionFunnel('pending')" onkeydown="if(event.key==='Enter')drillDetectionFunnel('pending')">
          <span class="funnel-label">⚠ Pending (unreviewed high risk)</span>
          <span class="funnel-count">${fmt(d.pending)} <span class="funnel-pct">${fmtCur(d.high_risk_payout)} at risk</span></span>
        </div>
      </div>
    </div>${foot}`;
}

// ═══════════════════════════════════════════════════════════
// FRAUD INTELLIGENCE (Effectiveness tab: trends + funnel; Affiliates tab: trajectory)
// ═══════════════════════════════════════════════════════════

function _renderFraudIntelligenceTrajectory(d, trajWrap) {
  if (!trajWrap) return;
  const traj = d.affiliate_trajectory || {};
  const affs = traj.affiliates || [];
  const filt = traj.action_filter || getFiTrajectoryActionFilter();
  const filtLabel = document.getElementById('fiTrajectoryActionFilter')?.selectedOptions?.[0]?.text || filt;
  if (!affs.length) {
    trajWrap.innerHTML = emptyState(
      '◇',
      traj.note || `No affiliates match “${filtLabel}”`,
      'Try “All affiliates”, record actions on affiliate detail pages, or wait for more weekly data.'
    );
    return;
  }
  const dirClass = (dir) =>
    dir === 'accelerating' ? 'fi-dir fi-dir-up' : dir === 'improving' ? 'fi-dir fi-dir-down' : 'fi-dir fi-dir-flat';
  const rows = affs.map(a => {
    const pill = affiliateActionPillHtml(a.webmaster_code, {
      action_status: a.action_status,
      action_type: a.action_type,
    });
    return `
        <tr class="clickable" onclick="window.location.href='/affiliate/${encodeURIComponent(a.webmaster_code)}'" title="Open affiliate detail for ${escapeHtml(a.webmaster_code)}">
          <td><code class="fi-aff-code">${escapeHtml(a.webmaster_code)}</code> <span style="font-size:10px;color:var(--accent)">↗</span></td>
          <td>${pill || '<span style="color:var(--text-muted);font-size:11px;">—</span>'}</td>
          <td style="text-align:right">${fmt(a.accounts_in_window)}</td>
          <td style="text-align:right">${a.early_high_risk_pct}% → ${a.late_high_risk_pct}%</td>
          <td style="text-align:right">${a.change_pp > 0 ? '+' : ''}${a.change_pp} pp</td>
          <td><span class="${dirClass(a.direction)}">${escapeHtml(a.direction)}</span></td>
          <td class="fi-hint-cell">${escapeHtml(a.hint)}</td>
        </tr>`;
  }).join('');
  trajWrap.innerHTML = `
        <div class="fi-traj-meta">${escapeHtml(traj.week_span || '')} · Filter: ${escapeHtml(filtLabel)}</div>
        <table class="data-table fi-traj-table no-sort">
          <thead><tr>
            <th>Affiliate</th>
            <th>Action${thColumnHint('Fraud-tool affiliate action recorded on the affiliate detail page (terminated, warned, under review, etc.).')}</th>
            <th style="text-align:right">Accounts (period)${thColumnHint('How many analyzed accounts this affiliate had in the selected weeks (from transaction dates). Not lifetime totals.')}</th>
            <th style="text-align:right">High-risk % (early → late)${thColumnHint('Compares the first half of the window to the second: what share of accounts scored high-risk in each half.')}</th>
            <th style="text-align:right">Change${thColumnHint('How many percentage points the high-risk share moved from the early half to the late half (positive = getting worse).')}</th>
            <th>Direction${thColumnHint('Quick read: Accelerating = fraud share rising; Improving = falling; Stable = roughly flat.')}</th>
            <th>Note</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
}

function _renderFraudIntelligenceTrendsAndFunnel(d) {
  const expEl = document.getElementById('fiExplanation');
  const projRow = document.getElementById('fiProjectionMetrics');
  const funnelWrap = document.getElementById('fiFunnelDollarsWrap');
  const chartEl = document.getElementById('chart-fraud-intelligence-ts');
  if (!expEl || !projRow) return;

  const proj = d.projection || {};
  expEl.textContent = proj.explanation || 'Projection uses your recent daily averages — not a forecast model.';

  const lb = proj.lookback_days || 14;
  projRow.innerHTML = `
    <div class="metric-card revenue-metric">
      <div class="metric-value negative">${fmtCur(proj.projected_monthly_at_risk_payout || 0)}</div>
      <div class="metric-label">Projected monthly high-risk payout</div>
      <div class="metric-sub">If the last ${lb} days repeat for a month</div>
    </div>
    <div class="metric-card revenue-metric">
      <div class="metric-value high">${fmt(Math.round(proj.projected_monthly_high_risk || 0))}</div>
      <div class="metric-label">Projected high-risk accounts / month</div>
      <div class="metric-sub">${fmt(proj.period_high_risk_accounts || 0)} in the last ${lb} days</div>
    </div>
    <div class="metric-card revenue-metric">
      <div class="metric-value">${fmtCur(proj.avg_daily_at_risk_payout || 0)}</div>
      <div class="metric-label">Avg daily high-risk payout</div>
      <div class="metric-sub">Last ${lb} days</div>
    </div>`;

  const series = (d.time_series && d.time_series.series) || [];
  if (chartEl) {
    if (chartInstances['chart-fraud-intelligence-ts']) {
      chartInstances['chart-fraud-intelligence-ts'].destroy();
      delete chartInstances['chart-fraud-intelligence-ts'];
    }
    if (series.length && series.some(s => (s.high_risk || 0) > 0 || (s.at_risk_payout || 0) > 0)) {
      const categories = series.map(s => s.date);
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      const chart = new ApexCharts(chartEl, {
        series: [
          { name: 'High-risk accounts', type: 'column', data: series.map(s => s.high_risk || 0) },
          { name: 'High-risk payout ($)', type: 'line', data: series.map(s => +Number(s.at_risk_payout || 0).toFixed(2)) },
        ],
        chart: { height: 260, background: 'transparent', toolbar: { show: true, tools: { download: true } } },
        xaxis: { categories, labels: { rotate: -45, style: { fontSize: '10px', colors: isDark ? '#a1a1aa' : '#6b7280' } } },
        yaxis: [
          { title: { text: 'Accounts', style: { color: 'var(--text-muted)', fontSize: '11px' } },
            labels: { style: { colors: 'var(--text-muted)' } } },
          { opposite: true,
            title: { text: 'Payout ($)', style: { color: 'var(--text-muted)', fontSize: '11px' } },
            labels: { formatter: v => '$' + Number(v).toFixed(0), style: { colors: 'var(--text-muted)' } } },
        ],
        colors: ['#ef4444', '#3b82f6'],
        stroke: { curve: 'smooth', width: [0, 2] },
        plotOptions: { bar: { columnWidth: '45%', borderRadius: 2 } },
        theme: { mode: isDark ? 'dark' : 'light' },
        grid: { borderColor: 'rgba(148,163,184,0.1)' },
        legend: { labels: { colors: 'var(--text-muted)' } },
        tooltip: { theme: isDark ? 'dark' : 'light' },
      });
      chart.render();
      chartInstances['chart-fraud-intelligence-ts'] = chart;
    } else {
      chartEl.innerHTML = emptyState('◌', 'No daily history yet', 'Run analysis so accounts appear by day.');
    }
  }

  const fd = d.funnel_dollars || {};
  const stages = fd.stages || [];
  if (funnelWrap) {
    if (!stages.length) {
      funnelWrap.innerHTML = emptyState('◌', 'No funnel data', '');
    } else {
      const maxC = Math.max(...stages.map(s => s.count || 0), 1);
      const drillable = { analyzed: 1, flagged_high: 1, reviewed: 1, confirmed: 1 };
      const bars = stages.map(s => {
        const w = Math.max(8, Math.round((s.count || 0) / maxC * 100));
        const amt = s.amount != null && s.amount !== undefined
          ? `<span class="fi-funnel-amt">${fmtCur(s.amount)}</span>` : '';
        const pctTxt = s.id !== 'analyzed' && s.pct_of_prior != null ? ` (${s.pct_of_prior}%)` : '';
        const sid = s.id ? String(s.id).replace(/'/g, "\\'") : '';
        const rowCl = sid && drillable[s.id] ? 'fi-funnel-row fi-funnel-drill' : 'fi-funnel-row';
        const click = sid && drillable[s.id]
          ? ` role="button" tabindex="0" title="Drill · same as Overview detection funnel" onclick="drillFiFunnelStage('${sid}')" onkeydown="if(event.key==='Enter')drillFiFunnelStage('${sid}')"`
          : '';
        return `<div class="${rowCl}"${click}>
          <div class="fi-funnel-label">${escapeHtml(s.label)}</div>
          <div class="fi-funnel-bar-track">
            <div class="fi-funnel-bar-fill" style="width:${w}%"></div>
          </div>
          <div class="fi-funnel-count">${fmt(s.count)}${pctTxt}${amt}</div>
        </div>`;
      }).join('');
      const pend = fd.pending_high_risk != null
        ? `<p class="fi-hint" style="margin-top:12px"><strong>${fmt(fd.pending_high_risk)}</strong> high-risk accounts still need an outcome.</p>`
        : '';
      funnelWrap.innerHTML = `<div class="fi-funnel-bars">${bars}</div>${pend}`;
    }
  }
}

async function loadAffiliateTrajectoryPanel() {
  const trajWrap = document.getElementById('fiTrajectoryWrap');
  if (!trajWrap) return;

  const actionFilter = getFiTrajectoryActionFilter();
  const res = await api(
    `/api/fraud-intelligence?days=90&lookback=14&weeks=4&trajectory_action_filter=${encodeURIComponent(actionFilter)}`,
    { skipCache: true }
  );
  if (res.error) {
    trajWrap.innerHTML = errorState('Could not load affiliate momentum', res.error, 'loadAffiliateTrajectoryPanel()');
    return;
  }
  _renderFraudIntelligenceTrajectory(res.data || {}, trajWrap);
}

const FI_TRAJECTORY_ACTION_FILTER_KEY = 'fd-momentum-action-filter';

function getFiTrajectoryActionFilter() {
  const el = document.getElementById('fiTrajectoryActionFilter');
  const raw = el?.value || localStorage.getItem(FI_TRAJECTORY_ACTION_FILTER_KEY) || 'needs_action';
  return String(raw).trim() || 'needs_action';
}

function initFiTrajectoryActionFilterSelect() {
  const el = document.getElementById('fiTrajectoryActionFilter');
  if (!el) return;
  const saved = localStorage.getItem(FI_TRAJECTORY_ACTION_FILTER_KEY);
  if (saved && [...el.options].some(o => o.value === saved)) el.value = saved;
}

function onFiTrajectoryActionFilterChange() {
  const el = document.getElementById('fiTrajectoryActionFilter');
  if (el) localStorage.setItem(FI_TRAJECTORY_ACTION_FILTER_KEY, el.value);
  loadAffiliateTrajectoryPanel();
}

async function loadFraudIntelligenceEffectiveness() {
  const expEl = document.getElementById('fiExplanation');
  const projRow = document.getElementById('fiProjectionMetrics');
  const funnelWrap = document.getElementById('fiFunnelDollarsWrap');
  const chartEl = document.getElementById('chart-fraud-intelligence-ts');
  if (!expEl || !projRow) return;

  const iq = new URLSearchParams({ days: '90', lookback: '14', weeks: '4' });
  const ddf = document.getElementById('analysisDateFrom')?.value?.trim()
    || document.getElementById('detectionFunnelDateFrom')?.value?.trim();
  const ddt = document.getElementById('analysisDateTo')?.value?.trim()
    || document.getElementById('detectionFunnelDateTo')?.value?.trim();
  if (ddf) iq.set('analyzed_date_from', ddf);
  if (ddt) iq.set('analyzed_date_to', ddt);
  const res = await api('/api/fraud-intelligence?' + iq.toString(), { skipCache: true });
  if (res.error) {
    expEl.textContent = '';
    projRow.innerHTML = '';
    const err = errorState('Could not load trends', res.error, 'loadFraudIntelligenceEffectiveness()');
    if (funnelWrap) funnelWrap.innerHTML = err;
    if (chartEl) chartEl.innerHTML = '';
    return;
  }

  _renderFraudIntelligenceTrendsAndFunnel(res.data || {});
}

// ═══════════════════════════════════════════════════════════
// ITEM 7: GEOGRAPHIC BREAKDOWN
// ═══════════════════════════════════════════════════════════

async function loadGeoBreakdown() {
  const wrap = document.getElementById('geoWrap');
  if (!wrap) return;

  const res = await api('/api/geo-breakdown');
  if (res.error) { wrap.innerHTML = errorState('Failed to load geo data', res.error, 'loadGeoBreakdown()'); return; }

  const countries = res.data?.countries || [];
  if (countries.length === 0) {
    wrap.innerHTML = emptyState('🌍', 'No geographic data', 'geo_country field is empty. This field is populated when accounts have country data.');
    return;
  }

  const maxTotal = Math.max(...countries.map(c => c.total), 1);

  // Top 10 for bar chart using ApexCharts
  const top10 = countries.slice(0, 10);
  setTimeout(() => {
    renderApexChart('chart-geo-bar', 'bar', {
      series: [
        { name: 'Total', data: top10.map(c => c.total) },
        { name: 'High Risk', data: top10.map(c => c.high_risk) }
      ],
      categories: top10.map(c => c.country)
    }, {
      colors: ['#3b82f6', '#ef4444'],
      height: 240,
      plotOptions: { bar: { horizontal: true, barHeight: '60%' } },
      dataLabels: { enabled: false },
      xaxis: { title: { text: 'Accounts' } },
      legend: { position: 'top' }
    });
  }, 100);

  const rows = countries.map((c, i) => {
    const barW = Math.round((c.total / maxTotal) * 100);
    const color = c.fraud_rate >= 50 ? 'var(--risk-high)' : c.fraud_rate >= 25 ? 'var(--risk-medium)' : 'var(--risk-low)';
    const wow = c.wow_delta == null ? '—'
      : `<span style="color:${c.wow_delta > 0 ? 'var(--risk-high)' : 'var(--risk-low)'}">${c.wow_delta > 0 ? '▲' : '▼'}${Math.abs(c.wow_delta)}%</span>`;
    return `<tr>
      <td><strong>${c.country}</strong>
        <div class="country-bar-wrap"><div class="country-bar-fill" style="width:${barW}%"></div></div>
      </td>
      <td style="text-align:right">${fmt(c.total)}</td>
      <td style="text-align:right;color:${color}">${fmt(c.high_risk)}</td>
      <td style="text-align:right;color:${color}">${c.fraud_rate}%</td>
      <td style="text-align:right">${fmtCur(c.payout_at_risk)}</td>
      <td style="text-align:right">${c.share_pct}%</td>
      <td style="text-align:right">${wow}</td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `
    <div class="panel-body"><div class="chart-container" id="chart-geo-bar" style="height:240px"></div></div>
    <table class="data-table no-sort">
      <thead><tr>
        <th>Country${thColumnHint('geo_country on fraud_results (Unknown if missing).')}</th>
        <th style="text-align:right">Total${thColumnHint('Row count for this country.')}</th>
        <th style="text-align:right">High Risk${thColumnHint('Count with score ≥ high-risk threshold.')}</th>
        <th style="text-align:right">Fraud Rate${thColumnHint('High risk ÷ total × 100.')}</th>
        <th style="text-align:right">Payout at Risk${thColumnHint('Sum of payout for high-risk accounts in this country.')}</th>
        <th style="text-align:right">Share${thColumnHint('This country’s share of rows in the table (top countries).')}</th>
        <th style="text-align:right">WoW${thColumnHint('Change in high-risk count vs prior week.')}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ═══════════════════════════════════════════════════════════
// ITEM 8: AFFILIATE SPARKLINES
// ═══════════════════════════════════════════════════════════

function buildSparkline(data, color = '#ef4444') {
  if (!data || data.length === 0) return '—';
  const w = 60, h = 24, pad = 2;
  const max = Math.max(...data, 1);
  const step = (w - pad * 2) / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v / max) * (h - pad * 2));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const lastVal = data[data.length - 1];
  const trend = data[data.length - 1] > data[0] ? '#ef4444' : data[data.length - 1] < data[0] ? '#22c55e' : '#94a3b8';
  return `<svg class="sparkline-svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <polyline points="${pts}" style="stroke:${trend}"/>
    <circle cx="${(pad + (data.length-1)*step).toFixed(1)}" cy="${(h - pad - ((lastVal/max)*(h-pad*2))).toFixed(1)}" r="2" fill="${trend}"/>
  </svg><span style="font-size:10px;color:${trend};margin-left:3px">${lastVal}</span>`;
}

let _sparklines    = {};
let _recentSpikes  = null;   // shared cross-tab spike lookup, loaded once

async function loadAffiliateSparklines() {
  const res = await api('/api/affiliate-sparklines');
  _sparklines = res.data?.sparklines || {};
}

// ═══════════════════════════════════════════════════════════
// ITEM 9: WEEK-OVER-WEEK COMPARISON
// ═══════════════════════════════════════════════════════════

async function loadWoW() {
  const days = parseInt(document.getElementById('wowDays')?.value || 14);
  const res = await api(`/api/temporal-wow?days=${days}`);

  if (res.error) { return; }

  const current = res.data?.current || [];
  const prior   = res.data?.prior   || [];

  if (current.length === 0 && prior.length === 0) return;

  document.getElementById('wowSubtitle').textContent =
    `High-risk accounts — last ${days} days vs prior ${days} days`;

  renderApexChart('chart-wow', 'line', {
    series: [
      { name: `This ${days} days`, data: current.map(d => d.high_risk) },
      { name: `Prior ${days} days`, data: prior.map(d => d.high_risk) }
    ],
    categories: current.length > 0
      ? current.map(d => d.date)
      : prior.map(d => d.date)
  }, {
    colors: ['#ef4444', '#94a3b8'],
    height: 300,
    stroke: { curve: 'smooth', width: [2.5, 2], dashArray: [0, 5] },
    markers: { size: 4 },
    xaxis: {
      type: 'datetime',
      labels: { datetimeUTC: false, format: 'MMM dd' }
    },
    yaxis: { title: { text: 'High-Risk Accounts' } },
    legend: { position: 'top' },
    annotations: {},
    tooltip: {
      shared: true,
      intersect: false,
      x: { format: 'MMM dd' }
    }
  });

  addChartControls('chart-wow', ['line', 'area', 'bar']);

  // Legend note
  const legendEl = document.getElementById('wowLegend');
  if (legendEl) {
    legendEl.innerHTML = `
      <span><span class="wow-legend-dot" style="background:#ef4444"></span>This ${days} days (solid)</span>
      <span><span class="wow-legend-dot" style="background:#94a3b8;border-top:2px dashed #94a3b8"></span>Prior ${days} days (dashed)</span>`;
  }
}

// ═══════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════
// SPIKE DETECTION
// ═══════════════════════════════════════════════════════════

let _spikeData = null; // cache full spike response

async function loadSpikeAnalysis() {
  const days  = parseInt(document.getElementById('spikeDays')?.value || 60);
  const chartWrap   = document.getElementById('spikeChartWrap');
  const historyWrap = document.getElementById('spikeHistoryWrap');
  if (chartWrap)   chartWrap.innerHTML   = '<div class="loading-spinner">Analyzing…</div>';
  if (historyWrap) historyWrap.innerHTML = '<div class="loading-spinner">Analyzing…</div>';

  const res = await api(`/api/spike-analysis?days=${days}`);
  if (res.error) {
    if (chartWrap)   chartWrap.innerHTML   = errorState('Spike analysis failed', res.error, 'loadSpikeAnalysis()');
    if (historyWrap) historyWrap.innerHTML = '';
    return;
  }

  _spikeData = res.data || {};
  const daily  = _spikeData.daily  || [];
  const spikes = _spikeData.spikes || [];
  const base   = _spikeData.baseline || {};

  // Update subtitle
  const sub = document.getElementById('spikeChartSubtitle');
  if (sub) sub.textContent = spikes.length > 0
    ? `${spikes.length} spike${spikes.length > 1 ? 's' : ''} detected in last ${days} days — click a marker to drill down`
    : `No anomalous spikes in last ${days} days (baseline avg: ${base.mean}/day)`;

  // ── Chart ───────────────────────────────────────────────
  if (chartWrap && daily.length > 0) {
    chartWrap.innerHTML = '<div id="chart-spike" style="min-height:320px;"></div>';

    // Colour each bar by spike level
    const colors = daily.map(d => {
      if (d.spike_level === 'severe')   return '#dc2626';
      if (d.spike_level === 'spike')    return '#f97316';
      if (d.spike_level === 'elevated') return '#f59e0b';
      return '#3b82f6';
    });

    // Annotations for spike days
    const annotations = spikes.map(s => ({
      x: new Date(s.date).getTime(),
      strokeDashArray: 0,
      borderColor: s.spike_level === 'severe' ? '#dc2626' : '#f97316',
      label: {
        style: { background: s.spike_level === 'severe' ? '#dc2626' : '#f97316', color: '#fff', fontSize: '10px', fontWeight: 700 },
        text: `+${s.pct_above_avg ?? ''}% (${s.z_score}σ)`,
        orientation: 'horizontal',
        offsetY: -4,
      }
    }));

    const chartEl = document.getElementById('chart-spike');
    if (chartEl && typeof ApexCharts !== 'undefined') {
      const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      const opts = {
        chart: {
          type: 'bar',
          height: 320,
          background: 'transparent',
          toolbar: { show: false },
          animations: { enabled: true, speed: 400 },
          events: {
            dataPointSelection: (e, ctx, cfg) => {
              const idx = cfg.dataPointIndex;
              const point = daily[idx];
              if (point) drillSpike(point.date);
            }
          }
        },
        series: [
          { name: 'Total Signups', data: daily.map(d => d.total) },
          { name: 'High Risk',     data: daily.map(d => d.high_risk) },
          { name: 'Baseline Avg',  data: daily.map(d => d.rolling_mean), type: 'line' }
        ],
        labels: daily.map(d => d.date),
        colors: ['#3b82f6', '#ef4444', '#94a3b8'],
        theme: { mode: theme },
        plotOptions: {
          bar: {
            columnWidth: '70%',
            colors: { ranges: [] }
          }
        },
        dataLabels: { enabled: false },
        stroke: { width: [0, 0, 2], curve: 'smooth', dashArray: [0, 0, 4] },
        fill: { opacity: [0.85, 0.85, 1] },
        markers: { size: [0, 0, 3] },
        xaxis: {
          type: 'datetime',
          labels: { datetimeUTC: false, format: 'MMM dd' }
        },
        yaxis: { title: { text: 'Accounts', style: { fontSize: '12px' } } },
        tooltip: {
          shared: true,
          intersect: false,
          x: { format: 'MMM dd, yyyy' },
          custom: ({ series, seriesIndex, dataPointIndex }) => {
            const d = daily[dataPointIndex];
            if (!d) return '';
            const lvlColor = d.spike_level === 'severe' ? '#dc2626'
              : d.spike_level === 'spike' ? '#f97316'
              : d.spike_level === 'elevated' ? '#f59e0b' : 'transparent';
            const lvlBadge = d.spike_level !== 'normal'
              ? `<div style="margin-top:4px"><span style="background:${lvlColor};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:700;">${d.spike_level.toUpperCase()} ${d.z_score}σ</span></div>`
              : '';
            return `<div style="padding:10px 14px;font-size:12px;min-width:160px;">
              <div style="font-weight:700;margin-bottom:6px;">${d.date}</div>
              <div>Total: <strong>${d.total}</strong></div>
              <div>High Risk: <strong style="color:#ef4444">${d.high_risk}</strong></div>
              ${d.rolling_mean != null ? `<div>Baseline: <strong>${d.rolling_mean}</strong></div>` : ''}
              ${d.z_score != null ? `<div>Z-score: <strong>${d.z_score}</strong></div>` : ''}
              ${lvlBadge}
              ${d.spike_level !== 'normal' ? '<div style="margin-top:6px;font-size:10px;color:#94a3b8;">Click bar to drill down ↓</div>' : ''}
            </div>`;
          }
        },
        annotations: { xaxis: annotations },
        legend: { position: 'top' }
      };

      // Destroy existing chart if any
      if (window._spikeChart) { try { window._spikeChart.destroy(); } catch(e) {} }
      window._spikeChart = new ApexCharts(chartEl, opts);
      window._spikeChart.render();
    }
  } else if (chartWrap) {
    chartWrap.innerHTML = emptyState('📈', 'No trend data', 'Run analysis to populate temporal data.');
  }

  // ── Spike history table ──────────────────────────────────
  if (historyWrap) {
    const histCount = document.getElementById('spikeHistoryCount');
    if (histCount) histCount.textContent = spikes.length > 0 ? `${spikes.length} anomalous days` : 'No spikes detected';

    if (spikes.length === 0) {
      historyWrap.innerHTML = emptyState('✅', 'No spikes detected', `Signup volume has been within normal range (avg: ${base.mean}/day ± ${base.std}).`);
    } else {
      const rows = spikes.map(s => {
        const lvl = `<span class="spike-level-badge ${s.spike_level}">${s.spike_level}</span>`;
        const pctStr = s.pct_above_avg != null ? `+${s.pct_above_avg}%` : '—';
        return `<tr style="cursor:pointer" onclick="drillSpike('${s.date}')">
          <td>${s.date}</td>
          <td style="text-align:right">${fmt(s.total)}</td>
          <td style="text-align:right;color:var(--risk-high)">${fmt(s.high_risk)}</td>
          <td style="text-align:right">${s.rolling_mean ?? '—'}</td>
          <td style="text-align:right;color:var(--risk-high);font-weight:600">${pctStr}</td>
          <td style="text-align:right">${s.z_score}σ</td>
          <td>${lvl}</td>
          <td style="text-align:right">${fmtCur(s.payout_at_risk)}</td>
          <td><button class="btn btn-sm" onclick="event.stopPropagation();drillSpike('${s.date}')">Drill ↓</button></td>
        </tr>`;
      }).join('');
      historyWrap.innerHTML = `<table class="data-table no-sort">
        <thead><tr>
          <th>Date</th>
          <th style="text-align:right">Total${thColumnHint('Signup / record count for that day in spike analysis.')}</th>
          <th style="text-align:right">High Risk${thColumnHint('High-risk accounts that day.')}</th>
          <th style="text-align:right">Baseline${thColumnHint('Rolling average volume used as expected level.')}</th>
          <th style="text-align:right">% Above Avg${thColumnHint('How far above the rolling baseline the day was.')}</th>
          <th style="text-align:right">Z-Score${thColumnHint('Standard deviations above baseline; higher = stronger spike.')}</th>
          <th>Level${thColumnHint('Severity bucket: normal, elevated, spike, or severe.')}</th>
          <th style="text-align:right">Payout at Risk${thColumnHint('High-risk payout attributed to that day.')}</th>
          <th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    }
  }

  // Show/hide overview spike alert
  _updateSpikeAlertBanner(spikes);

  // Per-affiliate spikes share the same lookback selector
  loadAffiliateSpikes(1);
}

let _affiliateSpikePage = 1;
const AFFILIATE_SPIKE_PAGE_SIZE = 20;

function _affiliateSpikeFetchBadge(row) {
  if (!row) return '—';
  if (row.day_in_progress) {
    return '<span class="volume-fetch-badge partial" title="Calendar day still open">In progress</span>';
  }
  if (row.partial_fetch) {
    const pct = row.local_match_pct != null ? `${row.local_match_pct}%` : '';
    return `<span class="volume-fetch-badge partial" title="Local fetch incomplete vs PS7 — scored on source counts">Partial${pct ? ` ${pct}` : ''}</span>`;
  }
  if (row.source_used_for_scoring) {
    return '<span class="volume-fetch-badge complete" title="Scored on PS7/MCP source counts">MCP</span>';
  }
  return '<span class="volume-fetch-badge unknown" title="Scored on local free/paid counts">Local</span>';
}

async function loadAffiliateSpikes(page = 1) {
  const wrap = document.getElementById('affiliateSpikeWrap');
  const countEl = document.getElementById('affiliateSpikeCount');
  const noteEl = document.getElementById('affiliateSpikeHybridNote');
  const pagerEl = document.getElementById('affiliateSpikePagination');
  if (!wrap) return;

  _affiliateSpikePage = Math.max(1, page || 1);
  const days = parseInt(document.getElementById('spikeDays')?.value || 30, 10);
  const level = document.getElementById('affiliateSpikeLevel')?.value || 'all';
  const minCount = parseInt(document.getElementById('affiliateSpikeMinCount')?.value || 5, 10);
  const sort = document.getElementById('affiliateSpikeSort')?.value || 'z_score';

  wrap.innerHTML = '<div class="loading-spinner">Loading affiliate spikes…</div>';
  if (pagerEl) pagerEl.style.display = 'none';
  if (countEl) countEl.textContent = '';
  if (noteEl) noteEl.textContent = '';

  const qs = new URLSearchParams({
    days: String(days),
    page: String(_affiliateSpikePage),
    per_page: String(AFFILIATE_SPIKE_PAGE_SIZE),
    level,
    min_count: String(minCount),
    sort,
  });
  const res = await api(`/api/affiliate-spikes?${qs}`);
  if (res.error) {
    wrap.innerHTML = errorState('Affiliate spike analysis failed', res.error, 'loadAffiliateSpikes()');
    return;
  }

  const d = res.data || {};
  const spikes = d.spikes || [];
  const pg = d.pagination || { page: 1, total_pages: 1, total: 0, per_page: AFFILIATE_SPIKE_PAGE_SIZE };
  const summary = d.summary || {};
  const hybrid = d.hybrid || {};

  if (noteEl) {
    const src = hybrid.counts_source === 'mcp'
      ? 'PS7/MCP source counts (event date)'
      : hybrid.counts_source === 'reconciliation_cache'
        ? 'cached reconciliation counts (event date)'
        : 'local free/paid counts (trans_datetime)';
    const excl = summary.excluded ? ` · ${summary.excluded} excluded (today / partial fetch)` : '';
    noteEl.textContent = `${src} for detection · local DB for drill-down${excl}`;
  }

  if (countEl) {
    const sev = summary.severe != null ? ` · ${summary.severe} severe` : '';
    countEl.textContent = pg.total
      ? `${pg.total} spike${pg.total === 1 ? '' : 's'} (≥${minCount} accts)${sev}`
      : `No affiliate spikes in last ${days} days`;
  }

  if (!spikes.length) {
    wrap.innerHTML = emptyState(
      '✅',
      'No affiliate spikes',
      `No webmaster exceeded ${level === 'severe' ? '3σ' : '2σ'} vs their 14-day baseline (min ${minCount} accounts/day).`,
    );
    if (pagerEl) pagerEl.style.display = 'none';
    return;
  }

  const rows = spikes.map(s => {
    const code = s.webmaster_code || '';
    const codeEsc = code.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    const pctStr = s.pct_above != null ? `+${s.pct_above}%` : '—';
    const lvl = `<span class="spike-level-badge ${s.spike_level}">${s.spike_level}</span>`;
    const hrPct = s.count > 0 ? ((s.high_risk / s.count) * 100).toFixed(0) : '0';
    const localNote = (s.source_used_for_scoring && s.local_count != null && s.local_count !== s.count)
      ? `<div style="font-size:10px;color:var(--text-muted)">local ${fmt(s.local_count)}</div>` : '';
    const rowCls = s.partial_fetch ? 'volume-row-partial' : '';
    return `<tr class="aff-drill-row ${rowCls}" style="cursor:pointer" onclick="drillSpikeAffiliate('${s.spike_date}','${codeEsc}')">
      <td>${escapeHtml(code)}</td>
      <td>${s.spike_date}</td>
      <td>${_affiliateSpikeFetchBadge(s)}</td>
      <td style="text-align:right">${fmt(s.count)}${localNote}</td>
      <td style="text-align:right">${s.baseline_avg ?? '—'}</td>
      <td style="text-align:right;color:var(--risk-high);font-weight:600">${pctStr}</td>
      <td style="text-align:right">${s.z_score != null ? s.z_score + 'σ' : '—'}</td>
      <td>${lvl}</td>
      <td style="text-align:right;color:var(--risk-high)">${fmt(s.high_risk)} <span style="color:var(--text-muted);font-size:11px">(${hrPct}%)</span></td>
      <td style="text-align:right">${fmtCur(s.payout_at_risk)}</td>
      <td><button class="btn btn-sm" onclick="event.stopPropagation();drillSpikeAffiliate('${s.spike_date}','${codeEsc}')">Drill ↓</button></td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `<table class="data-table no-sort">
    <thead><tr>
      <th>Affiliate${thColumnHint('Webmaster code with a per-affiliate volume spike.')}</th>
      <th>Date${thColumnHint('Event date (trans_datetime / PS7 trans_date).')}</th>
      <th>Source${thColumnHint('Whether the spike was scored on MCP source or local counts.')}</th>
      <th style="text-align:right">Count${thColumnHint('Scored volume that day (MCP total when available).')}</th>
      <th style="text-align:right">Baseline${thColumnHint('Affiliate 14-day rolling average before that day.')}</th>
      <th style="text-align:right">% Above${thColumnHint('How far above that affiliate’s baseline.')}</th>
      <th style="text-align:right">Z-Score${thColumnHint('Standard deviations above the affiliate baseline.')}</th>
      <th>Level${thColumnHint('spike ≥2σ, severe ≥3σ.')}</th>
      <th style="text-align:right">High Risk${thColumnHint('Analyzed high-risk accounts on the event day (local).')}</th>
      <th style="text-align:right">Payout at Risk${thColumnHint('High-risk payout on the event day (local).')}</th>
      <th></th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;

  if (pagerEl) {
    if (pg.total_pages > 1) {
      pagerEl.style.display = '';
      pagerEl.innerHTML = `
        <button class="btn btn-sm" ${pg.page <= 1 ? 'disabled' : ''} onclick="loadAffiliateSpikes(${pg.page - 1})">← Prev</button>
        <span class="pagination-info">Page ${pg.page} of ${pg.total_pages} (${fmt(pg.total)} spikes)</span>
        <button class="btn btn-sm" ${pg.page >= pg.total_pages ? 'disabled' : ''} onclick="loadAffiliateSpikes(${pg.page + 1})">Next →</button>`;
    } else {
      pagerEl.style.display = 'none';
    }
  }
}

function _updateSpikeAlertBanner(spikes) {
  const banner = document.getElementById('spikeAlertBanner');
  if (!banner) return;

  // Only alert if there's a spike in the last 2 days
  const today     = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const recentSpike = spikes.find(s => s.date === today || s.date === yesterday);

  if (!recentSpike) {
    banner.style.display = 'none';
    return;
  }

  const when = recentSpike.date === today ? 'today' : 'yesterday';
  const pct  = recentSpike.pct_above_avg != null ? `+${recentSpike.pct_above_avg}%` : 'unusual';
  banner.style.display = '';
  banner.innerHTML = `<div class="spike-alert-banner">
    <span class="spike-icon">⚠</span>
    <span class="spike-text">
      <strong>Signup spike detected ${when}:</strong>
      ${fmt(recentSpike.total)} signups (${pct} above 14-day average, ${recentSpike.z_score}σ) —
      ${fmt(recentSpike.high_risk)} high-risk accounts.
    </span>
    <button class="spike-btn" onclick="showTab('temporal');setTimeout(()=>drillSpike('${recentSpike.date}'),300)">
      Investigate →
    </button>
  </div>`;
}

async function drillSpike(date) {
  const wrap = document.getElementById('spikeDrillWrap');
  if (!wrap) return;

  wrap.style.display = '';
  wrap.innerHTML = `<div class="spike-drill-panel">
    <div class="spike-drill-header">
      <h3>🔍 Spike Drill-Down — ${date}</h3>
      <button class="spike-close" onclick="document.getElementById('spikeDrillWrap').style.display='none'">✕</button>
    </div>
    <div class="spike-drill-body"><div class="loading-spinner">Loading breakdown…</div></div>
  </div>`;

  // Scroll into view
  wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const res = await api(`/api/spike-drill/${date}`);
  if (res.error) {
    wrap.innerHTML = `<div class="spike-drill-panel">
      <div class="spike-drill-header">
        <h3>🔍 Spike Drill-Down — ${date}</h3>
        <button class="spike-close" onclick="this.closest('#spikeDrillWrap').style.display='none'">✕</button>
      </div>
      <div class="spike-drill-body">${errorState('Failed to load drill-down', res.error)}</div>
    </div>`;
    return;
  }

  const d = res.data;
  if (!d || d.total === 0) {
    wrap.innerHTML = `<div class="spike-drill-panel">
      <div class="spike-drill-header">
        <h3>🔍 Spike Drill-Down — ${date}</h3>
        <button class="spike-close" onclick="document.getElementById('spikeDrillWrap').style.display='none'">✕</button>
      </div>
      <div class="spike-drill-body">${emptyState('⊘', 'No data for this date', '')}</div>
    </div>`;
    return;
  }

  // Find spike metadata from cached data
  const spikeMeta = (_spikeData?.spikes || []).find(s => s.date === date);
  const pctAbove = spikeMeta?.pct_above_avg != null ? `+${spikeMeta.pct_above_avg}% above avg` : '';
  const zscore   = spikeMeta ? `${spikeMeta.z_score}σ` : '';
  const hrPct    = d.total > 0 ? (d.high_risk / d.total * 100).toFixed(1) : 0;
  const dateKey  = date.replace(/-/g, '');
  const insight  = d.insight?.summary || '';

  // Affiliate rows
  const maxAffCount = Math.max(...(d.affiliates || []).map(a => a.count), 1);
  const affRows = (d.affiliates || []).slice(0, 15).map(a => {
    const barW = Math.round(a.count / maxAffCount * 100);
    const vsBase = a.vs_baseline != null
      ? `<span style="color:${a.vs_baseline > 0 ? 'var(--risk-high)' : 'var(--risk-low)'}">
           ${a.vs_baseline > 0 ? '▲' : '▼'}${Math.abs(a.vs_baseline)}%
         </span>`
      : '<span style="color:var(--text-muted)">new</span>';
    const codeEsc = (a.webmaster_code || '').replace(/'/g, "\\'");
    return `<tr class="aff-drill-row" onclick="drillSpikeAffiliate('${date}','${codeEsc}')">
      <td><strong>${escapeHtml(a.webmaster_code)}</strong>
        <div class="aff-contrib-bar"><div class="aff-contrib-fill" style="width:${barW}%"></div></div>
      </td>
      <td style="text-align:right">${fmt(a.count)}</td>
      <td style="text-align:right">${a.share_pct}%</td>
      <td style="text-align:right;color:var(--risk-high)">${fmt(a.high_risk)}</td>
      <td style="text-align:right">${a.avg_daily ?? '—'}/day</td>
      <td style="text-align:right">${vsBase}</td>
      <td style="text-align:right">${fmtCur(a.payout)}</td>
      <td>View accounts →</td>
    </tr>`;
  }).join('');

  // Campaign rows (clickable drill-down)
  const campRows = (d.campaigns || []).slice(0, 8).map(c => {
    const campName = c.campaign || 'Unknown';
    return `<tr class="camp-drill-row" onclick="drillSpikeCampaign('${date}', ${JSON.stringify(campName)})">
      <td><strong>${escapeHtml(campName)}</strong></td>
      <td style="text-align:right">${fmt(c.count)}</td>
      <td style="text-align:right">${c.share_pct}%</td>
      <td style="text-align:right;color:var(--risk-high)">${fmt(c.high_risk)}</td>
      <td style="text-align:right">${c.avg_risk?.toFixed(1)}</td>
      <td>View accounts →</td>
    </tr>`;
  }).join('');

  const flagRows = renderSpikeFlagTableRows(d.flags, 10);

  const sampleRows = (d.sample || []).slice(0, 10).map(a =>
    `<tr onclick="openAccountModal('${a.duid}')" style="cursor:pointer">
      <td>${truncate(a.email || '', 32)}</td>
      <td>${riskBadge(a.risk_score)}</td>
      <td>${fmtCur(a.payout_amount)}</td>
      <td>${renderSpikeFlagPills(a.flags, 2)}</td>
      <td style="color:var(--text-muted)">${escapeHtml(a.webmaster_code || '—')}</td>
    </tr>`
  ).join('');

  const driversHtml = `<div class="spike-drill-grid">
    <div class="drill-section" id="spike-aff-section-${dateKey}">
      <div class="drill-section-title">Affiliates — click a row</div>
      ${affRows ? `<table class="data-table">
        <thead><tr>
          <th>Affiliate</th><th style="text-align:right">Count</th><th style="text-align:right">Share</th>
          <th style="text-align:right">High Risk</th><th style="text-align:right">Baseline</th>
          <th style="text-align:right">vs Avg</th><th style="text-align:right">Payout</th><th></th>
        </tr></thead><tbody>${affRows}</tbody></table>
        <div id="spike-aff-subpanel-${dateKey}" style="margin-top:8px;"></div>`
        : '<p style="color:var(--text-muted);font-size:12px">No affiliate data.</p>'}
    </div>
    <div class="drill-section" id="spike-camp-section-${dateKey}">
      <div class="drill-section-title">Campaigns — click a row</div>
      ${campRows ? `<table class="data-table">
        <thead><tr>
          <th>Campaign</th><th style="text-align:right">Count</th><th style="text-align:right">Share</th>
          <th style="text-align:right">High Risk</th><th style="text-align:right">Avg Risk</th><th></th>
        </tr></thead><tbody>${campRows}</tbody></table>
        <div id="spike-camp-subpanel-${dateKey}" style="margin-top:8px;"></div>`
        : '<p style="color:var(--text-muted);font-size:12px">No campaign data.</p>'}
    </div>
  </div>`;

  const flagsHtml = flagRows
    ? `<table class="data-table"><thead><tr><th>Flag</th><th style="text-align:right">Count</th><th style="text-align:right">% of day</th></tr></thead><tbody>${flagRows}</tbody></table>`
    : '<p style="color:var(--text-muted);font-size:12px">No flags detected on this day.</p>';

  const sampleHtml = sampleRows
    ? `<table class="data-table"><thead><tr><th>Email</th><th>Risk</th><th>Payout</th><th>Flags</th><th>Affiliate</th></tr></thead><tbody>${sampleRows}</tbody></table>`
    : '<p style="color:var(--text-muted);font-size:12px">No samples available.</p>';

  wrap.innerHTML = `<div class="spike-drill-panel">
    <div class="spike-drill-header">
      <h3>🔍 Spike Drill-Down — ${date}</h3>
      <button class="spike-close" onclick="document.getElementById('spikeDrillWrap').style.display='none'">✕</button>
    </div>
    <div class="spike-drill-body">

      <div class="spike-stat-row">
        <div class="spike-stat-card">
          <div class="ss-label">Total Signups</div>
          <div class="ss-value">${fmt(d.total)}</div>
          ${pctAbove ? `<div class="ss-delta">${pctAbove}</div>` : ''}
        </div>
        <div class="spike-stat-card">
          <div class="ss-label">High Risk</div>
          <div class="ss-value" style="color:var(--risk-high)">${fmt(d.high_risk)}</div>
          <div class="ss-delta">${hrPct}% of total</div>
        </div>
        <div class="spike-stat-card">
          <div class="ss-label">Z-Score</div>
          <div class="ss-value">${zscore || '—'}</div>
          ${spikeMeta ? `<div class="ss-delta"><span class="spike-level-badge ${spikeMeta.spike_level}">${spikeMeta.spike_level}</span></div>` : ''}
        </div>
        <div class="spike-stat-card">
          <div class="ss-label">Affiliates</div>
          <div class="ss-value">${(d.affiliates || []).length}</div>
          <div class="ss-delta">${(d.campaigns || []).length} campaigns</div>
        </div>
      </div>

      ${insight ? `<div class="spike-insight-banner">${escapeHtml(insight)}</div>` : ''}

      ${spikeAccordion('Drivers — affiliates &amp; campaigns', driversHtml, true)}
      ${spikeAccordion(`Top flags (${Math.min((d.flags || []).length, 10)} shown)`, flagsHtml, false)}
      ${spikeAccordion(`Sample accounts — top ${Math.min(10, d.sample?.length || 0)} by risk`, sampleHtml, false)}

    </div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════
// VOLUME ANOMALIES (registrations + sales, trans_datetime)
// ═══════════════════════════════════════════════════════════

let _volumeAnomalyData = null;

function _volumeLevelBadge(level) {
  if (!level || level === 'normal' || level === 'in_progress' || level.startsWith('elevated')) {
    if (level === 'in_progress') {
      return '<span class="volume-level-badge normal" title="Day still in progress — not scored as surge/dip">in progress</span>';
    }
    return level && level !== 'normal'
      ? `<span class="volume-level-badge normal">${level.replace('_', ' ')}</span>`
      : '<span class="volume-level-badge normal">normal</span>';
  }
  const label = level.replace('_', ' ');
  return `<span class="volume-level-badge ${level}">${label}</span>`;
}

function _volumeLevelLabel(level) {
  const map = {
    surge_severe: 'severe surge',
    surge: 'surge',
    dip_severe: 'severe dip',
    dip: 'dip',
    elevated_up: 'elevated',
    elevated_down: 'elevated dip',
    in_progress: 'in progress',
    normal: 'normal',
  };
  return map[level] || level || 'normal';
}

function _isVolumeAnomaly(level) {
  return ['surge', 'surge_severe', 'dip', 'dip_severe'].includes(level);
}

function _volumeExcludedReasonLabel(reason) {
  if (reason === 'day_in_progress') return 'day in progress';
  if (reason === 'partial_fetch') return 'partial fetch';
  return reason ? String(reason).replace(/_/g, ' ') : 'excluded';
}

function _volumeExcludedSummary(excluded) {
  if (!excluded.length) return '';
  const reasons = {};
  for (const row of excluded) {
    const key = row.excluded_reason || (row.day_in_progress ? 'day_in_progress' : 'partial_fetch');
    reasons[key] = (reasons[key] || 0) + 1;
  }
  const parts = Object.entries(reasons).map(([reason, n]) => {
    const label = _volumeExcludedReasonLabel(reason);
    return n === 1 ? `1 ${label}` : `${n} ${label}`;
  });
  return parts.join(', ');
}

function _volumeFetchBadge(dayRow) {
  if (!dayRow) return '—';
  if (dayRow.day_in_progress) {
    return '<span class="volume-fetch-badge partial" title="Calendar day still open — anomaly signals deferred until day closes">In progress</span>';
  }
  if (dayRow.partial_fetch) {
    const pct = dayRow.local_match_pct != null ? `${dayRow.local_match_pct}%` : '';
    return `<span class="volume-fetch-badge partial" title="Local fetch incomplete — drill-down may be missing rows">Partial${pct ? ` ${pct}` : ''}</span>`;
  }
  if (dayRow.local_data_complete === false) {
    return '<span class="volume-fetch-badge partial">Partial</span>';
  }
  if (dayRow.source_used_for_scoring || dayRow.reconciliation_status === 'complete') {
    return '<span class="volume-fetch-badge complete">Complete</span>';
  }
  if (dayRow.reconciliation_status) {
    return `<span class="volume-fetch-badge ${dayRow.reconciliation_status}">${dayRow.reconciliation_status.replace('_', ' ')}</span>`;
  }
  return '<span class="volume-fetch-badge unknown">—</span>';
}

async function loadVolumeAnomalies() {
  const days = parseInt(document.getElementById('volumeAnomalyDays')?.value || 60, 10);
  const summaryEl = document.getElementById('volumeAnomalySummary');
  const chartWrap = document.getElementById('volumeAnomalyChartWrap');
  const historyWrap = document.getElementById('volumeAnomalyHistoryWrap');

  if (summaryEl) summaryEl.innerHTML = '<div class="loading-spinner">Loading…</div>';
  if (chartWrap) chartWrap.innerHTML = '<div class="loading-spinner">Loading…</div>';
  if (historyWrap) historyWrap.innerHTML = '<div class="loading-spinner">Loading…</div>';

  const res = await api(`/api/volume-anomalies?days=${days}`);
  if (res.error) {
    const err = errorState('Volume anomaly analysis failed', res.error, 'loadVolumeAnomalies()');
    if (summaryEl) summaryEl.innerHTML = err;
    if (chartWrap) chartWrap.innerHTML = '';
    if (historyWrap) historyWrap.innerHTML = '';
    return;
  }

  _volumeAnomalyData = res.data || {};
  const daily = _volumeAnomalyData.daily || [];
  const anomalies = _volumeAnomalyData.anomalies || [];
  const excluded = _volumeAnomalyData.excluded_anomalies || [];
  const base = _volumeAnomalyData.baseline || {};
  const hybrid = _volumeAnomalyData.hybrid || {};

  const sub = document.getElementById('volumeAnomalySubtitle');
  if (sub) {
    const srcLabel = hybrid.counts_source === 'mcp'
      ? 'PS7/MCP source counts'
      : hybrid.counts_source === 'reconciliation_cache'
        ? 'cached reconciliation counts'
        : 'local DB counts';
    const exclSummary = _volumeExcludedSummary(excluded);
    const exclNote = exclSummary ? ` · ${exclSummary} excluded` : '';
    sub.textContent = `${srcLabel} for detection · local DB for drill-down${exclNote} · ${days}-day window`;
  }

  // Summary cards: latest registration + sales anomaly (if any)
  if (summaryEl) {
    const today = new Date().toISOString().slice(0, 10);
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const recent = anomalies.find(a => a.date === today || a.date === yesterday) || anomalies[0];

    const cards = [
      `<div class="volume-anomaly-card">
        <div class="va-label">Registrations (avg/day)</div>
        <div class="va-value">${base.registrations_mean ?? '—'}</div>
        <div class="va-hint">± ${base.registrations_std ?? '—'} std</div>
      </div>`,
      `<div class="volume-anomaly-card">
        <div class="va-label">Sales (avg/day)</div>
        <div class="va-value">${base.sales_mean ?? '—'}</div>
        <div class="va-hint">± ${base.sales_std ?? '—'} std</div>
      </div>`,
    ];

    if (recent) {
      const regCls = _isVolumeAnomaly(recent.registration_level)
        ? (recent.registration_level.includes('dip') ? 'dip' : 'surge') : '';
      const salCls = _isVolumeAnomaly(recent.sales_level)
        ? (recent.sales_level.includes('dip') ? 'dip' : 'surge') : '';
      cards.push(`<div class="volume-anomaly-card ${regCls}">
        <div class="va-label">Latest reg signal · ${recent.date}</div>
        <div class="va-value">${fmt(recent.registrations)}</div>
        <div class="va-hint">${_volumeLevelBadge(recent.registration_level)} ${recent.registration_z != null ? `${recent.registration_z}σ` : ''}</div>
      </div>`);
      cards.push(`<div class="volume-anomaly-card ${salCls}">
        <div class="va-label">Latest sales signal · ${recent.date}</div>
        <div class="va-value">${fmt(recent.sales)}</div>
        <div class="va-hint">${_volumeLevelBadge(recent.sales_level)} ${recent.sales_z != null ? `${recent.sales_z}σ` : ''}</div>
      </div>`);
    } else {
      cards.push(`<div class="volume-anomaly-card"><div class="va-label">Status</div><div class="va-value" style="font-size:14px;">Within range</div><div class="va-hint">No surges or dips detected</div></div>`);
    }
    summaryEl.innerHTML = cards.join('');
  }

  // Chart: dual series with baseline lines
  if (chartWrap) {
    if (daily.length === 0) {
      chartWrap.innerHTML = emptyState('📊', 'No volume data', 'Fetch free and paid records to populate registration and sales trends.');
    } else {
      chartWrap.innerHTML = '<div id="chart-volume-anomaly" style="min-height:340px;"></div>';
      const chartEl = document.getElementById('chart-volume-anomaly');
      if (chartEl && typeof ApexCharts !== 'undefined') {
        const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
        if (window._volumeAnomalyChart) {
          try { window._volumeAnomalyChart.destroy(); } catch (_) {}
        }
        window._volumeAnomalyChart = new ApexCharts(chartEl, {
          chart: {
            type: 'line',
            height: 340,
            background: 'transparent',
            toolbar: { show: false },
            events: {
              dataPointSelection: (_e, _ctx, cfg) => {
                const idx = cfg.dataPointIndex;
                const point = daily[idx];
                if (point) drillVolumeAnomaly(point.date);
              },
            },
          },
          series: [
            { name: 'Registrations', type: 'column', data: daily.map(d => d.registrations) },
            { name: 'Sales', type: 'column', data: daily.map(d => d.sales) },
            { name: 'Reg baseline', type: 'line', data: daily.map(d => d.reg_rolling_mean) },
            { name: 'Sales baseline', type: 'line', data: daily.map(d => d.sales_rolling_mean) },
          ],
          labels: daily.map(d => d.date),
          colors: ['#6366f1', '#22c55e', '#a78bfa', '#86efac'],
          theme: { mode: theme },
          stroke: { width: [0, 0, 2, 2], curve: 'smooth', dashArray: [0, 0, 4, 4] },
          plotOptions: { bar: { columnWidth: '45%' } },
          dataLabels: { enabled: false },
          xaxis: { type: 'datetime', labels: { datetimeUTC: false, format: 'MMM dd' } },
          yaxis: { title: { text: 'Count' } },
          legend: { position: 'top' },
          tooltip: {
            shared: true,
            custom: ({ dataPointIndex }) => {
              const d = daily[dataPointIndex];
              if (!d) return '';
              return `<div style="padding:10px 14px;font-size:12px;">
                <div style="font-weight:700;margin-bottom:6px;">${d.date}</div>
                <div>Registrations: <strong>${d.registrations}</strong> ${_volumeLevelBadge(d.registration_level)}</div>
                <div>Sales: <strong>${d.sales}</strong> ${_volumeLevelBadge(d.sales_level)}</div>
                ${d.local_registrations != null && d.source_registrations != null && d.local_registrations !== d.source_registrations
                  ? `<div style="color:#94a3b8;font-size:11px;">Local: ${d.local_registrations} reg / ${d.local_sales ?? '—'} sales</div>` : ''}
                ${d.day_in_progress ? '<div style="color:#94a3b8;font-size:11px;">Day in progress — not scored as surge/dip</div>' : ''}
                ${d.partial_fetch && !d.day_in_progress ? '<div style="color:#f59e0b;font-size:11px;">⚠ Partial local fetch</div>' : ''}
                ${d.conversion_rate != null ? `<div>Conversion: <strong>${d.conversion_rate}%</strong></div>` : ''}
                <div style="margin-top:6px;font-size:10px;color:#94a3b8;">Click to drill down ↓</div>
              </div>`;
            },
          },
        });
        window._volumeAnomalyChart.render();
      }
    }
  }

  // History table
  const histCount = document.getElementById('volumeAnomalyHistoryCount');
  if (histCount) {
    const exclSummary = _volumeExcludedSummary(excluded);
    const exclTxt = exclSummary ? ` · ${exclSummary} excluded` : '';
    histCount.textContent = anomalies.length > 0
      ? `${anomalies.length} anomal${anomalies.length === 1 ? 'y' : 'ies'} detected${exclTxt}`
      : excluded.length > 0
        ? `No anomalies (${exclSummary} excluded)`
        : 'No anomalies detected';
  }
  if (historyWrap) {
    if (anomalies.length === 0 && excluded.length === 0) {
      historyWrap.innerHTML = emptyState('✅', 'Volume within normal range', `Registration and sales counts stayed within ±2σ of the 14-day rolling baseline.`);
    } else {
      const rows = anomalies.map(a => {
        const regPct = a.reg_pct_vs_baseline != null ? `${a.reg_pct_vs_baseline > 0 ? '+' : ''}${a.reg_pct_vs_baseline}%` : '—';
        const salPct = a.sales_pct_vs_baseline != null ? `${a.sales_pct_vs_baseline > 0 ? '+' : ''}${a.sales_pct_vs_baseline}%` : '—';
        const rowCls = a.partial_fetch ? 'volume-row-partial' : '';
        return `<tr class="${rowCls}" style="cursor:pointer" onclick="drillVolumeAnomaly('${a.date}')">
          <td>${a.date}</td>
          <td>${_volumeFetchBadge(a)}</td>
          <td style="text-align:right">${fmt(a.registrations)}</td>
          <td>${_volumeLevelBadge(a.registration_level)}</td>
          <td style="text-align:right">${a.registration_z != null ? a.registration_z + 'σ' : '—'}</td>
          <td style="text-align:right">${regPct}</td>
          <td style="text-align:right">${fmt(a.sales)}</td>
          <td>${_volumeLevelBadge(a.sales_level)}</td>
          <td style="text-align:right">${a.sales_z != null ? a.sales_z + 'σ' : '—'}</td>
          <td style="text-align:right">${salPct}</td>
          <td style="text-align:right">${a.conversion_rate != null ? a.conversion_rate + '%' : '—'}</td>
          <td><button class="btn btn-sm" onclick="event.stopPropagation();drillVolumeAnomaly('${a.date}')">Drill ↓</button></td>
        </tr>`;
      }).join('');
      const excludedRows = excluded.map(a => {
        const regPct = a.reg_pct_vs_baseline != null ? `${a.reg_pct_vs_baseline > 0 ? '+' : ''}${a.reg_pct_vs_baseline}%` : '—';
        const salPct = a.sales_pct_vs_baseline != null ? `${a.sales_pct_vs_baseline > 0 ? '+' : ''}${a.sales_pct_vs_baseline}%` : '—';
        const reason = a.excluded_reason || (a.day_in_progress ? 'day_in_progress' : 'partial_fetch');
        const reasonLabel = _volumeExcludedReasonLabel(reason);
        const title = reason === 'day_in_progress'
          ? 'Excluded: calendar day still open (partial day vs full-day baseline)'
          : 'Excluded: partial local fetch would skew signal';
        const countReg = reason === 'day_in_progress'
          ? (a.registrations ?? a.source_registrations)
          : (a.local_registrations ?? a.registrations);
        const countSal = reason === 'day_in_progress'
          ? (a.sales ?? a.source_sales)
          : (a.local_sales ?? a.sales);
        return `<tr class="volume-row-excluded" title="${title}">
          <td>${a.date}</td>
          <td>${_volumeFetchBadge(a)}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(countReg)}</td>
          <td><span class="volume-level-badge normal">excluded</span></td>
          <td style="text-align:right;color:var(--text-muted)">${a.registration_z != null ? a.registration_z + 'σ' : '—'}</td>
          <td style="text-align:right;color:var(--text-muted)">${regPct}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(countSal)}</td>
          <td><span class="volume-level-badge normal">—</span></td>
          <td style="text-align:right;color:var(--text-muted)">${a.sales_z != null ? a.sales_z + 'σ' : '—'}</td>
          <td style="text-align:right;color:var(--text-muted)">${salPct}</td>
          <td style="text-align:right;color:var(--text-muted)">—</td>
          <td><span style="font-size:11px;color:var(--text-muted)">${reasonLabel}</span></td>
        </tr>`;
      }).join('');
      historyWrap.innerHTML = `<table class="data-table no-sort">
        <thead><tr>
          <th>Date</th>
          <th>Fetch</th>
          <th style="text-align:right">Registrations</th>
          <th>Reg signal</th>
          <th style="text-align:right">Reg z</th>
          <th style="text-align:right">Reg vs baseline</th>
          <th style="text-align:right">Sales</th>
          <th>Sales signal</th>
          <th style="text-align:right">Sales z</th>
          <th style="text-align:right">Sales vs baseline</th>
          <th style="text-align:right">Conv %</th>
          <th></th>
        </tr></thead>
        <tbody>${rows}${excludedRows}</tbody>
      </table>`;
    }
  }
}

async function drillVolumeAnomaly(date) {
  const wrap = document.getElementById('volumeAnomalyDrillWrap');
  if (!wrap) return;

  wrap.style.display = '';
  wrap.innerHTML = `<div class="volume-drill-panel">
    <div class="volume-drill-header">
      <h3>📊 Volume Drill-Down — ${date}</h3>
      <button class="spike-close" onclick="document.getElementById('volumeAnomalyDrillWrap').style.display='none'">✕</button>
    </div>
    <div class="volume-drill-body"><div class="loading-spinner">Loading breakdown…</div></div>
  </div>`;
  wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const res = await api(`/api/volume-anomalies/drill/${date}`);
  if (res.error) {
    wrap.querySelector('.volume-drill-body').innerHTML = errorState('Failed to load drill-down', res.error, `drillVolumeAnomaly('${date}')`);
    return;
  }

  const d = res.data;
  const meta = (_volumeAnomalyData?.daily || []).find(x => x.date === date);

  const partialBanner = d.partial_fetch
    ? `<div class="volume-partial-banner">
        ⚠ Partial local fetch (${d.local_match_pct != null ? d.local_match_pct + '%' : 'incomplete'} of PS7 source).
        Drill-down shows only locally stored rows${d.source_registrations != null ? ` (${fmt(d.registrations)} local vs ${fmt(d.source_registrations)} source registrations)` : ''}.
      </div>`
    : '';

  const affTable = (rows, title) => {
    if (!rows || rows.length === 0) {
      return `<div class="drill-section"><div class="drill-section-title">${title}</div><p style="color:var(--text-muted);font-size:12px;">No affiliate breakdown.</p></div>`;
    }
    const body = rows.map(a => {
      const vs = a.vs_baseline_pct != null
        ? `<span style="color:${a.vs_baseline_pct > 0 ? 'var(--risk-high)' : '#3b82f6'}">${a.vs_baseline_pct > 0 ? '+' : ''}${a.vs_baseline_pct}%</span>`
        : '—';
      return `<tr class="clickable" onclick="window.open('/affiliate/${encodeURIComponent(a.webmaster_code)}','_blank')">
        <td><code>${escapeHtml(a.webmaster_code)}</code></td>
        <td style="text-align:right">${fmt(a.count)}</td>
        <td style="text-align:right">${a.share_pct}%</td>
        <td style="text-align:right">${a.avg_daily ?? '—'}</td>
        <td style="text-align:right">${vs}</td>
      </tr>`;
    }).join('');
    return `<div class="drill-section">
      <div class="drill-section-title">${title}</div>
      <table class="data-table no-sort">
        <thead><tr>
          <th>Affiliate</th><th style="text-align:right">Count</th><th style="text-align:right">Share</th>
          <th style="text-align:right">14d avg/day</th><th style="text-align:right">vs baseline</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
  };

  wrap.querySelector('.volume-drill-body').innerHTML = `
    ${partialBanner}
    <div class="spike-stat-row" style="margin-bottom:16px;">
      <div class="spike-stat-card">
        <div class="ss-label">Registrations</div>
        <div class="ss-value">${fmt(d.registrations)}</div>
        ${meta ? `<div class="ss-delta">${_volumeLevelBadge(meta.registration_level)} ${meta.registration_z != null ? meta.registration_z + 'σ' : ''}</div>` : ''}
      </div>
      <div class="spike-stat-card">
        <div class="ss-label">Sales</div>
        <div class="ss-value">${fmt(d.sales)}</div>
        ${meta ? `<div class="ss-delta">${_volumeLevelBadge(meta.sales_level)} ${meta.sales_z != null ? meta.sales_z + 'σ' : ''}</div>` : ''}
      </div>
      <div class="spike-stat-card">
        <div class="ss-label">Conversion</div>
        <div class="ss-value">${d.conversion_rate != null ? d.conversion_rate + '%' : '—'}</div>
      </div>
    </div>
    <div class="volume-drill-grid">
      ${affTable(d.registration_affiliates, 'Registration volume by affiliate')}
      ${affTable(d.sales_affiliates, 'Sales volume by affiliate')}
    </div>`;
}

// ═══════════════════════════════════════════════════════════
// SPIKE AFFILIATE / CAMPAIGN DRILL (level 3)
// ═══════════════════════════════════════════════════════════

async function drillSpikeAffiliate(date, affCode, page = 1, flagFilter = '') {
  const dateKey = date.replace(/-/g, '');
  const subpanel = document.getElementById(`spike-aff-subpanel-${dateKey}`);
  if (!subpanel) return;

  clearSpikeSubpanels(dateKey);
  document.querySelectorAll('.aff-drill-row').forEach(r => {
    if (r.textContent.includes(affCode)) r.style.background = 'rgba(99,102,241,0.08)';
  });

  subpanel.innerHTML = `<div class="aff-sub-panel"><div class="aff-sub-body"><div class="loading-spinner">Loading ${escapeHtml(affCode)}…</div></div></div>`;
  subpanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const qs = new URLSearchParams({ page: String(page), per_page: '25' });
  if (flagFilter) qs.set('flag', flagFilter);
  const res = await api(`/api/spike-drill/${date}/affiliate/${encodeURIComponent(affCode)}?${qs}`);
  if (res.error) {
    subpanel.innerHTML = `<div class="aff-sub-panel"><div class="aff-sub-body">${errorState('Failed to load accounts', res.error)}</div></div>`;
    return;
  }

  subpanel.innerHTML = renderSpikeAffiliatePanel(date, affCode, res.data, flagFilter);
  subpanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSpikeAffiliatePanel(date, affCode, d, flagFilter = '') {
  const dateKey = date.replace(/-/g, '');
  const total = d.total || 0;
  const hrPct = total > 0 ? ((d.high_risk / total) * 100).toFixed(1) : 0;
  const base = d.baseline;
  const vsStr = base?.vs_baseline_pct != null
    ? `<span style="color:${base.vs_baseline_pct > 0 ? 'var(--risk-high)' : 'var(--risk-low)'}">
        ${base.vs_baseline_pct > 0 ? '▲' : '▼'}${Math.abs(base.vs_baseline_pct)}% vs normal
       </span>`
    : '';

  const flagRows = renderSpikeFlagTableRows(d.top_flags, 8);
  const campRows = (d.camp_split || []).map(c =>
    `<tr><td>${escapeHtml(c.campaign || 'Unknown')}</td>
     <td style="text-align:right">${c.count}</td>
     <td style="text-align:right;color:var(--risk-high)">${c.high_risk}</td></tr>`
  ).join('');

  const accountsTotal = d.accounts_total ?? (d.accounts || []).length;
  const pg = d.pagination || { page: 1, total_pages: 1 };
  const flagNote = flagFilter ? ` · filtered by ${humanizeFlagKey(flagFilter)}` : '';

  return `<div class="aff-sub-panel">
    <div class="aff-sub-header">
      <button class="aff-back-btn" onclick="clearSpikeSubpanels('${dateKey}')">← Back</button>
      <h4>${escapeHtml(affCode)} — ${date}</h4>
      <div class="aff-sub-stat"><div class="asv">${fmt(total)}</div><div class="asl">Signups</div></div>
      <div class="aff-sub-stat"><div class="asv" style="color:var(--risk-high)">${fmt(d.high_risk)}</div><div class="asl">High Risk (${hrPct}%)</div></div>
      ${base ? `<div class="aff-sub-stat"><div class="asv">${base.avg_daily}</div><div class="asl">Normal/day ${vsStr}</div></div>` : ''}
      <div class="aff-sub-stat"><div class="asv">${fmtCur(d.total_payout)}</div><div class="asl">Payout</div></div>
    </div>
    <div class="aff-sub-body">
      <div class="aff-sub-breadcrumb">
        <span onclick="clearSpikeSubpanels('${dateKey}')" style="cursor:pointer;color:var(--accent)">Spike ${date}</span>
        <span class="bc-sep">›</span><span class="bc-active">${escapeHtml(affCode)}</span>
        <span class="bc-sep">—</span><span>${total} accounts</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div>
          <div class="drill-section-title">Flags on this day</div>
          ${flagRows ? `<table class="data-table"><thead><tr><th>Flag</th><th style="text-align:right">Count</th><th style="text-align:right">%</th></tr></thead><tbody>${flagRows}</tbody></table>` : '<p style="font-size:12px;color:var(--text-muted)">No flags.</p>'}
        </div>
        <div>
          <div class="drill-section-title">By campaign</div>
          ${campRows ? `<table class="data-table"><thead><tr><th>Campaign</th><th style="text-align:right">Count</th><th style="text-align:right">High Risk</th></tr></thead><tbody>${campRows}</tbody></table>` : '<p style="font-size:12px;color:var(--text-muted)">No campaign data.</p>'}
        </div>
      </div>
      <div class="drill-section-title">Accounts — ${accountsTotal} total${flagNote} (showing page ${pg.page})</div>
      ${renderSpikeAccountsTable(d.accounts, { showCampaign: true, showAffiliate: false })}
      ${renderSpikePagination(date, 'affiliate', affCode, d.pagination, flagFilter, 'drillSpikeAffiliate')}
    </div>
  </div>`;
}

async function drillSpikeCampaign(date, campName, page = 1, flagFilter = '') {
  const dateKey = date.replace(/-/g, '');
  const subpanel = document.getElementById(`spike-camp-subpanel-${dateKey}`);
  if (!subpanel) return;

  clearSpikeSubpanels(dateKey);
  document.querySelectorAll('.camp-drill-row').forEach(r => {
    if (r.textContent.includes(campName)) r.style.background = 'rgba(99,102,241,0.08)';
  });

  subpanel.innerHTML = `<div class="aff-sub-panel"><div class="aff-sub-body"><div class="loading-spinner">Loading ${escapeHtml(campName)}…</div></div></div>`;
  subpanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const qs = new URLSearchParams({ page: String(page), per_page: '25' });
  if (flagFilter) qs.set('flag', flagFilter);
  const res = await api(`/api/spike-drill/${date}/campaign/${encodeURIComponent(campName)}?${qs}`);
  if (res.error) {
    subpanel.innerHTML = `<div class="aff-sub-panel"><div class="aff-sub-body">${errorState('Failed to load accounts', res.error)}</div></div>`;
    return;
  }

  subpanel.innerHTML = renderSpikeCampaignPanel(date, campName, res.data, flagFilter);
  subpanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSpikeCampaignPanel(date, campName, d, flagFilter = '') {
  const dateKey = date.replace(/-/g, '');
  const total = d.total || 0;
  const hrPct = total > 0 ? ((d.high_risk / total) * 100).toFixed(1) : 0;
  const base = d.baseline;
  const vsStr = base?.vs_baseline_pct != null
    ? `<span style="color:${base.vs_baseline_pct > 0 ? 'var(--risk-high)' : 'var(--risk-low)'}">
        ${base.vs_baseline_pct > 0 ? '▲' : '▼'}${Math.abs(base.vs_baseline_pct)}% vs normal
       </span>`
    : '';

  const flagRows = renderSpikeFlagTableRows(d.top_flags, 8);
  const affRows = (d.aff_split || []).map(a =>
    `<tr><td>${escapeHtml(a.webmaster_code || 'Unknown')}</td>
     <td style="text-align:right">${a.count}</td>
     <td style="text-align:right;color:var(--risk-high)">${a.high_risk}</td></tr>`
  ).join('');

  const accountsTotal = d.accounts_total ?? (d.accounts || []).length;
  const pg = d.pagination || { page: 1, total_pages: 1 };
  const flagNote = flagFilter ? ` · filtered by ${humanizeFlagKey(flagFilter)}` : '';

  return `<div class="aff-sub-panel">
    <div class="aff-sub-header">
      <button class="aff-back-btn" onclick="clearSpikeSubpanels('${dateKey}')">← Back</button>
      <h4>${escapeHtml(campName)} — ${date}</h4>
      <div class="aff-sub-stat"><div class="asv">${fmt(total)}</div><div class="asl">Signups</div></div>
      <div class="aff-sub-stat"><div class="asv" style="color:var(--risk-high)">${fmt(d.high_risk)}</div><div class="asl">High Risk (${hrPct}%)</div></div>
      ${base ? `<div class="aff-sub-stat"><div class="asv">${base.avg_daily}</div><div class="asl">Normal/day ${vsStr}</div></div>` : ''}
      <div class="aff-sub-stat"><div class="asv">${fmtCur(d.total_payout)}</div><div class="asl">Payout</div></div>
    </div>
    <div class="aff-sub-body">
      <div class="aff-sub-breadcrumb">
        <span onclick="clearSpikeSubpanels('${dateKey}')" style="cursor:pointer;color:var(--accent)">Spike ${date}</span>
        <span class="bc-sep">›</span><span class="bc-active">${escapeHtml(campName)}</span>
        <span class="bc-sep">—</span><span>${total} accounts</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div>
          <div class="drill-section-title">Flags on this day</div>
          ${flagRows ? `<table class="data-table"><thead><tr><th>Flag</th><th style="text-align:right">Count</th><th style="text-align:right">%</th></tr></thead><tbody>${flagRows}</tbody></table>` : '<p style="font-size:12px;color:var(--text-muted)">No flags.</p>'}
        </div>
        <div>
          <div class="drill-section-title">By affiliate</div>
          ${affRows ? `<table class="data-table"><thead><tr><th>Affiliate</th><th style="text-align:right">Count</th><th style="text-align:right">High Risk</th></tr></thead><tbody>${affRows}</tbody></table>` : '<p style="font-size:12px;color:var(--text-muted)">No affiliate data.</p>'}
        </div>
      </div>
      <div class="drill-section-title">Accounts — ${accountsTotal} total${flagNote} (showing page ${pg.page})</div>
      ${renderSpikeAccountsTable(d.accounts, { showCampaign: false, showAffiliate: true })}
      ${renderSpikePagination(date, 'campaign', campName, d.pagination, flagFilter, 'drillSpikeCampaign')}
    </div>
  </div>`;
}

// ═══════════════════════════════════════════════════════════
// REVENUE IMPACT
// ═══════════════════════════════════════════════════════════

async function loadRevenueImpact() {
  if (!document.getElementById('ri-savings')) return;

  // Load both existing revenue impact and new business metrics in parallel
  const [impactRes, metricsRes] = await Promise.all([
    api('/api/revenue-impact'),
    api('/api/business/metrics')
  ]);
  
  // Handle existing revenue impact
  if (!impactRes.error) {
    const data = impactRes.data;
    const impact = data.impact || {};
    const totals = data.totals || {};
    const timeline = data.timeline || [];
    
    // Update metrics (keep existing logic)
    const rs = document.getElementById('ri-savings');
    const rp = document.getElementById('ri-potential');
    const ra = document.getElementById('ri-at-risk');
    const rpr = document.getElementById('ri-precision');
    if (rs) rs.textContent = fmtCur(impact.estimated_savings || 0);
    if (rp) rp.textContent = fmtCur(impact.potential_savings || 0);
    if (ra) ra.textContent = fmtCur(totals.high_risk_payout || 0);
    if (rpr) rpr.textContent = `${impact.precision || 0}%`;
    
    if (timeline.length > 0 && document.getElementById('chart-revenue-timeline')) {
      const accent = (getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#2563eb').trim();
      const dates = timeline.map(t => t.date);
      renderApexChart('chart-revenue-timeline', 'line', {
        series: [
          { name: 'At-Risk Payout', data: timeline.map(t => t.at_risk_payout) },
          { name: 'Total Payout', data: timeline.map(t => t.total_payout) }
        ],
        categories: dates
      }, {
        height: 220,
        colors: ['#ef4444', accent],
        stroke: { curve: 'smooth', width: 2, dashArray: [0, 5] },
        fill: { type: 'solid', opacity: [0.25, 0] },
        markers: { size: [3, 0] },
        legend: { position: 'top', horizontalAlign: 'center' },
        yaxis: {
          labels: { formatter: (v) => fmtCur(v) }
        }
      });
    }
  }
  
  // Handle new business metrics
  if (!metricsRes.error && metricsRes.data) {
    const metrics = metricsRes.data;
    
    // Store for potential display (could add to UI if needed)
    window.businessMetrics = metrics;
    
    // Log for now (can add UI elements later)
    console.log('Business Metrics:', {
      fraud_prevented: metrics.fraud_prevented,
      false_positive_rate: metrics.false_positive_rate,
      industry_benchmarks: metrics.industry_benchmarks
    });
  }
}

// ─── Overview ───
let _highRiskData = [];

// Drill into overview metrics
function drillMetric(type) {
  // Navigate to Reports tab with appropriate filter
  switchTab('reports');
  
  setTimeout(() => {
    const riskFilter = document.getElementById('reportRiskFilter');
    const groupBy = document.getElementById('reportGroupBy');
    
    if (type === 'high') {
      if (riskFilter) riskFilter.value = '50';
    } else if (type === 'medium') {
      if (riskFilter) riskFilter.value = '25';
    } else if (type === 'revenue' || type === 'all') {
      if (riskFilter) riskFilter.value = '0';
    }
    
    if (groupBy) groupBy.value = '';
    
    loadReports();
  }, 100);
}
async function loadOverview() {
  // Pre-warm the cross-tab spike cache so all other tabs get badges immediately
  loadRecentSpikes();

  // Digest + funnel + spike banner (revenue impact & deep trends live on Effectiveness tab)
  loadDigest();
  loadDetectionFunnel();
  // Spike alert banner: runs quietly, only shows if recent spike found
  api('/api/spike-analysis?days=3').then(res => {
    if (!res.error) _updateSpikeAlertBanner(res.data?.spikes || []);
  });

  const statsRes = await api('/api/stats');

  // Handle stats
  if (statsRes.error) {
    showToast('Failed to load stats: ' + statsRes.error, 'error');
  }
  const stats = statsRes.data;
  
  if (stats) {
    document.getElementById('m-total').textContent = fmt(stats.total_analyzed);
    document.getElementById('m-high').innerHTML = fmt(stats.high_risk) + velocityBadge(stats.velocity?.high_risk_change);
    document.getElementById('m-medium').textContent = fmt(stats.medium_risk);
    document.getElementById('m-revenue').innerHTML = fmtCur(stats.revenue_at_risk) + velocityBadge(stats.velocity?.revenue_change);

    // Week-over-week delta subtitles under metric cards
    const wowAnalyzed = stats.velocity?.total_change;
    const wowHigh     = stats.velocity?.high_risk_change;
    const wowRevenue  = stats.velocity?.revenue_change;
    const wowFmt = (v) => v == null ? 'vs last week: no prior data' : `vs last week: ${v > 0 ? '+' : ''}${v}%`;
    const wowColor = (v) => v == null ? '' : (v > 0 ? 'color:var(--risk-high)' : 'color:var(--risk-low)');
    const el = (id, v) => { const e = document.getElementById(id); if (e) { e.innerHTML = `<span style="${wowColor(v)}">${wowFmt(v)}</span>`; } };
    el('m-total-delta',   wowAnalyzed);
    el('m-high-delta',    wowHigh);
    el('m-revenue-delta', wowRevenue);

    // Badge in nav
    // Update badges in both sidebar and embed top nav
    const badgeCount = stats.high_risk > 0 ? stats.high_risk : null;
    ['nav-badge-high', 'embed-badge-high'].forEach(id => {
      const badge = document.getElementById(id);
      if (badge) {
        badge.textContent = badgeCount || '';
        badge.style.display = badgeCount ? '' : 'none';
      }
    });

    // Risk Distribution Donut Chart (ApexCharts)
    const total = stats.total_analyzed || 1;
    const low = total - stats.high_risk - stats.medium_risk;
    
    renderApexChart('chart-risk-donut', 'donut', {
      values: [stats.high_risk, stats.medium_risk, low],
      labels: ['High Risk', 'Medium Risk', 'Low Risk']
    }, {
      colors: ['#ef4444', '#f59e0b', '#22c55e'],
      height: 280,
      legend: { show: true, position: 'bottom', fontSize: '13px' },
      plotOptions: {
        pie: {
          donut: {
            size: '65%',
            labels: {
              show: true,
              name: { show: true, fontSize: '14px', fontWeight: 600 },
              value: { show: true, fontSize: '22px', fontWeight: 700, formatter: (val) => val.toLocaleString() },
              total: {
                show: true,
                label: 'Total Accounts',
                fontSize: '14px',
                fontWeight: 600,
                formatter: () => total.toLocaleString()
              }
            }
          }
        }
      },
      dataLabels: { enabled: true, formatter: (val, opts) => `${val.toFixed(1)}%` }
    });
    
    addChartControls('chart-risk-donut', ['donut', 'pie', 'radialBar']);

    // Risk by Type Bar Chart (Paid vs Free) - ApexCharts
    const byType = stats.by_type || [];
    const paidData = byType.find(t => t.data_type === 'paid') || { high_risk: 0, medium_risk: 0, total: 0 };
    const freeData = byType.find(t => t.data_type === 'free') || { high_risk: 0, medium_risk: 0, total: 0 };
    
    renderApexChart('chart-risk-bar', 'bar', {
      series: [
        { name: 'Paid', data: [paidData.high_risk || 0, paidData.medium_risk || 0] },
        { name: 'Free', data: [freeData.high_risk || 0, freeData.medium_risk || 0] }
      ],
      categories: ['High Risk', 'Medium Risk']
    }, {
      colors: ['#6366f1', '#22d3ee'],
      height: 280,
      plotOptions: {
        bar: {
          horizontal: false,
          columnWidth: '55%',
          dataLabels: { position: 'top' }
        }
      },
      dataLabels: {
        enabled: true,
        offsetY: -20,
        style: { fontSize: '12px', fontWeight: 600 }
      },
      xaxis: { title: { text: 'Risk Level', style: { fontSize: '13px', fontWeight: 600 } } },
      yaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
      legend: { position: 'top', horizontalAlign: 'left' }
    });
    
    addChartControls('chart-risk-bar', ['bar', 'line', 'area']);
  }
}

async function loadReviewQueue() {
  await loadHouseAffiliates();
  await loadAffiliateActions();
  const [highRiskRes, pendingRes] = await Promise.all([
    api('/api/fraud-results?min_risk=50&limit=500'),
    api('/api/pending-reviews')
  ]);

  let highRisk = highRiskRes.data;
  const wrap = document.getElementById('highRiskTableWrap');

  if (highRiskRes.error) {
    if (wrap) wrap.innerHTML = errorState('Failed to load data', highRiskRes.error, 'loadReviewQueue()');
  } else if (!highRisk || highRisk.length === 0) {
    if (wrap) wrap.innerHTML = emptyState('⊘', 'No high-risk accounts', 'Run fraud analysis to populate this view.');
    _highRiskData = [];
    rawDataCache.hr = [];
  } else {
    const seen = new Set();
    highRisk = highRisk.filter(r => {
      const key = r.duid || r.email;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    rawDataCache.hr = [...highRisk];
    filterTable('hr', '');
  }

  _pendingData = pendingRes.data || [];
  const reviewMetrics = document.getElementById('reviewMetrics');
  if (reviewMetrics) {
    const hrCount = rawDataCache.hr?.length || 0;
    const pendCount = _pendingData.length;
    reviewMetrics.innerHTML = `
      <div class="metric-card"><div class="metric-label">High Risk Loaded</div><div class="metric-value high">${fmt(hrCount)}</div></div>
      <div class="metric-card"><div class="metric-label">Pending Review</div><div class="metric-value medium">${fmt(pendCount)}</div></div>
      <div class="metric-card"><div class="metric-label">Purpose</div><div class="metric-value" style="font-size:14px;line-height:1.4;">Triage &amp; record outcomes</div></div>`;
  }
  renderPendingTable();
}

function renderPendingTable() {
  const pWrap = document.getElementById('pendingTableWrap');
  const pc = document.getElementById('pendingCount');
  if (pc) pc.textContent = _pendingData.length + ' pending';
  if (!pWrap) return;
  if (_pendingData.length === 0) {
    pWrap.innerHTML = emptyState('✓', 'All caught up', 'No unreviewed high-risk accounts.');
    updateTablePagination('pend', 1, 1, 0);
    return;
  }
  const pageMeta = getTablePageSlice('pend', _pendingData);
  pWrap.innerHTML = buildTable('pend', [
    { key: 'email', label: 'Email', hint: 'High-risk account awaiting a review outcome.', render: v => truncate(v, 30) },
    { key: 'risk_score', label: 'Risk', numeric: true, right: true, hint: 'Model score ≥ high-risk threshold; no outcome recorded yet.', render: v => riskBadge(v) },
    { key: 'payout_amount', label: 'Payout', numeric: true, right: true, hint: 'Payout amount from the source record.', render: v => fmtCur(v) },
    { key: 'duid', label: 'Actions', hint: 'Quick-record outcome without opening the full review modal.', render: (v) =>
      `<button class="btn btn-sm btn-fraud" onclick="event.stopPropagation();pendingActionByDuid('${v}','confirmed_fraud')">Fraud</button> ` +
      `<button class="btn btn-sm btn-fp" onclick="event.stopPropagation();pendingActionByDuid('${v}','false_positive')">FP</button> ` +
      `<button class="btn btn-sm btn-review" onclick="event.stopPropagation();pendingActionByDuid('${v}','under_review')">Review</button>`
    }
  ], pageMeta.pageRows, { clickable: true, onClick: 'openPendingModalByDuid', onClickKey: 'duid', emptyIcon: '✓', emptyTitle: 'All caught up' });
  updateTablePagination('pend', pageMeta.page, pageMeta.totalPages, pageMeta.totalRows, pageMeta.pageSize);
}

function openHighRiskModalByDuid(duid) {
  const key = decodeURIComponent(String(duid || ''));
  const row = (rawDataCache.hr || []).find(r => String(r.duid) === key)
    || (_highRiskData || []).find(r => String(r.duid) === key);
  if (row) openOutcomeModal(row.duid, row.email);
}
function openHighRiskModal(idx) {
  const row = _highRiskData[idx];
  if (row) openOutcomeModal(row.duid, row.email);
}
function openPendingModalByDuid(duid) {
  const key = decodeURIComponent(String(duid || ''));
  const row = (_pendingData || []).find(r => String(r.duid) === key);
  if (row) openOutcomeModal(row.duid, row.email);
}
function openPendingModal(idx) {
  const row = _pendingData[idx];
  if (row) openOutcomeModal(row.duid, row.email);
}

function pendingActionByDuid(duid, outcome) {
  const row = (_pendingData || []).find(r => String(r.duid) === String(duid));
  if (!row) return;
  pendingAction(_pendingData.indexOf(row), outcome);
}

// ─── Bulk Actions ───
let _bulkSelected = new Set();

function toggleBulkSelect(duid, checkbox) {
  if (checkbox.checked) {
    _bulkSelected.add(duid);
  } else {
    _bulkSelected.delete(duid);
  }
  updateBulkUI();
}

function toggleSelectAll(masterCheckbox) {
  const checkboxes = document.querySelectorAll('.bulk-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = masterCheckbox.checked;
    const duid = cb.dataset.duid;
    if (masterCheckbox.checked) {
      _bulkSelected.add(duid);
    } else {
      _bulkSelected.delete(duid);
    }
  });
  updateBulkUI();
}

function updateBulkUI() {
  const bar = document.getElementById('bulkActionsBar');
  const count = document.getElementById('bulkSelectedCount');
  if (_bulkSelected.size > 0) {
    bar.style.display = 'flex';
    count.textContent = _bulkSelected.size + ' selected';
  } else {
    bar.style.display = 'none';
  }
  // Update row highlighting
  document.querySelectorAll('.data-table tbody tr').forEach(tr => {
    const cb = tr.querySelector('.bulk-checkbox');
    if (cb) {
      tr.classList.toggle('selected', cb.checked);
    }
  });
}

function clearBulkSelection() {
  _bulkSelected.clear();
  document.querySelectorAll('.bulk-checkbox').forEach(cb => cb.checked = false);
  const masterCb = document.getElementById('selectAllHighRisk');
  if (masterCb) masterCb.checked = false;
  updateBulkUI();
}

async function bulkMarkAs(outcome) {
  if (_bulkSelected.size === 0) {
    showToast('No accounts selected', 'error');
    return;
  }

  const duids = Array.from(_bulkSelected);

  try {
    const r = await fetch('/api/bulk-outcomes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duids, outcome, notes: 'Bulk action from dashboard' })
    });
    const data = await r.json();

    if (r.ok) {
      showToast(`Marked ${data.success_count} accounts as ${outcome.replace('_', ' ')}`);
      clearBulkSelection();
      clearApiCache();
      loadTabData(currentTab);
    } else {
      showToast(data.error || 'Bulk action failed', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
}

// ─── Affiliates ───
async function loadAffiliates() {
  loadAffiliateTrajectoryPanel();

  // If already viewing a drill-down, don't reset it
  const drillPanel = document.getElementById('affiliates-drill');
  if (drillPanel && drillPanel.style.display !== 'none' && currentDrillAffiliate) {
    return;
  }

  // Pre-warm spike cache if not already loaded
  if (!_recentSpikes) loadRecentSpikes().then(() => _renderAffiliateTable());

  await loadHouseAffiliates();
  await loadAffiliateActions();

  // Load geo breakdown + sparklines + value/fraud matrix in parallel (non-blocking)
  loadGeoBreakdown();
  loadAffiliateMatrix();
  loadRiskCalibration();
  loadAffiliateSparklines().then(() => _renderAffiliateTable());

  const res = await api('/api/affiliates');
  const wrap = document.getElementById('affiliatesTableWrap');
  
  document.getElementById('affiliates-main').style.display = '';
  document.getElementById('affiliates-drill').style.display = 'none';
  
  if (res.error) {
    wrap.innerHTML = errorState('Failed to load affiliates', res.error, 'loadAffiliates()');
    return;
  }
  
  const allAffiliates = res.data || [];
  rawDataCache.aff = [...allAffiliates];

  const searchInput = document.getElementById('searchAffiliates');
  if (searchInput) searchInput.value = '';
  const filterSelect = document.getElementById('filterAffRisk');
  if (filterSelect) filterSelect.value = '';
  const houseSelect = document.getElementById('filterAffHouse');
  if (houseSelect) houseSelect.value = 'external';

  const externalExclude = externalOnlyExcludeLower();
  const visibleCount = allAffiliates.filter(row => !externalExclude.has((row.webmaster_code || '').toLowerCase())).length;
  const hiddenCount = allAffiliates.length - visibleCount;
  document.getElementById('affCount').textContent = `${visibleCount} affiliates` + (hiddenCount > 0 ? ` (${hiddenCount} house/whitelist hidden)` : '');

  filterTable('aff', '');
}

function _renderAffiliateTable() {
  filterTable('aff', document.getElementById('searchAffiliates')?.value || '');
}

function drillAffiliate(idx) {
  const aff = affiliatesData[idx];
  if (!aff) return;
  drillAffiliateByCode(aff.webmaster_code);
}
function openDrillModal(idx) {
  const row = _drillData[idx];
  if (row) openOutcomeModal(row.duid, row.email);
}
function closeDrilldown() {
  document.getElementById('affiliates-main').style.display = '';
  document.getElementById('affiliates-drill').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════
// ANALYSIS TAB — filters, lazy sub-tab loading
// ═══════════════════════════════════════════════════════════
let _analysisSubTabLoaded = {};

function analysisFilterParams() {
  const q = new URLSearchParams();
  const df = document.getElementById('analysisDateFrom')?.value?.trim();
  const dt = document.getElementById('analysisDateTo')?.value?.trim();
  const aff = document.getElementById('analysisAffiliate')?.value?.trim();
  const camp = document.getElementById('analysisCampaign')?.value?.trim();
  if (df) q.set('date_from', df);
  if (dt) q.set('date_to', dt);
  if (aff) q.set('affiliate', aff);
  if (camp) q.set('campaign', camp);
  const s = q.toString();
  return s ? '?' + s : '';
}

function getActiveAnalysisSubTab() {
  const active = document.querySelector('#tab-anomaly .major-tab.active');
  return active?.dataset?.major || 'anomaly-major-actions';
}

function clearAnalysisFilters() {
  ['analysisDateFrom', 'analysisDateTo', 'analysisAffiliate', 'analysisCampaign'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  _analysisSubTabLoaded = {};
  reloadAnalysisSubTab();
}

function reloadAnalysisSubTab() {
  _analysisSubTabLoaded = {};
  if (currentTab === 'anomaly') loadAnalysisSubTab(getActiveAnalysisSubTab());
}

async function loadAnalysisSubTab(panelId) {
  if (!panelId) panelId = 'anomaly-major-actions';
  if (_analysisSubTabLoaded[panelId]) return;
  _analysisSubTabLoaded[panelId] = true;

  switch (panelId) {
    case 'anomaly-major-actions':
      return loadActionCenter();
    case 'anomaly-major-rules':
      return loadRuleQuality();
    case 'anomaly-major-patterns':
      return loadPatternMovement();
    case 'anomaly-major-monitoring':
      return loadAnalysisMonitoring();
    default:
      return loadActionCenter();
  }
}

async function loadActionCenter() {
  loadRevenueImpact();
  loadFraudIntelligenceEffectiveness();
  const filters = analysisFilterParams();
  const [effRes, actionRes, coverageRes] = await Promise.all([
    api('/api/effectiveness'),
    api('/api/analysis/action-items' + filters),
    api('/api/analysis/review-coverage'),
  ]);

  renderActionItems(actionRes.data);
  renderReviewCoverage(coverageRes.data);
  renderEffectivenessSummary(effRes.data);
}

function renderActionItems(data) {
  const wrap = document.getElementById('actionItemsWrap');
  if (!wrap) return;
  const items = data?.items || [];
  if (!items.length) {
    wrap.innerHTML = emptyState('✓', 'No urgent actions', 'Detection looks stable for current filters. Check Rule Quality for tuning opportunities.');
    return;
  }
  wrap.innerHTML = items.map(item => {
    const sevColor = item.severity === 'high' ? 'var(--risk-high)'
      : item.severity === 'medium' ? 'var(--risk-medium)' : 'var(--text-muted)';
    return `<div class="action-item-card" style="border-left:3px solid ${sevColor};padding:12px 14px;margin-bottom:8px;background:var(--bg-card);border-radius:6px;">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
        <div>
          <div style="font-weight:600;font-size:13px;">${escapeHtml(item.title)}</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:4px;">${escapeHtml(item.detail || '')}</div>
        </div>
        <button class="btn btn-sm btn-secondary" onclick="drilldownAnalysisAction('${item.drilldown || ''}')">${escapeHtml(item.action || 'View')}</button>
      </div>
    </div>`;
  }).join('');
}

function drilldownAnalysisAction(target) {
  const map = {
    resolution: 'anomaly-major-monitoring',
    monitoring: 'anomaly-major-monitoring',
    rule_quality: 'anomaly-major-rules',
    patterns: 'anomaly-major-patterns',
    review: 'review',
    affiliates: 'affiliates',
  };
  if (target === 'review') {
    switchTab('review');
    return;
  }
  if (target === 'affiliates') {
    switchTab('affiliates');
    return;
  }
  const panel = map[target] || 'anomaly-major-actions';
  const btn = document.querySelector(`#anomalyMajorTabs .major-tab[data-major="${panel}"]`);
  if (btn) btn.click();
}

function renderReviewCoverage(data) {
  const row = document.getElementById('reviewCoverageMetrics');
  if (!row || !data) return;
  const tiers = data.tiers || {};
  const samp = data.sampling || {};
  const cards = [
    { v: `${tiers.high?.pct_reviewed ?? 0}%`, l: 'High-risk reviewed', sub: `${tiers.high?.reviewed ?? 0} / ${tiers.high?.total ?? 0}` },
    { v: `${tiers.medium?.pct_reviewed ?? 0}%`, l: 'Medium-risk reviewed', sub: `${tiers.medium?.reviewed ?? 0} / ${tiers.medium?.total ?? 0}` },
    { v: fmt(samp.pending ?? 0), l: 'Samples pending', sub: `${samp.total_samples ?? 0} total drawn` },
    { v: samp.estimated_false_negative_rate != null ? `${samp.estimated_false_negative_rate}%` : '—', l: 'Est. missed fraud', sub: `${samp.missed_fraud ?? 0} in samples` },
  ];
  row.innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="metric-label">${c.l}</div>
      <div class="metric-value">${c.v}</div>
      <div class="metric-sub">${c.sub}</div>
    </div>`).join('');
}

function renderEffectivenessSummary(eff) {
  const cards = document.getElementById('effCards');
  if (!cards) return;
  if (!eff) {
    cards.innerHTML = emptyState('◈', 'No effectiveness data', 'Record fraud outcomes first.');
    return;
  }
  cards.innerHTML = [
    { v: fmt(eff.total_flagged_high), l: 'Flagged High' },
    { v: fmt(eff.reviewed_high), l: 'Reviewed High' },
    { v: fmt(eff.confirmed_fraud_high), l: 'Confirmed Fraud' },
    { v: fmt(eff.false_positives_high), l: 'False Positives' },
    { v: fmtPct(eff.precision_high), l: 'Precision (High)' },
    { v: fmtCur(eff.total_payout_at_risk), l: 'Payout at Risk' },
    { v: fmtCur(eff.confirmed_fraud_amount), l: 'Confirmed Loss' },
    { v: fmtCur(eff.recovery_amount), l: 'Recovered' },
  ].map(c => `<div class="eff-card"><div class="eff-value">${c.v}</div><div class="eff-label">${c.l}</div></div>`).join('');

  const highData = [eff.confirmed_fraud_high || 0, eff.false_positives_high || 0,
    (eff.reviewed_high || 0) - (eff.confirmed_fraud_high || 0) - (eff.false_positives_high || 0)];
  const medData = [eff.confirmed_fraud_medium || 0, eff.false_positives_medium || 0,
    (eff.reviewed_medium || 0) - (eff.confirmed_fraud_medium || 0) - (eff.false_positives_medium || 0)];

  function outcomePie(el, data) {
    const node = document.getElementById(el);
    if (!node) return;
    if (data.every(v => v === 0)) {
      node.innerHTML = emptyState('◌', 'No reviews yet', 'Record outcomes to see breakdown.');
      return;
    }
    node.innerHTML = '';
    renderApexChart(el, 'donut', {
      labels: ['Confirmed Fraud', 'False Positive', 'Under Review'],
      values: data,
    }, {
      height: 260,
      colors: ['#ef4444', '#22c55e', '#f59e0b'],
      legend: { show: false },
      plotOptions: { pie: { donut: { size: '55%' } } },
      dataLabels: { enabled: true, style: { fontFamily: 'DM Mono, monospace', fontSize: '10px' } },
    });
  }
  outcomePie('chart-eff-high', highData);
  outcomePie('chart-eff-medium', medData);
}

async function loadRuleQuality() {
  const filters = analysisFilterParams();
  await Promise.all([
    loadRulePerformance(),
    loadCooccurrence(),
    loadModelPerformance(),
    loadMlSupervised(),
    loadFPCost(),
  ]);
  const fpRes = await api('/api/false-positive-analysis' + filters);
  renderFpAnalysis(fpRes.data);
}

function renderFpAnalysis(fpAnalysis) {
  const fpWrap = document.getElementById('fpAnalysisWrap');
  if (!fpWrap) return;
  if (fpAnalysis && fpAnalysis.flag_analysis && fpAnalysis.flag_analysis.length > 0) {
    fpWrap.innerHTML = buildTable('fpan', [
      { key: 'flag', label: 'Flag', hint: 'Detection rule name from reviewed accounts.', render: v => `<span style="font-size:11px">${truncate(v, 35)}</span>` },
      { key: 'fraud_count', label: 'Fraud', numeric: true, right: true, render: v => `<span style="color:var(--risk-high)">${v}</span>` },
      { key: 'fp_count', label: 'FP', numeric: true, right: true, render: v => `<span style="color:var(--risk-low)">${v}</span>` },
      { key: 'total', label: 'Total', numeric: true, right: true },
      { key: 'precision', label: 'Precision', numeric: true, right: true, render: v => {
        const color = v >= 70 ? 'var(--risk-low)' : v >= 50 ? 'var(--risk-medium)' : 'var(--risk-high)';
        return `<span style="color:${color}">${v}%</span>`;
      }},
      { key: 'confidence', label: 'Confidence', render: v => `<span class="conf-badge conf-${v || 'neutral'}">${(v || '—').replace(/_/g, ' ')}</span>` },
    ], fpAnalysis.flag_analysis, { emptyIcon: '📊', emptyTitle: 'No flag analysis data' });
  } else {
    fpWrap.innerHTML = emptyState('📊', 'No false positive data yet', 'Record more outcomes to see which flags cause the most false positives.');
  }
}

async function loadCooccurrence() {
  const wrap = document.getElementById('cooccurrenceWrap');
  if (!wrap) return;
  const res = await api('/api/analysis/rule-cooccurrence' + analysisFilterParams());
  if (res.error) {
    wrap.innerHTML = errorState('Failed to load co-occurrence', res.error, 'loadCooccurrence()');
    return;
  }
  const pairs = res.data?.pairs || [];
  const triples = res.data?.triples || [];
  if (!pairs.length && !triples.length) {
    wrap.innerHTML = emptyState('⊞', 'Not enough reviewed data', 'Need more confirmed fraud / false positive outcomes for combination analysis.');
    return;
  }
  const renderRows = (rows, title) => {
    if (!rows.length) return '';
    return `<div style="padding:10px 16px;font-size:12px;font-weight:600;color:var(--text-muted);">${title}</div>
      <table class="data-table no-sort"><thead><tr>
        <th>Combination</th><th style="text-align:right">Reviewed</th><th style="text-align:right">Precision</th><th>Confidence</th>
      </tr></thead><tbody>
      ${rows.map(r => `<tr>
        <td style="font-size:11px">${truncate(r.combo, 50)}</td>
        <td style="text-align:right">${r.reviewed}</td>
        <td style="text-align:right;color:${r.precision >= 70 ? 'var(--risk-low)' : r.precision >= 50 ? 'var(--risk-medium)' : 'var(--risk-high)'}">${r.precision}%</td>
        <td><span class="conf-badge conf-${r.confidence}">${r.confidence.replace(/_/g, ' ')}</span></td>
      </tr>`).join('')}
      </tbody></table>`;
  };
  wrap.innerHTML = renderRows(pairs, 'Top pairs') + renderRows(triples, 'Top triples');
}

async function loadPatternMovement() {
  const filters = analysisFilterParams();
  const [risingRes, crossRes] = await Promise.all([
    api('/api/analysis/rising-patterns' + filters),
    api('/api/cross-affiliate'),
  ]);
  renderRisingPatterns(risingRes.data);
  renderCrossAffiliate(crossRes.data);
  return runPatternDiscovery();
}

function renderRisingPatterns(data) {
  const wrap = document.getElementById('risingPatternsWrap');
  if (!wrap) return;
  const typeMap = { Flags: 'flag', Domains: 'domain', Affiliates: 'affiliate', Campaigns: 'campaign' };
  const sections = [
    { key: 'flags', label: 'Flags', nameKey: 'flag' },
    { key: 'domains', label: 'Domains', nameKey: 'domain' },
    { key: 'affiliates', label: 'Affiliates', nameKey: 'affiliate' },
    { key: 'campaigns', label: 'Campaigns', nameKey: 'campaign' },
  ];
  const rows = [];
  sections.forEach(sec => {
    (data?.[sec.key] || []).slice(0, 8).forEach(item => {
      const name = item[sec.nameKey];
      rows.push({
        type: sec.label,
        name,
        recent: item.recent_count,
        baseline: item.baseline_count,
        delta: item.delta_pct,
        drillKey: `${typeMap[sec.label]}|${name}`,
      });
    });
  });
  if (!rows.length) {
    wrap.innerHTML = emptyState('📈', 'No rising patterns', 'Nothing significantly above baseline for current filters.');
    return;
  }
  wrap.innerHTML = buildTable('rising', [
    { key: 'type', label: 'Type' },
    { key: 'name', label: 'Pattern', render: v => `<span style="font-size:11px">${truncate(String(v).replace(/_/g, ' '), 40)}</span>` },
    { key: 'recent', label: 'Last 7d', numeric: true, right: true },
    { key: 'baseline', label: 'Prior 28d', numeric: true, right: true },
    { key: 'delta', label: 'Rate change', numeric: true, right: true, render: v => `<span style="color:var(--risk-high)">+${v}%</span>` },
  ], rows, {
    emptyIcon: '📈',
    emptyTitle: 'No rising patterns',
    clickable: true,
    onClick: 'openAnalysisDrilldownFromKey',
    onClickKey: 'drillKey',
  });
}

const ANALYSIS_DRILL_TYPE_LABELS = {
  flag: 'Flag',
  domain: 'Domain',
  affiliate: 'Affiliate',
  campaign: 'Campaign',
  day: 'Day',
};

let _analysisDrilldown = { type: '', value: '', page: 1, totalPages: 1 };

function openAnalysisDrilldownFromKey(encodedKey) {
  const raw = decodeURIComponent(String(encodedKey || ''));
  const pipe = raw.indexOf('|');
  if (pipe < 1) return;
  openAnalysisDrilldown(raw.slice(0, pipe), raw.slice(pipe + 1));
}

function openAnalysisDrilldown(type, value, page = 1) {
  if (!type || !value) return;
  _analysisDrilldown = { type, value, page, totalPages: 1 };
  const panel = document.getElementById('analysisDrilldownPanel');
  if (panel) {
    panel.style.display = '';
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  const label = ANALYSIS_DRILL_TYPE_LABELS[type] || type;
  const title = document.getElementById('analysisDrilldownTitle');
  if (title) title.textContent = `${label}: ${value}`;
  loadAnalysisDrilldownPage(0);
}

function closeAnalysisDrilldown() {
  const panel = document.getElementById('analysisDrilldownPanel');
  if (panel) panel.style.display = 'none';
  _analysisDrilldown = { type: '', value: '', page: 1, totalPages: 1 };
}

function loadAnalysisDrilldownPage(delta) {
  if (!_analysisDrilldown.type) return;
  if (delta) _analysisDrilldown.page = Math.max(1, _analysisDrilldown.page + delta);
  loadAnalysisDrilldown(_analysisDrilldown.page);
}

async function loadAnalysisDrilldown(page = 1) {
  const { type, value } = _analysisDrilldown;
  const wrap = document.getElementById('analysisDrilldownWrap');
  const sub = document.getElementById('analysisDrilldownSubtitle');
  const pag = document.getElementById('analysisDrilldownPagination');
  if (!wrap || !type) return;

  wrap.innerHTML = '<div class="loading-spinner">Loading accounts…</div>';
  const minRisk = document.getElementById('patternRisk')?.value || '50';
  const url = `/api/analysis/drilldown?type=${encodeURIComponent(type)}&value=${encodeURIComponent(value)}&page=${page}&per_page=50&min_risk=${encodeURIComponent(minRisk || '0')}`;
  const res = await api(url);

  if (res.error) {
    wrap.innerHTML = errorState('Failed to load accounts', res.error);
    if (pag) pag.style.display = 'none';
    return;
  }

  const { accounts, total, total_pages: totalPages } = res.data;
  _analysisDrilldown.page = page;
  _analysisDrilldown.totalPages = totalPages || 1;

  if (sub) sub.textContent = `${fmt(total)} account${total === 1 ? '' : 's'} · risk ≥ ${minRisk || 0}`;

  const exportLink = document.getElementById('analysisDrilldownExport');
  if (exportLink) {
    exportLink.href = `/api/export/fraud-results?min_risk=${encodeURIComponent(minRisk || '50')}&limit=5000`;
  }

  if (!accounts || !accounts.length) {
    wrap.innerHTML = emptyState('📋', 'No accounts found', 'Try lowering the risk filter or pick another pattern.');
    if (pag) pag.style.display = 'none';
    return;
  }

  wrap.innerHTML = buildTable('analysisDrill', [
    {
      key: 'email',
      label: 'Email',
      render: (v, row) => {
        const d = row.duid != null ? String(row.duid) : '';
        const lab = truncate(String(v || ''), 32);
        return d
          ? `<span class="mono clickable" data-open-account="${escapeHtml(d)}" title="Account details">${escapeHtml(lab)}</span>`
          : escapeHtml(lab);
      },
    },
    { key: 'risk_score', label: 'Risk', render: v => riskBadge(v) },
    {
      key: 'trans_datetime',
      label: 'Date',
      muted: true,
      render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
    },
    { key: 'data_type', label: 'Type', render: v => `<span class="type-badge ${v}">${v || '—'}</span>` },
    {
      key: 'affiliate',
      label: 'Affiliate',
      muted: true,
      render: (v) =>
        v
          ? `<span class="mono clickable" data-affiliate-drill="${escapeHtml(v)}" title="Open affiliate">${escapeHtml(truncate(String(v), 16))}</span>`
          : '—',
    },
    { key: 'payout_amount', label: 'Payout', render: v => fmtCur(v) },
    {
      key: 'duid',
      label: '',
      render: (v) =>
        `<button type="button" class="btn btn-sm" data-open-account="${escapeHtml(String(v != null ? v : ''))}">View</button>`,
    },
  ], accounts, { emptyIcon: '📋', emptyTitle: 'No accounts' });

  if (pag) {
    pag.style.display = totalPages > 1 ? 'flex' : 'none';
    const info = document.getElementById('analysisDrilldownPageInfo');
    if (info) info.textContent = `Page ${page} of ${totalPages} (${fmt(total)} accounts)`;
    const prev = document.getElementById('analysisDrilldownPrev');
    const next = document.getElementById('analysisDrilldownNext');
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= totalPages;
  }
}

function renderCrossAffiliate(crossAff) {
  const crossWrap = document.getElementById('crossAffWrap');
  if (!crossWrap) return;
  if (crossAff && crossAff.cross_affiliate_domains && crossAff.cross_affiliate_domains.length > 0) {
    const rows = crossAff.cross_affiliate_domains.map(r => ({
      ...r,
      drillKey: `domain|${r.domain}`,
    }));
    crossWrap.innerHTML = buildTable('xaff', [
      { key: 'domain', label: 'Domain' },
      { key: 'affiliates', label: 'Affiliates', numeric: true, right: true },
      { key: 'accounts', label: 'Accounts', numeric: true, right: true },
      { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true, render: v => v != null ? v.toFixed(0) : '—' },
    ], rows, {
      emptyIcon: '⊞',
      emptyTitle: 'No cross-affiliate patterns',
      clickable: true,
      onClick: 'openAnalysisDrilldownFromKey',
      onClickKey: 'drillKey',
    });
  } else {
    crossWrap.innerHTML = emptyState('⊞', 'No cross-affiliate patterns', 'Patterns appear when domains or IPs span multiple affiliates.');
  }
}

async function loadAnalysisMonitoring() {
  await Promise.all([
    loadResolutionTracking(),
    loadDrift(),
    loadSampling(),
  ]);
}

// ─── Effectiveness (legacy alias) ───
async function loadEffectiveness() {
  return loadActionCenter();
}

// ─── Resolution Tracking ───
async function loadResolutionTracking() {
  const res = await api('/api/resolution/summary');
  if (res.error || !res.data) return;
  const d = res.data;
  const s = d.summary || {};

  // Metric cards
  const mRow = document.getElementById('resolutionMetrics');
  if (mRow) {
    const closureColor = s.closure_rate >= 80 ? 'var(--risk-low)' : s.closure_rate >= 50 ? 'var(--risk-medium)' : 'var(--risk-high)';
    mRow.innerHTML = [
      { v: fmt(s.total_confirmed),   l: 'Confirmed Fraud',     sub: 'total outcomes' },
      { v: `${s.closure_rate}%`,     l: 'Closure Rate',        sub: 'actioned / confirmed', color: closureColor },
      { v: fmt(s.suspended),         l: 'Suspended',           sub: 'accounts actioned' },
      { v: fmt(s.clawback_received), l: 'Clawback Received',   sub: 'payments recovered' },
      { v: fmtCur(s.total_recovered),l: 'Total Recovered',     sub: 'from clawbacks' },
      { v: fmt(s.total_fp),          l: 'False Positives',     sub: `${fmt(s.fp_cleared)} cleared` },
    ].map(c => `
      <div class="metric-card">
        <div class="metric-label">${c.l}</div>
        <div class="metric-value" style="${c.color ? `color:${c.color}` : ''}">${c.v}</div>
        <div class="metric-sub">${c.sub}</div>
      </div>`).join('');
  }

  // Unresolved queue
  const unresolved = d.unresolved || [];
  const countEl = document.getElementById('unresolvedCount');
  if (countEl) countEl.textContent = `${unresolved.length} pending action`;

  const wrap = document.getElementById('unresolvedTableWrap');
  if (!wrap) return;
  if (unresolved.length === 0) {
    wrap.innerHTML = `<div style="padding:20px;text-align:center;color:var(--risk-low);font-size:13px;">
      ✓ All confirmed fraud cases have been actioned
    </div>`;
    return;
  }

  const RESOLUTION_OPTIONS = [
    { v: 'pending',             l: '— Pending —' },
    { v: 'suspended',           l: 'Account Suspended' },
    { v: 'clawback_requested',  l: 'Clawback Requested' },
    { v: 'clawback_received',   l: 'Clawback Received' },
    { v: 'no_action',           l: 'No Action Taken' },
    { v: 'monitoring',          l: 'Monitoring' },
  ];

  wrap.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>DUID</th><th>Email</th><th>Risk</th>
        <th style="text-align:right">Payout</th>
        <th>Reviewed</th>
        <th>Resolution</th>
        <th></th>
      </tr></thead>
      <tbody>
        ${unresolved.map(r => `
          <tr id="resrow-${r.duid}">
            <td><code style="font-size:11px">${r.duid}</code></td>
            <td>${truncate(r.email || '—', 28)}</td>
            <td>${riskBadge(r.risk_score)}</td>
            <td style="text-align:right">${fmtCur(r.payout_amount)}</td>
            <td style="font-size:11px;color:var(--text-muted)">${r.reviewed_at ? r.reviewed_at.slice(0,10) : '—'}</td>
            <td>
              <select class="filter-select" id="res-sel-${r.duid}" style="font-size:12px;padding:4px 8px;">
                ${RESOLUTION_OPTIONS.map(o => `<option value="${o.v}">${o.l}</option>`).join('')}
              </select>
            </td>
            <td>
              <button class="btn btn-sm" onclick="saveResolution('${r.duid}')">Save</button>
            </td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

async function saveResolution(duid) {
  const sel = document.getElementById(`res-sel-${duid}`);
  if (!sel || sel.value === 'pending') {
    showToast('Select a resolution status first', 'warning');
    return;
  }
  const btn = sel.closest('tr').querySelector('button');
  const origText = btn.textContent;
  btn.textContent = '…';
  btn.disabled = true;

  try {
    const r = await fetch('/api/resolution/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duid, status: sel.value })
    });
    const json = await r.json();
    if (!r.ok || json.error) throw new Error(json.error || `HTTP ${r.status}`);
    showToast(`Resolution saved for ${duid}`, 'success');
    clearApiCache();
    const row = document.getElementById(`resrow-${duid}`);
    if (row) row.style.opacity = '0.4';
    setTimeout(loadResolutionTracking, 800);
  } catch (e) {
    showToast(`Failed: ${e.message}`, 'error');
    btn.textContent = origText;
    btn.disabled = false;
  }
}

// ─── False Positive Cost ───
async function loadFPCost() {
  const res = await api('/api/false-positive-cost' + analysisFilterParams());
  if (res.error || !res.data) return;
  const d = res.data;
  const s = d.summary || {};

  // Metric cards
  const mRow = document.getElementById('fpCostMetrics');
  if (mRow) {
    mRow.innerHTML = [
      { v: fmt(s.total_fp),      l: 'Total False Positives', sub: 'flagged but legitimate' },
      { v: fmtCur(s.total_cost), l: 'Est. Revenue at Risk',  sub: 'sum of FP payout amounts', highlight: true },
      { v: fmtCur(s.avg_cost),   l: 'Avg Cost per FP',       sub: 'avg payout per FP account' },
      { v: fmtCur(s.median_cost),l: 'Median Cost per FP',    sub: 'median payout per FP account' },
    ].map(c => `
      <div class="metric-card">
        <div class="metric-label">${c.l}</div>
        <div class="metric-value" style="${c.highlight ? 'color:var(--risk-medium)' : ''}">${c.v}</div>
        <div class="metric-sub">${c.sub}</div>
      </div>`).join('');
  }

  // By-flag table
  const flagWrap = document.getElementById('fpCostByFlagWrap');
  if (flagWrap) {
    if (!d.by_flag || d.by_flag.length === 0) {
      flagWrap.innerHTML = emptyState('◌', 'No FP data yet', 'Record false positive outcomes to see cost by rule.');
    } else {
      const maxCost = Math.max(...d.by_flag.map(f => f.cost));
      flagWrap.innerHTML = `
        <table class="data-table">
          <thead><tr>
            <th>Flag / Rule</th>
            <th style="text-align:right">FP Count</th>
            <th style="text-align:right">Total Revenue Lost</th>
            <th style="text-align:right">Avg per FP</th>
            <th>Cost Share</th>
          </tr></thead>
          <tbody>
            ${d.by_flag.map(f => {
              const pct = maxCost > 0 ? (f.cost / maxCost * 100).toFixed(0) : 0;
              return `<tr>
                <td><code style="font-size:11px">${truncate(f.flag, 38)}</code></td>
                <td style="text-align:right">${fmt(f.count)}</td>
                <td style="text-align:right;color:var(--risk-medium)">${fmtCur(f.cost)}</td>
                <td style="text-align:right">${fmtCur(f.avg_cost)}</td>
                <td style="padding-right:12px">
                  <div style="background:rgba(245,158,11,0.15);height:8px;border-radius:4px;overflow:hidden">
                    <div style="background:var(--risk-medium);width:${pct}%;height:100%;border-radius:4px;"></div>
                  </div>
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>`;
    }
  }

  const chartEl = document.getElementById('fpCostTrendChart');
  if (chartEl && d.monthly && d.monthly.length > 0) {
    chartEl.innerHTML = '';
    renderApexChart('fpCostTrendChart', 'line', {
      series: [{ name: 'Revenue at Risk ($)', data: d.monthly.map(m => +(m.cost || 0).toFixed(2)) }],
      categories: d.monthly.map(m => m.period),
    }, {
      height: 220,
      colors: ['#f59e0b'],
      stroke: { curve: 'smooth', width: 2 },
      xaxis: { title: { text: 'Month' } },
      yaxis: { labels: { formatter: v => '$' + Number(v).toFixed(0) } },
    });
  } else if (chartEl) {
    chartEl.innerHTML = emptyState('◌', 'No monthly FP data', 'Record false positive outcomes to see trend.');
  }
}

// ─── Affiliate Value vs Fraud Matrix ───
async function loadAffiliateMatrix() {
  const res = await api('/api/affiliate/value-fraud-matrix');
  if (res.error || !res.data) return;
  const d   = res.data;
  const exclude = externalOnlyExcludeLower();
  const rows = (d.matrix || []).filter(r => !exclude.has((r.webmaster_code || '').toLowerCase()));
  const summ = d.summary || {};
  const thresh = d.thresholds || {};

  const matrixPanel = document.getElementById('affMatrixPanel');
  if (rows.length === 0) {
    if (matrixPanel) matrixPanel.style.display = 'none';
    return;
  }
  if (matrixPanel) matrixPanel.style.display = '';

  // Summary chips
  const sumRow = document.getElementById('affMatrixSummaryRow');
  if (sumRow) {
    const chips = [
      { label: '✓ Keep',        count: summ.keep,        color: 'var(--risk-low)' },
      { label: '⚠ Investigate', count: summ.investigate, color: 'var(--risk-high)' },
      { label: '○ Monitor',     count: summ.monitor,     color: 'var(--text-muted)' },
      { label: '✗ Review',      count: summ.review,      color: 'var(--risk-medium)' },
      { label: '✔ Actioned',    count: summ.actioned || 0, color: '#6366f1' },
    ];
    sumRow.innerHTML = chips.map(c => `
      <div style="display:flex;align-items:center;gap:8px;background:var(--bg-card);
                  border:1px solid var(--border);border-radius:8px;padding:8px 14px;">
        <span style="font-weight:700;font-size:18px;color:${c.color}">${c.count}</span>
        <span style="font-size:12px;color:var(--text-muted)">${c.label}</span>
      </div>`).join('');
  }

  // Scatter chart
  const QUAD_COLORS = { keep: '#22c55e', investigate: '#ef4444', monitor: '#94a3b8', review: '#f59e0b' };
  const QUAD_LABELS = { keep: 'Keep', investigate: 'Investigate', monitor: 'Monitor', review: 'Review' };

  const byQuad = {};
  rows.forEach(r => {
    if (!byQuad[r.quadrant]) byQuad[r.quadrant] = [];
    byQuad[r.quadrant].push({ x: r.total_payout, y: r.fraud_rate, name: r.webmaster_code });
  });

  const series = Object.entries(byQuad).map(([q, pts]) => ({
    name: QUAD_LABELS[q] || q,
    data: pts.map(p => ({ x: p.x, y: p.y, name: p.name })),
    color: QUAD_COLORS[q] || '#94a3b8',
  }));

  const chartEl = document.getElementById('affMatrixChart');
  if (chartEl && series.length > 0) {
    const sc = new ApexCharts(chartEl, {
      series,
      chart:  { type: 'scatter', height: 320, background: 'transparent', toolbar: { show: false } },
      xaxis:  { title: { text: 'Total Payout ($)', style: { color: 'var(--text-muted)', fontSize: '11px' } },
                labels: { formatter: v => '$' + Number(v).toFixed(0), style: { colors: 'var(--text-muted)' } } },
      yaxis:  { title: { text: 'Risk fraud % (lifetime, score ≥50)', style: { color: 'var(--text-muted)', fontSize: '11px' } },
                labels: { formatter: v => v + '%', style: { colors: 'var(--text-muted)' } },
                min: 0, max: 100 },
      markers: { size: 7, strokeWidth: 0, hover: { sizeOffset: 3 } },
      // Quadrant reference lines (median thresholds)
      annotations: {
        xaxis: [{ x: thresh.median_payout,
                  borderColor: 'rgba(148,163,184,0.4)', strokeDashArray: 4,
                  label: { text: 'Med. Revenue', style: { color: 'var(--text-muted)', fontSize: '10px', background: 'transparent' } } }],
        yaxis: [{ y: thresh.median_fraud_rate,
                  borderColor: 'rgba(148,163,184,0.4)', strokeDashArray: 4,
                  label: { text: 'Med. Fraud %', style: { color: 'var(--text-muted)', fontSize: '10px', background: 'transparent' } } }],
      },
      tooltip: {
        custom: ({ seriesIndex, dataPointIndex, w }) => {
          const pt = w.config.series[seriesIndex].data[dataPointIndex];
          const r  = rows.find(x => x.webmaster_code === pt.name) || {};
          const confirmedLine = (r.confirmed_rate != null)
            ? `<br>Confirmed fraud: ${r.confirmed_rate}% (${r.confirmed_count} reviewed)`
            : (r.reviewed_count > 0 ? `<br>Reviews logged: ${r.reviewed_count}` : '');
          const actionedLine = r.actioned_count > 0
            ? `<br><span style="color:#6366f1">✔ ${r.actioned_count} actioned</span>` : '';
          const min30 = thresh.fraud_rate_30d_min_sample ?? 5;
          const rate30Line = (r.fraud_rate_30d != null)
            ? `<br>Last 30d (analyzed): ${r.fraud_rate_30d}% (${r.high_risk_30d} high / ${r.accounts_30d} accts)`
            : (r.accounts_30d > 0
                ? `<br>Last 30d: &lt;${min30} accounts in window (n=${r.accounts_30d})`
                : '');
          return `<div style="padding:8px 12px;font-size:12px;line-height:1.6">
            <strong>${pt.name}</strong><br>
            Revenue: $${Number(pt.x).toFixed(2)}<br>
            Risk-score fraud rate: ${Number(pt.y).toFixed(1)}%${rate30Line}${confirmedLine}${actionedLine}
          </div>`;
        }
      },
      theme:  { mode: document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark' },
      grid:   { borderColor: 'rgba(148,163,184,0.1)' },
      legend: { labels: { colors: 'var(--text-muted)' } },
    });
    sc.render();
  }

  // Decision table — sorted: investigate first, then review, then monitor, then actioned, then keep
  const ORDER = { investigate: 0, review: 1, monitor: 2, actioned: 3, keep: 4 };
  const sorted = [...rows].sort((a, b) => (ORDER[a.quadrant] ?? 9) - (ORDER[b.quadrant] ?? 9));

  const wrap = document.getElementById('affMatrixTableWrap');
  if (wrap) {
  const SIGNAL_CSS = {
    keep:        'color:var(--risk-low)',
    investigate: 'color:var(--risk-high);font-weight:600',
    review:      'color:var(--risk-medium);font-weight:600',
    monitor:     'color:var(--text-muted)',
    actioned:    'color:#6366f1;font-weight:600',
  };
  const SIGNAL_BADGE = (quadrant, label) =>
    `<span class="signal-badge ${quadrant}">${label}</span>`;
    wrap.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>Affiliate</th>
          <th style="text-align:right">Revenue</th>
          <th style="text-align:right">Risk % (life)</th>
          <th style="text-align:right">Risk % (30d)</th>
          <th style="text-align:right">Confirmed %</th>
          <th style="text-align:right">Fraud Payout</th>
          <th style="text-align:right">Clean Payout</th>
          <th style="text-align:right">Accounts</th>
          <th>Signal</th>
          <th style="width:32px"></th>
        </tr></thead>
        <tbody>
          ${sorted.map(r => {
            const confirmedCell = r.confirmed_rate != null
              ? `<span title="${r.confirmed_count} of ${r.reviewed_count} reviewed accounts confirmed fraud">${r.confirmed_rate}%</span>`
              : (r.reviewed_count > 0
                  ? `<span style="color:var(--text-muted);font-size:11px" title="${r.reviewed_count} reviewed, not enough for rate">${r.reviewed_count} rev.</span>`
                  : `<span style="color:var(--text-muted);opacity:0.4">—</span>`);
            const reviewedBadge = r.reviewed_count > 0
              ? `<span title="${r.reviewed_count} accounts have outcomes recorded" style="font-size:9px;background:rgba(99,102,241,0.15);color:#6366f1;border-radius:3px;padding:1px 4px;margin-left:4px">reviewed</span>`
              : '';
            const min30 = thresh.fraud_rate_30d_min_sample ?? 5;
            const cell30 = (r.fraud_rate_30d != null)
              ? `<span title="Accounts analyzed in last 30 days: ${r.accounts_30d}">${r.fraud_rate_30d}%</span>`
              : (r.accounts_30d > 0
                  ? `<span style="color:var(--text-muted);font-size:11px" title="Fewer than ${min30} accounts in 30d window">n=${r.accounts_30d}</span>`
                  : `<span style="color:var(--text-muted);opacity:0.4">—</span>`);
            return `
            <tr onclick="window.location.href='/affiliate/${encodeURIComponent(r.webmaster_code)}'" style="cursor:pointer">
              <td>
                <span style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                  <code style="font-size:12px">${r.webmaster_code}</code>${affiliateActionPillHtml(r.webmaster_code)}${reviewedBadge}
                </span>
              </td>
              <td style="text-align:right">${fmtCur(r.total_payout)}</td>
              <td style="text-align:right">${r.fraud_rate}%</td>
              <td style="text-align:right">${cell30}</td>
              <td style="text-align:right">${confirmedCell}</td>
              <td style="text-align:right;color:var(--risk-high)">${fmtCur(r.fraud_payout)}</td>
              <td style="text-align:right;color:var(--risk-low)">${fmtCur(r.clean_payout)}</td>
              <td style="text-align:right">${fmt(r.total_accounts)}</td>
              <td>${SIGNAL_BADGE(r.quadrant, r.signal)}</td>
              <td onclick="event.stopPropagation()">
                <a href="/affiliate/${encodeURIComponent(r.webmaster_code)}" target="_blank"
                   style="font-size:10px;color:var(--accent);text-decoration:none;opacity:0.6;padding:2px 6px;border:1px solid var(--border);border-radius:3px;white-space:nowrap;transition:opacity 0.1s;"
                   onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'"
                   title="Open affiliate detail page">↗</a>
              </td>
            </tr>`}).join('')}
        </tbody>
      </table>`;
  }
}

/** Score buckets + per-flag outcome mix (fraud_outcomes calibration). */
async function loadRiskCalibration() {
  const bucketsEl = document.getElementById('affRiskCalibrationBuckets');
  const flagsEl = document.getElementById('affRiskCalibrationFlags');
  if (!bucketsEl && !flagsEl) return;

  const [bRes, fRes] = await Promise.all([
    api('/api/analytics/outcome-score-buckets'),
    api('/api/analytics/flag-outcome-precision'),
  ]);

  if (bucketsEl) {
    if (bRes.error || !bRes.data) {
      bucketsEl.innerHTML = `<p class="text-muted" style="padding:12px;">Could not load score buckets.</p>`;
    } else {
      const rows = bRes.data.buckets || [];
      const totals = bRes.data.totals || {};
      if (rows.length === 0) {
        bucketsEl.innerHTML = `<p class="text-muted" style="padding:12px;">No reviewed accounts yet. Record outcomes to calibrate risk tiers.</p>`;
      } else {
        bucketsEl.innerHTML = `
          <p style="font-size:12px;color:var(--text-muted);margin:0 0 10px 0;">
            Among accounts with an outcome in <code>fraud_outcomes</code>, by risk score at analysis time.
            <strong>Precision (closed)</strong> = confirmed ÷ (confirmed + false positive + legitimate).
            Total reviewed: <strong>${totals.reviewed ?? 0}</strong>.
          </p>
          <table class="data-table">
            <thead><tr>
              <th>Score bucket</th>
              <th style="text-align:right">Reviewed</th>
              <th style="text-align:right">Confirmed</th>
              <th style="text-align:right">False pos.</th>
              <th style="text-align:right">Legit</th>
              <th style="text-align:right">Under review</th>
              <th style="text-align:right">Confirmed %</th>
              <th style="text-align:right">Precision (closed)</th>
            </tr></thead>
            <tbody>
              ${rows.map(r => `
                <tr>
                  <td><code>${r.bucket}</code></td>
                  <td style="text-align:right">${fmt(r.reviewed)}</td>
                  <td style="text-align:right">${fmt(r.confirmed_fraud)}</td>
                  <td style="text-align:right">${fmt(r.false_positive)}</td>
                  <td style="text-align:right">${fmt(r.legitimate)}</td>
                  <td style="text-align:right">${fmt(r.under_review)}</td>
                  <td style="text-align:right">${r.confirmed_rate}%</td>
                  <td style="text-align:right">${r.precision_closed_pct != null ? r.precision_closed_pct + '%' : '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>`;
      }
    }
  }

  if (flagsEl) {
    if (fRes.error || !fRes.data) {
      flagsEl.innerHTML = `<p class="text-muted" style="padding:12px;">Could not load flag precision.</p>`;
    } else {
      const flags = fRes.data.flags || [];
      if (flags.length === 0) {
        flagsEl.innerHTML = `<p class="text-muted" style="padding:12px;">No flag-level data yet (needs reviewed accounts with detection flags).</p>`;
      } else {
        flagsEl.innerHTML = `
          <p style="font-size:12px;color:var(--text-muted);margin:0 0 10px 0;">
            For each detection flag: outcomes among reviewed accounts that had that flag. Sorted by review volume.
          </p>
          <div style="overflow-x:auto;max-height:320px;">
          <table class="data-table">
            <thead><tr>
              <th>Flag</th>
              <th style="text-align:right">Reviewed</th>
              <th style="text-align:right">Confirmed</th>
              <th style="text-align:right">False pos.</th>
              <th style="text-align:right">Legit</th>
              <th style="text-align:right">Under review</th>
              <th style="text-align:right">Confirmed %</th>
              <th style="text-align:right">Precision (closed)</th>
            </tr></thead>
            <tbody>
              ${flags.map(r => `
                <tr>
                  <td><code style="font-size:11px">${r.flag}</code></td>
                  <td style="text-align:right">${fmt(r.reviewed)}</td>
                  <td style="text-align:right">${fmt(r.confirmed_fraud)}</td>
                  <td style="text-align:right">${fmt(r.false_positive)}</td>
                  <td style="text-align:right">${fmt(r.legitimate)}</td>
                  <td style="text-align:right">${fmt(r.under_review)}</td>
                  <td style="text-align:right">${r.confirmed_rate_pct}%</td>
                  <td style="text-align:right">${r.precision_closed_pct != null ? r.precision_closed_pct + '%' : '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table></div>`;
      }
    }
  }
}

// ─── Drift ───
async function loadDrift() {
  const res = await api('/api/metrics-history?days=30');
  const driftEl = document.getElementById('chart-drift');
  const precEl = document.getElementById('chart-precision');
  const rows = Array.isArray(res.data) ? res.data : [];
  if (res.error || rows.length === 0) {
    if (driftEl) driftEl.innerHTML = emptyState('⏤', 'No metrics history', 'Metrics are recorded when you run the effectiveness dashboard in the CLI.');
    if (precEl) precEl.innerHTML = '';
    return;
  }

  if (driftEl) driftEl.innerHTML = '';
  if (precEl) precEl.innerHTML = '';

  // Group by date
  const byDate = {};
  rows.forEach(r => {
    if (!byDate[r.metric_date]) byDate[r.metric_date] = {};
    byDate[r.metric_date][r.risk_tier] = r;
  });
  const dates = Object.keys(byDate).sort();

  const highFlagged = dates.map(d => byDate[d].high?.total_flagged || 0);
  const medFlagged = dates.map(d => byDate[d].medium?.total_flagged || 0);
  const lowFlagged = dates.map(d => byDate[d].low?.total_flagged || 0);

  renderApexChart('chart-drift', 'line', {
    series: [
      { name: 'High Risk', data: highFlagged },
      { name: 'Medium Risk', data: medFlagged },
      { name: 'Low Risk', data: lowFlagged }
    ],
    categories: dates
  }, {
    height: 340,
    colors: ['#ef4444', '#f59e0b', '#22c55e'],
    stroke: { curve: 'straight', width: 2 },
    markers: { size: 5 },
    legend: { position: 'top', horizontalAlign: 'center' },
    yaxis: { title: { text: 'Flagged Accounts' } }
  });

  const precHigh = dates.map(d => byDate[d].high?.precision_rate);
  const precMed = dates.map(d => byDate[d].medium?.precision_rate);

  renderApexChart('chart-precision', 'line', {
    series: [
      { name: 'High Risk Precision', data: precHigh.map(v => (v != null ? v * 100 : null)) },
      { name: 'Medium Risk Precision', data: precMed.map(v => (v != null ? v * 100 : null)) }
    ],
    categories: dates
  }, {
    height: 300,
    colors: ['#ef4444', '#f59e0b'],
    stroke: { curve: 'straight', width: 2 },
    markers: { size: 5 },
    legend: { position: 'top', horizontalAlign: 'center' },
    yaxis: { min: 0, max: 105, title: { text: 'Precision %' } }
  });
}

// ─── Billing ───
function openBillingSharedAccount(idx) {
  const r = window._billingSharedData?.[idx];
  if (r && r.duid) window.open('/account/' + encodeURIComponent(r.duid), '_blank');
}

async function loadBilling() {
  const [summaryRes, clustersRes, namesRes, ipsRes, sharedRes] = await Promise.all([
    api('/api/billing/summary'),
    api('/api/billing'),
    api('/api/billing/names'),
    api('/api/billing/ips'),
    api('/api/billing/shared-card-signals'),
  ]);

  const summary = summaryRes.data || {};
  const clusters = clustersRes.data || [];
  const names = namesRes.data || [];
  const ips = ipsRes.data || [];
  let shared = sharedRes.data || [];
  const externalExclude = externalOnlyExcludeLower();
  if (externalExclude.size) {
    shared = shared.filter(
      r => !externalExclude.has(String(r.webmaster_code || '').trim().toLowerCase())
    );
  }

  // Summary cards
  const mWrap = document.getElementById('billingMetrics');
  if (summary) {
    mWrap.innerHTML = [
      { v: fmt(summary.name_clusters), l: 'Name Clusters' },
      { v: fmt(summary.high_chargeback_accounts), l: 'Accounts with Chargebacks' }
    ].map(c => `<div class="metric-card"><div class="metric-label">${c.l}</div><div class="metric-value">${c.v}</div></div>`).join('');
  }

  // Note: Shared billing ID clusters removed (unreliable processor_subscriber_id data)

  // Store for drilldown
  window._billingClusters = clusters;

  // Names table - clickable for drilldown
  window._billingNames = names;
  document.getElementById('billingNamesWrap').innerHTML = buildTable('bnm', [
    { key: 'full_name', label: 'Name', render: v => v ? v.replace(/\b\w/g, c => c.toUpperCase()) : '—' },
    { key: 'account_count', label: 'Unique Accts', numeric: true, right: true, render: v => fmt(v) },
    { key: 'transaction_count', label: 'Transactions', numeric: true, right: true, render: (v, row) => {
      if (!v || v === row.account_count) return fmt(v || row.account_count);
      return `<span title="${fmt(v)} transactions across ${fmt(row.account_count)} accounts">${fmt(v)} <span style="color:var(--text-muted);font-size:10px;">(${fmt(row.account_count)} accts)</span></span>`;
    }},
    { key: 'unique_cards', label: 'Unique Cards', numeric: true, right: true },
    { key: 'unique_emails', label: 'Unique Emails', numeric: true, right: true, render: (v, row) => {
      const count = v || (row.emails ? row.emails.split(',').filter(e => e.trim()).length : 1);
      const tooltip = count === 1 ? 'Same email for all accounts' : `${count} distinct emails`;
      return `<span title="${tooltip}" style="color:${count === 1 ? 'var(--risk-high)' : 'inherit'}">${count}${count === 1 ? ' ⚠' : ''}</span>`;
    }},
    { key: 'total_payout', label: 'Total Payout', numeric: true, right: true, render: v => fmtCur(v) },
    { key: 'emails', label: 'Sample Email', muted: true, render: v => {
      const first = (v || '').split(',')[0].trim();
      const total = (v || '').split(',').filter(e => e.trim()).length;
      return truncate(first, 28) + (total > 1 ? ` +${total - 1}` : '');
    }},
    { key: 'full_name', label: '', render: v => `<a href="/cluster/name/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge" title="Open investigation page">↗</a>` }
  ], names, { clickable: true, onClick: 'drillNameCluster', emptyIcon: '⊡', emptyTitle: 'No name clusters', emptyDesc: 'No names appear across multiple accounts.' });

  // IPs table - clickable for drilldown
  window._billingIps = ips;
  document.getElementById('billingIpsWrap').innerHTML = buildTable('bip', [
    { key: 'ip', label: 'IP Address' },
    { key: 'unique_cards', label: 'Unique Cards', numeric: true, right: true },
    { key: 'total_transactions', label: 'Transactions', numeric: true, right: true },
    { key: 'total_payout', label: 'Total Payout', numeric: true, right: true, render: v => fmtCur(v) },
    { key: 'emails', label: 'Emails', muted: true, render: v => truncate(v, 36) },
    { key: 'ip', label: '', render: v => `<a href="/cluster/ip/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge" title="Open investigation page">↗</a>` }
  ], ips, { clickable: true, onClick: 'drillBillingIp', emptyIcon: '⊡', emptyTitle: 'No IP cross-references', emptyDesc: 'No IPs used with multiple billing methods.' });

  window._billingSharedData = shared;
  const shWrap = document.getElementById('billingSharedWrap');
  if (shWrap) {
    if (sharedRes.error) {
      shWrap.innerHTML = errorState('Could not load shared-card data', sharedRes.error);
    } else if (!shared.length) {
      shWrap.innerHTML = emptyState('💳', 'No shared-card signals yet',
        'After admin API enrichment, accounts where the same payment method appears on multiple DUIDs show here. A stable card fingerprint from the API would enable tighter “same card” clusters.');
    } else {
      shWrap.innerHTML = buildTable('bsh', [
        { key: 'duid', label: 'DUID', render: v => `<a href="/account/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge">${v}</a>` },
        { key: 'email', label: 'Email', render: v => truncate(String(v || ''), 30) },
        { key: 'shared_card_count', label: 'Linked accts', numeric: true, right: true, hint: 'Count of other DUIDs sharing this payment method (from admin API).' },
        { key: 'risk_score', label: 'Risk', numeric: true, right: true, render: v => riskBadge(v) },
        { key: 'webmaster_code', label: 'Affiliate', muted: true },
      ], shared, { clickable: true, onClick: 'openBillingSharedAccount', emptyIcon: '💳', emptyTitle: 'No rows' });
    }
  }
}

// Name cluster drilldown
async function drillNameCluster(idx) {
  const cluster = window._billingNames?.[idx];
  if (!cluster) return;
  
  const name = cluster.full_name;
  const res = await api(`/api/billing/name/${encodeURIComponent(name)}`);
  
  if (res.error) {
    showToast('Failed to load name cluster: ' + res.error, 'error');
    return;
  }
  
  showClusterModal('Name Cluster', `Name: ${name}`, {
    accounts: cluster.account_count,
    high_risk: 0,
    avg_risk: 0,
    total_payout: cluster.total_payout
  }, res.data || [], 'name', name);
}

// Billing IP drilldown
async function drillBillingIp(idx) {
  const cluster = window._billingIps?.[idx];
  if (!cluster) return;
  
  const ip = cluster.ip;
  const res = await api(`/api/cluster/ip/${encodeURIComponent(ip)}`);
  
  if (res.error) {
    showToast('Failed to load IP cluster: ' + res.error, 'error');
    return;
  }
  
  showClusterModal('IP Cross-Reference', `IP: ${ip}`, {
    accounts: cluster.total_transactions,
    high_risk: 0,
    avg_risk: 0,
    total_payout: cluster.total_payout
  }, res.data || [], 'ip', ip);
}

// Billing cluster drilldown
async function drillBillingCluster(idx) {
  const cluster = window._billingClusters?.[idx];
  if (!cluster) return;
  
  const billingId = cluster.processor_subscriber_id;
  const res = await api(`/api/billing/cluster/${encodeURIComponent(billingId)}`);
  
  if (res.error) {
    showToast('Failed to load cluster details: ' + res.error, 'error');
    return;
  }
  
  const accounts = res.data || [];
  const sortedAccounts = [...accounts].sort(
    (a, b) => (Number(b.risk_score) || 0) - (Number(a.risk_score) || 0)
  );
  const previewAccounts = sortedAccounts.slice(0, CLUSTER_MODAL_PREVIEW_LIMIT);
  const overflowNote = accounts.length > CLUSTER_MODAL_PREVIEW_LIMIT
    ? `<div class="cluster-preview-note">Showing top ${CLUSTER_MODAL_PREVIEW_LIMIT} by risk · ${fmt(accounts.length - CLUSTER_MODAL_PREVIEW_LIMIT)} more accounts in this cluster</div>`
    : '';

  const modal = document.getElementById('accountModal');
  const body = document.getElementById('accountModalBody');

  setClusterModalMode(true, 'Billing Cluster');
  modal.classList.add('open');
  body.innerHTML = `
    <div class="cluster-modal-header">
      <div>
        <div class="cluster-modal-subtitle">Processor: ${escapeHtml(cluster.proc_name || '—')} · Billing ID: ${escapeHtml(truncate(billingId, 30))}</div>
      </div>
    </div>

    <div class="cluster-kpi-strip">
      <span class="cluster-kpi-item"><strong>${fmt(cluster.account_count)}</strong> accounts</span>
      <span class="cluster-kpi-item">payout <strong>${fmtCur(cluster.total_payout)}</strong></span>
      <span class="cluster-kpi-item">avg chargebacks <strong>${(cluster.avg_chargebacks || 0).toFixed(1)}</strong></span>
    </div>

    <div class="cluster-hint">Click Details to open an account</div>
    <div class="cluster-table-scroll">
      ${buildTable('bcldetail', [
        { key: 'email', label: 'Email', render: v => renderClusterEmail(v) },
        { key: 'first_name', label: 'First Name', render: v => escapeHtml(v || '—') },
        { key: 'last_name', label: 'Last Name', render: v => escapeHtml(v || '—') },
        { key: 'payout_amount', label: 'Payout', numeric: true, right: true, render: v => fmtCur(v) },
        { key: 'duid', label: 'Actions', render: v => `<button class="btn btn-sm" onclick="event.stopPropagation();openAccountDetail('${v}')">Details</button>` }
      ], previewAccounts, { noSort: true, emptyIcon: '⊡', emptyTitle: 'No accounts' })}
      ${overflowNote}
    </div>

    <div class="account-actions">
      <button class="btn btn-cancel" onclick="closeAccountModal()">Close</button>
    </div>
  `;
}

// ═══════════════════════════════════════════════════════════
// REPORTS TAB
// ═══════════════════════════════════════════════════════════

let reportsData = [];
let reportsDataRaw = [];
let reportsGrouped = false;
let expandedEmails = new Set();
let _reportsDebounceTimer = null;
let reportsCurrentPage = 1;
const REPORTS_PAGE_SIZE = 50;
const REPORTS_LIMIT_STORAGE_KEY = 'fd-reports-limit';
const REPORTS_LIMIT_MAX = 50000;

function getReportFetchLimit() {
  const el = document.getElementById('reportLimit');
  const raw = parseInt(el?.value || localStorage.getItem(REPORTS_LIMIT_STORAGE_KEY) || '5000', 10);
  const limit = Number.isFinite(raw) ? raw : 5000;
  return Math.max(1, Math.min(limit, REPORTS_LIMIT_MAX));
}

function initReportLimitSelect() {
  const el = document.getElementById('reportLimit');
  if (!el) return;
  const saved = localStorage.getItem(REPORTS_LIMIT_STORAGE_KEY);
  if (saved && [...el.options].some(o => o.value === saved)) el.value = saved;
}

function onReportLimitChange() {
  const el = document.getElementById('reportLimit');
  if (el) localStorage.setItem(REPORTS_LIMIT_STORAGE_KEY, el.value);
  loadReports();
}

function debounceLoadReports() {
  if (_reportsDebounceTimer) clearTimeout(_reportsDebounceTimer);
  _reportsDebounceTimer = setTimeout(() => loadReports(), 400);
}

async function loadReports() {
  await loadHouseAffiliates();
  const minRisk = document.getElementById('reportRiskFilter')?.value || '50';
  const dataType = document.getElementById('reportTypeFilter')?.value || '';
  const houseFilter = document.getElementById('reportHouseFilter')?.value || 'external';
  const groupBy = document.getElementById('reportGroupBy')?.value || '';
  const affiliateFilter = (document.getElementById('reportAffiliateFilter')?.value || '').trim().toLowerCase();
  const analyzedFrom = (document.getElementById('reportAnalyzedFrom')?.value || '').trim();
  const analyzedTo = (document.getElementById('reportAnalyzedTo')?.value || '').trim();
  const outcomeRaw = document.getElementById('reportOutcomeFilter')?.value || '';
  const maxRiskHidden = (document.getElementById('reportMaxRisk')?.value || '').trim();

  const wrap = document.getElementById('reportsTableWrap');
  wrap.innerHTML = loading();

  const fetchLimit = getReportFetchLimit();
  let url = `/api/fraud-results?min_risk=${encodeURIComponent(minRisk)}&limit=${fetchLimit}`;

  if (maxRiskHidden) {
    url += `&max_risk=${encodeURIComponent(maxRiskHidden)}`;
    const mrEl = document.getElementById('reportMaxRisk');
    if (mrEl) mrEl.value = '';
  }

  const showReviewedRows = Boolean(
    (outcomeRaw && outcomeRaw !== '__unreviewed__') ||
    analyzedFrom || analyzedTo ||
    minRisk === '0'
  );
  if (outcomeRaw === '__unreviewed__') {
    url += '&exclude_reviewed=1';
  } else if (showReviewedRows) {
    url += '&exclude_reviewed=0';
  }

  if (outcomeRaw && outcomeRaw !== '__unreviewed__') {
    url += `&outcome=${encodeURIComponent(outcomeRaw)}`;
  }

  if (analyzedFrom) url += `&analyzed_date_from=${encodeURIComponent(analyzedFrom)}`;
  if (analyzedTo) url += `&analyzed_date_to=${encodeURIComponent(analyzedTo)}`;

  const res = await api(url);
  
  if (res.error) {
    wrap.innerHTML = errorState('Failed to load reports', res.error, 'loadReports()');
    return;
  }
  
  let data = res.data || [];
  // One row per DUID (defensive; server merge should not fan out duplicates).
  const seenReports = new Set();
  data = data.filter(r => {
    const k = r.duid || r.email || '';
    if (!k || seenReports.has(k)) return false;
    seenReports.add(k);
    return true;
  });
  
  // Apply type filter
  if (dataType) {
    data = data.filter(r => r.data_type === dataType);
  }
  
  // Apply affiliate filter
  if (affiliateFilter) {
    data = data.filter(r => (r.webmaster_code || '').toLowerCase().includes(affiliateFilter));
  }
  
  // Apply house + whitelist filter
  if (houseFilter === 'external') {
    const externalExclude = externalOnlyExcludeLower();
    data = data.filter(r => {
      const code = (r.webmaster_code || '').toLowerCase();
      return !externalExclude.has(code);
    });
  }
  
  reportsDataRaw = [...data];
  reportsData = [...data];
  reportsCurrentPage = 1;
  
  // Update metrics
  const metrics = document.getElementById('reportsMetrics');
  const highCount = data.filter(r => r.risk_score >= 50).length;
  const medCount = data.filter(r => r.risk_score >= 25 && r.risk_score < 50).length;
  const totalPayout = data.reduce((sum, r) => sum + (r.payout_amount || 0), 0);
  const uniqueAffiliates = new Set(data.map(r => r.webmaster_code).filter(Boolean)).size;
  
  const atFetchCap = data.length >= fetchLimit;
  const capHint = atFetchCap
    ? ` <span class="metric-hint" title="More accounts may match — raise Max records or export CSV">(cap)</span>`
    : '';
  metrics.innerHTML = `
    <div class="metric-card"><div class="metric-label">Records Loaded</div><div class="metric-value">${fmt(data.length)}${capHint}</div></div>
    <div class="metric-card"><div class="metric-label">High Risk</div><div class="metric-value high">${fmt(highCount)}</div></div>
    <div class="metric-card"><div class="metric-label">Medium Risk</div><div class="metric-value medium">${fmt(medCount)}</div></div>
    <div class="metric-card"><div class="metric-label">Total Payout</div><div class="metric-value">${fmtCur(totalPayout)}</div></div>
    <div class="metric-card"><div class="metric-label">Unique Affiliates</div><div class="metric-value">${fmt(uniqueAffiliates)}</div></div>
  `;

  updateReportsSummaryHint(data.length, data.length, atFetchCap, fetchLimit);
  
  // Summary charts (full filtered set, not paginated table slice)
  renderFlagDistribution(data);
  renderRiskByAffiliate(data);
  
  // Render table based on grouping
  if (groupBy === 'affiliate') {
    renderReportsGroupedByAffiliate(data);
    updateReportsPagination(0, 1, 0, true);
  } else if (groupBy === 'campaign') {
    renderReportsGroupedByCampaign(data);
    updateReportsPagination(0, 1, 0, true);
  } else {
    renderReportsTable();
  }
}

function renderReportsGroupedByAffiliate(data) {
  const wrap = document.getElementById('reportsTableWrap');
  
  // Group by affiliate
  const byAffiliate = {};
  data.forEach(r => {
    const aff = r.webmaster_code || 'Unknown';
    if (!byAffiliate[aff]) {
      byAffiliate[aff] = { records: [], highRisk: 0, totalPayout: 0, avgRisk: 0 };
    }
    byAffiliate[aff].records.push(r);
    if (r.risk_score >= 50) byAffiliate[aff].highRisk++;
    byAffiliate[aff].totalPayout += r.payout_amount || 0;
  });
  
  // Calculate averages and sort by high risk count
  const grouped = Object.entries(byAffiliate).map(([affiliate, stats]) => ({
    affiliate,
    total_records: stats.records.length,
    high_risk_count: stats.highRisk,
    total_payout: stats.totalPayout,
    avg_risk: stats.records.reduce((s, r) => s + r.risk_score, 0) / stats.records.length,
    records: stats.records
  })).sort((a, b) => b.high_risk_count - a.high_risk_count);
  
  window._reportsGrouped = grouped;
  
  wrap.innerHTML = buildTable('rptgroup', [
    { key: 'affiliate', label: 'Affiliate' },
    { key: 'total_records', label: 'Records', numeric: true, right: true },
    { key: 'high_risk_count', label: 'High Risk', numeric: true, right: true, render: v => `<span style="color:var(--risk-high)">${v}</span>` },
    { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true, render: v => v?.toFixed(1) },
    { key: 'total_payout', label: 'Total Payout', numeric: true, right: true, render: v => fmtCur(v) }
  ], grouped, { clickable: true, onClick: 'drillReportAffiliate', onClickKey: 'affiliate', emptyIcon: '📋', emptyTitle: 'No data' });
}

function renderReportsGroupedByCampaign(data) {
  const wrap = document.getElementById('reportsTableWrap');
  
  // Group by campaign
  const byCampaign = {};
  data.forEach(r => {
    const camp = r.campaign || 'Unknown';
    if (!byCampaign[camp]) {
      byCampaign[camp] = { records: [], highRisk: 0, totalPayout: 0 };
    }
    byCampaign[camp].records.push(r);
    if (r.risk_score >= 50) byCampaign[camp].highRisk++;
    byCampaign[camp].totalPayout += r.payout_amount || 0;
  });
  
  const grouped = Object.entries(byCampaign).map(([campaign, stats]) => ({
    campaign,
    total_records: stats.records.length,
    high_risk_count: stats.highRisk,
    total_payout: stats.totalPayout,
    avg_risk: stats.records.reduce((s, r) => s + r.risk_score, 0) / stats.records.length,
    records: stats.records
  })).sort((a, b) => b.high_risk_count - a.high_risk_count);
  
  window._reportsGroupedCampaign = grouped;
  
  wrap.innerHTML = buildTable('rptcampgroup', [
    { key: 'campaign', label: 'Campaign', render: v => truncate(v, 30) },
    { key: 'total_records', label: 'Records', numeric: true, right: true },
    { key: 'high_risk_count', label: 'High Risk', numeric: true, right: true, render: v => `<span style="color:var(--risk-high)">${v}</span>` },
    { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true, render: v => v?.toFixed(1) },
    { key: 'total_payout', label: 'Total Payout', numeric: true, right: true, render: v => fmtCur(v) }
  ], grouped, { clickable: true, onClick: 'drillReportCampaign', onClickKey: 'campaign', emptyIcon: '📋', emptyTitle: 'No data' });
}

function drillReportAffiliate(affiliateKey) {
  const key = decodeURIComponent(String(affiliateKey || ''));
  const group = window._reportsGrouped?.find(g => g.affiliate === key);
  if (!group) return;
  
  showClusterModal('Affiliate Report', `Affiliate: ${group.affiliate}`, {
    accounts: group.total_records,
    high_risk: group.high_risk_count,
    avg_risk: group.avg_risk,
    total_payout: group.total_payout
  }, group.records);
}

function drillReportCampaign(campaignKey) {
  const key = decodeURIComponent(String(campaignKey || ''));
  const group = window._reportsGroupedCampaign?.find(g => g.campaign === key);
  if (!group) return;
  
  showClusterModal('Campaign Report', `Campaign: ${group.campaign}`, {
    accounts: group.total_records,
    high_risk: group.high_risk_count,
    avg_risk: group.avg_risk,
    total_payout: group.total_payout
  }, group.records);
}

function toggleEmailGroup(email) {
  if (expandedEmails.has(email)) {
    expandedEmails.delete(email);
  } else {
    expandedEmails.add(email);
  }
  renderReportsTable();
}

function updateReportsSummaryHint(visibleCount, loadedCount, atFetchCap, fetchLimit) {
  const el = document.getElementById('reportsSummaryHint');
  if (!el) return;
  const search = (document.getElementById('searchReports')?.value || '').trim();
  const parts = [
    `Charts reflect ${fmt(visibleCount)} record${visibleCount === 1 ? '' : 's'} matching your filters`,
  ];
  if (search && visibleCount !== loadedCount) {
    parts[0] = `Charts reflect ${fmt(visibleCount)} search result${visibleCount === 1 ? '' : 's'} (${fmt(loadedCount)} loaded)`;
  }
  if (atFetchCap) {
    parts.push(`load capped at ${fmt(fetchLimit)} — raise Max records or export CSV for more`);
  }
  el.textContent = parts.join('. ') + '.';
}

function updateReportsPagination(totalRows, page, pageSize, groupedView = false) {
  const paginationEl = document.getElementById('reportsPagination');
  if (!paginationEl) return;
  if (groupedView || totalRows <= pageSize) {
    paginationEl.style.display = 'none';
    return;
  }
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  const safePage = Math.max(1, Math.min(page, totalPages));
  reportsCurrentPage = safePage;
  paginationEl.style.display = 'block';
  const info = document.getElementById('reportsPageInfo');
  if (info) {
    info.textContent = `Page ${safePage} of ${totalPages} (${fmt(totalRows)} accounts)`;
  }
  const prev = document.getElementById('reportsPrevPage');
  const next = document.getElementById('reportsNextPage');
  if (prev) prev.disabled = safePage <= 1;
  if (next) next.disabled = safePage >= totalPages;
}

function loadReportsPage(page) {
  const totalPages = Math.max(1, Math.ceil(reportsData.length / REPORTS_PAGE_SIZE));
  reportsCurrentPage = Math.max(1, Math.min(page, totalPages));
  renderReportsTable();
}

function loadReportsPrevPage() {
  loadReportsPage(reportsCurrentPage - 1);
}

function loadReportsNextPage() {
  loadReportsPage(reportsCurrentPage + 1);
}

function getReportsPageSlice(rows) {
  const start = (reportsCurrentPage - 1) * REPORTS_PAGE_SIZE;
  return rows.slice(start, start + REPORTS_PAGE_SIZE);
}

function renderReportsTable() {
  const wrap = document.getElementById('reportsTableWrap');
  
  if (reportsGrouped) {
    renderGroupedReportsTable(wrap);
    updateReportsPagination(0, 1, 0, true);
    return;
  }

  const pageRows = getReportsPageSlice(reportsData);
  updateReportsPagination(reportsData.length, reportsCurrentPage, REPORTS_PAGE_SIZE);

  wrap.innerHTML = buildTable('reports', [
      { key: 'email', label: 'Email', hint: 'From fraud_results; badge if the same email appears on multiple DUIDs.', render: (v, row) => {
        const count = reportsData.filter(r => r.email === v).length;
        const countBadge = count > 1 ? `<span class="email-dup-badge" title="${count} accounts with this email">${count}</span>` : '';
        return truncate(v, 32) + countBadge;
      }},
      { key: 'risk_score', label: 'Risk', numeric: true, right: true, hint: 'Latest model score for this row.', render: v => riskBadge(v) },
      { key: 'flags', label: 'Flags', hint: 'Rules that fired; truncated in grid view.', render: v => {
        if (!v) return '—';
        const flags = String(v).replace(/[\[\]']/g, '').split(',').map(f => f.trim()).filter(f => f);
        return flags.slice(0, 2).map(f => `<span class="flag-tag">${f.replace('_', ' ')}</span>`).join(' ') + 
               (flags.length > 2 ? ` +${flags.length - 2}` : '');
      }},
      { key: 'payout_amount', label: 'Payout', numeric: true, right: true, hint: 'Payout amount when present on the record.', render: v => fmtCur(v) },
      { key: 'webmaster_code', label: 'Affiliate', muted: true, hint: 'webmaster_code on the analyzed record.', render: v => v || '<span class="muted">—</span>' },
      { key: 'data_type', label: 'Type', muted: true, hint: 'free vs paid source row used in analysis.' }
    ], pageRows, {
      clickable: true,
      onClick: 'openReportModalByDuid',
      onClickKey: 'duid',
      emptyIcon: '📋',
      emptyTitle: 'No matching records',
    });
}

function renderGroupedReportsTable(wrap) {
  // Group records by email
  const groups = {};
  reportsData.forEach((r, idx) => {
    const email = r.email || 'unknown';
    if (!groups[email]) groups[email] = [];
    groups[email].push({ ...r, _idx: idx });
  });
  
  // Sort groups by highest risk score in group, then by count
  const sortedGroups = Object.entries(groups).sort((a, b) => {
    const maxRiskA = Math.max(...a[1].map(r => r.risk_score || 0));
    const maxRiskB = Math.max(...b[1].map(r => r.risk_score || 0));
    if (maxRiskB !== maxRiskA) return maxRiskB - maxRiskA;
    return b[1].length - a[1].length;
  });
  
  if (sortedGroups.length === 0) {
    wrap.innerHTML = `<div class="empty-state"><span class="empty-icon">📋</span><h4>No matching records</h4></div>`;
    return;
  }
  
  let html = `<table class="data-table grouped-table no-sort">
    <thead><tr>
      <th style="width:40px"></th>
      <th>Email</th>
      <th class="text-right">Max Risk${thColumnHint('Highest risk_score among rows sharing this email.')}</th>
      <th>Top Flags${thColumnHint('Most frequent flags across duplicate-email rows.')}</th>
      <th class="text-right">Total Payout${thColumnHint('Sum of payout_amount across grouped rows.')}</th>
      <th>Affiliates${thColumnHint('Distinct affiliate codes in this email group.')}</th>
      <th class="text-right">Count${thColumnHint('Number of DUIDs / rows grouped under this email.')}</th>
    </tr></thead>
    <tbody>`;
  
  sortedGroups.forEach(([email, records]) => {
    const isExpanded = expandedEmails.has(email);
    const maxRisk = Math.max(...records.map(r => r.risk_score || 0));
    const totalPayout = records.reduce((sum, r) => sum + (r.payout_amount || 0), 0);
    const affiliates = [...new Set(records.map(r => r.webmaster_code).filter(Boolean))];
    const allFlags = {};
    records.forEach(r => {
      if (!r.flags) return;
      const flags = String(r.flags).replace(/[\[\]']/g, '').split(',').map(f => f.trim()).filter(f => f);
      flags.forEach(f => { allFlags[f] = (allFlags[f] || 0) + 1; });
    });
    const topFlags = Object.entries(allFlags).sort((a,b) => b[1] - a[1]).slice(0, 2).map(f => f[0]);
    
    // Group header row
    const expandIcon = records.length > 1 ? (isExpanded ? '▼' : '▶') : '·';
    const clickable = records.length > 1 ? `onclick="toggleEmailGroup('${email.replace(/'/g, "\\'")}')" style="cursor:pointer"` : '';
    
    html += `<tr class="group-header ${isExpanded ? 'expanded' : ''}" ${clickable}>
      <td class="expand-cell">${expandIcon}</td>
      <td>${truncate(email, 32)}</td>
      <td class="text-right">${riskBadge(maxRisk)}</td>
      <td>${topFlags.map(f => `<span class="flag-tag">${f.replace(/_/g, ' ')}</span>`).join(' ') || '—'}</td>
      <td class="text-right">${fmtCur(totalPayout)}</td>
      <td class="muted">${affiliates.length > 0 ? affiliates.slice(0,2).join(', ') + (affiliates.length > 2 ? '...' : '') : '<span class="muted">—</span>'}</td>
      <td class="text-right"><span class="count-badge ${records.length > 1 ? 'multiple' : ''}">${records.length}</span></td>
    </tr>`;
    
    // Child rows (if expanded)
    if (isExpanded && records.length > 1) {
      records.forEach(r => {
        const flags = r.flags ? String(r.flags).replace(/[\[\]']/g, '').split(',').map(f => f.trim()).filter(f => f) : [];
        html += `<tr class="group-child" onclick="openReportModalByDuid('${encodeURIComponent(String(r.duid || ''))}')">
          <td></td>
          <td class="muted" style="padding-left:24px">↳ ${truncate(r.duid || '', 16)}</td>
          <td class="text-right">${riskBadge(r.risk_score)}</td>
          <td>${flags.slice(0, 2).map(f => `<span class="flag-tag">${f.replace(/_/g, ' ')}</span>`).join(' ') || '—'}</td>
          <td class="text-right">${fmtCur(r.payout_amount)}</td>
          <td class="muted">${r.webmaster_code || '—'}</td>
          <td class="text-right muted">${r.data_type || ''}</td>
        </tr>`;
      });
    }
  });
  
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

function filterReportsTable() {
  const search = (document.getElementById('searchReports')?.value || '').toLowerCase();
  
  if (!search) {
    reportsData = [...reportsDataRaw];
  } else {
    reportsData = reportsDataRaw.filter(r => {
      return (r.email || '').toLowerCase().includes(search) ||
             (r.flags || '').toLowerCase().includes(search) ||
             (r.webmaster_code || '').toLowerCase().includes(search) ||
             (r.duid || '').toLowerCase().includes(search);
    });
  }
  
  const countEl = document.getElementById('reportSearchCount');
  if (countEl) {
    countEl.textContent = search ? `${reportsData.length} of ${reportsDataRaw.length}` : '';
  }

  reportsCurrentPage = 1;
  const fetchLimit = getReportFetchLimit();
  const atFetchCap = reportsDataRaw.length >= fetchLimit;
  updateReportsSummaryHint(reportsData.length, reportsDataRaw.length, atFetchCap, fetchLimit);
  renderFlagDistribution(reportsData);
  renderRiskByAffiliate(reportsData);

  const groupBy = document.getElementById('reportGroupBy')?.value || '';
  if (groupBy === 'affiliate') {
    renderReportsGroupedByAffiliate(reportsData);
    updateReportsPagination(0, 1, 0, true);
  } else if (groupBy === 'campaign') {
    renderReportsGroupedByCampaign(reportsData);
    updateReportsPagination(0, 1, 0, true);
  } else {
    renderReportsTable();
  }
}

function openReportModalByDuid(duid) {
  const key = decodeURIComponent(String(duid || ''));
  const row = reportsData.find(r => String(r.duid) === key)
    || reportsDataRaw.find(r => String(r.duid) === key);
  if (row) openOutcomeModal(row.duid, row.email);
}

function openReportModal(idx) {
  const row = reportsData[idx];
  if (row) openOutcomeModal(row.duid, row.email);
}

async function rescoreWomanConcentration() {
  const btn = document.getElementById('btnRescoreWomanConc');
  const statusEl = document.getElementById('rescoreWomanConcStatus');
  if (!btn) return;
  const originalText = btn.textContent;
  btn.textContent = 'Working…';
  btn.disabled = true;
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = '';
  }
  try {
    const res = await api('/api/rescore-woman-concentration', { method: 'POST' });
    if (res.error) {
      showToast('Patch failed: ' + res.error, 'error');
      if (statusEl) statusEl.textContent = res.error;
    } else {
      const diag = [
        res.database_path ? `DB: ${res.database_path}` : null,
        res.fraud_results_rows != null ? `fraud_results ${res.fraud_results_rows} rows` : null,
        res.free_rows != null ? `free ${res.free_rows}` : null,
        res.paid_rows != null ? `paid ${res.paid_rows}` : null,
      ].filter(Boolean).join(' · ');
      const msg = res.message
        ? res.message + (diag ? ` (${diag})` : '')
        : `Updated ${res.updated ?? 0} row(s); ${res.rows_considered ?? 0} with gender considered; ` +
          `${res.affiliates_over_threshold ?? 0} affiliate(s) over threshold.` + (diag ? ` (${diag})` : '');
      showToast(msg);
      if (statusEl) statusEl.textContent = msg;
      if (typeof loadReports === 'function') loadReports();
    }
  } catch (e) {
    showToast('Request failed: ' + e.message, 'error');
    if (statusEl) statusEl.textContent = e.message;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function rescoreSequentialEmail() {
  const btn = document.getElementById('btnRescoreSequentialEmail');
  const statusEl = document.getElementById('rescoreSequentialEmailStatus');
  if (!btn) return;
  const originalText = btn.textContent;
  btn.textContent = 'Working…';
  btn.disabled = true;
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = '';
  }
  try {
    const res = await api('/api/rescore-sequential-email', { method: 'POST' });
    if (res.error) {
      showToast('Patch failed: ' + res.error, 'error');
      if (statusEl) statusEl.textContent = res.error;
    } else {
      const diag = [
        res.database_path ? `DB: ${res.database_path}` : null,
        res.fraud_results_rows != null ? `fraud_results ${res.fraud_results_rows} rows` : null,
        res.free_rows != null ? `free ${res.free_rows}` : null,
        res.paid_rows != null ? `paid ${res.paid_rows}` : null,
      ].filter(Boolean).join(' · ');
      const msg = res.message
        ? res.message + (diag ? ` (${diag})` : '')
        : `Updated ${res.updated ?? 0} row(s); ${res.rows_considered ?? 0} emails considered; ` +
          `${res.clusters_found ?? 0} cluster(s).` + (diag ? ` (${diag})` : '');
      showToast(msg);
      if (statusEl) statusEl.textContent = msg;
      if (typeof loadReports === 'function') loadReports();
    }
  } catch (e) {
    showToast('Request failed: ' + e.message, 'error');
    if (statusEl) statusEl.textContent = e.message;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function backfillAffiliates() {
  const btn = document.getElementById('backfillAffiliatesBtn');
  const originalText = btn.innerHTML;
  btn.innerHTML = '<span class="btn-icon">⟳</span> Working...';
  btn.disabled = true;
  
  try {
    const res = await api('/api/backfill-affiliates', { method: 'POST' });
    
    if (res.error) {
      showToast('Backfill failed: ' + res.error, 'error');
    } else {
      const { needs_backfill, total_updated } = res;
      if (total_updated > 0) {
        showToast(`Updated ${total_updated} of ${needs_backfill} affiliate records`);
        loadReports(); // Reload to show updated data
      } else if (needs_backfill === 0) {
        showToast('All records already have affiliate data');
      } else {
        showToast(`${needs_backfill} records need affiliates but no source data found`, 'error');
      }
    }
  } catch (e) {
    showToast('Request failed: ' + e.message, 'error');
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

/** Parse fraud_results.flags (JSON array or legacy comma-split). */
function parseFlagsListFromRecord(flagsField) {
  if (flagsField == null || flagsField === '') return [];
  const s = String(flagsField).trim();
  if (!s) return [];
  if (s.startsWith('[')) {
    try {
      const arr = JSON.parse(s);
      if (Array.isArray(arr)) return arr.map(x => String(x)).filter(Boolean);
    } catch (_) {
      try {
        const arr = JSON.parse(s.replace(/'/g, '"'));
        if (Array.isArray(arr)) return arr.map(x => String(x)).filter(Boolean);
      } catch (_) { /* fall through */ }
    }
  }
  return s.replace(/^\[|\]$/g, '').split(',').map(f => f.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
}

function cleanFlagTokenForDistribution(f) {
  let s = String(f || '').trim();
  if (!s) return '';
  s = s.replace(/^["']+/, '').replace(/["']+$/, '');
  while (/["'`]+$/.test(s)) s = s.replace(/["'`]+$/, '').trim();
  return s;
}

/**
 * Roll ASN-/country-specific enrichment flags into stable buckets for the All Accounts chart.
 * (Otherwise every OVH / Akamai variant becomes its own bar.)
 */
function flagDistributionBucket(flagRaw) {
  const f = cleanFlagTokenForDistribution(flagRaw);
  if (!f) return null;
  const lower = f.toLowerCase();
  if (lower.startsWith('login_ip_datacenter_')) return 'Login IP datacenter';
  if (lower.startsWith('registration_ip_datacenter_')) return 'Registration IP datacenter';
  if (lower.startsWith('login_ip_vpn_')) return 'Login IP VPN';
  if (lower.startsWith('registration_ip_vpn_')) return 'Registration IP VPN';
  if (lower.startsWith('geo_login_mismatch_')) return 'Geo login mismatch';
  if (lower.startsWith('ip_country_mismatch_')) return 'IP country mismatch (reg vs login)';
  if (lower.startsWith('ip_state_mismatch_')) return 'IP state mismatch (reg vs login)';
  if (lower.startsWith('login_high_risk_country_')) return 'Login high-risk country';
  return f.replace(/_/g, ' ');
}

/** Human-readable label for a catalog flag key (spike drill, tables). */
function humanizeFlagKey(flagKey) {
  if (!flagKey) return '—';
  return flagDistributionBucket(flagKey) || String(flagKey).replace(/_/g, ' ');
}

function renderSpikeFlagPills(flagsField, maxPills = 3) {
  const flags = parseFlagsListFromRecord(flagsField);
  if (!flags.length) return '<span style="color:var(--text-muted)">—</span>';
  const pills = flags.slice(0, maxPills).map(f =>
    `<span class="spike-flag-pill">${escapeHtml(humanizeFlagKey(f))}</span>`
  ).join('');
  const extra = flags.length > maxPills
    ? `<span class="spike-flag-pill spike-flag-pill-muted">+${flags.length - maxPills}</span>`
    : '';
  return pills + extra;
}

function renderSpikeFlagTableRows(flags, limit = 8) {
  return (flags || []).slice(0, limit).map(f => `
    <tr>
      <td><span class="spike-flag-pill">${escapeHtml(humanizeFlagKey(f.flag))}</span></td>
      <td style="text-align:right">${fmt(f.count)}</td>
      <td style="text-align:right">${f.pct}%</td>
    </tr>
  `).join('');
}

function spikeAccordion(title, bodyHtml, open = false) {
  return `<details class="spike-accordion"${open ? ' open' : ''}>
    <summary class="spike-accordion-summary">${title}</summary>
    <div class="spike-accordion-body">${bodyHtml}</div>
  </details>`;
}

function clearSpikeSubpanels(dateKey) {
  const aff = document.getElementById(`spike-aff-subpanel-${dateKey}`);
  const camp = document.getElementById(`spike-camp-subpanel-${dateKey}`);
  if (aff) aff.innerHTML = '';
  if (camp) camp.innerHTML = '';
  document.querySelectorAll('.aff-drill-row, .camp-drill-row').forEach(r => { r.style.background = ''; });
}

function renderSpikeAccountsTable(accounts, opts = {}) {
  const { showAffiliate = false, showCampaign = true } = opts;
  if (!accounts || !accounts.length) {
    return '<p style="font-size:12px;color:var(--text-muted)">No accounts found.</p>';
  }
  const rows = accounts.map(a => `
    <tr onclick="openAccountModal && openAccountModal('${a.duid}')" style="cursor:pointer">
      <td>${truncate(a.email || '', 34)}</td>
      <td>${riskBadge(a.risk_score)}</td>
      <td>${fmtCur(a.payout_amount)}</td>
      ${showCampaign ? `<td style="font-size:11px;color:var(--text-muted)">${escapeHtml(a.campaign || '—')}</td>` : ''}
      ${showAffiliate ? `<td style="font-size:11px;color:var(--text-muted)">${escapeHtml(a.webmaster_code || '—')}</td>` : ''}
      <td style="font-size:11px">${renderSpikeFlagPills(a.flags, 2)}</td>
    </tr>
  `).join('');
  const head = `
    <th>Email</th><th>Risk</th><th>Payout</th>
    ${showCampaign ? '<th>Campaign</th>' : ''}
    ${showAffiliate ? '<th>Affiliate</th>' : ''}
    <th>Flags</th>`;
  return `<div class="spike-accounts-scroll">
    <table class="data-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
  </div>`;
}

function renderSpikePagination(date, entityType, entityKey, pagination, flagFilter, loadFnName) {
  if (!pagination || pagination.total_pages <= 1) return '';
  const pg = pagination.page;
  const tp = pagination.total_pages;
  const ff = flagFilter ? JSON.stringify(flagFilter) : "''";
  const ek = JSON.stringify(entityKey);
  return `<div class="spike-pagination">
    <button class="btn btn-sm" ${pg <= 1 ? 'disabled' : ''}
      onclick="${loadFnName}('${date}', ${ek}, ${pg - 1}, ${ff})">← Prev</button>
    <span class="pagination-info">Page ${pg} of ${tp}</span>
    <button class="btn btn-sm" ${pg >= tp ? 'disabled' : ''}
      onclick="${loadFnName}('${date}', ${ek}, ${pg + 1}, ${ff})">Next →</button>
  </div>`;
}

function renderFlagDistribution(data) {
  const flagCounts = {};
  data.forEach(r => {
    const flags = parseFlagsListFromRecord(r.flags);
    flags.forEach(raw => {
      const bucket = flagDistributionBucket(raw);
      if (bucket) flagCounts[bucket] = (flagCounts[bucket] || 0) + 1;
    });
  });
  
  const sorted = Object.entries(flagCounts).sort((a, b) => b[1] - a[1]);
  const el = document.getElementById('flagDistribution');
  
  if (sorted.length === 0) {
    el.innerHTML = '<div class="empty-state"><p>No flags found</p></div>';
    return;
  }
  
  const max = sorted[0][1];
  el.innerHTML = sorted.map(([flag, count]) => `
    <div class="flag-stat">
      <span class="flag-name">${escapeHtml(flag)}</span>
      <span class="flag-count">${count}</span>
      <div class="flag-bar"><div class="flag-fill" style="width:${(count / max) * 100}%"></div></div>
    </div>
  `).join('');
}

function renderRiskByAffiliate(data) {
  // Group by affiliate
  const byAff = {};
  data.forEach(r => {
    const aff = r.webmaster_code || 'Unknown';
    if (!byAff[aff]) byAff[aff] = { high: 0, medium: 0, low: 0, payout: 0 };
    if (r.risk_score >= 50) byAff[aff].high++;
    else if (r.risk_score >= 25) byAff[aff].medium++;
    else byAff[aff].low++;
    byAff[aff].payout += r.payout_amount || 0;
  });
  
  // Sort by high risk count and take top 10
  const sorted = Object.entries(byAff)
    .sort((a, b) => b[1].high - a[1].high)
    .slice(0, 10);
  
  if (sorted.length === 0) {
    document.getElementById('chart-risk-affiliate').innerHTML = '<div class="empty-state"><p>No data</p></div>';
    return;
  }
  
  const affiliates = sorted.map(s => s[0]);
  const highCounts = sorted.map(s => s[1].high);
  const medCounts = sorted.map(s => s[1].medium);
  
  // Affiliate Risk Chart (ApexCharts)
  renderApexChart('chart-risk-affiliate', 'bar', {
    series: [
      { name: 'High Risk', data: highCounts },
      { name: 'Medium Risk', data: medCounts }
    ],
    categories: affiliates
  }, {
    colors: ['#ef4444', '#f59e0b'],
    height: 320,
    plotOptions: {
      bar: {
        horizontal: false,
        columnWidth: '70%',
        dataLabels: { position: 'top' }
      }
    },
    chart: { stacked: true },
    dataLabels: {
      enabled: true,
      style: { fontSize: '11px', fontWeight: 600 }
    },
    xaxis: {
      labels: { rotate: -45, rotateAlways: true },
      title: { text: 'Affiliate Code', style: { fontSize: '13px', fontWeight: 600 } }
    },
    yaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
    legend: { position: 'top', horizontalAlign: 'center' }
  });
  
  addChartControls('chart-risk-affiliate', ['bar', 'line', 'area']);
}

function exportReport() {
  const minRisk = document.getElementById('reportRiskFilter')?.value || '50';
  const limit = getReportFetchLimit();
  exportData('fraud-results', { min_risk: minRisk, limit: String(limit) });
}

// ═══════════════════════════════════════════════════════════
// TEMPORAL TRENDS TAB
// ═══════════════════════════════════════════════════════════

/** Daily / hourly / weekday charts + temporal metric row (does not reload funnel or WoW). */
async function loadTemporalAnalysisCharts() {
  const days = document.getElementById('temporalDays')?.value || 14;
  const res = await api(`/api/temporal-analysis?days=${days}`);

  if (res.error) {
    showToast('Failed to load temporal data: ' + res.error, 'error');
    return;
  }

  const data = res.data || {};
  const daily = data.daily || [];
  const hourly = data.hourly || [];
  const weekday = data.weekday || [];

  const totalRecords = daily.reduce((sum, d) => sum + d.count, 0);
  const totalHighRisk = daily.reduce((sum, d) => sum + (d.high_risk_count || 0), 0);
  const totalPayout = daily.reduce((sum, d) => sum + d.total_payout, 0);
  const avgRisk = daily.length > 0 ? daily.reduce((sum, d) => sum + d.avg_risk, 0) / daily.length : 0;

  const midpoint = Math.floor(daily.length / 2);
  const firstHalf = daily.slice(0, midpoint);
  const secondHalf = daily.slice(midpoint);
  const firstHalfHR = firstHalf.reduce((s, d) => s + (d.high_risk_count || 0), 0);
  const secondHalfHR = secondHalf.reduce((s, d) => s + (d.high_risk_count || 0), 0);
  const hrVelocity = firstHalfHR > 0 ? Math.round((secondHalfHR - firstHalfHR) / firstHalfHR * 100) : null;

  const tm = document.getElementById('temporalMetrics');
  if (tm) {
    tm.innerHTML = `
    <div class="metric-card"><div class="metric-label">Records (${days}d)</div><div class="metric-value">${fmt(totalRecords)}</div></div>
    <div class="metric-card"><div class="metric-label">High Risk</div><div class="metric-value high">${fmt(totalHighRisk)}${velocityBadge(hrVelocity)}</div></div>
    <div class="metric-card"><div class="metric-label">Avg Risk</div><div class="metric-value">${avgRisk.toFixed(1)}</div></div>
    <div class="metric-card"><div class="metric-label">Total Payout</div><div class="metric-value">${fmtCur(totalPayout)}</div></div>
    <div class="metric-card"><div class="metric-label">Trend</div><div class="metric-value" style="font-size:16px;">${hrVelocity !== null ? (hrVelocity > 5 ? '📈 Increasing' : hrVelocity < -5 ? '📉 Decreasing' : '➡️ Stable') : '—'}</div></div>
  `;
  }

  if (daily.length > 0) {
    renderApexChart('chart-daily-trend', 'area', {
      series: [
        { name: 'All Records', data: daily.map(d => d.count) },
        { name: 'High Risk', data: daily.map(d => d.high_risk_count) }
      ],
      categories: daily.map(d => d.date)
    }, {
      colors: ['#3b82f6', '#ef4444'],
      height: 320,
      stroke: { curve: 'smooth', width: 2 },
      fill: {
        type: 'gradient',
        gradient: {
          shadeIntensity: 1,
          opacityFrom: 0.6,
          opacityTo: 0.2
        }
      },
      xaxis: {
        type: 'datetime',
        labels: { datetimeUTC: false, format: 'MMM dd' },
        title: { text: 'Date', style: { fontSize: '13px', fontWeight: 600 } }
      },
      yaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
      legend: { position: 'top', horizontalAlign: 'center' },
      markers: { size: 4, hover: { size: 6 } }
    });

    addChartControls('chart-daily-trend', ['area', 'line', 'bar']);
  }

  if (hourly.length > 0) {
    renderApexChart('chart-hourly', 'bar', {
      series: [{
        name: 'Accounts',
        data: hourly.map(h => h.count)
      }],
      categories: hourly.map(h => `${h.hour}:00`)
    }, {
      colors: hourly.map(h => h.avg_risk > 40 ? '#ef4444' : h.avg_risk > 25 ? '#f59e0b' : '#22c55e'),
      height: 250,
      plotOptions: {
        bar: {
          columnWidth: '75%',
          distributed: true
        }
      },
      dataLabels: { enabled: false },
      xaxis: { title: { text: 'Hour of Day', style: { fontSize: '13px', fontWeight: 600 } } },
      yaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
      legend: { show: false }
    });

    addChartControls('chart-hourly', ['bar', 'line']);
  }

  if (weekday.length > 0) {
    const wdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    renderApexChart('chart-weekday', 'bar', {
      series: [{
        name: 'Accounts',
        data: weekday.map(w => w.count)
      }],
      categories: weekday.map(w => w.weekday_name || wdays[w.weekday])
    }, {
      colors: weekday.map(w => w.avg_risk > 40 ? '#ef4444' : w.avg_risk > 25 ? '#f59e0b' : '#22c55e'),
      height: 250,
      plotOptions: {
        bar: {
          columnWidth: '65%',
          distributed: true
        }
      },
      dataLabels: { enabled: false },
      xaxis: { title: { text: 'Day of Week', style: { fontSize: '13px', fontWeight: 600 } } },
      yaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
      legend: { show: false }
    });

    addChartControls('chart-weekday', ['bar', 'line']);
  }
}

async function loadTemporal() {
  loadVolumeAnomalies();
  loadWoW();
  loadSpikeAnalysis();
  loadFunnel();
  await loadTemporalAnalysisCharts();
  // Charts in hidden sub-tabs may need reflow after data loads
  setTimeout(resizeAllCharts, 120);
}

function setFunnelCampaignAndLoad(campaign) {
  const el = document.getElementById('funnelCampaign');
  if (el) el.value = campaign || '';
  loadFunnel();
}

async function loadFunnel() {
  const el = document.getElementById('funnelPanelBody');
  if (!el) return;
  const aff = document.getElementById('funnelAffiliate')?.value?.trim() || '';
  const camp = document.getElementById('funnelCampaign')?.value?.trim() || '';
  const df = document.getElementById('funnelDateFrom')?.value || '';
  const dt = document.getElementById('funnelDateTo')?.value || '';
  const params = new URLSearchParams();
  if (aff) params.set('affiliate', aff);
  if (camp) params.set('campaign', camp);
  if (df) params.set('date_from', df);
  if (dt) params.set('date_to', dt);
  // Keep panel height during load so lower panels (e.g. WoW chart) don’t jump up and look like they “replaced” the funnel.
  const prevH = el.getBoundingClientRect().height;
  el.style.minHeight = `${Math.max(360, Math.round(prevH))}px`;
  el.innerHTML = '<div class="loading-spinner">Loading…</div>';
  let res = null;
  try {
    res = await api('/api/funnel?' + params.toString());
  } catch (e) {
    el.innerHTML = errorState('Failed to load funnel', e.message || String(e), 'loadFunnel()');
    return;
  } finally {
    el.style.minHeight = '';
  }
  if (!res || res.error) {
    el.innerHTML = `<div style="padding:16px;color:var(--risk-high);">Failed to load funnel: ${escapeHtml(res?.error || 'Unknown error')}</div>`;
    return;
  }
  const d = res.data;
  if (!d) {
    el.innerHTML = emptyState('◐', 'No funnel data', '');
    return;
  }
  const free = d.free_signups || 0;
  const conv = d.converted_paid || 0;
  const hr = d.high_risk_paid || 0;
  const pct = (a, b) => (b > 0 ? ((a / b) * 100).toFixed(1) : '0.0');
  const bar = (label, n, rel, color) => {
    const w = free > 0 ? Math.max(8, (n / free) * 100) : 0;
    return `<div style="margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
        <span>${label}</span><strong>${fmt(n)}</strong> <span style="color:var(--text-muted);">(${rel})</span>
      </div>
      <div style="height:28px;background:var(--surface2);border-radius:6px;overflow:hidden;">
        <div style="height:100%;width:${w}%;min-width:${n ? '4px' : '0'};background:${color};transition:width .3s;"></div>
      </div>
    </div>`;
  };
  let affTable = '';
  const rows = d.by_affiliate || [];
  const campRows = d.by_campaign || [];
  const hrTh = d.high_risk_threshold ?? 50;
  const affRowHtml = (a, isCamp) => {
    const oc = isCamp
      ? `onclick="setFunnelCampaignAndLoad(${JSON.stringify(a.campaign || '')})" title="Filter funnel to this campaign"`
      : `onclick="window.open('/affiliate/${encodeURIComponent(a.affiliate)}','_blank')" title="Open affiliate detail"`;
    const label = isCamp ? escapeHtml(a.campaign || '') : `<code>${escapeHtml(a.affiliate)}</code>`;
    const nconv = a.non_conversion_pct != null ? a.non_conversion_pct : (a.free_signups ? (100 - (a.conversion_rate || 0)).toFixed(2) : '0');
    const hrf = a.high_risk_pct_of_free != null ? a.high_risk_pct_of_free : '0';
    return `<tr style="cursor:pointer" ${oc}>
          <td>${label}</td>
          <td class="num">${fmt(a.free_signups)}</td>
          <td class="num">${fmt(a.converted_paid)}</td>
          <td class="num">${a.conversion_rate}%</td>
          <td class="num">${nconv}%</td>
          <td class="num">${fmt(a.high_risk_paid)}</td>
          <td class="num">${hrf}%</td>
          <td class="num">${a.fraud_among_converted_pct}%</td>
          <td class="num">${fmtCur(a.payout_at_risk)}</td>
        </tr>`;
  };
  if (rows.length > 0) {
    affTable = `
      <h4 style="margin:20px 0 8px;font-size:13px;">Top affiliates by free signups</h4>
      <div style="overflow-x:auto;">
      <table class="data-table no-sort" style="width:100%;font-size:12px;">
        <thead><tr>
          <th>Affiliate</th><th class="num">Free</th><th class="num">Paid</th>
          <th class="num">Conv %${thColumnHint('Share of free signups that also have a paid record (same DUID in free and paid). Uses the same date and campaign filters as this funnel.')}</th>
          <th class="num">Non-conv %${thColumnHint('Share of free signups with no paid record in this window (100% − conv %).')}</th>
          <th class="num">HR paid${thColumnHint(`Paid conversions with model risk score ≥ ${hrTh} in fraud_results (not manual review).`)}</th>
          <th class="num">HR % of free${thColumnHint('High-risk paid count ÷ free signups × 100 — exposure vs top-of-funnel volume.')}</th>
          <th class="num">HR % conv${thColumnHint('High-risk paid ÷ paid conversions × 100. Model score only, not confirmed fraud.')}</th>
          <th class="num">Payout @ risk${thColumnHint(`One payout per converted DUID (paid.payout_amount) for accounts scoring ≥ ${hrTh}; summed without double-counting duplicate joins.`)}</th>
        </tr></thead><tbody>
        ${rows.map(a => affRowHtml(a, false)).join('')}
        </tbody></table></div>`;
  }
  let campTable = '';
  if (campRows.length > 0) {
    campTable = `
      <h4 style="margin:20px 0 8px;font-size:13px;">Top campaigns by free signups</h4>
      <p style="font-size:11px;color:var(--text-muted);margin:0 0 8px;">Click a row to set the campaign filter above and reload.</p>
      <div style="overflow-x:auto;">
      <table class="data-table no-sort" style="width:100%;font-size:12px;">
        <thead><tr>
          <th>Campaign</th><th class="num">Free</th><th class="num">Paid</th>
          <th class="num">Conv %</th>
          <th class="num">Non-conv %</th>
          <th class="num">HR paid</th>
          <th class="num">HR % of free</th>
          <th class="num">HR % conv</th>
          <th class="num">Payout @ risk</th>
        </tr></thead><tbody>
        ${campRows.map(c => affRowHtml(c, true)).join('')}
        </tbody></table></div>`;
  }
  el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start;">
      <div>
        <p style="font-size:12px;color:var(--text-muted);margin:0 0 12px;">
          High-risk threshold: <strong>${d.high_risk_threshold}</strong> · Conversion = DUID in both <code>free</code> and <code>paid</code>.
          High-risk flags use model scores in <code>fraud_results</code>, not investigator outcomes.
        </p>
        ${bar('1. Free signups', free, '100% of funnel base', '#3b82f6')}
        ${bar('2. Converted to paid', conv, `${pct(conv, free)}% of free`, '#8b5cf6')}
        ${bar(`3. High-risk paid (≥${d.high_risk_threshold})`, hr, `${pct(hr, conv)}% of paid`, '#ef4444')}
        <div style="margin-top:12px;font-size:13px;">
          <strong>Payout at risk (high-risk paid):</strong> ${fmtCur(d.payout_at_risk || 0)}
        </div>
      </div>
      <div class="metrics-row" style="flex-direction:column;gap:8px;">
        <div class="metric-card"><div class="metric-label">Conversion rate</div><div class="metric-value">${d.conversion_rate}%</div></div>
        <div class="metric-card"><div class="metric-label">High-risk among converted</div><div class="metric-value high">${d.fraud_among_converted_pct}%</div></div>
      </div>
    </div>
    ${affTable}${campTable}`;
}

async function loadModelPerformance() {
  const el = document.getElementById('modelPerformanceBody');
  if (!el) return;
  el.innerHTML = '<div class="loading-spinner">Loading…</div>';
  const res = await api('/api/model-performance');
  if (res.error) {
    el.innerHTML = `<div style="padding:16px;color:var(--risk-high);">${escapeHtml(res.error)}</div>`;
    return;
  }
  const d = res.data;
  if (!d || (d.reviewed_count | 0) === 0) {
    el.innerHTML = emptyState('◈', 'No reviewed outcomes yet',
      'Mark accounts as confirmed fraud or false positive to see precision, recall, and threshold curves.');
    return;
  }
  const ad = d.at_default || {};
  const mat = (v) => (v == null ? '—' : `${v}%`);
  const cm = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:360px;font-size:12px;text-align:center;">
      <div style="padding:12px;background:var(--surface2);border-radius:8px;"><div style="color:var(--text-muted);">TN</div><div style="font-size:22px;font-weight:700;">${fmt(ad.tn)}</div><div>low risk + FP outcome</div></div>
      <div style="padding:12px;background:rgba(239,68,68,0.12);border-radius:8px;"><div style="color:var(--text-muted);">FP</div><div style="font-size:22px;font-weight:700;">${fmt(ad.fp)}</div><div>high risk + FP outcome</div></div>
      <div style="padding:12px;background:rgba(34,197,94,0.12);border-radius:8px;"><div style="color:var(--text-muted);">FN</div><div style="font-size:22px;font-weight:700;">${fmt(ad.fn)}</div><div>low risk + fraud outcome</div></div>
      <div style="padding:12px;background:rgba(59,130,246,0.15);border-radius:8px;"><div style="color:var(--text-muted);">TP</div><div style="font-size:22px;font-weight:700;">${fmt(ad.tp)}</div><div>high risk + fraud outcome</div></div>
    </div>`;
  const head = `
    <div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px;align-items:flex-start;">
      ${cm}
      <div style="flex:1;min-width:200px;">
        <div class="metrics-row" style="flex-wrap:wrap;">
          <div class="metric-card"><div class="metric-label">Reviewed</div><div class="metric-value">${fmt(d.reviewed_count)}</div></div>
          <div class="metric-card"><div class="metric-label">Precision @ ${d.default_threshold}</div><div class="metric-value">${mat(ad.precision)}</div></div>
          <div class="metric-card"><div class="metric-label">Recall @ ${d.default_threshold}</div><div class="metric-value">${mat(ad.recall)}</div></div>
          <div class="metric-card"><div class="metric-label">F1 @ ${d.default_threshold}</div><div class="metric-value">${mat(ad.f1)}</div></div>
        </div>
        <p style="font-size:11px;color:var(--text-muted);margin:8px 0 0;">Labels use outcome records only (confirmed fraud vs false positive). “High risk” = score ≥ threshold.</p>
      </div>
    </div>`;
  el.innerHTML = head + `
    <div class="grid-2" style="margin-top:16px;">
      <div class="panel" style="box-shadow:none;border:1px solid var(--border);">
        <div class="panel-header"><span class="panel-title">Precision & recall vs threshold</span></div>
        <div class="panel-body"><div id="chart-model-threshold" class="chart-container" style="height:280px;"></div></div>
      </div>
      <div class="panel" style="box-shadow:none;border:1px solid var(--border);">
        <div class="panel-header"><span class="panel-title">Weekly trend @ ${d.default_threshold}</span></div>
        <div class="panel-body"><div id="chart-model-weekly" class="chart-container" style="height:280px;"></div></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px;box-shadow:none;border:1px solid var(--border);">
      <div class="panel-header"><span class="panel-title">Per-flag precision (reviewed sample)</span></div>
      <div class="panel-body no-pad" id="modelPerfFlagTable"></div>
    </div>`;
  const th = d.thresholds || [];
  const xs = th.map(t => t.threshold);
  if (th.length) {
    renderApexChart('chart-model-threshold', 'line', {
      series: [
        { name: 'Precision %', data: th.map(t => t.precision) },
        { name: 'Recall %', data: th.map(t => t.recall) },
        { name: 'F1 %', data: th.map(t => t.f1) }
      ],
      categories: xs.map(String)
    }, {
      height: 280,
      colors: ['#3b82f6', '#22c55e', '#f59e0b'],
      stroke: { curve: 'straight', width: 2, dashArray: [0, 0, 5] },
      markers: { size: 4 },
      xaxis: { title: { text: 'Threshold' } },
      yaxis: { min: 0, max: 105, title: { text: '%' } }
    });
  }
  const wk = d.weekly || [];
  if (wk.length) {
    renderApexChart('chart-model-weekly', 'line', {
      series: [
        { name: 'Precision %', data: wk.map(x => x.precision) },
        { name: 'Recall %', data: wk.map(x => x.recall) }
      ],
      categories: wk.map(x => x.week)
    }, {
      height: 280,
      colors: ['#3b82f6', '#22c55e'],
      stroke: { curve: 'straight', width: 2 },
      markers: { size: 4 },
      xaxis: { title: { text: 'Week' }, labels: { rotate: -45 } },
      yaxis: { min: 0, max: 105, title: { text: '%' } }
    });
  }
  const flags = d.by_flag || [];
  const tbl = document.getElementById('modelPerfFlagTable');
  if (tbl) {
    tbl.innerHTML = flags.length ? buildTable('mpf', [
      { key: 'flag', label: 'Flag' },
      { key: 'confirmed_fraud', label: 'Fraud' },
      { key: 'false_positive', label: 'FP' },
      { key: 'total', label: 'Total' },
      { key: 'precision_pct', label: 'Precision %', render: v => v == null ? '—' : `${v}%` }
    ], flags, { emptyIcon: '—', emptyTitle: 'No flags' }) : emptyState('—', 'No per-flag breakdown', '');
  }
}

async function loadMlSupervised() {
  const el = document.getElementById('mlSupervisedBody');
  if (!el) return;
  el.innerHTML = '<div class="loading-spinner">Loading ML…</div>';
  const [statusRes, compareRes] = await Promise.all([
    api('/api/ml/status', { skipCache: true }),
    api('/api/ml/compare', { skipCache: true })
  ]);
  const st = statusRes.data || {};
  const cmp = compareRes.data || {};
  if (statusRes.error) {
    el.innerHTML = `<div style="padding:16px;color:var(--risk-high);">${escapeHtml(statusRes.error)}</div>`;
    return;
  }
  if (!st.sklearn_available) {
    el.innerHTML = emptyState('◈', 'scikit-learn not installed',
      'Run <code>pip install scikit-learn</code> to enable supervised fraud prediction.');
    return;
  }
  const minN = st.min_labeled_samples || 30;
  const active = st.active_model;
  const pctFmt = (v) => (v == null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(1)}%`);
  let head = `
    <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">
      <strong>Supervised ML</strong> — logistic regression on reviewed outcomes
      (${fmt(st.labeled_count || 0)} labeled: ${fmt(st.confirmed_fraud_count || 0)} fraud, ${fmt(st.false_positive_count || 0)} FP).
      Minimum to train: ${minN}.
    </div>`;
  if (!active) {
    head += `<p style="font-size:13px;margin:8px 0;">${st.ready_to_train
      ? 'Enough labels to train. Click <strong>Train ML model</strong> above.'
      : `Need ${minN - (st.labeled_count || 0)} more reviewed outcomes before training.`}</p>`;
    el.innerHTML = head;
    return;
  }
  const rocAuc = active.test_roc_auc;
  const cvMean = active.cv_roc_auc_mean;
  head += `
    <div class="metrics-row" style="flex-wrap:wrap;margin-bottom:12px;">
      <div class="metric-card"><div class="metric-label">Active model</div><div class="metric-value" style="font-size:14px;">${escapeHtml(active.run_id || '—')}</div></div>
      <div class="metric-card"><div class="metric-label">Test ROC-AUC</div><div class="metric-value">${rocAuc != null ? rocAuc : '—'}</div></div>
      <div class="metric-card"><div class="metric-label">CV ROC-AUC</div><div class="metric-value">${cvMean != null ? `${cvMean}${active.cv_roc_auc_std != null ? ` ± ${active.cv_roc_auc_std}` : ''}` : '—'}</div></div>
      <div class="metric-card"><div class="metric-label">Test precision</div><div class="metric-value">${pctFmt(active.test_precision)}</div></div>
      <div class="metric-card"><div class="metric-label">Test recall</div><div class="metric-value">${pctFmt(active.test_recall)}</div></div>
    </div>`;
  const rules = cmp.rules;
  const ml = cmp.ml;
  if (rules || ml) {
    head += `<div class="grid-2" style="margin-top:8px;">
      <div class="panel" style="box-shadow:none;border:1px solid var(--border);">
        <div class="panel-header"><span class="panel-title">Rules @ ${rules?.threshold ?? '—'}</span></div>
        <div class="panel-body" style="font-size:13px;">
          Precision: <strong>${rules?.precision != null ? rules.precision + '%' : '—'}</strong> ·
          Recall: <strong>${rules?.recall != null ? rules.recall + '%' : '—'}</strong>
          <div style="color:var(--text-muted);margin-top:4px;">TP ${fmt(rules?.tp)} · FP ${fmt(rules?.fp)} · FN ${fmt(rules?.fn)}</div>
        </div>
      </div>
      <div class="panel" style="box-shadow:none;border:1px solid var(--border);">
        <div class="panel-header"><span class="panel-title">ML @ ${ml?.threshold ?? '—'}</span></div>
        <div class="panel-body" style="font-size:13px;">
          ${ml ? `Precision: <strong>${ml.precision != null ? ml.precision + '%' : '—'}</strong> · Recall: <strong>${ml.recall != null ? ml.recall + '%' : '—'}</strong>
          <div style="color:var(--text-muted);margin-top:4px;">TP ${fmt(ml.tp)} · FP ${fmt(ml.fp)} · FN ${fmt(ml.fn)}</div>`
            : 'Score all accounts after training to compare.'}
        </div>
      </div>
    </div>`;
  }
  const roc = st.roc_curve || [];
  head += `<div class="panel" style="margin-top:12px;box-shadow:none;border:1px solid var(--border);">
    <div class="panel-header"><span class="panel-title">ROC curve (hold-out test)</span></div>
    <div class="panel-body"><div id="chart-ml-roc" class="chart-container" style="height:240px;"></div></div>
  </div>`;
  const top = st.top_features || [];
  if (top.length) {
    head += `<div class="panel" style="margin-top:12px;box-shadow:none;border:1px solid var(--border);">
      <div class="panel-header"><span class="panel-title">Top feature weights</span></div>
      <div class="panel-body no-pad" id="mlTopFeaturesTable"></div>
    </div>`;
  }
  el.innerHTML = head.replace(/motion\.div/g, 'div');
  if (roc.length) {
    renderApexChart('chart-ml-roc', 'line', {
      series: [{ name: 'TPR', data: roc.map(p => p.tpr) }],
      categories: roc.map(p => String(p.fpr))
    }, {
      height: 240,
      chart: { type: 'line' },
      xaxis: { title: { text: 'FPR' }, min: 0, max: 1 },
      yaxis: { title: { text: 'TPR' }, min: 0, max: 1 },
      stroke: { width: 2 }
    });
  }
  const tft = document.getElementById('mlTopFeaturesTable');
  if (tft && top.length) {
    tft.innerHTML = buildTable('mlfeat', [
      { key: 'name', label: 'Feature' },
      { key: 'coefficient', label: 'Coef', render: v => v == null ? '—' : Number(v).toFixed(4) }
    ], top, { emptyIcon: '—', emptyTitle: 'No features' });
  }
}

document.getElementById('btnTrainMlModel')?.addEventListener('click', async () => {
  const btn = document.getElementById('btnTrainMlModel');
  if (!btn || btn.disabled) return;
  if (!confirm('Train a new logistic regression model on reviewed outcomes and score all accounts?')) return;
  btn.disabled = true;
  btn.textContent = 'Training…';
  const res = await api('/api/ml/train', { method: 'POST', skipCache: true });
  btn.disabled = false;
  btn.textContent = 'Train ML model';
  if (res.error || (res.data && res.data.error)) {
    showToast(res.error || res.data.error, 'error');
  } else {
    showToast(`Model trained (ROC-AUC ${res.data?.test_metrics?.roc_auc ?? '—'})`, 'success');
    _apiResponseCache.delete('/api/ml/status');
    _apiResponseCache.delete('/api/ml/compare');
    loadMlSupervised();
    loadModelPerformance();
  }
});

// ═══════════════════════════════════════════════════════════
// PATTERN DISCOVERY TAB
// ═══════════════════════════════════════════════════════════
let patternCache = null;
let patternCacheTime = null;
let patternCacheExpiresAt = null;
const PATTERN_CACHE_TTL_MS = 5 * 60 * 1000;

async function runPatternDiscovery() {
  const btn = document.getElementById('runPatternBtn');
  const status = document.getElementById('patternStatus');
  
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span> Analyzing...';
  status.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;">🔍 Discovering patterns in fraud data...</div>';
  
  const minRisk = document.getElementById('patternRisk')?.value || '';
  const base = analysisFilterParams();
  const sep = base ? '&' : '?';
  const url = minRisk
    ? `/api/pattern-discovery${base}${base ? '&' : '?'}min_risk=${minRisk}`
    : `/api/pattern-discovery${base}`;
  const res = await api(url);
  
  btn.disabled = false;
  btn.innerHTML = '<span class="btn-icon">🔍</span> Analyze Patterns';
  
  if (res.error) {
    status.innerHTML = `<div style="color:var(--risk-high);font-size:12px;">⚠️ Analysis failed: ${res.error}</div>`;
    showToast('Pattern discovery failed: ' + res.error, 'error');
    return;
  }
  
  // Cache results (expires after TTL)
  patternCache = res.data;
  patternCacheTime = new Date().toLocaleString();
  patternCacheExpiresAt = Date.now() + PATTERN_CACHE_TTL_MS;
  
  status.innerHTML = `<div style="color:var(--text-success);font-size:12px;">✓ Analysis complete (${patternCacheTime})</div>`;
  showToast('Pattern discovery complete', 'success');
  
  // Load from cache
  loadPatterns();
}

async function loadPatterns() {
  if (patternCache && patternCacheExpiresAt && patternCacheExpiresAt > Date.now()) {
    displayPatterns(patternCache);
    return;
  }
  return runPatternDiscovery();
}

function displayPatterns(data) {
  const flags = data.flags || [];
  const domains = data.domains || [];
  const riskDist = data.risk_distribution || [];
  const total = data.total_records || 0;
  
  // Metrics
  document.getElementById('patternMetrics').innerHTML = `
    <div class="metric-card"><div class="metric-label">Records Analyzed</div><div class="metric-value">${fmt(total)}</div></div>
    <div class="metric-card"><div class="metric-label">Unique Flags</div><div class="metric-value">${flags.length}</div></div>
    <div class="metric-card"><div class="metric-label">Email Domains</div><div class="metric-value">${domains.length}</div></div>
  `;
  
  // Flag frequency table
  const flagsWrap = document.getElementById('patternFlagsWrap');
  if (flags.length === 0) {
    flagsWrap.innerHTML = emptyState('🔍', 'No patterns found', 'Run fraud analysis first');
  } else {
    flagsWrap.innerHTML = flags.map(f => `
      <div class="flag-stat clickable-drill" onclick='openAnalysisDrilldown("flag", ${JSON.stringify(f.flag)})' title="View accounts">
        <span class="flag-name">${f.flag.replace(/_/g, ' ')}</span>
        <span class="flag-count">${f.count} (${f.pct}%)</span>
        <div class="flag-bar"><div class="flag-fill" style="width:${f.pct}%"></div></div>
      </div>
    `).join('');
  }
  
  // Domains chart
  if (domains.length > 0) {
    // Top Domains Chart (ApexCharts)
    renderApexChart('chart-domains', 'bar', {
      series: [{
        name: 'Accounts',
        data: domains.map(d => d.count)
      }],
      categories: domains.map(d => d.domain)
    }, {
      colors: ['#8b5cf6'],
      height: 320,
      plotOptions: {
        bar: {
          horizontal: true,
          dataLabels: { position: 'top' }
        }
      },
      dataLabels: {
        enabled: true,
        offsetX: 30,
        style: { fontSize: '12px', fontWeight: 600 }
      },
      xaxis: { title: { text: 'Account Count', style: { fontSize: '13px', fontWeight: 600 } } },
      yaxis: { labels: { maxWidth: 180, style: { fontSize: '11px' } } }
    });
    
    addChartControls('chart-domains', ['bar', 'line']);
  }
  
  // Risk distribution chart
  if (riskDist.length > 0) {
    // Risk Distribution Chart (ApexCharts)
    renderApexChart('chart-risk-dist', 'donut', {
      values: riskDist.map(r => r.count),
      labels: riskDist.map(r => r.range)
    }, {
      colors: ['#22c55e', '#f59e0b', '#f97316', '#ef4444'],
      height: 280,
      legend: { position: 'bottom', fontSize: '13px' },
      plotOptions: {
        pie: {
          donut: {
            size: '60%',
            labels: {
              show: true,
              name: { show: true, fontSize: '14px', fontWeight: 600 },
              value: { show: true, fontSize: '20px', fontWeight: 700, formatter: (val) => val.toLocaleString() },
              total: {
                show: true,
                label: 'Total Accounts',
                fontSize: '14px',
                fontWeight: 600
              }
            }
          }
        }
      }
    });
    
    addChartControls('chart-risk-dist', ['donut', 'pie', 'bar']);
  }
}

// ═══════════════════════════════════════════════════════════
// CLUSTER ANALYSIS TAB
// ═══════════════════════════════════════════════════════════

let _clusterData = {};

async function loadClusters() {
  return loadClusterAnalysis();
}

async function loadClusterAnalysis() {
  const hideHouse = document.getElementById('hideHouseIpToggle')?.checked !== false;
  const res = await api(`/api/cluster-analysis?hide_house=${hideHouse}`);
  
  if (res.error) {
    showToast('Failed to load clusters: ' + res.error, 'error');
    return;
  }
  
  const data = res.data || {};
  const ipClusters = data.ip_clusters || [];
  const domainClusters = data.domain_clusters || [];
  const affiliateClusters = data.affiliate_clusters || [];
  
  // Store for drilldown
  _clusterData = { ipClusters, domainClusters, affiliateClusters };
  
  // IP clusters table - clickable for drilldown
  const ipWrap = document.getElementById('ipClustersWrap');
  if (ipClusters.length === 0) {
    ipWrap.innerHTML = emptyState('🔗', 'No IP clusters', 'No accounts share the same IP');
  } else {
    ipWrap.innerHTML = buildTable('ip', [
      { key: 'ip', label: 'IP Address' },
      { key: 'accounts', label: 'Accounts', numeric: true, right: true },
      { key: 'high_risk', label: 'High Risk', numeric: true, right: true, render: v => `<span style="color:var(--risk-high)">${v}</span>` },
      { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true },
      { key: 'total_payout', label: 'Payout', numeric: true, right: true, render: v => fmtCur(v) },
      { key: 'ip', label: '', render: v => `<a href="/cluster/ip/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge" title="Open investigation page">↗</a>` }
    ], ipClusters, { clickable: true, onClick: 'drillIpCluster', emptyIcon: '🔗', emptyTitle: 'No IP clusters' });
  }
  
  // Domain clusters table - clickable for drilldown
  const domainWrap = document.getElementById('domainClustersWrap');
  if (domainClusters.length === 0) {
    domainWrap.innerHTML = emptyState('📧', 'No domain clusters', 'No high-risk domain concentrations');
  } else {
    domainWrap.innerHTML = buildTable('domain', [
      { key: 'domain', label: 'Domain' },
      { key: 'accounts', label: 'Accounts', numeric: true, right: true },
      { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true, render: v => v?.toFixed(1) },
      { key: 'total_payout', label: 'Payout', numeric: true, right: true, render: v => fmtCur(v) },
      { key: 'domain', label: '', render: v => `<a href="/cluster/domain/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge" title="Open investigation page">↗</a>` }
    ], domainClusters, { clickable: true, onClick: 'drillDomainCluster', emptyIcon: '📧', emptyTitle: 'No domain clusters' });
  }

  // Affiliate clusters table - clickable for drilldown
  const affWrap = document.getElementById('affiliateClustersWrap');
  if (affiliateClusters.length === 0) {
    affWrap.innerHTML = emptyState('👥', 'No affiliate clusters', 'No high-risk affiliate concentrations');
  } else {
    affWrap.innerHTML = buildTable('affcluster', [
      { key: 'affiliate', label: 'Affiliate' },
      { key: 'accounts', label: 'Accounts', numeric: true, right: true },
      { key: 'high_risk_pct', label: 'High Risk %', numeric: true, right: true, render: v => `<span style="color:${v > 10 ? 'var(--risk-high)' : 'inherit'}">${v?.toFixed(1)}%</span>` },
      { key: 'avg_risk', label: 'Avg Risk', numeric: true, right: true, render: v => v?.toFixed(1) },
      { key: 'total_payout', label: 'Payout', numeric: true, right: true, render: v => fmtCur(v) },
      { key: 'affiliate', label: '', render: v => `<a href="/cluster/affiliate/${encodeURIComponent(v)}" target="_blank" onclick="event.stopPropagation()" class="aff-link-badge" title="Open investigation page">↗</a>` }
    ], affiliateClusters, { clickable: true, onClick: 'drillAffiliateCluster', emptyIcon: '👥', emptyTitle: 'No affiliate clusters' });
  }
}

// IP Cluster drilldown
async function drillIpCluster(idx) {
  const cluster = _clusterData.ipClusters?.[idx];
  if (!cluster) return;
  
  const ip = cluster.ip;
  const res = await api(`/api/cluster/ip/${encodeURIComponent(ip)}`);
  
  if (res.error) {
    showToast('Failed to load IP cluster: ' + res.error, 'error');
    return;
  }
  
  showClusterModal('IP Cluster', `IP: ${ip}`, cluster, res.data || [], 'ip', ip);
}

// Domain Cluster drilldown
async function drillDomainCluster(idx) {
  const cluster = _clusterData.domainClusters?.[idx];
  if (!cluster) return;
  
  const domain = cluster.domain;
  const res = await api(`/api/cluster/domain/${encodeURIComponent(domain)}`);
  
  if (res.error) {
    showToast('Failed to load domain cluster: ' + res.error, 'error');
    return;
  }
  
  showClusterModal('Domain Cluster', `Domain: ${domain}`, cluster, res.data || [], 'domain', domain);
}

// Affiliate Cluster drilldown — dedicated affiliate page (avoids buried in-tab drill)
function drillAffiliateCluster(idx) {
  const cluster = _clusterData.affiliateClusters?.[idx];
  if (!cluster) return;
  window.location.href = '/affiliate/' + encodeURIComponent(cluster.affiliate);
}

/** Open the standalone affiliate investigation page (same as “Open full page”). */
function drillAffiliateByCode(code) {
  if (!code) return;
  window.location.href = '/affiliate/' + encodeURIComponent(code);
}

// Generic cluster modal
function showClusterModal(title, subtitle, summary, accounts, clusterType, clusterId) {
  const modal = document.getElementById('accountModal');
  const body = document.getElementById('accountModalBody');

  setClusterModalMode(true, title);

  const fullPageHref = (clusterType && clusterId)
    ? `/cluster/${clusterType}/${encodeURIComponent(clusterId)}`
    : null;

  const accountCount = summary.accounts ?? summary.account_count ?? accounts.length ?? 0;
  const highRisk = summary.high_risk || 0;
  const avgRisk = (summary.avg_risk || 0).toFixed(1);
  const totalPayout = fmtCur(summary.total_payout);

  const sortedAccounts = [...accounts].sort(
    (a, b) => (Number(b.risk_score) || 0) - (Number(a.risk_score) || 0)
  );
  const previewAccounts = sortedAccounts.slice(0, CLUSTER_MODAL_PREVIEW_LIMIT);
  window._clusterModalAccounts = previewAccounts;

  const overflowNote = accounts.length > CLUSTER_MODAL_PREVIEW_LIMIT
    ? `<div class="cluster-preview-note">Showing top ${CLUSTER_MODAL_PREVIEW_LIMIT} by risk · ${fmt(accounts.length - CLUSTER_MODAL_PREVIEW_LIMIT)} more on full investigation page</div>`
    : '';

  modal.classList.add('open');
  body.innerHTML = `
    <div class="cluster-modal-header">
      <div>
        <div class="cluster-modal-subtitle">${escapeHtml(subtitle)}</div>
      </div>
      ${fullPageHref ? `
        <a href="${fullPageHref}" target="_blank" class="cluster-full-page-link"
           title="Open dedicated investigation page">
          Full Investigation ↗
        </a>` : ''}
    </div>

    <div class="cluster-kpi-strip">
      <span class="cluster-kpi-item"><strong>${fmt(accountCount)}</strong> accounts</span>
      <span class="cluster-kpi-item danger"><strong>${fmt(highRisk)}</strong> high risk</span>
      <span class="cluster-kpi-item">avg <strong>${avgRisk}</strong></span>
      <span class="cluster-kpi-item">payout <strong>${totalPayout}</strong></span>
    </div>

    <div class="cluster-hint">Click any row to view account detail</div>
    <div class="cluster-table-scroll">
      ${buildTable('clusterdetail', [
        { key: 'email', label: 'Email', render: v => renderClusterEmail(v) },
        { key: 'risk_score', label: 'Risk', numeric: true, right: true, render: v => riskBadge(v) },
        { key: 'flags', label: 'Flags', render: v => renderClusterFlags(v) }
      ], previewAccounts, {
        clickable: true,
        onClick: '_openClusterAccount',
        noSort: true,
        emptyIcon: '⊘',
        emptyTitle: 'No accounts'
      })}
      ${overflowNote}
    </div>

    <div class="account-actions">
      ${fullPageHref ? `
        <a href="${fullPageHref}" target="_blank" class="btn btn-primary" style="text-decoration:none;">
          Open Full Investigation ↗
        </a>` : ''}
      <button class="btn btn-cancel" onclick="closeAccountModal()">Close</button>
    </div>
  `;
}

function _openClusterAccount(idx) {
  const row = window._clusterModalAccounts?.[idx];
  const duid = row && (row.duid || row.DUID);
  if (duid) openAccountDetail(duid);
}

// ═══════════════════════════════════════════════════════════
// LOW-RISK SAMPLING TAB
// ═══════════════════════════════════════════════════════════

async function loadSampling() {
  const res = await api('/api/low-risk-samples?status=pending');
  
  if (res.error) {
    showToast('Failed to load samples: ' + res.error, 'error');
    return;
  }
  
  const samples = res.data || [];
  const statusOf = s => s.review_status || s.status || 'pending';

  const totalReviewed = samples.filter(s => statusOf(s) !== 'pending').length;
  const pendingCount = samples.filter(s => statusOf(s) === 'pending').length;
  
  document.getElementById('samplingMetrics').innerHTML = `
    <div class="metric-card"><div class="metric-label">Pending Review</div><div class="metric-value">${fmt(pendingCount)}</div></div>
    <div class="metric-card"><div class="metric-label">Total Samples</div><div class="metric-value">${fmt(samples.length)}</div></div>
  `;
  
  document.getElementById('samplingCount').textContent = `${pendingCount} pending`;
  
  // Samples table
  const wrap = document.getElementById('samplingTableWrap');
  if (samples.length === 0) {
    wrap.innerHTML = emptyState('🎲', 'No samples', 'Generate a sample batch to review low-risk accounts');
  } else {
    wrap.innerHTML = buildTable('sample', [
      { key: 'email', label: 'Email', render: v => truncate(v, 36) },
      { key: 'risk_score', label: 'Risk', numeric: true, right: true },
      { key: 'sampled_at', label: 'Sampled', muted: true, render: (v, row) => {
        const ts = v || row.created_at;
        return ts ? new Date(ts).toLocaleDateString() : '—';
      }},
      { key: 'duid', label: 'Actions', render: (v, row) =>
        statusOf(row) === 'pending'
          ? (`<button class="btn btn-sm btn-fraud" onclick="event.stopPropagation();reviewSample('${v}','missed_fraud')">Fraud</button> ` +
             `<button class="btn btn-sm btn-fp" onclick="event.stopPropagation();reviewSample('${v}','legitimate')">OK</button>`)
          : `<span style="color:var(--text-muted);font-size:11px">${statusOf(row).replace(/_/g, ' ')}</span>`
      }
    ], samples, { emptyIcon: '🎲', emptyTitle: 'No samples' });
  }
}

async function createSampleBatch() {
  const count = parseInt(document.getElementById('sampleCount').value) || 20;
  const maxRisk = parseInt(document.getElementById('sampleMaxRisk').value) || 24;
  
  const res = await api('/api/low-risk-samples', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count, max_risk: maxRisk })
  });
  
  if (res.error) {
    showToast('Failed to create samples: ' + res.error, 'error');
    return;
  }
  
  showToast(`Created ${res.data?.count || 0} samples`, 'success');
  clearApiCache();
  loadSampling();
}

async function reviewSample(duid, status) {
  const res = await api(`/api/low-risk-samples/${encodeURIComponent(duid)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, notes: 'Low-risk sample review' })
  });
  
  if (res.error) {
    showToast('Failed to record sample review: ' + res.error, 'error');
    return;
  }
  
  showToast('Sample review recorded', 'success');
  clearApiCache();
  _analysisSubTabLoaded['anomaly-major-monitoring'] = false;
  loadSampling();
}

// ═══════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════
// FLAGS DASHBOARD TAB
// ═══════════════════════════════════════════════════════════

let currentFlagPage = 1;
let selectedFlag = '';

async function loadFlagsTab() {
  await loadFlagsList();
}

function filterFlagSelectOptions() {
  const select = document.getElementById('flagSelect');
  if (!select) return;
  const q = (document.getElementById('flagSearchInput')?.value || '').toLowerCase().trim();
  for (const opt of select.options) {
    if (!opt.value) {
      opt.hidden = false;
      continue;
    }
    const hay = `${opt.value} ${opt.textContent}`.toLowerCase();
    opt.hidden = !!(q && !hay.includes(q));
  }
}

async function loadFlagsList() {
  const select = document.getElementById('flagSelect');
  if (!select) return;
  const currentValue = select.value;

  const res = await api('/api/flags/list');

  if (res.error) {
    select.innerHTML = '<option value="">Error loading flags — click ↻ to retry</option>';
    console.error('Flags list error:', res.error);
    return;
  }

  const flags = (res.data && res.data.flags) ? res.data.flags : [];

  if (flags.length === 0) {
    select.innerHTML = '<option value="">No flags found — run fraud analysis first</option>';
    return;
  }

  let html = `<option value="">— Select a flag (${flags.length} groups) —</option>`;
  for (const f of flags) {
    const esc = String(f.flag).replace(/"/g, '&quot;');
    html += `<option value="${esc}">${f.flag} (${fmt(f.count)})</option>`;
  }

  select.innerHTML = html;
  filterFlagSelectOptions();

  // Restore selection if it still exists
  if (currentValue && flags.some(f => f.flag === currentValue)) {
    select.value = currentValue;
    // Re-trigger the data load if we restored a selection
    loadFlagData();
  }
}

async function loadFlagData() {
  const flag = document.getElementById('flagSelect').value;

  if (!flag) {
    document.getElementById('flagDashboardContent').style.display = 'none';
    document.getElementById('flagEmptyState').style.display = 'block';
    selectedFlag = '';
    return;
  }

  selectedFlag = flag;
  document.getElementById('flagDashboardContent').style.display = 'block';
  document.getElementById('flagEmptyState').style.display = 'none';

  // Load all flag data in parallel
  await Promise.all([
    loadFlagSummary(flag),
    loadFlagAffiliates(flag),
    loadFlagCooccurrence(flag),
    loadFlagAccounts(1)
  ]);
}

async function loadFlagSummary(flag) {
  const res = await api(`/api/flags/${encodeURIComponent(flag)}/summary`);

  if (res.error) {
    showToast('Failed to load flag summary', 'error');
    return;
  }

  const data = res.data;

  // Update metrics
  document.getElementById('flagTotalAffected').textContent = fmt(data.total_affected);
  document.getElementById('flagTotalSub').textContent = `${fmt(data.high_risk_count)} high risk · ${fmt(data.medium_risk_count)} medium`;

  document.getElementById('flagPaidFree').textContent = `${data.paid_pct}% / ${data.free_pct}%`;
  document.getElementById('flagPaidFreeSub').textContent = `${fmt(data.paid_count)} paid · ${fmt(data.free_count)} free`;

  const avgRiskEl = document.getElementById('flagAvgRisk');
  avgRiskEl.textContent = data.avg_risk_score;
  avgRiskEl.className = 'metric-value ' + (data.avg_risk_score >= 50 ? 'high' : data.avg_risk_score >= 25 ? 'medium' : 'low');

  document.getElementById('flagTotalPayout').textContent = fmtCur(data.total_payout);

  renderApexChart('flagRiskDistChart', 'bar', {
    series: [{ name: 'Accounts', data: [data.high_risk_count, data.medium_risk_count, data.low_risk_count] }],
    categories: ['High (50+)', 'Medium (25-49)', 'Low (0-24)']
  }, {
    height: 280,
    colors: ['rgba(220, 38, 38, 0.8)', 'rgba(217, 119, 6, 0.8)', 'rgba(5, 150, 105, 0.8)'],
    plotOptions: { bar: { distributed: true, borderRadius: 4 } },
    legend: { show: false },
    yaxis: { title: { text: 'Accounts' } }
  });

  renderApexChart('flagPaidFreeChart', 'donut', {
    labels: ['Paid', 'Free'],
    values: [data.paid_count, data.free_count]
  }, {
    height: 260,
    colors: ['rgba(37, 99, 235, 0.8)', 'rgba(124, 58, 237, 0.8)'],
    legend: { show: false },
    plotOptions: { pie: { donut: { size: '60%' } } },
    dataLabels: { enabled: true }
  });
}

async function loadFlagAffiliates(flag) {
  const wrap = document.getElementById('flagAffiliatesWrap');
  wrap.innerHTML = '<div class="loading-spinner">Loading affiliates...</div>';

  const res = await api(`/api/flags/${encodeURIComponent(flag)}/affiliates`);

  if (res.error) {
    wrap.innerHTML = errorState('Failed to load', res.error);
    return;
  }

  const affiliates = res.data.affiliates || [];
  document.getElementById('flagAffiliateCount').textContent = `${affiliates.length} affiliates`;

  // Also populate the affiliate filter dropdown
  const affFilter = document.getElementById('flagAccountsAffiliate');
  let filterHtml = '<option value="">All Affiliates</option>';
  for (const aff of affiliates.slice(0, 30)) {
    filterHtml += `<option value="${aff.affiliate}">${aff.affiliate} (${aff.count})</option>`;
  }
  affFilter.innerHTML = filterHtml;

  if (affiliates.length === 0) {
    wrap.innerHTML = emptyState('⊞', 'No affiliate data', 'No affiliates found for this flag');
    return;
  }

  wrap.innerHTML = buildTable('flagAff', [
    {
      key: 'affiliate',
      label: 'Affiliate',
      render: (v) =>
        `<span class="mono clickable" data-affiliate-drill="${escapeHtml(v)}" title="Open affiliate (search pre-filled with this flag)">${escapeHtml(v)}</span>`,
    },
    { key: 'count', label: 'Accounts', render: v => fmt(v) },
    { key: 'avg_risk', label: 'Avg Risk', render: v => riskBadge(Math.round(v)) },
    { key: 'paid_count', label: 'Paid', render: v => fmt(v) },
    { key: 'free_count', label: 'Free', render: v => fmt(v) },
    { key: 'paid_pct', label: 'Paid %', render: v => v + '%' },
    { key: 'total_payout', label: 'Payout', render: v => fmtCur(v) }
  ], affiliates, { emptyIcon: '⊞', emptyTitle: 'No affiliates' });
}

function pickCooccurFlag(flagKey) {
  const fs = document.getElementById('flagSearchInput');
  if (fs) fs.value = '';
  const sel = document.getElementById('flagSelect');
  if (sel) sel.value = flagKey;
  filterFlagSelectOptions();
  loadFlagData();
}

async function loadFlagCooccurrence(flag) {
  const wrap = document.getElementById('flagCooccurrenceWrap');
  wrap.innerHTML = '<div class="loading-spinner">Loading co-occurrence data...</div>';

  const res = await api(`/api/flags/${encodeURIComponent(flag)}/cooccurrence`);

  if (res.error) {
    wrap.innerHTML = errorState('Failed to load', res.error);
    return;
  }

  const cooccur = res.data.cooccurrence || [];

  if (cooccur.length === 0) {
    wrap.innerHTML = '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px;">No co-occurring flags found (this flag usually appears alone)</div>';
    return;
  }

  let html = '<div class="cooccurrence-grid">';
  for (const item of cooccur) {
    const fk = JSON.stringify(item.flag);
    html += `
      <div class="cooccur-tag" onclick="pickCooccurFlag(${fk})" title="Click to analyze this flag">
        <span>${item.flag}</span>
        <span class="cooccur-count">${fmt(item.count)}</span>
        <span class="cooccur-pct">(${item.pct}%)</span>
      </div>
    `;
  }
  html += '</div>';

  wrap.innerHTML = html;
}

async function loadFlagAccounts(page = 1) {
  if (!selectedFlag) return;

  currentFlagPage = page;
  const wrap = document.getElementById('flagAccountsWrap');
  wrap.innerHTML = '<div class="loading-spinner">Loading accounts...</div>';

  const dataType = document.getElementById('flagAccountsDataType').value;
  const affiliate = document.getElementById('flagAccountsAffiliate').value;

  let url = `/api/flags/${encodeURIComponent(selectedFlag)}/accounts?page=${page}&per_page=50`;
  if (dataType) url += `&data_type=${dataType}`;
  if (affiliate) url += `&affiliate=${encodeURIComponent(affiliate)}`;

  const res = await api(url);

  if (res.error) {
    wrap.innerHTML = errorState('Failed to load', res.error);
    return;
  }

  const { accounts, total, total_pages } = res.data;

  if (accounts.length === 0) {
    wrap.innerHTML = emptyState('📋', 'No accounts found', 'Try adjusting your filters');
    document.getElementById('flagAccountsPagination').style.display = 'none';
    return;
  }

  wrap.innerHTML = buildTable('flagAccts', [
    {
      key: 'email',
      label: 'Email',
      render: (v, row) => {
        const d = row.duid != null ? String(row.duid) : '';
        const lab = truncate(String(v || ''), 30);
        return d
          ? `<span class="mono clickable" data-open-account="${escapeHtml(d)}" title="Account details">${escapeHtml(lab)}</span>`
          : escapeHtml(lab);
      },
    },
    { key: 'risk_score', label: 'Risk', render: v => riskBadge(v) },
    { key: 'data_type', label: 'Type', render: v => `<span class="type-badge ${v}">${v}</span>` },
    {
      key: 'affiliate',
      label: 'Affiliate',
      muted: true,
      render: (v) =>
        v
          ? `<span class="mono clickable" data-affiliate-drill="${escapeHtml(v)}" title="Open affiliate detail">${escapeHtml(truncate(String(v), 15))}</span>`
          : '—',
    },
    { key: 'payout_amount', label: 'Payout', render: v => fmtCur(v) },
    {
      key: 'duid',
      label: '',
      render: (v) =>
        `<button type="button" class="btn btn-sm" data-open-account="${escapeHtml(String(v != null ? v : ''))}">View</button>`,
    },
  ], accounts, { emptyIcon: '📋', emptyTitle: 'No accounts' });

  // Update pagination
  const paginationEl = document.getElementById('flagAccountsPagination');
  if (total_pages > 1) {
    paginationEl.style.display = 'block';
    document.getElementById('flagPageInfo').textContent = `Page ${page} of ${total_pages} (${fmt(total)} accounts)`;
    document.getElementById('flagPrevPage').disabled = page <= 1;
    document.getElementById('flagNextPage').disabled = page >= total_pages;
  } else {
    paginationEl.style.display = 'none';
  }
}

// ═══════════════════════════════════════════════════════════
// EXPLORE DATA (EDA) TAB
// ═══════════════════════════════════════════════════════════

async function loadExplore() {
  // Load summary first
  await loadExploreSummary();
  // Then load completeness and distributions in parallel
  await Promise.all([
    loadExploreCompleteness(),
    loadExploreDistribution(),
    loadExploreCorrelations()
  ]);
}

async function loadExploreSummary() {
  const res = await api('/api/explore/summary');

  if (res.error) {
    document.getElementById('exploreRecordCount').textContent = '—';
    document.getElementById('exploreRecordSub').textContent = 'Error loading';
    return;
  }

  const data = res.data;

  // Total records
  const totalRecords = data.record_counts.fraud_results;
  document.getElementById('exploreRecordCount').textContent = fmt(totalRecords);
  document.getElementById('exploreRecordSub').textContent =
    `${fmt(data.record_counts.paid)} paid · ${fmt(data.record_counts.free)} free`;

  // Date range
  const earliest = data.date_range.earliest ? new Date(data.date_range.earliest).toLocaleDateString() : '—';
  const latest = data.date_range.latest ? new Date(data.date_range.latest).toLocaleDateString() : '—';
  if (earliest !== '—' && latest !== '—') {
    // Calculate days span
    const daySpan = Math.round((new Date(data.date_range.latest) - new Date(data.date_range.earliest)) / (1000 * 60 * 60 * 24));
    document.getElementById('exploreDateRange').textContent = `${daySpan}d`;
    document.getElementById('exploreDateSub').textContent = `${earliest} — ${latest}`;
  } else {
    document.getElementById('exploreDateRange').textContent = '—';
    document.getElementById('exploreDateSub').textContent = 'No data yet';
  }

  // Data quality score
  const qualityScore = data.completeness_score;
  const qualityEl = document.getElementById('exploreQualityScore');
  qualityEl.textContent = qualityScore + '%';
  qualityEl.className = 'metric-value ' + (qualityScore >= 80 ? 'low' : qualityScore >= 50 ? 'medium' : 'high');

  // Review rate
  const totalOutcomes = data.outcome_breakdown.confirmed_fraud + data.outcome_breakdown.false_positive + data.outcome_breakdown.under_review;
  const reviewRate = totalRecords > 0 ? Math.round(totalOutcomes / totalRecords * 100) : 0;
  document.getElementById('exploreReviewRate').textContent = reviewRate + '%';
  document.getElementById('exploreReviewSub').textContent =
    `${fmt(totalOutcomes)} reviewed of ${fmt(totalRecords)}`;
}

async function loadExploreCompleteness() {
  const res = await api('/api/explore/completeness');
  const wrap = document.getElementById('exploreCompletenessWrap');

  if (res.error) {
    wrap.innerHTML = errorState('Failed to load', res.error, 'loadExploreCompleteness()');
    return;
  }

  const { fields, total_records } = res.data;
  document.getElementById('exploreCompletenessSubtitle').textContent = `${fmt(total_records)} total records`;

  if (!fields || fields.length === 0) {
    wrap.innerHTML = emptyState('📊', 'No data', 'Run fraud analysis to generate data');
    return;
  }

  let html = '<div class="completeness-bar-container">';

  for (const field of fields) {
    html += `
      <div class="completeness-row">
        <span class="completeness-label">${field.label}</span>
        <div class="completeness-bar-wrap">
          <div class="completeness-bar ${field.quality}" style="width:${field.percent_complete}%"></div>
        </div>
        <span class="completeness-pct">${field.percent_complete}%</span>
      </div>
    `;
  }

  html += '</div>';
  wrap.innerHTML = html;
}

async function loadExploreDistribution() {
  const field = document.getElementById('exploreDistField').value;
  const res = await api(`/api/explore/distributions?field=${field}`);

  const chartEl = document.getElementById('exploreDistChart');
  const statsEl = document.getElementById('exploreDistStats');

  if (res.error) {
    chartEl.innerHTML = `<div class="empty-state"><p>${res.error}</p></div>`;
    return;
  }

  const data = res.data;

  if (data.type === 'numeric') {
    const histogram = data.histogram || [];
    chartEl.innerHTML = '';
    const barColors = histogram.map(h => {
      if (field === 'risk_score') {
        const mid = (h.bin_start + h.bin_end) / 2;
        if (mid >= 50) return 'rgba(220, 38, 38, 0.8)';
        if (mid >= 25) return 'rgba(217, 119, 6, 0.8)';
        return 'rgba(5, 150, 105, 0.8)';
      }
      return 'rgba(37, 99, 235, 0.7)';
    });
    renderApexChart('exploreDistChart', 'bar', {
      series: [{ name: 'Count', data: histogram.map(h => h.count) }],
      categories: histogram.map(h => h.label)
    }, {
      height: 320,
      colors: barColors,
      plotOptions: { bar: { distributed: true, borderRadius: 2 } },
      xaxis: { title: { text: field === 'risk_score' ? 'Risk Score' : 'Value' }, labels: { rotate: -45 } },
      yaxis: { title: { text: 'Count' } },
      legend: { show: false }
    });

    // Stats
    const stats = data.stats;
    document.getElementById('exploreStatMin').textContent = field === 'payout_amount' ? fmtCur(stats.min) : fmt(stats.min);
    document.getElementById('exploreStatMax').textContent = field === 'payout_amount' ? fmtCur(stats.max) : fmt(stats.max);
    document.getElementById('exploreStatMean').textContent = field === 'payout_amount' ? fmtCur(stats.mean) : stats.mean;
    document.getElementById('exploreStatMedian').textContent = field === 'payout_amount' ? fmtCur(stats.median) : stats.median;
    document.getElementById('exploreStatStd').textContent = field === 'payout_amount' ? fmtCur(stats.std) : stats.std;
    document.getElementById('exploreStatCount').textContent = fmt(stats.count);
    statsEl.style.display = 'grid';

  } else {
    const categories = data.categories || [];
    chartEl.innerHTML = '';
    const catColors = ['#2563eb', '#7c3aed', '#059669', '#d97706', '#dc2626', '#6366f1', '#14b8a6', '#f59e0b', '#ef4444', '#8b5cf6'];
    renderApexChart('exploreDistChart', 'donut', {
      labels: categories.map(c => c.value),
      values: categories.map(c => c.count)
    }, {
      height: 320,
      colors: categories.map((_, i) => catColors[i % catColors.length]),
      legend: { show: false },
      plotOptions: { pie: { donut: { size: '55%' } } },
      dataLabels: { enabled: true }
    });

    // Hide numeric stats for categorical
    document.getElementById('exploreStatMin').textContent = '—';
    document.getElementById('exploreStatMax').textContent = '—';
    document.getElementById('exploreStatMean').textContent = '—';
    document.getElementById('exploreStatMedian').textContent = '—';
    document.getElementById('exploreStatStd').textContent = '—';
    document.getElementById('exploreStatCount').textContent = fmt(data.total);
  }
}

async function loadExploreCorrelations() {
  const res = await api('/api/explore/correlations');

  const chartEl = document.getElementById('exploreCorrelationChart');
  const riskBinEl = document.getElementById('exploreRiskBinChart');
  const tableEl = document.getElementById('exploreCorrelationTable');

  if (res.error) {
    chartEl.innerHTML = `<div class="empty-state" style="padding:40px;"><p>Error: ${res.error}</p></div>`;
    return;
  }

  const data = res.data;

  if (data.total_reviewed === 0) {
    chartEl.innerHTML = `<div class="empty-state" style="padding:40px;"><p>No reviewed outcomes yet. Mark accounts as confirmed fraud or false positive to see correlations.</p></div>`;
    riskBinEl.innerHTML = '';
    tableEl.innerHTML = '';
    document.getElementById('exploreCorrelationSub').textContent = '0 outcomes reviewed';
    return;
  }

  document.getElementById('exploreCorrelationSub').textContent = `${fmt(data.total_reviewed)} outcomes reviewed`;

  // Flag effectiveness horizontal bar chart
  const flagData = data.flag_effectiveness.slice(0, 10);

  if (flagData.length > 0) {
    chartEl.innerHTML = '';
    renderApexChart('exploreCorrelationChart', 'bar', {
      series: [{ name: 'Precision %', data: flagData.map(f => f.precision) }],
      categories: flagData.map(f => truncate(f.flag, 20))
    }, {
      height: Math.max(280, flagData.length * 36),
      plotOptions: {
        bar: { horizontal: true, distributed: true, borderRadius: 2, dataLabels: { position: 'right' } }
      },
      colors: flagData.map(f => {
        if (f.precision >= 70) return 'rgba(5, 150, 105, 0.8)';
        if (f.precision >= 40) return 'rgba(217, 119, 6, 0.8)';
        return 'rgba(220, 38, 38, 0.8)';
      }),
      xaxis: { max: 105, title: { text: 'Precision %' } },
      dataLabels: { enabled: true, formatter: (v) => (v != null ? v + '%' : '') },
      legend: { show: false }
    });
  } else {
    chartEl.innerHTML = `<div class="empty-state" style="padding:40px;"><p>Not enough flag data</p></div>`;
  }

  const riskBins = data.risk_bin_fraud_rate || [];

  if (riskBins.length > 0) {
    riskBinEl.innerHTML = '';
    renderApexChart('exploreRiskBinChart', 'bar', {
      series: [{ name: 'Fraud rate', data: riskBins.map(r => r.fraud_rate) }],
      categories: riskBins.map(r => r.bin)
    }, {
      height: 320,
      colors: riskBins.map(r => {
        if (r.fraud_rate >= 70) return 'rgba(220, 38, 38, 0.8)';
        if (r.fraud_rate >= 40) return 'rgba(217, 119, 6, 0.8)';
        return 'rgba(5, 150, 105, 0.8)';
      }),
      plotOptions: { bar: { distributed: true, dataLabels: { position: 'top' } } },
      dataLabels: { enabled: true, formatter: (v) => (v != null ? v + '%' : '') },
      xaxis: { title: { text: 'Risk Score Bin' }, labels: { rotate: -30 } },
      yaxis: {
        max: Math.max(100, ...riskBins.map(r => r.fraud_rate + 10)),
        title: { text: 'Fraud Rate %' }
      },
      legend: { show: false }
    });
  } else {
    riskBinEl.innerHTML = '';
  }

  // Table of flag effectiveness
  if (flagData.length > 0) {
    let tableHtml = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Flag</th>
            <th>Total Flagged</th>
            <th>Confirmed Fraud</th>
            <th>False Positives</th>
            <th>Precision</th>
            <th>Strength</th>
          </tr>
        </thead>
        <tbody>
    `;

    for (const flag of flagData) {
      const strengthClass = flag.strength === 'strong' ? 'low' : flag.strength === 'moderate' ? 'medium' : 'high';
      tableHtml += `
        <tr>
          <td><span class="mono">${flag.flag}</span></td>
          <td>${fmt(flag.total_flagged)}</td>
          <td>${fmt(flag.confirmed_fraud)}</td>
          <td>${fmt(flag.false_positives)}</td>
          <td><span class="risk-badge ${strengthClass}">${flag.precision}%</span></td>
          <td style="text-transform:capitalize">${flag.strength}</td>
        </tr>
      `;
    }

    tableHtml += '</tbody></table>';
    tableEl.innerHTML = tableHtml;
  } else {
    tableEl.innerHTML = '';
  }
}

async function runExploreOutlierDetection() {
  const btn = document.getElementById('exploreOutlierBtn');
  const wrap = document.getElementById('exploreOutliersWrap');

  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span> Detecting...';
  wrap.innerHTML = '<div class="loading-spinner">Analyzing data for outliers...</div>';

  const res = await api('/api/explore/outliers');

  btn.disabled = false;
  btn.innerHTML = '<span class="btn-icon">🔍</span> Detect Outliers';

  if (res.error) {
    wrap.innerHTML = errorState('Detection Failed', res.error, 'runExploreOutlierDetection()');
    return;
  }

  const data = res.data;

  let html = '<div class="outlier-categories">';

  // Payout outliers
  html += `
    <div class="outlier-category">
      <h4>💰 Unusual Payouts <span class="count-badge">${data.payout_outliers?.length || 0}</span></h4>
      <div class="outlier-list">
  `;

  if (data.payout_outliers && data.payout_outliers.length > 0) {
    for (const item of data.payout_outliers) {
      html += `
        <div class="outlier-item" onclick="openAccountModal('${item.duid}')">
          <div class="outlier-main">
            <span class="outlier-primary">${truncate(item.email, 25)}</span>
            <span class="outlier-secondary">${item.affiliate || '—'}</span>
          </div>
          <span class="outlier-value">${fmtCur(item.payout_amount)}</span>
        </div>
      `;
    }
  } else {
    html += '<div style="color:var(--text-muted);font-size:11px;padding:8px;">No payout outliers detected</div>';
  }

  html += '</div></div>';

  // Unusual affiliates
  html += `
    <div class="outlier-category">
      <h4>🚨 High-Risk Affiliates <span class="count-badge">${data.unusual_affiliates?.length || 0}</span></h4>
      <div class="outlier-list">
  `;

  if (data.unusual_affiliates && data.unusual_affiliates.length > 0) {
    for (const item of data.unusual_affiliates) {
      html += `
        <div class="outlier-item" onclick="switchTab('affiliates'); setTimeout(() => document.querySelector('[data-code=\\'${item.affiliate}\\']')?.click(), 100)">
          <div class="outlier-main">
            <span class="outlier-primary">${item.affiliate}</span>
            <span class="outlier-secondary">${item.total_accounts} accounts · avg ${item.avg_risk} risk</span>
          </div>
          <span class="outlier-value">${item.high_risk_pct}%</span>
        </div>
      `;
    }
  } else {
    html += '<div style="color:var(--text-muted);font-size:11px;padding:8px;">No high-risk affiliates detected</div>';
  }

  html += '</div></div>';

  // Flag combinations
  html += `
    <div class="outlier-category">
      <h4>🔗 Suspicious Flag Combos <span class="count-badge">${data.flag_combinations?.length || 0}</span></h4>
      <div class="outlier-list">
  `;

  if (data.flag_combinations && data.flag_combinations.length > 0) {
    for (const item of data.flag_combinations) {
      html += `
        <div class="outlier-item">
          <div class="outlier-main">
            <span class="outlier-primary">${item.combination}</span>
          </div>
          <span class="outlier-value warning">${item.count}x</span>
        </div>
      `;
    }
  } else {
    html += '<div style="color:var(--text-muted);font-size:11px;padding:8px;">No suspicious combinations found</div>';
  }

  html += '</div></div>';

  // Temporal spikes
  html += `
    <div class="outlier-category">
      <h4>📈 Volume Spikes <span class="count-badge">${data.temporal_spikes?.length || 0}</span></h4>
      <div class="outlier-list">
  `;

  if (data.temporal_spikes && data.temporal_spikes.length > 0) {
    for (const item of data.temporal_spikes) {
      html += `
        <div class="outlier-item">
          <div class="outlier-main">
            <span class="outlier-primary">${item.date}</span>
            <span class="outlier-secondary">${item.count} records · ${item.high_risk} high risk</span>
          </div>
          <span class="outlier-value warning">${item.vs_average}</span>
        </div>
      `;
    }
  } else {
    html += '<div style="color:var(--text-muted);font-size:11px;padding:8px;">No volume spikes detected</div>';
  }

  html += '</div></div>';

  html += '</div>';

  wrap.innerHTML = html;
}

// SETTINGS TAB
// ═══════════════════════════════════════════════════════════

let currentSettings = {};

// ═══════════════════════════════════════════════════════════
// PIPELINE SCHEDULER UI
// ═══════════════════════════════════════════════════════════

let _schedPollInterval = null;
const SCHED_HEALTH_DISMISS_KEY = 'fd_sched_health_dismiss';

const PIPELINE_STAGE_LABELS = {
  not_fetched: 'Not fetched',
  partial_fetch: 'Partial fetch',
  partial_source_match: 'Source mismatch',
  needs_mcp_check: 'Needs MCP check',
  fetched: 'Fetched',
  partial_analysis: 'Analyzing…',
  analyzed: 'Analyzed',
};

function formatMatchPct(row) {
  const pct = row.local_match_pct;
  if (pct == null || row.reconciliation_status === 'source_unavailable') {
    return '<span style="color:var(--text-muted)">—</span>';
  }
  const color = pct >= 99.5 ? 'var(--risk-low)' : pct >= 90 ? 'var(--risk-medium)' : 'var(--risk-high)';
  return `<span style="color:${color};font-weight:600">${pct}%</span>`;
}

function renderPipelineDailyStatus(cov) {
  const body = document.getElementById('pipelineDailyBody');
  const summary = document.getElementById('pipelineCoverageSummary');
  if (!body) return;

  const daily = (cov && cov.daily) ? cov.daily.slice().reverse() : [];
  if (!daily.length) {
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No coverage data</td></tr>';
    if (summary) summary.textContent = '';
    return;
  }

  if (summary) {
    const parts = [];
    if (cov.missing_count) parts.push(`${cov.missing_count} missing`);
    if (cov.partial_count) parts.push(`${cov.partial_count} partial`);
    if (cov.mcp_partial_count) parts.push(`${cov.mcp_partial_count} MCP mismatch`);
    if (cov.analysis_backlog_count) parts.push(`${fmt(cov.analysis_backlog_count)} pending analysis`);
    summary.textContent = parts.length ? parts.join(' · ') : 'All days OK';
  }

  body.innerHTML = daily.map(row => {
    const stage = row.pipeline_stage || 'fetched';
    const stageLabel = PIPELINE_STAGE_LABELS[stage] || stage;
    const needsAction = ['not_fetched', 'partial_fetch', 'partial_source_match', 'partial_analysis'].includes(stage);
    const sourceTotal = row.source_expected_total;
    const sourceLabel = sourceTotal != null ? fmt(sourceTotal) : '—';
    const exportUrl = `/api/export/fraud-results?min_risk=50&trans_date_from=${row.day}&trans_date_to=${row.day}&exclude_reviewed=true`;
    const reconBtn = (row.reconciliation_status && row.reconciliation_status !== 'unknown')
      ? `<button type="button" class="pipeline-day-btn" onclick="openReconciliationDrilldown('${row.day}')">Source</button>`
      : '';
    return `<tr>
      <td><code>${row.day}</code></td>
      <td><span class="pipeline-stage ${stage}">${stageLabel}</span></td>
      <td>${sourceLabel}</td>
      <td>${fmt(row.fetched_total || 0)}</td>
      <td>${formatMatchPct(row)}</td>
      <td>${fmt(row.source_analyzed || 0)}${row.analysis_pct != null ? ` <span style="color:var(--text-muted)">(${row.analysis_pct}%)</span>` : ''}</td>
      <td>${fmt(row.pending_analysis || 0)}</td>
      <td>
        <div class="pipeline-day-actions">
          ${needsAction ? `<button type="button" class="pipeline-day-btn" onclick="runPipelineDay('${row.day}')">Run</button>` : ''}
          ${reconBtn}
          <button type="button" class="pipeline-day-btn" onclick="openPipelineDrilldown('${row.day}')">Review</button>
          <a class="pipeline-day-btn" href="${exportUrl}" download>Export</a>
        </div>
      </td>
    </tr>`;
  }).join('');
}

async function openReconciliationDrilldown(day) {
  const panel = document.getElementById('reconciliationDrilldownPanel');
  const wrap = document.getElementById('reconciliationDrilldownWrap');
  const title = document.getElementById('reconciliationDrilldownTitle');
  const sub = document.getElementById('reconciliationDrilldownSubtitle');
  if (!panel || !wrap) return;
  panel.style.display = '';
  if (title) title.textContent = `Source reconciliation — ${day}`;
  if (sub) sub.textContent = 'Loading affiliate breakdown…';
  wrap.innerHTML = '<div class="loading-spinner">Loading…</div>';
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const res = await api(`/api/scheduler/reconciliation/day/${encodeURIComponent(day)}`);
  if (res.error) {
    wrap.innerHTML = errorState('Failed to load reconciliation', res.error);
    return;
  }
  const data = res.data || {};
  if (data.source_unavailable) {
    if (sub) sub.textContent = 'MCP/Elasticsearch not configured or unreachable';
    wrap.innerHTML = emptyState('◇', 'Source unavailable', 'Set scheduler.mcp_reconciliation.mcp_url (and CAMSODA_MCP_AUTH) or elasticsearch_url in config to enable PS7 reconciliation.');
    return;
  }
  const affiliates = data.affiliates || [];
  const partial = data.partial_count || 0;
  if (sub) sub.textContent = `${affiliates.length} affiliates · ${partial} below match threshold`;

  const rows = affiliates.filter(a => a.status !== 'complete').slice(0, 100);
  if (!rows.length) {
    wrap.innerHTML = emptyState('✓', 'Source match OK', 'All affiliates are within the configured match threshold.');
    return;
  }
  wrap.innerHTML = buildTable('reconAff', [
    { key: 'affiliate', label: 'Affiliate', render: v => `<span class="mono">${escapeHtml(String(v))}</span>` },
    { key: 'expected_total', label: 'Expected', numeric: true, right: true },
    { key: 'local_total', label: 'Local', numeric: true, right: true },
    { key: 'match_pct', label: 'Match', numeric: true, right: true, render: v => v != null ? `${v}%` : '—' },
    { key: 'missing_estimate', label: 'Missing', numeric: true, right: true },
    { key: 'status', label: 'Status', render: v => `<span class="pipeline-stage ${v === 'complete' ? 'analyzed' : 'partial_source_match'}">${escapeHtml(String(v))}</span>` },
  ], rows, { emptyIcon: '◇', emptyTitle: 'No mismatches' });
}

function closeReconciliationDrilldown() {
  const panel = document.getElementById('reconciliationDrilldownPanel');
  if (panel) panel.style.display = 'none';
}

async function runPipelineDay(day) {
  const res = await api('/api/scheduler/run-day', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day }),
  });
  if (res.error) {
    showToast(res.error, 'error');
    return;
  }
  showToast(`Pipeline started for ${day}`, 'success');
  loadSchedulerStatus();
}

async function openPipelineDrilldown(day) {
  const res = await api(`/api/analysis/review-queue?trans_date=${encodeURIComponent(day)}&min_risk=50&limit=200`);
  const n = (res.data && res.data.total) ? res.data.total : 0;
  if (n > 0) {
    showToast(`${n} high-risk account${n === 1 ? '' : 's'} pending review for ${day}`, 'info');
  } else {
    showToast(`No pending high-risk reviews for ${day}`, 'success');
  }
}

function updateSchedulerHealthBanner(d) {
  const b = document.getElementById('schedulerHealthBanner');
  const t = document.getElementById('schedulerHealthText');
  if (!b || !t) return;
  if (sessionStorage.getItem(SCHED_HEALTH_DISMISS_KEY) === '1') {
    b.style.display = 'none';
    return;
  }
  const h = d.scheduled_health || {};
  const cov = d.coverage_health || {};
  const vpn = d.vpn_wait || {};
  let msg = '';
  if (h.stale && h.message) {
    msg = h.message;
  } else if (cov.degraded && cov.message) {
    msg = cov.message;
  } else if (vpn.status === 'waiting') {
    msg = `Waiting for VPN/API (${vpn.seconds_remaining ?? '?'}s remaining)…`;
  } else if (vpn.status === 'timeout') {
    msg = 'VPN/API not ready — connect VPN; automatic retry is scheduled.';
  }
  if (msg) {
    b.style.display = 'flex';
    t.textContent = msg;
  } else {
    b.style.display = 'none';
  }
}

async function loadSchedulerStatus() {
  const [res, covRes] = await Promise.all([
    api('/api/scheduler/status'),
    api('/api/scheduler/coverage'),
  ]);
  if (res.error || !res.data) return;
  const d = res.data;
  if (covRes.data) {
    renderPipelineDailyStatus(covRes.data);
    d.coverage_health = covRes.data;
  }

  // Status bar
  const dot   = document.getElementById('pipelineDot');
  const label = document.getElementById('pipelineStatusLabel');
  const next  = document.getElementById('pipelineNextRun');

  const cur = d.current_run || {};
  if (cur.status === 'running') {
    dot.className   = 'psb-dot running';
    label.textContent = `Pipeline running — ${cur.step || '…'}`;
    if (next) next.textContent = `Run ID: ${cur.run_id || ''}`;
    showPipelineProgress(cur);
    // Poll until done
    if (!_schedPollInterval) {
      _schedPollInterval = setInterval(loadSchedulerStatus, 2000);
    }
  } else {
    clearInterval(_schedPollInterval);
    _schedPollInterval = null;

    // Show completed/failed card if we have a recent result
    if (cur.status === 'completed' || cur.status === 'failed') {
      showPipelineProgress(cur);
      loadSchedulerHistory(); // refresh history table
    }

    if (!d.scheduler_available) {
      dot.className   = 'psb-dot disabled';
      label.innerHTML = 'APScheduler not installed — <code style="font-size:11px">pip install apscheduler</code>';
    } else if (!d.enabled) {
      dot.className   = 'psb-dot disabled';
      label.textContent = 'Scheduled pipeline: disabled';
    } else {
      dot.className   = 'psb-dot ok';
      label.textContent = 'Scheduled pipeline: active';
    }

    if (d.next_run && next) {
      const dt = new Date(d.next_run);
      next.textContent = `Next: ${dt.toLocaleString()} UTC`;
    } else if (next) {
      next.textContent = '';
    }

    // Restore run button
    const btn = document.getElementById('pipelineRunBtn');
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run Pipeline Now'; }
  }

  // Populate config form
  document.getElementById('schedEnabled').checked     = !!d.enabled;
  document.getElementById('schedHour').value          = d.hour ?? 14;
  document.getElementById('schedMinute').value        = d.minute ?? 0;
  document.getElementById('schedDaysBack').value      = d.days_back ?? 1;
  updateSchedPreview();

  // Last run banner
  if (d.last_run && label && cur.status !== 'running') {
    const lr = d.last_run;
    const ago = lr.completed_at
      ? ` (${timeSince(lr.completed_at)} ago)`
      : '';
    const statusClass = lr.status === 'completed' ? 'color:var(--risk-low)' : 'color:var(--risk-high)';
    label.innerHTML += `<span style="font-size:11px;margin-left:12px;${statusClass}">
      Last run: ${lr.status}${ago} — ${fmt(lr.records_analyzed)} analyzed, ${fmt(lr.high_risk_found)} high-risk
    </span>`;
  }

  updateSchedulerHealthBanner(d);

  const sc = document.getElementById('schedStartupCatchup');
  if (sc) sc.checked = d.startup_catchup !== false;
  const cse = document.getElementById('schedCatchupSkipEnrich');
  if (cse) cse.checked = d.catchup_skip_enrichment !== false;
  const ccd = document.getElementById('schedCatchupChunkDays');
  if (ccd) ccd.checked = d.catchup_chunk_days !== false;
  const nm = document.getElementById('schedNotifyMacos');
  if (nm) nm.checked = d.notify_macos !== false;

  const eap = document.getElementById('schedEnrichAfterPipeline');
  if (eap) eap.checked = d.enrich_after_pipeline !== false;
  const efl = document.getElementById('schedEnrichFreshLimit');
  if (efl && d.enrich_fresh_limit != null) efl.value = String(d.enrich_fresh_limit);
  const eld = document.getElementById('schedEnrichLookbackDays');
  if (eld && d.enrich_lookback_days != null) eld.value = String(d.enrich_lookback_days);
  const ema = document.getElementById('schedEnrichMaxAttempts');
  if (ema && d.enrich_max_transient_attempts != null) ema.value = String(d.enrich_max_transient_attempts);
  const ehc = document.getElementById('schedEnrichHealthCheck');
  if (ehc) ehc.checked = d.enrich_health_check !== false;
  const eb = d.enrich_backlog || {};
  const ebe = document.getElementById('schedEnrichBacklogEnabled');
  if (ebe) ebe.checked = eb.enabled !== false;
  const ebi = document.getElementById('schedEnrichBacklogInterval');
  if (ebi && eb.interval_minutes != null) ebi.value = String(eb.interval_minutes);
  const ebb = document.getElementById('schedEnrichBacklogBatch');
  if (ebb && eb.batch_limit != null) ebb.value = String(eb.batch_limit);
  const ebt = document.getElementById('schedEnrichBacklogThrottle');
  if (ebt && eb.throttle_seconds != null) ebt.value = String(eb.throttle_seconds);
  const ebs = document.getElementById('schedEnrichBacklogStatus');
  if (ebs) {
    const bc = d.enrichment_backlog_count;
    const nr = d.enrich_backlog_next;
    const last = d.enrich_backlog_last || {};
    let lines = [];
    if (bc != null) lines.push(`Backlog: ${fmt(bc)} unenriched`);
    if (nr) {
      try {
        lines.push(`Next drainer: ${new Date(nr).toLocaleString()} (local)`);
      } catch (_) {
        lines.push(`Next drainer: ${nr}`);
      }
    } else if (ebe && !ebe.checked) {
      lines.push('Backlog drainer: off');
    } else if (!d.scheduler_running) {
      lines.push('Scheduler not running — drainer inactive');
    } else {
      lines.push('Next drainer: — (save settings or restart app after installing APScheduler)');
    }
    if (last.completed_at) {
      const le = last.enriched != null ? `, enriched ${fmt(last.enriched)}` : '';
      const uu = last.unavailable != null ? `, closed ${fmt(last.unavailable)}` : '';
      const er = last.errors != null ? `, errors ${fmt(last.errors)}` : '';
      lines.push(`Last drainer: ${timeSince(last.completed_at)} ago${le}${uu}${er}`);
    }
    ebs.innerHTML = lines.map(l => `<span style="display:block">${l}</span>`).join('');
  }

  const ch = document.getElementById('catchupHint');
  const cb = document.getElementById('catchupRunBtn');
  if (d.catchup_suggestion && ch) {
    const s = d.catchup_suggestion;
    ch.textContent = s.message || (s.error ? String(s.error) : '');
    if (cb) {
      if (cur.status === 'running') {
        cb.disabled = true;
        cb.textContent = '⏳ Pipeline running…';
        cb.title = '';
      } else {
        const can = (s.days_back | 0) > 0;
        cb.disabled = !can;
        cb.textContent = '▶ Run suggested catch-up';
        cb.title = can ? '' : 'No gap to recover (or adjust thresholds in config)';
      }
    }
  }
  if (ch && d.coverage_health?.degraded && d.coverage_health.message) {
    const extra = d.coverage_health.message;
    ch.textContent = ch.textContent ? `${ch.textContent} · ${extra}` : extra;
  }
  if (ch && d.analysis_backlog_count > 0) {
    const ab = `Analysis backlog: ${fmt(d.analysis_backlog_count)} rows`;
    ch.textContent = ch.textContent ? `${ch.textContent} · ${ab}` : ab;
  }
}

function showPipelineProgress(cur) {
  const el = document.getElementById('pipelineRunProgress');
  if (!el) return;
  el.style.display = '';

  const isRunning   = cur.status === 'running';
  const isCompleted = cur.status === 'completed';
  const isFailed    = cur.status === 'failed';

  document.getElementById('prcRunning').style.display   = isRunning   ? '' : 'none';
  document.getElementById('prcCompleted').style.display = isCompleted ? '' : 'none';
  document.getElementById('prcFailed').style.display    = isFailed    ? '' : 'none';

  if (isRunning) {
    document.getElementById('pipelineRunStep').textContent      = cur.step || 'Running…';
    document.getElementById('pipelineRunId').textContent        = cur.run_id ? `#${cur.run_id}` : '';
    document.getElementById('pipelineProgressFill').style.width = `${cur.progress || 0}%`;
    document.getElementById('pipelineRunPct').textContent       = `${cur.progress || 0}%`;

    // Elapsed timer
    if (cur.started && !_pipelineTimerInterval) {
      _pipelineStartTime = new Date(cur.started);
      _pipelineTimerInterval = setInterval(() => {
        const secs = Math.floor((Date.now() - _pipelineStartTime) / 1000);
        const el = document.getElementById('pipelineElapsed');
        if (el) el.textContent = secs >= 60 ? `${Math.floor(secs/60)}m ${secs%60}s` : `${secs}s`;
      }, 1000);
    }

    // Sub-step detail
    const stepEl = document.getElementById('prcStepDetail');
    if (stepEl) stepEl.textContent = cur.date_range ? `Range: ${cur.date_range}` : '';
    const fetchEl = document.getElementById('prcFetched');
    if (fetchEl) fetchEl.textContent = cur.records_fetched > 0 ? `${fmt(cur.records_fetched)} fetched` : '';
  }

  if (isCompleted) {
    _clearPipelineTimer();
    const duration = cur.duration_s != null
      ? (cur.duration_s >= 60 ? `${Math.floor(cur.duration_s/60)}m ${Math.round(cur.duration_s%60)}s` : `${Math.round(cur.duration_s)}s`)
      : '';
    const ago = cur.completed ? timeSince(cur.completed) + ' ago' : '';
    document.getElementById('prcCompletedMeta').textContent =
      [ago, duration ? `took ${duration}` : '', cur.date_range || ''].filter(Boolean).join(' · ');
    document.getElementById('prcStatFetched').textContent   = fmt(cur.records_fetched  ?? 0);
    document.getElementById('prcStatAnalyzed').textContent  = fmt(cur.records_analyzed ?? 0);
    document.getElementById('prcStatHighRisk').textContent  = fmt(cur.high_risk_found  ?? 0);
  }

  if (isFailed) {
    _clearPipelineTimer();
    document.getElementById('prcErrorMsg').textContent = cur.error || cur.step || 'Unknown error';
  }
}

function _clearPipelineTimer() {
  if (_pipelineTimerInterval) {
    clearInterval(_pipelineTimerInterval);
    _pipelineTimerInterval = null;
  }
}

function hidePipelineProgress() {
  // Don't hide — leave completed/failed result visible until next run starts
}

let _pipelineTimerInterval = null;
let _pipelineStartTime     = null;

function updateSchedPreview() {
  const h = String(document.getElementById('schedHour')?.value || 2).padStart(2,'0');
  const m = String(document.getElementById('schedMinute')?.value || 0).padStart(2,'0');
  const d = document.getElementById('schedDaysBack')?.value || 1;
  const el = document.getElementById('schedPreview');
  if (el) el.textContent = `Preview: daily at ${h}:${m} UTC, fetching last ${d} day(s)`;
}

// Wire up live preview on input
['schedHour','schedMinute','schedDaysBack'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', updateSchedPreview);
});

async function saveScheduleConfig() {
  const enabled   = document.getElementById('schedEnabled').checked;
  const hour      = parseInt(document.getElementById('schedHour').value);
  const minute    = parseInt(document.getElementById('schedMinute').value);
  const days_back = parseInt(document.getElementById('schedDaysBack').value);
  const startup_catchup = document.getElementById('schedStartupCatchup')?.checked !== false;
  const catchup_skip_enrichment = document.getElementById('schedCatchupSkipEnrich')?.checked !== false;
  const catchup_chunk_days = document.getElementById('schedCatchupChunkDays')?.checked !== false;
  const notify_macos    = document.getElementById('schedNotifyMacos')?.checked !== false;
  const enrich_after_pipeline = document.getElementById('schedEnrichAfterPipeline')?.checked !== false;
  const enrich_fresh_limit = parseInt(document.getElementById('schedEnrichFreshLimit')?.value ?? '500', 10);
  const enrich_lookback_days = parseInt(document.getElementById('schedEnrichLookbackDays')?.value ?? '90', 10);
  const enrich_max_transient_attempts = parseInt(document.getElementById('schedEnrichMaxAttempts')?.value ?? '5', 10);
  const enrich_health_check = document.getElementById('schedEnrichHealthCheck')?.checked !== false;
  const enrich_backlog = {
    enabled: document.getElementById('schedEnrichBacklogEnabled')?.checked !== false,
    interval_minutes: parseInt(document.getElementById('schedEnrichBacklogInterval')?.value ?? '15', 10),
    batch_limit: parseInt(document.getElementById('schedEnrichBacklogBatch')?.value ?? '2000', 10),
    throttle_seconds: parseFloat(document.getElementById('schedEnrichBacklogThrottle')?.value ?? '0.25'),
  };

  try {
    const r = await fetch('/api/scheduler/configure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled, hour, minute, days_back,
        startup_catchup,
        catchup_skip_enrichment,
        catchup_chunk_days,
        notify_macos,
        enrich_after_pipeline,
        enrich_fresh_limit,
        enrich_lookback_days,
        enrich_max_transient_attempts,
        enrich_health_check,
        enrich_backlog,
      }),
    });
    const json = await r.json();
    if (!r.ok || json.error) throw new Error(json.error || `HTTP ${r.status}`);
    showToast(enabled
      ? `Schedule saved: daily at ${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')} UTC`
      : 'Scheduled pipeline disabled', 'success');
    loadSchedulerStatus();
  } catch (e) {
    showToast(`Failed: ${e.message}`, 'error');
  }
}

async function triggerPipelineRun() {
  const btn      = document.getElementById('pipelineRunBtn');
  const days_back = parseInt(document.getElementById('manualDaysBack').value) || 1;

  btn.disabled    = true;
  btn.textContent = '⏳ Starting…';

  try {
    const r = await fetch('/api/scheduler/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days_back }),
    });
    const json = await r.json();
    if (!r.ok || json.error) throw new Error(json.error || `HTTP ${r.status}`);
    showToast(`Pipeline started — last ${days_back} day(s)`, 'success');
    // Start polling immediately
    setTimeout(loadSchedulerStatus, 800);
  } catch (e) {
    showToast(`Failed: ${e.message}`, 'error');
    btn.disabled    = false;
    btn.textContent = '▶ Run Pipeline Now';
  }
}

async function triggerSuggestedCatchup() {
  const btn = document.getElementById('catchupRunBtn');
  if (btn?.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Starting…';
  }
  try {
    const r = await fetch('/api/scheduler/run-catchup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_suggestion: true }),
    });
    const json = await r.json();
    if (!r.ok || json.error) throw new Error(json.error || `HTTP ${r.status}`);
    const chunkNote = json.chunked ? ' (day-by-day)' : '';
    showToast(`Catch-up started — ${json.days_back} day(s) lookback${chunkNote}`, 'success');
    setTimeout(loadSchedulerStatus, 800);
  } catch (e) {
    showToast(e.message || 'Catch-up failed', 'error');
    if (btn) btn.disabled = false;
  } finally {
    if (btn) {
      btn.textContent = '▶ Run suggested catch-up';
      setTimeout(loadSchedulerStatus, 400);
    }
  }
}

async function loadSchedulerHistory() {
  const res = await api('/api/scheduler/history?limit=25');
  const wrap = document.getElementById('pipelineHistoryWrap');
  if (!wrap) return;
  if (res.error || !res.data || res.data.length === 0) {
    wrap.innerHTML = emptyState('⏱', 'No pipeline runs yet', 'Click "Run Pipeline Now" or enable the schedule.');
    return;
  }

  wrap.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>Run ID</th><th>Type</th><th>Status</th>
        <th>Started</th><th style="text-align:right">Fetched</th>
        <th style="text-align:right">Analyzed</th>
        <th style="text-align:right">High Risk</th>
        <th style="text-align:right">Duration</th>
        <th>Date Range</th>
      </tr></thead>
      <tbody>
        ${res.data.map(r => {
          const startStr = r.started_at ? new Date(r.started_at).toLocaleString() : '—';
          const dur = r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '—';
          const errorCell = r.error_message
            ? `<tr><td colspan="9" style="padding:4px 16px 8px;font-size:11px;color:var(--risk-high)">${r.error_message}</td></tr>`
            : '';
          return `
            <tr title="${r.error_message || ''}">
              <td><code style="font-size:11px">${r.run_id}</code></td>
              <td><span class="run-badge ${r.run_type || 'manual'}">${r.run_type || 'manual'}</span></td>
              <td><span class="run-badge ${r.status || 'unknown'}">${r.status || '—'}</span></td>
              <td style="font-size:11px;color:var(--text-muted)">${startStr}</td>
              <td style="text-align:right">${fmt(r.records_fetched)}</td>
              <td style="text-align:right">${fmt(r.records_analyzed)}</td>
              <td style="text-align:right;color:var(--risk-high)">${fmt(r.high_risk_found)}</td>
              <td style="text-align:right;font-family:var(--mono);font-size:11px">${dur}</td>
              <td style="font-size:11px;color:var(--text-muted)">
                ${r.date_range_start || '—'} → ${r.date_range_end || '—'}
              </td>
            </tr>${errorCell}`;
        }).join('')}
      </tbody>
    </table>`;
}

// Helper: human-readable time since
function timeSince(isoStr) {
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 60)    return `${Math.round(diff)}s`;
  if (diff < 3600)  return `${Math.round(diff/60)}m`;
  if (diff < 86400) return `${Math.round(diff/3600)}h`;
  return `${Math.round(diff/86400)}d`;
}

async function testAdminApi() {
  const btn = document.getElementById('btnTestAdminApi');
  const result = document.getElementById('adminApiTestResult');
  if (!btn || btn.disabled) return;

  btn.disabled = true;
  btn.textContent = 'Testing…';
  result.textContent = '';
  result.style.color = '';

  try {
    const res = await fetch('/api/admin-api/test');
    const data = await res.json();
    if (data.ok) {
      result.textContent = '✓ ' + (data.message || 'Connected');
      result.style.color = '#22c55e';
    } else {
      result.textContent = '✗ ' + (data.message || 'Failed');
      result.style.color = '#ef4444';
    }
  } catch (e) {
    result.textContent = '✗ Request failed: ' + e.message;
    result.style.color = '#ef4444';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

async function loadSettings() {
  const res = await api('/api/settings');
  
  if (res.error) {
    showToast('Failed to load settings: ' + res.error, 'error');
    return;
  }
  
  currentSettings = res.data || {};
  
  // Risk score settings
  const riskScores = currentSettings.risk_scores || {};
  const riskScoreHtml = Object.entries(riskScores).map(([key, value]) => `
    <div class="form-row" style="margin-bottom:8px;">
      <label class="form-label" style="flex:2;margin:0;line-height:32px;">${key.replace(/_/g, ' ')}</label>
      <input type="number" class="form-input" style="flex:1;max-width:80px;" data-risk-key="${key}" value="${value}" min="0" max="100">
    </div>
  `).join('');
  document.getElementById('riskScoreSettings').innerHTML = riskScoreHtml || '<p class="text-muted">No risk scores configured</p>';
  
  // Threshold settings
  const thresholds = currentSettings.thresholds || {};
  document.getElementById('thresholdSettings').innerHTML = `
    <div class="form-row" style="margin-bottom:8px;">
      <label class="form-label" style="flex:2;margin:0;line-height:32px;">High Risk Threshold</label>
      <input type="number" class="form-input" style="flex:1;max-width:80px;" id="settingHighThreshold" value="${thresholds.high_risk_threshold || 50}" min="0" max="100">
    </div>
    <div class="form-row" style="margin-bottom:8px;">
      <label class="form-label" style="flex:2;margin:0;line-height:32px;">Medium Risk Threshold</label>
      <input type="number" class="form-input" style="flex:1;max-width:80px;" id="settingMedThreshold" value="${thresholds.medium_risk_threshold || 25}" min="0" max="100">
    </div>
  `;
  
  // Suspicious names
  const suspiciousNames = currentSettings.suspicious_names || [];
  document.getElementById('suspiciousNamesSettings').innerHTML = `
    <textarea class="form-input" id="settingSuspiciousNames" rows="4" placeholder="One name per line...">${suspiciousNames.join('\n')}</textarea>
  `;

  // QA / internal billing names
  const qaBillingNames = currentSettings.qa_billing_names || [];
  document.getElementById('qaBillingNamesSettings').innerHTML = `
    <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
      These names are excluded from billing clusters. One full name per line (e.g. <code>maxwell ofosu</code>).
    </p>
    <textarea class="form-input" id="settingQaBillingNames" rows="4" placeholder="One full name per line...">${qaBillingNames.join('\n')}</textarea>
  `;

  // Whitelisted affiliates
  const whitelisted = currentSettings.whitelisted_affiliates || [];
  document.getElementById('whitelistedSettings').innerHTML = `
    <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
      Skipped during fraud analysis and hidden from External-only views, including
      <strong>Clusters → Shared cards (admin)</strong> (together with house affiliates).
    </p>
    <textarea class="form-input" id="settingWhitelisted" rows="4" placeholder="One affiliate per line...">${whitelisted.join('\n')}</textarea>
  `;

  // Whitelisted IPs
  const whitelistedIps = currentSettings.whitelisted_ips || [];
  document.getElementById('whitelistedIpsSettings').innerHTML = `
    <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
      IPs listed here are <strong>never</strong> flagged by IP velocity or shared-IP rules.
      Use for QA testers, internal tools, and known-safe infrastructure. One IP per line (IPv4).
    </p>
    <textarea class="form-input" id="settingWhitelistedIps" rows="5"
      placeholder="e.g. 73.167.181.87">${whitelistedIps.join('\n')}</textarea>
  `;

  const whitelistedFps = currentSettings.whitelisted_card_fingerprints || [];
  document.getElementById('whitelistedCardFingerprintsSettings').innerHTML = `
    <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
      Copy <code>card_fingerprint</code> from any test account’s Admin section (shared payment methods).
      Links via these cards are ignored for shared-card risk and the Clusters → Shared cards (admin) list.
      After saving, re-run <strong>Admin enrichment</strong> so stored link counts update.
    </p>
    <textarea class="form-input" id="settingWhitelistedCardFingerprints" rows="4"
      placeholder="One fingerprint per line">${whitelistedFps.join('\n')}</textarea>
  `;

  const whitelistedDuids = currentSettings.whitelisted_duids || [];
  document.getElementById('whitelistedDuidsSettings').innerHTML = `
    <p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
      Quick hide for QA accounts in Shared cards (admin). Does not remove shared-card points until enrichment re-runs with a test-card fingerprint above.
    </p>
    <textarea class="form-input" id="settingWhitelistedDuids" rows="5"
      placeholder="e.g. 384920329">${whitelistedDuids.join('\n')}</textarea>
  `;

  const apiHint = document.getElementById('apiKeySourceHint');
  const apiMasked = document.getElementById('apiKeyMaskedLine');
  const wUrl = document.getElementById('webhookIngestUrl');
  const wHint = document.getElementById('webhookTokenHint');
  if (apiHint) {
    const src = currentSettings.api_key_source || 'none';
    if (src === 'environment') {
      apiHint.textContent = 'Key is loaded from the FRAUD_DETECTION_API_KEY environment variable (overrides file).';
    } else if (src === 'file') {
      apiHint.textContent = 'Key is stored in config.json on the server.';
    } else {
      apiHint.textContent = 'No affiliate API key configured — fetching from the network is disabled.';
    }
  }
  if (apiMasked) {
    apiMasked.textContent = currentSettings.api_key_configured
      ? `Current key (masked): ${currentSettings.api_key_masked || '****'}`
      : '';
  }
  if (wUrl) {
    wUrl.textContent = `${window.location.origin}/api/webhook/ingest`;
  }
  if (wHint) {
    const ws = currentSettings.webhook_token_source || 'none';
    if (ws === 'environment') {
      wHint.textContent = 'Webhook token is set via WEBHOOK_INGEST_TOKEN (env). Clear env to manage in UI.';
    } else if (currentSettings.webhook_ingest_configured) {
      wHint.textContent = `Token active (masked): ${currentSettings.webhook_token_masked || '****'}`;
    } else {
      wHint.textContent = 'No webhook token yet — generate one or set WEBHOOK_INGEST_TOKEN before calling the ingest endpoint.';
    }
  }
  const apiKeyInput = document.getElementById('settingApiKey');
  if (apiKeyInput) apiKeyInput.value = '';
  const whInput = document.getElementById('webhookTokenInput');
  if (whInput) whInput.value = '';

  // Admin platform API status
  const adminHint = document.getElementById('adminApiHint');
  if (adminHint) {
    if (currentSettings.admin_api_configured) {
      adminHint.textContent = `Signed in (${currentSettings.admin_api_username || '***'})`;
      adminHint.style.color = 'var(--risk-low)';
    } else {
      adminHint.textContent = 'Not signed in — use the login prompt or sign in below.';
      adminHint.style.color = 'var(--text-muted)';
    }
    if (currentSettings.scheduler_admin_configured) {
      adminHint.textContent += ' · Scheduler has server admin credentials (env).';
    }
  }
  const adminUserInput = document.getElementById('settingAdminUser');
  const adminPassInput = document.getElementById('settingAdminPass');
  if (adminUserInput) adminUserInput.value = '';
  if (adminPassInput) adminPassInput.value = '';

  loadWebhookActivity();
}

async function saveSettings() {
  // Gather risk scores
  const riskScores = {};
  document.querySelectorAll('[data-risk-key]').forEach(input => {
    riskScores[input.dataset.riskKey] = parseInt(input.value) || 0;
  });
  
  // Gather thresholds
  const thresholds = {
    high_risk_threshold: parseInt(document.getElementById('settingHighThreshold')?.value) || 50,
    medium_risk_threshold: parseInt(document.getElementById('settingMedThreshold')?.value) || 25
  };
  
  // Gather suspicious names
  const suspiciousNames = (document.getElementById('settingSuspiciousNames')?.value || '')
    .split('\n').map(n => n.trim()).filter(n => n);

  // Gather QA billing names
  const qaBillingNames = (document.getElementById('settingQaBillingNames')?.value || '')
    .split('\n').map(n => n.trim()).filter(n => n);

  // Gather whitelisted affiliates
  const whitelisted = parseAffiliateCodeList(document.getElementById('settingWhitelisted')?.value);

  // Gather whitelisted IPs
  const whitelistedIps = (document.getElementById('settingWhitelistedIps')?.value || '')
    .split('\n').map(i => i.trim()).filter(i => i);

  const whitelistedCardFingerprints = (document.getElementById('settingWhitelistedCardFingerprints')?.value || '')
    .split('\n').map(s => s.trim()).filter(Boolean);

  const whitelistedDuids = (document.getElementById('settingWhitelistedDuids')?.value || '')
    .split('\n').map(s => s.trim()).filter(s => /^\d+$/.test(s));

  const newApiKey = (document.getElementById('settingApiKey')?.value || '').trim();
  const payload = {
    risk_scores: riskScores,
    thresholds,
    suspicious_names: suspiciousNames,
    qa_billing_names: qaBillingNames,
    whitelisted_card_fingerprints: whitelistedCardFingerprints,
    whitelisted_duids: whitelistedDuids,
    whitelisted_affiliates: whitelisted,
    whitelisted_ips: whitelistedIps,
  };
  if (newApiKey) payload.api_key = newApiKey;

  const res = await api('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  
  if (res.error) {
    showToast('Failed to save settings: ' + res.error, 'error');
    return;
  }
  
  showToast('Settings saved successfully', 'success');
  loadSettings();
  loadHouseAffiliates();
}

async function runTestEmail() {
  const email = (document.getElementById('testEmailInput')?.value || '').trim();
  const out = document.getElementById('testEmailResult');
  if (!email) {
    showToast('Enter an email address', 'error');
    return;
  }
  const res = await api('/api/test-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (out) {
    out.style.display = 'block';
    if (res.error) {
      out.textContent = res.error;
      return;
    }
    const d = res.data || res;
    out.textContent = JSON.stringify(d, null, 2);
  }
}

async function saveWebhookToken() {
  const tok = (document.getElementById('webhookTokenInput')?.value || '').trim();
  if (!tok) {
    showToast('Paste a token or use Regenerate', 'error');
    return;
  }
  const res = await api('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ webhook_ingest_token: tok }),
  });
  if (res.error) {
    showToast(res.error, 'error');
    return;
  }
  showToast('Webhook token saved', 'success');
  document.getElementById('webhookTokenInput').value = '';
  loadSettings();
}

async function regenerateWebhookToken() {
  if (!confirm('Generate a new webhook token? Existing callers must update their Authorization header.')) return;
  const res = await api('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regenerate_webhook_token: true }),
  });
  if (res.error) {
    showToast(res.error, 'error');
    return;
  }
  const tok = res.data && res.data.webhook_ingest_token;
  await loadSettings();
  const inp = document.getElementById('webhookTokenInput');
  if (tok && inp) {
    inp.value = tok;
    inp.type = 'text';
  }
  showToast('New webhook token generated — copy from the field above; it is also saved to config.', 'success');
}

async function loadWebhookActivity() {
  const wrap = document.getElementById('webhookActivityTable');
  if (!wrap) return;
  const res = await api('/api/webhook/activity?limit=20');
  if (res.error) {
    wrap.innerHTML = `<span style="color:#dc2626;">${escapeHtml(res.error)}</span>`;
    return;
  }
  const events = (res.data && res.data.events) || res.events || [];
  if (!events.length) {
    wrap.textContent = 'No webhook ingests logged yet.';
    return;
  }
  const rows = events.map((e) => {
    const t = e.created_at || '';
    return `<tr><td style="padding:4px 8px;font-family:var(--mono);font-size:11px;">${escapeHtml(String(t))}</td>` +
      `<td style="padding:4px 8px;">f +${e.free_inserted}/${e.free_duplicates} d</td>` +
      `<td style="padding:4px 8px;">p +${e.paid_inserted}/${e.paid_duplicates} d</td>` +
      `<td style="padding:4px 8px;">analyzed ${e.analyzed_count || 0}</td>` +
      `<td style="padding:4px 8px;font-size:11px;">${escapeHtml((e.message || '').slice(0, 80))}</td></tr>`;
  }).join('');
  wrap.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:12px;"><tbody>${rows}</tbody></table>`;
}

function toggleSystemLogs() {
  const body = document.getElementById('systemLogsBody');
  const chev = document.getElementById('systemLogsChevron');
  if (!body) return;
  const open = body.style.display === 'none';
  body.style.display = open ? 'block' : 'none';
  if (chev) chev.textContent = open ? 'Hide' : 'Show';
  if (open) refreshSystemLogs();
}

async function refreshSystemLogs() {
  const pre = document.getElementById('systemLogsOutput');
  if (!pre) return;
  const res = await api('/api/logs?lines=150');
  if (res.error) {
    pre.textContent = res.error;
    return;
  }
  const lines = (res.data && res.data.lines) || res.lines || [];
  pre.textContent = lines.join('\n') || '(empty)';
}

// ═══════════════════════════════════════════════════════════
// CAMPAIGNS TAB
// ═══════════════════════════════════════════════════════════

let _campaignsData = [];
let _campDrillData = [];

async function loadCampaigns() {
  // Load fraud-rate ranking in parallel
  loadCampaignRanking();

  const wrap = document.getElementById('campaignsTableWrap');
  wrap.innerHTML = loading();

  // Hide drill panel
  const drill = document.getElementById('campaign-drill');
  if (drill) drill.style.display = 'none';
  const campMain = document.querySelectorAll('#tab-campaigns > .panel');
  campMain.forEach(p => p.style.display = '');

  const data = await api('/api/campaign-analysis');
  _campaignsData = data?.data?.campaigns || data?.campaigns || [];

  if (_campaignsData.length === 0) {
    wrap.innerHTML = emptyState('📣', 'No campaign data', 'Run fraud analysis on data with campaign information.');
    document.getElementById('campaignCount').textContent = '0 campaigns';
    rawDataCache.camp = [];
    return;
  }

  rawDataCache.camp = [..._campaignsData];
  filterTable('camp', '');
}

function filterCampaignsByAffiliate() {
  const affFilter = (document.getElementById('filterCampAffiliate')?.value || '').trim().toLowerCase();
  if (!affFilter) {
    rawDataCache.camp = [..._campaignsData];
  } else {
    // Filter campaigns where the campaign name or affiliate code contains the query
    rawDataCache.camp = _campaignsData.filter(c =>
      (c.campaign || '').toLowerCase().includes(affFilter) ||
      (c.affiliate || '').toLowerCase().includes(affFilter)
    );
  }
  filterTable('camp', document.getElementById('searchCampaigns')?.value || '');
}

async function drillCampaignByName(campaignName) {
  if (!campaignName) return;

  const drill = document.getElementById('campaign-drill');
  const campMain = document.querySelectorAll('#tab-campaigns > .panel');
  campMain.forEach(p => p.style.display = 'none');
  if (drill) drill.style.display = '';

  document.getElementById('campDrillTitle').textContent = 'Campaign: ' + campaignName;
  document.getElementById('campDrillTableWrap').innerHTML = loading();
  document.getElementById('campDrillCount').textContent = '';

  const res = await api(`/api/campaign/${encodeURIComponent(campaignName)}/accounts`);

  if (res.error) {
    document.getElementById('campDrillTableWrap').innerHTML = errorState('Failed to load campaign accounts', res.error);
    return;
  }

  _campDrillData = res.data || [];
  rawDataCache.campDrill = [..._campDrillData];
  document.getElementById('campDrillCount').textContent = _campDrillData.length + ' accounts';
  filterTable('campDrill', '');
}

async function drillCampaign(idx) {
  const visibleData = rawDataCache.camp || _campaignsData;
  const camp = visibleData[idx];
  if (!camp) return;
  await drillCampaignByName(camp.campaign);
}

async function openCampaignFromSearch(campaignName) {
  hideSearchResults();
  document.getElementById('globalSearchInput').value = '';

  if (currentTab !== 'campaigns') {
    switchTab('campaigns');
    await loadCampaigns();
  }

  await drillCampaignByName(campaignName);
}

function openCampDrillModalByDuid(duid) {
  const key = decodeURIComponent(String(duid || ''));
  const row = (_campDrillData || []).find(r => String(r.duid) === key)
    || (rawDataCache.campDrill || []).find(r => String(r.duid) === key);
  if (row) openOutcomeModal(row.duid, row.email);
}
function openCampDrillModal(idx) {
  const row = _campDrillData[idx];
  if (row) openOutcomeModal(row.duid, row.email);
}

function closeCampaignDrill() {
  const drill = document.getElementById('campaign-drill');
  if (drill) drill.style.display = 'none';
  const campMain = document.querySelectorAll('#tab-campaigns > .panel');
  campMain.forEach(p => p.style.display = '');
}

// ═══════════════════════════════════════════════════════════
// AFFILIATE COMPARISON
// ═══════════════════════════════════════════════════════════

async function compareAffiliates() {
  const input = document.getElementById('compareAffiliatesInput').value.trim();
  const resultDiv = document.getElementById('affiliateComparisonResult');

  if (!input) {
    showToast('Enter affiliate codes to compare', 'error');
    return;
  }

  resultDiv.innerHTML = loading();

  const data = await api(`/api/affiliate-comparison?codes=${encodeURIComponent(input)}`);

  if (data?.error) {
    resultDiv.innerHTML = `<div class="empty-state"><p>${data.error}</p></div>`;
    return;
  }

  if (!data?.affiliates || data.affiliates.length === 0) {
    resultDiv.innerHTML = emptyState('⊞', 'No affiliates found', 'Check the codes and try again.');
    return;
  }

  // Build comparison grid
  const affiliates = data.affiliates;
  let html = '<div class="comparison-grid" style="display:grid;grid-template-columns:repeat(' + (affiliates.length + 1) + ', 1fr);gap:0;border:1px solid var(--border);border-radius:8px;overflow:hidden;">';

  // Header row
  html += '<div class="comp-header" style="padding:12px;background:var(--bg-secondary);font-weight:600;font-size:11px;color:var(--text-muted);text-transform:uppercase;">Metric</div>';
  affiliates.forEach(a => {
    html += `<div class="comp-header" style="padding:12px;background:var(--bg-secondary);font-weight:600;font-family:var(--mono);font-size:12px;text-align:center;">${a.webmaster_code}</div>`;
  });

  const metrics = [
    { key: 'total_accounts', label: 'Total Accounts', fmt: v => fmt(v) },
    { key: 'high_risk_count', label: 'High Risk', fmt: v => `<span style="color:var(--risk-high)">${fmt(v)}</span>` },
    { key: 'high_risk_pct', label: 'High Risk %', fmt: v => v + '%' },
    { key: 'avg_risk_score', label: 'Avg Risk Score', fmt: v => v?.toFixed(1) || '—' },
    { key: 'total_payout', label: 'Total Payout', fmt: v => fmtCur(v) },
    { key: 'high_risk_payout', label: 'At-Risk Payout', fmt: v => fmtCur(v) },
    { key: 'campaign_count', label: 'Campaigns', fmt: v => fmt(v) }
  ];

  metrics.forEach(m => {
    html += `<div style="padding:10px 12px;border-top:1px solid var(--border-subtle);font-size:11px;color:var(--text-muted);">${m.label}</div>`;
    affiliates.forEach(a => {
      html += `<div style="padding:10px 12px;border-top:1px solid var(--border-subtle);text-align:center;font-family:var(--mono);font-size:12px;">${m.fmt(a[m.key])}</div>`;
    });
  });

  // Top flags row
  html += `<div style="padding:10px 12px;border-top:1px solid var(--border-subtle);font-size:11px;color:var(--text-muted);">Top Flags</div>`;
  affiliates.forEach(a => {
    const flags = (a.top_flags || []).slice(0, 3).map(f => f.flag).join(', ') || '—';
    html += `<div style="padding:10px 12px;border-top:1px solid var(--border-subtle);text-align:center;font-size:10px;">${truncate(flags, 30)}</div>`;
  });

  html += '</div>';
  resultDiv.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════
// ACTIONS TAB
// ═══════════════════════════════════════════════════════════

let activityLog = [];

async function loadActionsTab() {
  loadHouseAffiliates();
  loadActivityFromAPI();
  loadFetchFilters();
  loadAnalysisFilters();
}

// Load affiliate codes and campaigns for fetch filters
let fetchAffiliatesList = [];
let fetchCampaignsList = [];
let selectedFetchAffiliates = new Set();
let selectedFetchCampaigns = new Set();

async function loadFetchFilters() {
  try {
    console.log('loadFetchFilters() called - loading affiliates from source...');
    
    // Load affiliates from SOURCE data (not analyzed results)
    const affData = await api('/api/source-affiliates');
    console.log('Fetch filters - API response:', affData);
    
    // The api() function wraps response in {data: {...}, error: null}
    const affiliates = affData?.data?.affiliates || affData?.affiliates;
    
    if (affiliates && Array.isArray(affiliates)) {
      fetchAffiliatesList = affiliates
        .filter(aff => aff.code && aff.code.trim())
        .sort((a, b) => b.total_accounts - a.total_accounts)
        .slice(0, 200);  // Top 200 affiliates
      console.log(`✓ Loaded ${fetchAffiliatesList.length} affiliates for FETCH filters`);
      renderFetchAffiliateList();
    } else {
      console.error('❌ No affiliates array in API response:', affData);
    }
    
    // Load campaigns for multi-select
    const campData = await api('/api/campaigns');
    const campaigns = campData?.data || campData;
    
    if (Array.isArray(campaigns) && campaigns.length) {
      fetchCampaignsList = campaigns
        .filter(c => c.campaign && c.campaign.trim())
        .map(c => ({ campaign: c.campaign, count: c.account_count || 0 }));
      console.log(`✓ Loaded ${fetchCampaignsList.length} campaigns for FETCH filters`);
      renderFetchCampaignList();
    }
  } catch (err) {
    console.error('❌ Failed to load fetch filters:', err);
  }
}

function renderFetchAffiliateList(filter = '') {
  const listEl = document.getElementById('fetchAffiliateList');
  if (!listEl) return;
  
  const filtered = filter 
    ? fetchAffiliatesList.filter(aff => aff.code.toLowerCase().includes(filter.toLowerCase()))
    : fetchAffiliatesList;
  
  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="padding:12px;text-align:center;color:#94a3b8;font-size:13px;">No affiliates found</div>';
    return;
  }
  
  listEl.innerHTML = filtered.map(aff => `
    <label>
      <input type="checkbox" value="${aff.code}" 
             ${selectedFetchAffiliates.has(aff.code) ? 'checked' : ''}
             onchange="toggleFetchAffiliate('${aff.code}', this.checked)">
      <span style="flex:1;">${aff.code}</span>
      <span class="badge" style="background:#e0f2fe;color:#0369a1;">${aff.total_accounts}</span>
    </label>
  `).join('');
}

function renderFetchCampaignList(filter = '') {
  const listEl = document.getElementById('fetchCampaignList');
  if (!listEl) return;
  
  const filtered = filter 
    ? fetchCampaignsList.filter(c => c.campaign.toLowerCase().includes(filter.toLowerCase()))
    : fetchCampaignsList;
  
  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="padding:12px;text-align:center;color:#94a3b8;font-size:13px;">No campaigns found</div>';
    return;
  }
  
  listEl.innerHTML = filtered.map(c => `
    <label>
      <input type="checkbox" value="${c.campaign}" 
             ${selectedFetchCampaigns.has(c.campaign) ? 'checked' : ''}
             onchange="toggleFetchCampaign('${c.campaign.replace(/'/g, "\\'")}', this.checked)">
      <span style="flex:1;">${c.campaign}</span>
      <span class="badge" style="background:#f0fdf4;color:#15803d;">${c.count}</span>
    </label>
  `).join('');
}

function toggleFetchAffiliateDropdown() {
  const dropdown = document.getElementById('fetchAffiliateDropdown');
  const isVisible = dropdown.style.display !== 'none';
  
  // Close other dropdowns
  document.getElementById('fetchCampaignDropdown').style.display = 'none';
  
  dropdown.style.display = isVisible ? 'none' : 'block';
  if (!isVisible) {
    document.getElementById('fetchAffiliateSearch').value = '';
    renderFetchAffiliateList();
  }
}

function toggleFetchCampaignDropdown() {
  const dropdown = document.getElementById('fetchCampaignDropdown');
  const isVisible = dropdown.style.display !== 'none';
  
  // Close other dropdowns
  document.getElementById('fetchAffiliateDropdown').style.display = 'none';
  
  dropdown.style.display = isVisible ? 'none' : 'block';
  if (!isVisible) {
    document.getElementById('fetchCampaignSearch').value = '';
    renderFetchCampaignList();
  }
}

function closeFetchAffiliateDropdown() {
  document.getElementById('fetchAffiliateDropdown').style.display = 'none';
  updateFetchAffiliateDisplay();
}

function closeFetchCampaignDropdown() {
  document.getElementById('fetchCampaignDropdown').style.display = 'none';
  updateFetchCampaignDisplay();
}

function toggleFetchAffiliate(code, checked) {
  if (checked) {
    selectedFetchAffiliates.add(code);
  } else {
    selectedFetchAffiliates.delete(code);
  }
  updateFetchAffiliateDisplay();
}

function toggleFetchCampaign(campaign, checked) {
  if (checked) {
    selectedFetchCampaigns.add(campaign);
  } else {
    selectedFetchCampaigns.delete(campaign);
  }
  updateFetchCampaignDisplay();
}

function toggleAllFetchAffiliates(checked) {
  const search = document.getElementById('fetchAffiliateSearch').value.toLowerCase();
  const filtered = search 
    ? fetchAffiliatesList.filter(aff => aff.code.toLowerCase().includes(search))
    : fetchAffiliatesList;
  
  filtered.forEach(aff => {
    if (checked) {
      selectedFetchAffiliates.add(aff.code);
    } else {
      selectedFetchAffiliates.delete(aff.code);
    }
  });
  
  renderFetchAffiliateList(search);
  updateFetchAffiliateDisplay();
}

function toggleAllFetchCampaigns(checked) {
  const search = document.getElementById('fetchCampaignSearch').value.toLowerCase();
  const filtered = search 
    ? fetchCampaignsList.filter(c => c.campaign.toLowerCase().includes(search))
    : fetchCampaignsList;
  
  filtered.forEach(c => {
    if (checked) {
      selectedFetchCampaigns.add(c.campaign);
    } else {
      selectedFetchCampaigns.delete(c.campaign);
    }
  });
  
  renderFetchCampaignList(search);
  updateFetchCampaignDisplay();
}

function filterFetchAffiliates() {
  const search = document.getElementById('fetchAffiliateSearch').value;
  renderFetchAffiliateList(search);
}

function filterFetchCampaigns() {
  const search = document.getElementById('fetchCampaignSearch').value;
  renderFetchCampaignList(search);
}

function updateFetchAffiliateDisplay() {
  const count = selectedFetchAffiliates.size;
  const countEl = document.getElementById('fetchAffiliateCount');
  const textEl = document.getElementById('fetchAffiliateDropdownText');
  
  if (count === 0) {
    countEl.textContent = '';
    textEl.textContent = 'Select affiliates...';
    textEl.style.color = '#94a3b8';
  } else {
    countEl.textContent = `(${count} selected)`;
    const codes = Array.from(selectedFetchAffiliates);
    if (count <= 3) {
      textEl.textContent = codes.join(', ');
    } else {
      textEl.textContent = `${codes.slice(0, 2).join(', ')}, +${count - 2} more`;
    }
    textEl.style.color = 'var(--text-primary)';
  }
}

function updateFetchCampaignDisplay() {
  const count = selectedFetchCampaigns.size;
  const countEl = document.getElementById('fetchCampaignCount');
  const textEl = document.getElementById('fetchCampaignDropdownText');
  
  if (count === 0) {
    countEl.textContent = '';
    textEl.textContent = 'Select campaigns...';
    textEl.style.color = '#94a3b8';
  } else {
    countEl.textContent = `(${count} selected)`;
    const campaigns = Array.from(selectedFetchCampaigns);
    if (count <= 3) {
      textEl.textContent = campaigns.join(', ');
    } else {
      textEl.textContent = `${campaigns.slice(0, 2).join(', ')}, +${count - 2} more`;
    }
    textEl.style.color = 'var(--text-primary)';
  }
}

// ─── Manual affiliate / campaign entry ───────────────────────────────────────
// Tracks codes entered manually (not from the DB dropdown)
const manualFetchAffiliates = new Set();
const manualFetchCampaigns  = new Set();

function addManualFetchAffiliate() {
  const input = document.getElementById('fetchAffiliateManual');
  const raw = (input.value || '').trim();
  if (!raw) return;
  // Support comma-separated bulk entry
  raw.split(',').map(s => s.trim()).filter(Boolean).forEach(code => {
    manualFetchAffiliates.add(code);
    selectedFetchAffiliates.add(code);  // also counts in the display
  });
  input.value = '';
  renderManualAffiliateTags();
  updateFetchAffiliateDisplay();
}

function removeManualFetchAffiliate(code) {
  manualFetchAffiliates.delete(code);
  selectedFetchAffiliates.delete(code);
  renderManualAffiliateTags();
  updateFetchAffiliateDisplay();
}

function renderManualAffiliateTags() {
  const wrap = document.getElementById('fetchAffiliateManualTags');
  if (!wrap) return;
  wrap.innerHTML = [...manualFetchAffiliates].map(code => `
    <span style="display:inline-flex;align-items:center;gap:4px;background:var(--accent,#0ea5e9);
                 color:#fff;border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600;">
      ${code}
      <span style="cursor:pointer;opacity:.8;" onclick="removeManualFetchAffiliate('${code}')">×</span>
    </span>`).join('');
}

function addManualFetchCampaign() {
  const input = document.getElementById('fetchCampaignManual');
  const raw = (input.value || '').trim();
  if (!raw) return;
  raw.split(',').map(s => s.trim()).filter(Boolean).forEach(name => {
    manualFetchCampaigns.add(name);
    selectedFetchCampaigns.add(name);
  });
  input.value = '';
  renderManualCampaignTags();
  updateFetchCampaignDisplay();
}

function removeManualFetchCampaign(name) {
  manualFetchCampaigns.delete(name);
  selectedFetchCampaigns.delete(name);
  renderManualCampaignTags();
  updateFetchCampaignDisplay();
}

function renderManualCampaignTags() {
  const wrap = document.getElementById('fetchCampaignManualTags');
  if (!wrap) return;
  wrap.innerHTML = [...manualFetchCampaigns].map(name => `
    <span style="display:inline-flex;align-items:center;gap:4px;background:var(--accent,#0ea5e9);
                 color:#fff;border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600;">
      ${name}
      <span style="cursor:pointer;opacity:.8;" onclick="removeManualFetchCampaign('${name.replace(/'/g,"\\'")}')">×</span>
    </span>`).join('');
}

// ─── Manual affiliate / campaign entry — Analysis panel ──────────────────────
const manualAnalysisAffiliates = new Set();
const manualAnalysisCampaigns  = new Set();

function addManualAnalysisAffiliate() {
  const input = document.getElementById('analysisAffiliateManual');
  const raw = (input.value || '').trim();
  if (!raw) return;
  raw.split(',').map(s => s.trim()).filter(Boolean).forEach(code => {
    manualAnalysisAffiliates.add(code);
    selectedAnalysisAffiliates.add(code);
  });
  input.value = '';
  renderManualAnalysisAffiliateTags();
  updateAnalysisAffiliateDisplay();
}

function removeManualAnalysisAffiliate(code) {
  manualAnalysisAffiliates.delete(code);
  selectedAnalysisAffiliates.delete(code);
  renderManualAnalysisAffiliateTags();
  updateAnalysisAffiliateDisplay();
}

function renderManualAnalysisAffiliateTags() {
  const wrap = document.getElementById('analysisAffiliateManualTags');
  if (!wrap) return;
  wrap.innerHTML = [...manualAnalysisAffiliates].map(code => `
    <span style="display:inline-flex;align-items:center;gap:4px;background:var(--accent,#0ea5e9);
                 color:#fff;border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600;">
      ${code}
      <span style="cursor:pointer;opacity:.8;" onclick="removeManualAnalysisAffiliate('${code}')">×</span>
    </span>`).join('');
}

function addManualAnalysisCampaign() {
  const input = document.getElementById('analysisCampaignManual');
  const raw = (input.value || '').trim();
  if (!raw) return;
  raw.split(',').map(s => s.trim()).filter(Boolean).forEach(name => {
    manualAnalysisCampaigns.add(name);
    selectedAnalysisCampaigns.add(name);
  });
  input.value = '';
  renderManualAnalysisCampaignTags();
  updateAnalysisCampaignDisplay();
}

function removeManualAnalysisCampaign(name) {
  manualAnalysisCampaigns.delete(name);
  selectedAnalysisCampaigns.delete(name);
  renderManualAnalysisCampaignTags();
  updateAnalysisCampaignDisplay();
}

function renderManualAnalysisCampaignTags() {
  const wrap = document.getElementById('analysisCampaignManualTags');
  if (!wrap) return;
  wrap.innerHTML = [...manualAnalysisCampaigns].map(name => `
    <span style="display:inline-flex;align-items:center;gap:4px;background:var(--accent,#0ea5e9);
                 color:#fff;border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600;">
      ${name}
      <span style="cursor:pointer;opacity:.8;" onclick="removeManualAnalysisCampaign('${name.replace(/'/g,"\\'")}')">×</span>
    </span>`).join('');
}


document.addEventListener('click', (e) => {
  const affDropdown = document.getElementById('fetchAffiliateDropdown');
  const affBtn = document.getElementById('fetchAffiliateDropdownBtn');
  const campDropdown = document.getElementById('fetchCampaignDropdown');
  const campBtn = document.getElementById('fetchCampaignDropdownBtn');
  
  if (affDropdown && !affDropdown.contains(e.target) && !affBtn.contains(e.target)) {
    affDropdown.style.display = 'none';
  }
  
  if (campDropdown && !campDropdown.contains(e.target) && !campBtn.contains(e.target)) {
    campDropdown.style.display = 'none';
  }
  
  // Analysis dropdowns
  const analysisAffDropdown = document.getElementById('analysisAffiliateDropdown');
  const analysisAffBtn = document.getElementById('analysisAffiliateDropdownBtn');
  const analysisCampDropdown = document.getElementById('analysisCampaignDropdown');
  const analysisCampBtn = document.getElementById('analysisCampaignDropdownBtn');
  
  if (analysisAffDropdown && !analysisAffDropdown.contains(e.target) && !analysisAffBtn.contains(e.target)) {
    analysisAffDropdown.style.display = 'none';
  }
  
  if (analysisCampDropdown && !analysisCampDropdown.contains(e.target) && !analysisCampBtn.contains(e.target)) {
    analysisCampDropdown.style.display = 'none';
  }
});

// ═══════════════════════════════════════════════════════════
// ANALYSIS FILTERS
// ═══════════════════════════════════════════════════════════

let analysisAffiliatesList = [];
let analysisCampaignsList = [];
let selectedAnalysisAffiliates = new Set();
let selectedAnalysisCampaigns = new Set();

async function loadAnalysisFilters() {
  try {
    console.log('loadAnalysisFilters() called - loading affiliates from source...');
    
    // Load affiliates from SOURCE data (not analyzed results)
    const affData = await api('/api/source-affiliates');
    console.log('Analysis filters - API response:', affData);
    
    // The api() function wraps response in {data: {...}, error: null}
    const affiliates = affData?.data?.affiliates || affData?.affiliates;
    
    if (affiliates && Array.isArray(affiliates)) {
      analysisAffiliatesList = affiliates
        .filter(aff => aff.code && aff.code.trim())
        .sort((a, b) => b.total_accounts - a.total_accounts)
        .slice(0, 200);
      console.log(`✓ Loaded ${analysisAffiliatesList.length} affiliates for ANALYSIS filters`);
      renderAnalysisAffiliateList();
    } else {
      console.error('❌ No affiliates array in API response:', affData);
    }
    
    // Load campaigns for multi-select
    const campData = await api('/api/campaigns');
    const campaigns = campData?.data || campData;

    if (Array.isArray(campaigns) && campaigns.length) {
      analysisCampaignsList = campaigns
        .filter(c => c.campaign && c.campaign.trim())
        .map(c => ({ campaign: c.campaign, count: c.account_count || 0 }));
      console.log(`✓ Loaded ${analysisCampaignsList.length} campaigns for ANALYSIS filters`);
      renderAnalysisCampaignList();
    } else {
      console.error('❌ No campaigns data in API response');
    }
  } catch (err) {
    console.error('❌ Failed to load analysis filters:', err);
  }
}

function renderAnalysisAffiliateList(filter = '') {
  const listEl = document.getElementById('analysisAffiliateList');
  if (!listEl) return;
  
  // DEBUG: Log the list state
  console.log('Rendering affiliate list:', {
    totalAffiliates: analysisAffiliatesList.length,
    filter: filter,
    sampleCodes: analysisAffiliatesList.slice(0, 5).map(a => a.code)
  });
  
  const filtered = filter 
    ? analysisAffiliatesList.filter(aff => aff.code.toLowerCase().includes(filter.toLowerCase()))
    : analysisAffiliatesList;
  
  console.log('Filtered results:', filtered.length);
  
  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="padding:12px;text-align:center;color:#94a3b8;font-size:13px;">No affiliates found</div>';
    return;
  }
  
  listEl.innerHTML = filtered.map(aff => `
    <label>
      <input type="checkbox" value="${aff.code}" 
             ${selectedAnalysisAffiliates.has(aff.code) ? 'checked' : ''}
             onchange="toggleAnalysisAffiliate('${aff.code}', this.checked)">
      <span style="flex:1;">${aff.code}</span>
      <span class="badge" style="background:#e0f2fe;color:#0369a1;">${aff.total_accounts}</span>
    </label>
  `).join('');
}

function renderAnalysisCampaignList(filter = '') {
  const listEl = document.getElementById('analysisCampaignList');
  if (!listEl) return;
  
  const filtered = filter 
    ? analysisCampaignsList.filter(c => c.campaign.toLowerCase().includes(filter.toLowerCase()))
    : analysisCampaignsList;
  
  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="padding:12px;text-align:center;color:#94a3b8;font-size:13px;">No campaigns found</div>';
    return;
  }
  
  listEl.innerHTML = filtered.map(c => `
    <label>
      <input type="checkbox" value="${c.campaign}" 
             ${selectedAnalysisCampaigns.has(c.campaign) ? 'checked' : ''}
             onchange="toggleAnalysisCampaign('${c.campaign.replace(/'/g, "\\'")}', this.checked)">
      <span style="flex:1;">${c.campaign}</span>
      <span class="badge" style="background:#f0fdf4;color:#15803d;">${c.count}</span>
    </label>
  `).join('');
}

function toggleAnalysisAffiliateDropdown() {
  const dropdown = document.getElementById('analysisAffiliateDropdown');
  const isVisible = dropdown.style.display !== 'none';
  
  document.getElementById('analysisCampaignDropdown').style.display = 'none';
  
  dropdown.style.display = isVisible ? 'none' : 'block';
  if (!isVisible) {
    document.getElementById('analysisAffiliateSearch').value = '';
    renderAnalysisAffiliateList();
  }
}

function toggleAnalysisCampaignDropdown() {
  const dropdown = document.getElementById('analysisCampaignDropdown');
  const isVisible = dropdown.style.display !== 'none';
  
  document.getElementById('analysisAffiliateDropdown').style.display = 'none';
  
  dropdown.style.display = isVisible ? 'none' : 'block';
  if (!isVisible) {
    document.getElementById('analysisCampaignSearch').value = '';
    renderAnalysisCampaignList();
  }
}

function closeAnalysisAffiliateDropdown() {
  document.getElementById('analysisAffiliateDropdown').style.display = 'none';
  updateAnalysisAffiliateDisplay();
}

function closeAnalysisCampaignDropdown() {
  document.getElementById('analysisCampaignDropdown').style.display = 'none';
  updateAnalysisCampaignDisplay();
}

function toggleAnalysisAffiliate(code, checked) {
  if (checked) {
    selectedAnalysisAffiliates.add(code);
  } else {
    selectedAnalysisAffiliates.delete(code);
  }
  updateAnalysisAffiliateDisplay();
}

function toggleAnalysisCampaign(campaign, checked) {
  if (checked) {
    selectedAnalysisCampaigns.add(campaign);
  } else {
    selectedAnalysisCampaigns.delete(campaign);
  }
  updateAnalysisCampaignDisplay();
}

function toggleAllAnalysisAffiliates(checked) {
  const search = document.getElementById('analysisAffiliateSearch').value.toLowerCase();
  const filtered = search 
    ? analysisAffiliatesList.filter(aff => aff.code.toLowerCase().includes(search))
    : analysisAffiliatesList;
  
  filtered.forEach(aff => {
    if (checked) {
      selectedAnalysisAffiliates.add(aff.code);
    } else {
      selectedAnalysisAffiliates.delete(aff.code);
    }
  });
  
  renderAnalysisAffiliateList(search);
  updateAnalysisAffiliateDisplay();
}

function toggleAllAnalysisCampaigns(checked) {
  const search = document.getElementById('analysisCampaignSearch').value.toLowerCase();
  const filtered = search 
    ? analysisCampaignsList.filter(c => c.campaign.toLowerCase().includes(search))
    : analysisCampaignsList;
  
  filtered.forEach(c => {
    if (checked) {
      selectedAnalysisCampaigns.add(c.campaign);
    } else {
      selectedAnalysisCampaigns.delete(c.campaign);
    }
  });
  
  renderAnalysisCampaignList(search);
  updateAnalysisCampaignDisplay();
}

function filterAnalysisAffiliates() {
  const search = document.getElementById('analysisAffiliateSearch').value;
  renderAnalysisAffiliateList(search);
}

function filterAnalysisCampaigns() {
  const search = document.getElementById('analysisCampaignSearch').value;
  renderAnalysisCampaignList(search);
}

function updateAnalysisAffiliateDisplay() {
  const count = selectedAnalysisAffiliates.size;
  const countEl = document.getElementById('analysisAffiliateCount');
  const textEl = document.getElementById('analysisAffiliateDropdownText');
  
  if (count === 0) {
    countEl.textContent = '';
    textEl.textContent = 'Select affiliates...';
    textEl.style.color = '#94a3b8';
  } else {
    countEl.textContent = `(${count} selected)`;
    const codes = Array.from(selectedAnalysisAffiliates);
    if (count <= 3) {
      textEl.textContent = codes.join(', ');
    } else {
      textEl.textContent = `${codes.slice(0, 2).join(', ')}, +${count - 2} more`;
    }
    textEl.style.color = 'var(--text-primary)';
  }
}

function updateAnalysisCampaignDisplay() {
  const count = selectedAnalysisCampaigns.size;
  const countEl = document.getElementById('analysisCampaignCount');
  const textEl = document.getElementById('analysisCampaignDropdownText');
  
  if (count === 0) {
    countEl.textContent = '';
    textEl.textContent = 'Select campaigns...';
    textEl.style.color = '#94a3b8';
  } else {
    countEl.textContent = `(${count} selected)`;
    const campaigns = Array.from(selectedAnalysisCampaigns);
    if (count <= 3) {
      textEl.textContent = campaigns.join(', ');
    } else {
      textEl.textContent = `${campaigns.slice(0, 2).join(', ')}, +${count - 2} more`;
    }
    textEl.style.color = 'var(--text-primary)';
  }
}

async function loadActivityFromAPI() {
  const wrap = document.getElementById('recentActivity');
  const data = await api('/api/activity-log?limit=30');

  if (!data?.activities || data.activities.length === 0) {
    // Fall back to localStorage activity
    loadActivityLog();
    return;
  }

  // Merge API activities with localStorage activities
  const apiActivities = data.activities.map(a => ({
    type: 'outcome',
    message: `${a.outcome?.replace('_', ' ')} - ${a.email || a.duid}`,
    timestamp: a.timestamp,
    outcome: a.outcome,
    email: a.email,
    duid: a.duid,
    notes: a.notes
  }));

  // Combine with local activities
  loadActivityLog();
  const combined = [...apiActivities, ...activityLog];
  combined.sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0));

  // Render combined
  wrap.innerHTML = combined.slice(0, 30).map(a => {
    const outcomeClass = a.outcome === 'confirmed_fraud' ? 'high' : a.outcome === 'false_positive' ? 'low' : a.outcome ? 'medium' : '';
    const outcomeLabel = a.outcome?.replace('_', ' ') || a.type || 'action';
    const time = a.timestamp ? new Date(a.timestamp).toLocaleString() : '—';
    const content = a.email || a.duid || a.message || 'Unknown action';
    return `
      <div class="activity-item" style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-subtle);">
        <span class="risk-badge ${outcomeClass}" style="min-width:100px;text-align:center;font-size:10px;">${outcomeLabel}</span>
        <div style="flex:1;min-width:0;">
          <div style="font-family:var(--mono);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${content}</div>
          ${a.notes ? `<div style="font-size:10px;color:var(--text-muted);">${truncate(a.notes, 50)}</div>` : ''}
        </div>
        <div style="font-family:var(--mono);font-size:10px;color:var(--text-muted);white-space:nowrap;">${time}</div>
      </div>
    `;
  }).join('') || '<div class="activity-empty">No recent activity</div>';
}

function toggleCustomDates() {
  const range = document.getElementById('fetchDateRange').value;
  document.getElementById('customDates').style.display = range === 'custom' ? 'block' : 'none';
}

function toggleAnalysisCustomDates() {
  const range = document.getElementById('analysisDateRange').value;
  document.getElementById('analysisCustomDates').style.display = range === 'custom' ? 'block' : 'none';

  // When a date range is selected, "New data only" will return 0 rows for
  // already-analyzed records. Auto-switch to "Re-analyze all" and warn.
  const scopeSel = document.getElementById('analysisScope');
  const scopeHint = document.getElementById('analysisScopeHint');
  if (range !== 'all') {
    if (scopeSel.value === 'new') {
      scopeSel.value = 'all';
    }
    if (scopeHint) {
      scopeHint.textContent = 'Switched to "Re-analyze all" — required when filtering by date range.';
      scopeHint.style.display = 'block';
    }
  } else {
    if (scopeHint) scopeHint.style.display = 'none';
  }
}

function onAnalysisScopeChange() {
  const range = document.getElementById('analysisDateRange').value;
  const scope = document.getElementById('analysisScope').value;
  const scopeHint = document.getElementById('analysisScopeHint');
  if (!scopeHint) return;
  if (scope === 'new' && range !== 'all') {
    scopeHint.textContent = '⚠ "New data only" may return 0 results if records were already analyzed. Use "Re-analyze all" with date filters.';
    scopeHint.style.display = 'block';
  } else {
    scopeHint.style.display = 'none';
  }
}

function toggleEDACustomDates() {
  const range = document.getElementById('edaDateRange').value;
  document.getElementById('edaCustomDates').style.display = range === 'custom' ? 'flex' : 'none';
}

// ═══ BULK FRAUD IMPORT ═══
async function bulkImportOutcomes() {
  const fileInput  = document.getElementById('bulkImportFile');
  const outcome    = document.getElementById('bulkOutcome')?.value || 'confirmed_fraud';
  const notes      = document.getElementById('bulkNotes')?.value || '';
  const statusEl   = document.getElementById('bulkImportStatus');
  const btn        = document.getElementById('bulkImportBtn');

  if (!fileInput?.files?.length) {
    showToast('Please select a CSV file first', 'error');
    return;
  }

  const file = fileInput.files[0];
  if (!file.name.endsWith('.csv')) {
    showToast('File must be a .csv', 'error');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Uploading…';
  statusEl.style.display = 'none';

  const formData = new FormData();
  formData.append('file',    file);
  formData.append('outcome', outcome);
  formData.append('notes',   notes);

  try {
    const res  = await fetch('/api/outcomes/bulk-import', { method: 'POST', body: formData });
    const data = await res.json();

    if (data.error) {
      statusEl.innerHTML = `<span style="color:var(--risk-high);">❌ ${data.error}</span>`;
    } else {
      statusEl.innerHTML = `
        <span style="color:var(--green);">✓ Import complete</span>
        &nbsp;·&nbsp; <strong>${data.imported}</strong> marked as <em>${data.outcome.replace('_',' ')}</em>
        &nbsp;·&nbsp; ${data.skipped} skipped (no matching DUID/email)
        ${data.errors?.length ? `<br><span style="color:var(--amber);font-size:11px;">Row errors: ${data.errors.join(', ')}</span>` : ''}
      `;
      showToast(`Imported ${data.imported} records as ${data.outcome.replace('_',' ')}`, 'success');
      clearApiCache();
      // Clear file input for next upload
      fileInput.value = '';
    }
    statusEl.style.display = 'block';
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--risk-high);">❌ Network error: ${e.message}</span>`;
    statusEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Upload & Import';
  }
}

// ═══ EDA (DATA EXPLORER) ═══

let currentEDAResults = null;

// ── EDA affiliate autocomplete ───────────────────────────────────────────────
let _edaAffiliateList = [];

async function initEDAAffiliateList() {
  if (_edaAffiliateList.length) return;
  try {
    const res = await api('/api/affiliates');
    const rows = res.data || res || [];
    _edaAffiliateList = rows.map(r => r.webmaster_code).filter(Boolean).sort();
  } catch {}
}

function filterEDAAffiliateSuggestions() {
  const input = document.getElementById('edaAffiliateInput');
  const box   = document.getElementById('edaAffiliateSuggestions');
  const clearBtn = document.getElementById('edaAffiliateClearBtn');
  const q = (input?.value || '').trim().toLowerCase();

  if (clearBtn) clearBtn.style.display = q ? '' : 'none';

  if (!q) { box.style.display = 'none'; return; }

  const matches = _edaAffiliateList.filter(a => a.toLowerCase().includes(q)).slice(0, 12);
  if (!matches.length) { box.style.display = 'none'; return; }

  box.innerHTML = matches.map(a => `
    <div onclick="selectEDAAffiliate('${a}')"
         style="padding:8px 12px;cursor:pointer;font-size:12px;font-family:var(--font-mono,monospace);
                border-bottom:1px solid var(--border);"
         onmouseover="this.style.background='var(--surface2)'"
         onmouseout="this.style.background=''">
      ${a}
    </div>`).join('');
  box.style.display = 'block';
}

function selectEDAAffiliate(code) {
  const input = document.getElementById('edaAffiliateInput');
  const box   = document.getElementById('edaAffiliateSuggestions');
  const clearBtn = document.getElementById('edaAffiliateClearBtn');
  if (input)    input.value = code;
  if (box)      box.style.display = 'none';
  if (clearBtn) clearBtn.style.display = '';
}

function clearEDAAffiliate() {
  const input = document.getElementById('edaAffiliateInput');
  const clearBtn = document.getElementById('edaAffiliateClearBtn');
  const box   = document.getElementById('edaAffiliateSuggestions');
  if (input)    input.value = '';
  if (clearBtn) clearBtn.style.display = 'none';
  if (box)      box.style.display = 'none';
}

function handleEDAAffiliateKey(e) {
  const box = document.getElementById('edaAffiliateSuggestions');
  if (e.key === 'Escape') { box.style.display = 'none'; return; }
  if (e.key === 'Enter')  { box.style.display = 'none'; runEDA(); return; }
}

// Close suggestions when clicking outside
document.addEventListener('click', e => {
  if (!e.target.closest('#edaAffiliateInput') && !e.target.closest('#edaAffiliateSuggestions')) {
    const box = document.getElementById('edaAffiliateSuggestions');
    if (box) box.style.display = 'none';
  }
});

async function runEDA() {
  const btn = document.getElementById('btnRunEDA');
  const dataset = document.getElementById('edaDataset').value;
  const dateRange = document.getElementById('edaDateRange').value;
  const affiliate = (document.getElementById('edaAffiliateInput')?.value || '').trim();

  if (btn.classList.contains('loading')) return;

  let payload = { data_type: dataset };

  if (affiliate) payload.affiliate = affiliate;

  if (dateRange === 'custom') {
    const startDate = document.getElementById('edaStartDate').value;
    const endDate = document.getElementById('edaEndDate').value;
    if (!startDate || !endDate) {
      showToast('Please select both start and end dates', 'error');
      return;
    }
    payload.start_date = startDate;
    payload.end_date = endDate;
  } else if (dateRange !== 'all') {
    const days = parseInt(dateRange);
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    payload.start_date = start.toISOString().split('T')[0];
    payload.end_date = end.toISOString().split('T')[0];
  }
  
  // Show loading
  btn.classList.add('loading');
  document.getElementById('edaBtnText').textContent = 'Analyzing...';
  document.getElementById('edaEmpty').style.display = 'none';
  document.getElementById('edaResults').style.display = 'none';
  document.getElementById('edaLoading').style.display = 'block';
  
  try {
    const res = await api('/api/eda/run', { method: 'POST', body: JSON.stringify(payload) });
    
    if (res.error) {
      showToast('EDA failed: ' + res.error, 'error');
      document.getElementById('edaLoading').style.display = 'none';
      document.getElementById('edaEmpty').style.display = 'block';
      return;
    }
    
    currentEDAResults = res;
    renderEDAResults(res);
    
    // Enable export button
    document.getElementById('btnExportEDA').disabled = false;
    
    showToast('EDA analysis complete!');
    
  } catch (e) {
    showToast('EDA error: ' + e.message, 'error');
    document.getElementById('edaLoading').style.display = 'none';
    document.getElementById('edaEmpty').style.display = 'block';
  } finally {
    btn.classList.remove('loading');
    document.getElementById('edaBtnText').textContent = 'Analyze';
  }
}

function renderEDAResults(results) {
  document.getElementById('edaLoading').style.display = 'none';
  document.getElementById('edaResults').style.display = 'block';

  // Overview stats
  const profile = results.profile || {};
  document.getElementById('edaTotalRecords').textContent = (profile.record_count || 0).toLocaleString();

  if (profile.date_range) {
    const start = new Date(profile.date_range.start).toLocaleDateString();
    const end = new Date(profile.date_range.end).toLocaleDateString();
    document.getElementById('edaDateRange').textContent = `${start} - ${end}`;
  } else {
    document.getElementById('edaDateRange').textContent = 'All time';
  }

  // Show affiliate filter badge if scoped
  const affBadgeEl = document.getElementById('edaAffiliateBadge');
  if (affBadgeEl) {
    if (results.affiliate_filter) {
      affBadgeEl.textContent = `Affiliate: ${results.affiliate_filter}`;
      affBadgeEl.style.display = '';
    } else {
      affBadgeEl.style.display = 'none';
    }
  }
  
  const completenessValues = Object.values(profile.completeness || {});
  const avgCompleteness = completenessValues.length > 0 
    ? (completenessValues.reduce((sum, c) => sum + c.percentage, 0) / completenessValues.length).toFixed(1)
    : 0;
  document.getElementById('edaCompleteness').textContent = avgCompleteness + '%';
  
  document.getElementById('edaUniqueEmails').textContent = (profile.unique_counts?.email || 0).toLocaleString();
  
  // Distributions (ApexCharts)
  renderDistributionCharts(results.distributions || {});
  
  // Correlations
  renderCorrelationCharts(results.correlations || {});
  
  // Quality issues
  renderQualityIssues(results.quality_issues || {});
  
  // Outliers
  renderOutliers(results.outliers || []);
}

function renderDistributionCharts(distributions) {
  const container = document.getElementById('edaDistributionCharts');
  container.innerHTML = '';
  
  // Email domains chart
  if (distributions.email_domains) {
    const domainDiv = document.createElement('div');
    domainDiv.id = 'eda-chart-email-domains';
    domainDiv.className = 'chart-container';
    domainDiv.style.marginBottom = '24px';
    container.appendChild(domainDiv);
    renderApexChart('eda-chart-email-domains', 'bar', {
      series: [{ name: 'Count', data: distributions.email_domains.values }],
      categories: distributions.email_domains.labels
    }, {
      height: 300,
      colors: ['#3b82f6'],
      title: { text: 'Top Email Domains', style: { fontSize: '14px' } },
      xaxis: { title: { text: 'Domain' } },
      yaxis: { title: { text: 'Count' } }
    });
  }
  
  // Payout amounts histogram
  if (distributions.payout_amounts && distributions.payout_amounts.histogram) {
    const amountDiv = document.createElement('div');
    amountDiv.id = 'eda-chart-payout-histogram';
    amountDiv.className = 'chart-container';
    amountDiv.style.marginBottom = '24px';
    container.appendChild(amountDiv);
    const h = distributions.payout_amounts.histogram;
    renderApexChart('eda-chart-payout-histogram', 'bar', {
      series: [{ name: 'Frequency', data: h.counts }],
      categories: h.bins.map(b => String(b))
    }, {
      height: 300,
      colors: ['#10b981'],
      title: { text: 'Payout Amount Distribution', style: { fontSize: '14px' } },
      xaxis: { title: { text: 'Amount ($)' } },
      yaxis: { title: { text: 'Frequency' } }
    });
  }
  
  // Hourly pattern
  if (distributions.hourly_pattern) {
    const hourDiv = document.createElement('div');
    hourDiv.id = 'eda-chart-hourly-pattern';
    hourDiv.className = 'chart-container';
    container.appendChild(hourDiv);
    const hp = distributions.hourly_pattern;
    renderApexChart('eda-chart-hourly-pattern', 'line', {
      series: [{ name: 'Count', data: hp.counts }],
      categories: hp.hours.map(h => String(h))
    }, {
      height: 300,
      colors: ['#8b5cf6'],
      stroke: { curve: 'smooth', width: 2 },
      markers: { size: 4 },
      title: { text: 'Registration Pattern by Hour', style: { fontSize: '14px' } },
      xaxis: { title: { text: 'Hour of Day' } },
      yaxis: { title: { text: 'Count' } }
    });
  }
}

function renderCorrelationCharts(correlations) {
  const container = document.getElementById('edaCorrelationCharts');
  container.innerHTML = '';
  
  if (!correlations || Object.keys(correlations).length === 0) {
    container.innerHTML = '<p style="color:#64748b;">No fraud data available for correlation analysis</p>';
    return;
  }
  
  // Fraud by domain
  if (correlations.fraud_by_domain && correlations.fraud_by_domain.length > 0) {
    const domainDiv = document.createElement('div');
    domainDiv.id = 'eda-chart-fraud-by-domain';
    domainDiv.className = 'chart-container';
    domainDiv.style.marginBottom = '24px';
    container.appendChild(domainDiv);
    const domains = correlations.fraud_by_domain.slice(0, 15);
    renderApexChart('eda-chart-fraud-by-domain', 'bar', {
      series: [{ name: 'Fraud rate', data: domains.map(d => d.fraud_rate) }],
      categories: domains.map(d => d.domain)
    }, {
      height: 300,
      colors: ['#ef4444'],
      title: { text: 'Fraud Rate by Email Domain', style: { fontSize: '14px' } },
      xaxis: { title: { text: 'Domain' } },
      yaxis: { title: { text: 'Fraud Rate (%)' } }
    });
  }
  
  // Fraud by hour
  if (correlations.fraud_by_hour && correlations.fraud_by_hour.length > 0) {
    const hourDiv = document.createElement('div');
    hourDiv.id = 'eda-chart-fraud-by-hour';
    hourDiv.className = 'chart-container';
    container.appendChild(hourDiv);
    const fbh = correlations.fraud_by_hour;
    renderApexChart('eda-chart-fraud-by-hour', 'line', {
      series: [{ name: 'Fraud rate', data: fbh.map(h => h.fraud_rate) }],
      categories: fbh.map(h => String(h.hour))
    }, {
      height: 300,
      colors: ['#f59e0b'],
      stroke: { curve: 'smooth', width: 2 },
      markers: { size: 4 },
      title: { text: 'Fraud Rate by Hour of Day', style: { fontSize: '14px' } },
      xaxis: { title: { text: 'Hour' } },
      yaxis: { title: { text: 'Fraud Rate (%)' } }
    });
  }
}

function renderQualityIssues(issues) {
  const container = document.getElementById('edaQualityIssues');
  container.innerHTML = '';
  
  const allIssues = [
    ...(issues.critical || []).map(i => ({ ...i, level: 'critical' })),
    ...(issues.warnings || []).map(i => ({ ...i, level: 'warning' })),
    ...(issues.info || []).map(i => ({ ...i, level: 'info' }))
  ];
  
  if (allIssues.length === 0) {
    container.innerHTML = '<div class="info-card" style="background:#f0fdf4;border-left:4px solid #10b981;"><p style="margin:0;">✓ No data quality issues detected</p></div>';
    return;
  }
  
  allIssues.forEach(issue => {
    const card = document.createElement('div');
    const colors = {
      critical: { bg: '#fef2f2', border: '#ef4444', icon: '🔴' },
      warning: { bg: '#fffbeb', border: '#f59e0b', icon: '⚠️' },
      info: { bg: '#f0f9ff', border: '#3b82f6', icon: 'ℹ️' }
    };
    const color = colors[issue.level];
    
    card.className = 'info-card';
    card.style.cssText = `background:${color.bg};border-left:4px solid ${color.border};margin-bottom:8px;`;
    card.innerHTML = `
      <div style="font-weight:600;">${color.icon} ${issue.type.replace(/_/g, ' ').toUpperCase()}</div>
      <div style="color:#475569;font-size:14px;margin-top:4px;">
        ${issue.field ? `Field: ${issue.field}<br>` : ''}
        Count: ${issue.count} ${issue.percentage ? `(${issue.percentage}%)` : ''}
      </div>
    `;
    container.appendChild(card);
  });
}

function renderOutliers(outliers) {
  const container = document.getElementById('edaOutliers');
  const countEl = document.getElementById('edaOutlierCount');
  const btnAutoFlag = document.getElementById('btnAutoFlagOutliers');
  
  countEl.textContent = `${outliers.length} outliers detected`;
  btnAutoFlag.disabled = outliers.length === 0;
  
  if (outliers.length === 0) {
    container.innerHTML = '<p style="color:#64748b;">No statistical outliers detected</p>';
    return;
  }
  
  container.innerHTML = `
    <p style="color:#64748b;margin-bottom:12px;">
      Outliers detected using statistical methods (Z-score > 3, disposable emails, high IP concentration)
    </p>
    <div class="info-card" style="background:#f0f9ff;border-left:4px solid #3b82f6;">
      <strong>${outliers.length}</strong> accounts flagged as outliers
      <div style="margin-top:8px;font-size:13px;color:#475569;">
        ${outliers.slice(0, 10).join(', ')}${outliers.length > 10 ? ` and ${outliers.length - 10} more` : ''}
      </div>
    </div>
  `;
}

async function autoFlagOutliers() {
  if (!currentEDAResults || !currentEDAResults.outliers || currentEDAResults.outliers.length === 0) {
    showToast('No outliers to flag', 'error');
    return;
  }
  
  const count = currentEDAResults.outliers.length;
  
  if (!confirm(`Flag ${count} outliers for manual review?\n\nThis will create "review_needed" outcomes for these accounts.`)) {
    return;
  }
  
  try {
    showToast('Flagging outliers...', 'info');
    
    const res = await api('/api/eda/auto-flag-outliers', {
      method: 'POST',
      body: JSON.stringify({
        outliers: currentEDAResults.outliers
      })
    });
    
    if (res.error) {
      showToast('Failed to flag outliers: ' + res.error, 'error');
    } else if (res.data) {
      const flagged = res.data.flagged || 0;
      const failed = res.data.failed || 0;
      
      if (failed > 0) {
        showToast(`Flagged ${flagged} outliers, ${failed} failed`, 'warning');
      } else {
        showToast(`Successfully flagged ${flagged} outliers for review`, 'success');
      }
      
      // Reload pending reviews
      clearApiCache();
      loadTabData(currentTab);
    } else {
      showToast('Outliers flagged successfully', 'success');
    }
  } catch (e) {
    console.error('Auto-flag error:', e);
    showToast('Failed to flag outliers: ' + e.message, 'error');
  }
}

async function exportEDAPDF() {
  if (!currentEDAResults) {
    showToast('No analysis to export', 'error');
    return;
  }
  
  try {
    showToast('Generating PDF...', 'info');
    
    const dataset = document.getElementById('edaDataset')?.value || 'combined';
    
    const res = await api('/api/eda/export-pdf', { 
      method: 'POST', 
      body: JSON.stringify({
        results: currentEDAResults,
        dataset: dataset
      })
    });
    
    if (res.error) {
      showToast('Export failed: ' + res.error, 'error');
    } else if (res.data && res.data.success) {
      showToast(`PDF saved: ${res.data.filename}`, 'success');
      console.log('PDF path:', res.data.path);
    } else {
      showToast('PDF generated successfully', 'success');
    }
  } catch (e) {
    console.error('Export error:', e);
    showToast('Export failed: ' + e.message, 'error');
  }
}

// ═══ HOUSE AFFILIATES ═══
let houseAffiliates = [];
/** From config; excluded from "External Only" views together with house affiliates */
let whitelistedAffiliatesFromConfig = [];

/** Parse affiliate codes from textarea (one per line; commas also accepted). */
function parseAffiliateCodeList(text) {
  return (text || '')
    .replace(/,/g, '\n')
    .split('\n')
    .map(a => a.trim())
    .filter(Boolean);
}

/** Lowercased codes hidden when affiliate filter is "External Only" (house + settings whitelist). */
function externalOnlyExcludeLower() {
  const s = new Set(houseAffiliates.map(h => String(h).toLowerCase()));
  for (const w of whitelistedAffiliatesFromConfig || []) {
    const t = String(w || '').trim().toLowerCase();
    if (t) s.add(t);
  }
  return s;
}

/** Lowercased webmaster_code → affiliate_actions row (fraud-tool close-the-loop). */
let affiliateActionsByCode = {};

async function loadAffiliateActions() {
  const res = await api('/api/affiliate-actions', { skipCache: true });
  affiliateActionsByCode = {};
  if (res.error || !Array.isArray(res.data)) return;
  for (const a of res.data) {
    const c = String(a.webmaster_code || '').toLowerCase();
    if (c) affiliateActionsByCode[c] = a;
  }
}

function affiliateActionPillHtml(code, actionOverride = null) {
  const a = actionOverride || affiliateActionsByCode[String(code || '').toLowerCase()];
  if (!a || !a.action_status) return '';
  const st = a.action_status;
  let text;
  let bg; let fg; let border;
  if (st === 'actioned') {
    const raw = (a.action_type || 'actioned').replace(/_/g, ' ');
    text = raw.charAt(0).toUpperCase() + raw.slice(1);
    bg = 'rgba(16,185,129,0.12)';
    fg = '#34d399';
    border = 'rgba(16,185,129,0.35)';
  } else if (st === 'under_review') {
    text = 'Review';
    bg = 'rgba(245,158,11,0.12)';
    fg = '#fbbf24';
    border = 'rgba(245,158,11,0.35)';
  } else if (st === 'flagged') {
    text = 'Flagged';
    bg = 'rgba(239,68,68,0.12)';
    fg = '#f87171';
    border = 'rgba(239,68,68,0.35)';
  } else if (st === 'cleared') {
    text = 'Cleared';
    bg = 'rgba(148,163,184,0.12)';
    fg = '#94a3b8';
    border = 'rgba(148,163,184,0.3)';
  } else if (st === 'monitoring') {
    text = 'Monitor';
    bg = 'rgba(59,130,246,0.12)';
    fg = '#60a5fa';
    border = 'rgba(59,130,246,0.35)';
  } else {
    text = String(st).replace(/_/g, ' ');
    bg = 'rgba(148,163,184,0.12)';
    fg = '#94a3b8';
    border = 'rgba(148,163,184,0.3)';
  }
  return `<span title="Fraud tool affiliate action" style="font-size:9px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;padding:2px 7px;border-radius:999px;background:${bg};color:${fg};border:1px solid ${border};white-space:nowrap;max-width:140px;overflow:hidden;text-overflow:ellipsis;display:inline-block;vertical-align:middle;">${text}</span>`;
}

async function loadHouseAffiliates() {
  try {
    const r = await fetch('/api/house-affiliates');
    const data = await r.json();
    houseAffiliates = data.house_affiliates || [];
    whitelistedAffiliatesFromConfig = data.whitelisted_affiliates || [];
    renderHouseAffiliates();
    updateHouseAffiliateHint();
  } catch (e) {
    console.error('Failed to load house affiliates:', e);
  }
}

let houseListExpanded = false;

function renderHouseAffiliates() {
  const el = document.getElementById('houseAffiliatesList');
  if (!el) return;
  
  if (houseAffiliates.length === 0) {
    el.innerHTML = '<div class="house-affiliates-empty">No house affiliates configured</div>';
    const toggle = document.getElementById('houseListToggle');
    if (toggle) toggle.style.display = 'none';
    return;
  }
  
  el.innerHTML = houseAffiliates.map(aff => `
    <div class="house-affiliate-tag">
      <span>${aff}</span>
      <button class="remove-btn" onclick="removeHouseAffiliate('${aff}')" title="Remove">×</button>
    </div>
  `).join('');
  
  // Show/hide expand toggle based on count
  const toggle = document.getElementById('houseListToggle');
  if (toggle) {
    if (houseAffiliates.length > 20) {
      toggle.style.display = 'flex';
      toggle.innerHTML = `<button onclick="toggleHouseList()">${houseListExpanded ? 'Collapse' : 'Expand'} (${houseAffiliates.length} total)</button>`;
    } else {
      toggle.style.display = 'none';
    }
  }
  
  el.classList.toggle('expanded', houseListExpanded);
}

function toggleHouseList() {
  houseListExpanded = !houseListExpanded;
  renderHouseAffiliates();
}

function updateHouseAffiliateHint() {
  const hint = document.getElementById('houseAffiliateHint');
  if (hint) {
    if (houseAffiliates.length === 0) {
      hint.textContent = 'No house affiliates configured';
    } else {
      hint.textContent = `${houseAffiliates.length} house affiliate${houseAffiliates.length > 1 ? 's' : ''} will be excluded`;
    }
  }
}

async function addHouseAffiliate() {
  const input = document.getElementById('houseAffiliateInput');
  const affiliate = input.value.trim();
  
  if (!affiliate) {
    showToast('Please enter an affiliate code', 'error');
    return;
  }
  
  if (houseAffiliates.includes(affiliate)) {
    showToast('Affiliate already in house list', 'error');
    return;
  }
  
  try {
    const r = await fetch('/api/house-affiliates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'add', affiliate })
    });
    const data = await r.json();
    
    if (r.ok) {
      houseAffiliates.push(affiliate);
      renderHouseAffiliates();
      updateHouseAffiliateHint();
      input.value = '';
      showToast(`Added '${affiliate}' to house affiliates`);
    } else {
      showToast(data.error || 'Failed to add affiliate', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
}

async function removeHouseAffiliate(affiliate) {
  try {
    const r = await fetch('/api/house-affiliates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'remove', affiliate })
    });
    const data = await r.json();
    
    if (r.ok) {
      houseAffiliates = houseAffiliates.filter(a => a !== affiliate);
      renderHouseAffiliates();
      updateHouseAffiliateHint();
      showToast(`Removed '${affiliate}' from house affiliates`);
    } else {
      showToast(data.error || 'Failed to remove affiliate', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
}

async function bulkAddHouseAffiliates() {
  const textarea = document.getElementById('bulkHouseInput');
  const content = textarea.value.trim();
  
  if (!content) {
    showToast('Please paste a list of affiliates', 'error');
    return;
  }
  
  // Parse: handle both comma and newline separated
  const affiliates = content
    .replace(/,/g, '\n')
    .split('\n')
    .map(a => a.trim())
    .filter(a => a && a.length > 0);
  
  if (affiliates.length === 0) {
    showToast('No valid affiliates found in list', 'error');
    return;
  }
  
  // Filter out duplicates
  const newAffiliates = affiliates.filter(a => !houseAffiliates.includes(a));
  
  if (newAffiliates.length === 0) {
    showToast('All affiliates already in house list', 'error');
    return;
  }
  
  try {
    const r = await fetch('/api/house-affiliates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'set', affiliates: [...houseAffiliates, ...newAffiliates] })
    });
    const data = await r.json();
    
    if (r.ok) {
      houseAffiliates = [...houseAffiliates, ...newAffiliates];
      renderHouseAffiliates();
      updateHouseAffiliateHint();
      textarea.value = '';
      showToast(`Added ${newAffiliates.length} house affiliates (${affiliates.length - newAffiliates.length} duplicates skipped)`);
    } else {
      showToast(data.error || 'Failed to import affiliates', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
}

async function clearAllHouseAffiliates() {
  if (!confirm('Are you sure you want to remove ALL house affiliates?')) {
    return;
  }
  
  try {
    const r = await fetch('/api/house-affiliates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'set', affiliates: [] })
    });
    const data = await r.json();
    
    if (r.ok) {
      houseAffiliates = [];
      renderHouseAffiliates();
      updateHouseAffiliateHint();
      showToast('Cleared all house affiliates');
    } else {
      showToast(data.error || 'Failed to clear affiliates', 'error');
    }
  } catch (e) {
    showToast('Network error: ' + e.message, 'error');
  }
}

function exportHouseAffiliates() {
  if (houseAffiliates.length === 0) {
    showToast('No house affiliates to export', 'error');
    return;
  }
  
  const content = houseAffiliates.join('\n');
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  
  const a = document.createElement('a');
  a.href = url;
  a.download = 'house_affiliates.txt';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  
  showToast(`Exported ${houseAffiliates.length} house affiliates`);
}

// Allow Enter key to add affiliate
document.addEventListener('DOMContentLoaded', () => {
  bindAdmin2LoginUi();
  void ensureAdmin2Session();
  initReportLimitSelect();
  initFiTrajectoryActionFilterSelect();
  document.getElementById('schedulerHealthDismiss')?.addEventListener('click', () => {
    sessionStorage.setItem(SCHED_HEALTH_DISMISS_KEY, '1');
    const b = document.getElementById('schedulerHealthBanner');
    if (b) b.style.display = 'none';
  });

  initMajorTabs('tab-clusters');
  initMajorTabs('tab-affiliates');
  initMajorTabs('tab-settings');
  initMajorTabs('tab-anomaly', (panelId) => {
    loadAnalysisSubTab(panelId);
    setTimeout(resizeAllCharts, 60);
  });
  initMajorTabs('tab-temporal', () => setTimeout(resizeAllCharts, 60));
  const input = document.getElementById('houseAffiliateInput');
  if (input) {
    input.addEventListener('keypress', e => {
      if (e.key === 'Enter') addHouseAffiliate();
    });
  }

  // Flags tab: affiliate drill-down + account modal (delegated — avoids broken inline onclick)
  document.getElementById('tab-flags')?.addEventListener('click', (e) => {
    const drill = e.target.closest('[data-affiliate-drill]');
    if (drill) {
      e.preventDefault();
      const code = drill.getAttribute('data-affiliate-drill');
      if (code) {
        const q =
          typeof selectedFlag === 'string' && selectedFlag.trim()
            ? `?q=${encodeURIComponent(selectedFlag.trim())}`
            : '';
        window.location.href = '/affiliate/' + encodeURIComponent(code) + q;
      }
      return;
    }
    const open = e.target.closest('[data-open-account]');
    if (open) {
      e.preventDefault();
      const duid = open.getAttribute('data-open-account');
      if (duid) void openAccountDetail(duid);
    }
  });
});

async function startFetch() {
  const btn = document.getElementById('btnFetch');
  const statusEl = document.getElementById('fetchStatus');
  
  if (btn.classList.contains('loading')) return;
  
  const dataType = document.getElementById('fetchDataType').value;
  const dateRange = document.getElementById('fetchDateRange').value;
  
  let basePayload = { data_type: dataType };
  
  if (dateRange === 'custom') {
    basePayload.start_date = document.getElementById('fetchStartDate').value;
    basePayload.end_date = document.getElementById('fetchEndDate').value;
    if (!basePayload.start_date || !basePayload.end_date) {
      showToast('Please select start and end dates', 'error');
      return;
    }
  } else {
    basePayload.days = parseInt(dateRange);
  }
  
  // Get selected affiliates and campaigns
  const affiliates = Array.from(selectedFetchAffiliates);
  const campaigns = Array.from(selectedFetchCampaigns);
  
  // Generate fetch combinations
  const fetchTasks = [];
  
  if (affiliates.length === 0 && campaigns.length === 0) {
    // No filters - single fetch
    fetchTasks.push({ ...basePayload });
  } else if (affiliates.length > 0 && campaigns.length === 0) {
    // Only affiliates selected
    affiliates.forEach(aff => {
      fetchTasks.push({ 
        ...basePayload, 
        filters: { webmaster_code: aff },
        _label: `Affiliate: ${aff}`
      });
    });
  } else if (affiliates.length === 0 && campaigns.length > 0) {
    // Only campaigns selected
    campaigns.forEach(camp => {
      fetchTasks.push({ 
        ...basePayload, 
        filters: { campaign: camp },
        _label: `Campaign: ${camp}`
      });
    });
  } else {
    // Both affiliates and campaigns - fetch combinations
    affiliates.forEach(aff => {
      campaigns.forEach(camp => {
        fetchTasks.push({ 
          ...basePayload, 
          filters: { webmaster_code: aff, campaign: camp },
          _label: `${aff} / ${camp}`
        });
      });
    });
  }
  
  if (fetchTasks.length > 50) {
    if (!confirm(`This will create ${fetchTasks.length} API requests. This may take a while. Continue?`)) {
      return;
    }
  }
  
  btn.classList.add('loading');
  document.getElementById('fetchBtnText').textContent = 'Fetching...';
  statusEl.className = 'action-status running';
  
  // Build status message
  let statusMsg = `Fetching ${fetchTasks.length} batch${fetchTasks.length > 1 ? 'es' : ''}`;
  if (affiliates.length > 0) statusMsg += ` (${affiliates.length} affiliate${affiliates.length > 1 ? 's' : ''})`;
  if (campaigns.length > 0) statusMsg += ` (${campaigns.length} campaign${campaigns.length > 1 ? 's' : ''})`;
  statusMsg += '...';
  statusEl.textContent = statusMsg;
  
  try {
    // Execute fetches sequentially to avoid overwhelming the API
    let totalNew = { free: 0, paid: 0 };
    let totalDuplicates = { free: 0, paid: 0 };
    let completed = 0;
    let failed = 0;
    const fetchErrors = [];
    
    for (const task of fetchTasks) {
      const label = task._label || 'data';
      delete task._label;  // Remove label before sending
      
      statusEl.textContent = `Fetching ${label}... (${completed + 1}/${fetchTasks.length})`;
      
      try {
        const r = await fetch('/api/fetch-data', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(task)
        });
        const data = await r.json();
        
        if (r.ok) {
          // Poll for completion of this individual fetch
          const result = await pollSingleFetch();
          const results = result.results || {};
          
          if (result.status === 'completed' || result.status === 'completed_with_errors') {
            for (const [type, typeData] of Object.entries(results)) {
              if (!typeData.error) {
                if (type === 'free') {
                  totalNew.free += typeData.inserted || 0;
                  totalDuplicates.free += typeData.duplicates || 0;
                } else if (type === 'paid') {
                  totalNew.paid += typeData.inserted || 0;
                  totalDuplicates.paid += typeData.duplicates || 0;
                }
              } else {
                console.error(`API error for ${label} [${type}]:`, typeData.error);
                fetchErrors.push(`${label} (${type}): ${typeData.error}`);
                failed++;
              }
            }
            if (result.status === 'completed') completed++;
          } else {
            failed++;
            const errMsg = result.error || 'Unknown error';
            console.error(`Fetch failed for ${label}:`, errMsg);
            fetchErrors.push(`${label}: ${errMsg}`);
          }
        } else {
          failed++;
          const errMsg = data.error || `HTTP ${r.status}`;
          console.error(`Failed to fetch ${label}:`, errMsg);
          fetchErrors.push(`${label}: ${errMsg}`);
        }
      } catch (e) {
        failed++;
        console.error(`Error fetching ${label}:`, e);
        fetchErrors.push(`${label}: ${e.message}`);
      }
      
      // Small delay between requests
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    
    // Show final results
    btn.classList.remove('loading');
    document.getElementById('fetchBtnText').textContent = 'Start Fetch';
    statusEl.className = completed > 0 || fetchErrors.length === 0 ? 'action-status success' : 'action-status error';
    
    let msg = `Fetch complete! `;
    if (totalNew.free > 0 || totalDuplicates.free > 0) {
      msg += `free: ${totalNew.free} new, ${totalDuplicates.free} duplicates. `;
    }
    if (totalNew.paid > 0 || totalDuplicates.paid > 0) {
      msg += `paid: ${totalNew.paid} new, ${totalDuplicates.paid} duplicates. `;
    }
    if (failed > 0) {
      msg += `(${failed} failed)`;
    }

    if (fetchErrors.length > 0) {
      statusEl.className = failed > 0 && completed === 0 ? 'action-status error' : 'action-status success';
      statusEl.innerHTML = `<div>${msg}</div>` + fetchErrors.map(e => `<div>⚠️ ${e}</div>`).join('');
      showToast('Fetch completed with errors — see details below', 'error');
    } else {
      statusEl.textContent = msg;
      showToast(`Completed ${completed}/${fetchTasks.length} fetches!`);
    }

    addActivity('fetch', msg + (fetchErrors.length ? ' Errors: ' + fetchErrors.join('; ') : ''));
    
    if (currentTab === 'overview' || currentTab === 'review') {
      clearApiCache();
      loadTabData(currentTab);
    }
    
  } catch (e) {
    btn.classList.remove('loading');
    document.getElementById('fetchBtnText').textContent = 'Start Fetch';
    statusEl.className = 'action-status error';
    statusEl.textContent = 'Network error: ' + e.message;
  }
}

// Poll a single fetch operation until completion
async function pollSingleFetch() {
  // Wait briefly to allow the server thread to set status to 'running'
  await new Promise(resolve => setTimeout(resolve, 300));
  return new Promise((resolve) => {
    let seenRunning = false;
    const poll = async () => {
      try {
        const r = await fetch('/api/fetch-status');
        const status = await r.json();
        
        if (status.status === 'running') {
          seenRunning = true;
          setTimeout(poll, 1000);
        } else if (status.status === 'completed' || status.status === 'completed_with_errors' || status.status === 'error') {
          resolve(status);
        } else {
          // idle or stale previous status — keep waiting if we haven't seen 'running' yet
          if (seenRunning) {
            resolve(status);
          } else {
            setTimeout(poll, 500);
          }
        }
      } catch (e) {
        resolve({ status: 'error', error: e.message });
      }
    };
    poll();
  });
}

async function pollFetchStatus() {
  const btn = document.getElementById('btnFetch');
  const statusEl = document.getElementById('fetchStatus');
  const progressContainer = document.getElementById('fetchProgress');
  const progressFill = document.getElementById('fetchProgressFill');
  const progressText = document.getElementById('fetchProgressText');
  const progressPct = document.getElementById('fetchProgressPct');
  
  try {
    const r = await fetch('/api/fetch-status');
    const status = await r.json();
    
    if (status.status === 'running') {
      const progress = status.progress || 0;
      const currentType = status.current_type || 'data';
      
      progressContainer.classList.add('visible');
      progressFill.style.width = progress + '%';
      progressText.textContent = `Fetching ${currentType}...`;
      progressPct.textContent = progress + '%';
      statusEl.textContent = 'Fetching data... This may take a minute.';
      
      setTimeout(pollFetchStatus, 1500);
    } else if (status.status === 'completed' || status.status === 'completed_with_errors') {
      btn.classList.remove('loading');
      document.getElementById('fetchBtnText').textContent = 'Start Fetch';
      progressContainer.classList.remove('visible');

      const results = status.results || {};
      const hasErrors = status.status === 'completed_with_errors';

      let msg = 'Fetch complete! ';
      const errorLines = [];
      for (const [type, data] of Object.entries(results)) {
        if (data.error) {
          errorLines.push(`${type}: API error — ${data.error}`);
        } else {
          msg += `${type}: ${data.inserted} new, ${data.duplicates} duplicates. `;
        }
      }

      if (errorLines.length > 0) {
        statusEl.className = 'action-status error';
        statusEl.innerHTML = (msg !== 'Fetch complete! ' ? `<div>${msg}</div>` : '') +
          errorLines.map(l => `<div>⚠️ ${l}</div>`).join('');
        showToast('Fetch completed with errors — check the platform API', 'error');
      } else {
        statusEl.className = 'action-status success';
        statusEl.textContent = msg;
        showToast('Data fetch completed!');
      }

      addActivity('fetch', msg + errorLines.join(' '));
      
      // Clear status after delay
      fetch('/api/clear-task-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: 'fetch' })
      });
      
      if (currentTab === 'overview' || currentTab === 'review') {
        clearApiCache();
        loadTabData(currentTab);
      }
      
    } else if (status.status === 'error') {
      btn.classList.remove('loading');
      document.getElementById('fetchBtnText').textContent = 'Start Fetch';
      statusEl.className = 'action-status error';
      statusEl.textContent = 'Error: ' + (status.error || 'Unknown error');
      progressContainer.classList.remove('visible');
      showToast('Fetch failed: ' + status.error, 'error');
    }
  } catch (e) {
    btn.classList.remove('loading');
    document.getElementById('fetchBtnText').textContent = 'Start Fetch';
    progressContainer.classList.remove('visible');
  }
}

async function startAnalysis() {
  const btn = document.getElementById('btnAnalysis');
  const statusEl = document.getElementById('analysisStatus');
  
  if (btn.classList.contains('loading')) return;
  
  const scope = document.getElementById('analysisScope').value;
  const houseFilter = document.getElementById('analysisHouseFilter').value;
  
  // Get selected affiliates and campaigns
  const affiliates = Array.from(selectedAnalysisAffiliates);
  const campaigns = Array.from(selectedAnalysisCampaigns);
  
  // Get date range
  const dateRange = document.getElementById('analysisDateRange').value;
  let startDate = null;
  let endDate = null;
  
  if (dateRange === 'custom') {
    startDate = document.getElementById('analysisStartDate').value;
    endDate = document.getElementById('analysisEndDate').value;
    if (!startDate || !endDate) {
      showToast('Please select both start and end dates', 'error');
      return;
    }
  } else if (dateRange !== 'all') {
    const days = parseInt(dateRange);
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    startDate = start.toISOString().split('T')[0];
    endDate = end.toISOString().split('T')[0];
  }
  
  btn.classList.add('loading');
  document.getElementById('analysisBtnText').textContent = 'Analyzing...';
  statusEl.className = 'action-status running';
  
  // Build status message
  let statusMsg = 'Running fraud detection analysis';
  if (affiliates.length > 0) statusMsg += ` (${affiliates.length} affiliate${affiliates.length > 1 ? 's' : ''})`;
  if (campaigns.length > 0) statusMsg += ` (${campaigns.length} campaign${campaigns.length > 1 ? 's' : ''})`;
  if (startDate && endDate) statusMsg += ` (${startDate} to ${endDate})`;
  statusMsg += '...';
  statusEl.textContent = statusMsg;
  
  try {
    const payload = { 
      analyze_all: scope === 'all',
      include_house: houseFilter === 'include'
    };
    
    // Add date range if specified
    if (startDate && endDate) {
      payload.start_date = startDate;
      payload.end_date = endDate;
    }
    
    // Add filters if selected
    if (affiliates.length > 0 || campaigns.length > 0) {
      payload.filters = {};
      if (affiliates.length > 0) payload.filters.affiliates = affiliates;
      if (campaigns.length > 0) payload.filters.campaigns = campaigns;
    }
    
    const r = await fetch('/api/run-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await r.json();
    
    if (r.ok) {
      pollAnalysisStatus();
    } else {
      btn.classList.remove('loading');
      document.getElementById('analysisBtnText').textContent = 'Start Analysis';
      statusEl.className = 'action-status error';
      statusEl.textContent = data.error || 'Failed to start analysis';
    }
  } catch (e) {
    btn.classList.remove('loading');
    document.getElementById('analysisBtnText').textContent = 'Start Analysis';
    statusEl.className = 'action-status error';
    statusEl.textContent = 'Network error: ' + e.message;
  }
}

async function pollAnalysisStatus() {
  const btn = document.getElementById('btnAnalysis');
  const statusEl = document.getElementById('analysisStatus');
  const progressContainer = document.getElementById('analysisProgress');
  const progressFill = document.getElementById('analysisProgressFill');
  const progressText = document.getElementById('analysisProgressText');
  const progressPct = document.getElementById('analysisProgressPct');
  
  try {
    const r = await fetch('/api/analysis-status');
    const status = await r.json();
    
    if (status.status === 'running') {
      const progress = status.progress || 0;
      const currentType = status.current_type || 'records';
      const processed = status.records_processed || 0;
      
      progressContainer.classList.add('visible');
      progressFill.style.width = progress + '%';
      progressText.textContent = `Analyzing ${currentType}... ${processed > 0 ? fmt(processed) + ' records' : ''}`;
      progressPct.textContent = progress + '%';
      statusEl.textContent = 'Analyzing records... This may take a moment.';
      
      setTimeout(pollAnalysisStatus, 1500);
    } else if (status.status === 'completed') {
      btn.classList.remove('loading');
      document.getElementById('analysisBtnText').textContent = 'Start Analysis';
      statusEl.className = 'action-status success';
      progressContainer.classList.remove('visible');
      
      const results = status.results || {};
      let msg = `Analysis complete! Free: ${results.free || 0}, Paid: ${results.paid || 0}, High Risk: ${results.high_risk || 0}`;
      if (results.house_skipped > 0) {
        msg += ` (${results.house_skipped} house records skipped)`;
      }
      if (results.duid_filtered > 0) {
        msg += ` (${results.duid_filtered} older accounts filtered)`;
      }
      statusEl.textContent = msg;
      
      addActivity('analysis', msg);
      showToast('Fraud analysis completed!');
      
      // Clear status
      fetch('/api/clear-task-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: 'analysis' })
      });
      
      if (currentTab === 'overview' || currentTab === 'review') {
        clearApiCache();
        loadTabData(currentTab);
      }
      
    } else if (status.status === 'error') {
      btn.classList.remove('loading');
      document.getElementById('analysisBtnText').textContent = 'Start Analysis';
      statusEl.className = 'action-status error';
      statusEl.textContent = 'Error: ' + (status.error || 'Unknown error');
      progressContainer.classList.remove('visible');
      showToast('Analysis failed: ' + status.error, 'error');
    }
  } catch (e) {
    btn.classList.remove('loading');
    document.getElementById('analysisBtnText').textContent = 'Start Analysis';
    progressContainer.classList.remove('visible');
  }
}

function addActivity(type, message) {
  const time = new Date().toLocaleTimeString();
  const timestamp = new Date().toISOString();
  activityLog.unshift({ type, message, time, timestamp });
  if (activityLog.length > 50) activityLog.pop();
  
  // Persist to localStorage
  try {
    localStorage.setItem('fd-activity-log', JSON.stringify(activityLog));
  } catch (e) {
    console.warn('Could not save activity log:', e);
  }
  
  renderActivity();
}

function loadActivityLog() {
  try {
    const saved = localStorage.getItem('fd-activity-log');
    if (saved) {
      activityLog = JSON.parse(saved);
      // Filter out entries older than 7 days
      const weekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
      activityLog = activityLog.filter(a => {
        if (!a.timestamp) return false;
        return new Date(a.timestamp).getTime() > weekAgo;
      });
      renderActivity();
    }
  } catch (e) {
    console.warn('Could not load activity log:', e);
    activityLog = [];
  }
}

function clearActivityLog() {
  activityLog = [];
  localStorage.removeItem('fd-activity-log');
  renderActivity();
  showToast('Activity log cleared');
}

function renderActivity() {
  const el = document.getElementById('recentActivity');
  if (!el) return;

  if (activityLog.length === 0) {
    el.innerHTML = '<div class="activity-empty">No recent actions</div>';
    return;
  }

  const today = new Date().toDateString();

  el.innerHTML = activityLog.map(a => {
    // Build the time label — show full date if not today
    let timeLabel = a.time;
    if (a.timestamp) {
      const d = new Date(a.timestamp);
      if (d.toDateString() !== today) {
        timeLabel = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                  + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      }
    }
    return `
    <div class="activity-item">
      <span class="activity-time" title="${a.timestamp || ''}">${timeLabel}</span>
      <span class="activity-type ${a.type}">${a.type.toUpperCase()}</span>
      ${a.message}
    </div>`;
  }).join('') + `
    <div style="text-align:center;padding:8px;">
      <button class="btn btn-sm btn-cancel" onclick="clearActivityLog()">Clear Log</button>
    </div>
  `;
}

// ═══ NAV GROUPS ═══
function toggleNavGroup(header) {
  const group = header.closest('.nav-group');
  group.classList.toggle('expanded');
}

function initNavGroups() {
  // Expand all nav groups by default
  document.querySelectorAll('.nav-group').forEach(g => g.classList.add('expanded'));
}

// ═══ COMMAND PALETTE ═══
let commandSelectedIndex = 0;
let commandItems = [];

function openCommandPalette() {
  const overlay = document.getElementById('commandPalette');
  const input = document.getElementById('commandInput');
  overlay.classList.add('open');
  input.value = '';
  input.focus();
  filterCommands('');
  closeFabMenu();
}

function closeCommandPalette() {
  document.getElementById('commandPalette').classList.remove('open');
  commandSelectedIndex = 0;
}

function filterCommands(query) {
  const items = document.querySelectorAll('#commandResults .command-item');
  const q = query.toLowerCase().trim();
  commandItems = [];

  items.forEach(item => {
    const text = item.textContent.toLowerCase();
    const match = !q || text.includes(q);
    item.style.display = match ? '' : 'none';
    if (match) commandItems.push(item);
  });

  // Update selection
  commandSelectedIndex = 0;
  updateCommandSelection();

  // Show/hide empty groups
  document.querySelectorAll('#commandResults .command-group').forEach(group => {
    const visibleItems = group.querySelectorAll('.command-item[style=""], .command-item:not([style])');
    const hasVisible = Array.from(visibleItems).some(i => i.style.display !== 'none');
    group.style.display = hasVisible ? '' : 'none';
  });
}

function updateCommandSelection() {
  commandItems.forEach((item, i) => {
    item.classList.toggle('selected', i === commandSelectedIndex);
  });
  if (commandItems[commandSelectedIndex]) {
    commandItems[commandSelectedIndex].scrollIntoView({ block: 'nearest' });
  }
}

function executeCommand(action) {
  closeCommandPalette();

  if (action.startsWith('nav:')) {
    const tab = action.replace('nav:', '');
    switchTab(tab);
  } else if (action.startsWith('action:')) {
    const act = action.replace('action:', '');
    switch(act) {
      case 'fetch': startFetch(); break;
      case 'analyze': startAnalysis(); break;
      case 'export': exportHighRisk(); break;
      case 'refresh': clearApiCache(); loadTabData(currentTab); break;
    }
  } else if (action.startsWith('toggle:')) {
    const toggle = action.replace('toggle:', '');
    switch(toggle) {
      case 'theme': toggleTheme(); break;
      case 'refresh': toggleAutoRefresh(); break;
    }
  }
}

// Command palette keyboard handling
document.addEventListener('keydown', e => {
  const overlay = document.getElementById('commandPalette');
  const isOpen = overlay.classList.contains('open');

  // Open with Cmd+K or Ctrl+K
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    if (isOpen) closeCommandPalette();
    else openCommandPalette();
    return;
  }

  if (!isOpen) return;

  switch(e.key) {
    case 'Escape':
      e.preventDefault();
      closeCommandPalette();
      break;
    case 'ArrowDown':
      e.preventDefault();
      commandSelectedIndex = Math.min(commandSelectedIndex + 1, commandItems.length - 1);
      updateCommandSelection();
      break;
    case 'ArrowUp':
      e.preventDefault();
      commandSelectedIndex = Math.max(commandSelectedIndex - 1, 0);
      updateCommandSelection();
      break;
    case 'Enter':
      e.preventDefault();
      if (commandItems[commandSelectedIndex]) {
        executeCommand(commandItems[commandSelectedIndex].dataset.action);
      }
      break;
  }
});

// Command palette input handling
document.getElementById('commandInput')?.addEventListener('input', e => {
  filterCommands(e.target.value);
});

// Command palette click handling
document.getElementById('commandResults')?.addEventListener('click', e => {
  const item = e.target.closest('.command-item');
  if (item) executeCommand(item.dataset.action);
});

// Close command palette on overlay click
document.getElementById('commandPalette')?.addEventListener('click', e => {
  if (e.target.classList.contains('command-palette-overlay')) {
    closeCommandPalette();
  }
});

// ═══ FAB (Floating Action Button) ═══
let fabOpen = false;

function toggleFabMenu() {
  fabOpen = !fabOpen;
  const fab = document.getElementById('fabMain');
  const menu = document.getElementById('fabMenu');
  fab.classList.toggle('open', fabOpen);
  menu.classList.toggle('open', fabOpen);
}

function closeFabMenu() {
  fabOpen = false;
  document.getElementById('fabMain')?.classList.remove('open');
  document.getElementById('fabMenu')?.classList.remove('open');
}

function fabAction(action) {
  closeFabMenu();

  switch(action) {
    case 'mark-fraud':
      bulkMarkAs('confirmed_fraud');
      break;

    case 'mark-fp':
      bulkMarkAs('false_positive');
      break;

    case 'export':
      exportHighRisk();
      break;
  }
}

// Close FAB menu on outside click
document.addEventListener('click', e => {
  if (fabOpen && !e.target.closest('.fab-container')) {
    closeFabMenu();
  }
});

// ═══ KEYBOARD SHORTCUTS (G + key for navigation) ═══
let lastKeyTime = 0;
let lastKey = '';

document.addEventListener('keydown', e => {
  // Skip if typing in input/textarea
  if (e.target.matches('input, textarea, select')) return;

  const now = Date.now();
  const timeSinceLastKey = now - lastKeyTime;

  // G + key shortcuts (within 500ms)
  if (lastKey === 'g' && timeSinceLastKey < 500) {
    switch(e.key.toLowerCase()) {
      case 'o': switchTab('overview'); break;
      case 'q': switchTab('review'); break;
      case 'a': switchTab('affiliates'); break;
      case 'c': switchTab('campaigns'); break;
      case 't': switchTab('temporal'); break;
      case 's': switchTab('settings'); break;
    }
    lastKey = '';
    return;
  }

  // Single key shortcuts
  switch(e.key.toLowerCase()) {
    case 'g':
      lastKey = 'g';
      lastKeyTime = now;
      break;
    case 'r':
      if (!e.metaKey && !e.ctrlKey) {
        loadTabData(currentTab);
        showToast('Refreshed');
      }
      break;
    case 't':
      if (!e.metaKey && !e.ctrlKey) {
        toggleTheme();
      }
      break;
    case '/':
      e.preventDefault();
      document.getElementById('globalSearchInput')?.focus();
      break;
  }
});

// ─── Admin Enrichment ─────────────────────────────────────────────────────────
let _enrichPollTimer = null;

async function startEnrichment() {
  const btn = document.getElementById('btnEnrich');
  const statusEl = document.getElementById('enrichStatus');
  const progressEl = document.getElementById('enrichProgress');
  const fillEl = document.getElementById('enrichProgressFill');
  const textEl = document.getElementById('enrichProgressText');
  const pctEl = document.getElementById('enrichProgressPct');
  const lastRunOnly = document.getElementById('enrichLastRunOnly')?.checked ?? true;
  const force = document.getElementById('enrichForce')?.checked ?? false;
  if (!btn || btn.classList.contains('loading')) return;

  btn.classList.add('loading');
  document.getElementById('enrichBtnText').textContent = 'Starting…';
  statusEl.style.display = 'none';

  // Show progress bar immediately so user knows something is happening
  progressEl.style.display = 'block';
  if (fillEl) fillEl.style.width = '0%';
  if (textEl) textEl.textContent = 'Contacting admin API…';
  if (pctEl) pctEl.textContent = '0%';

  try {
    const res = await fetch('/api/enrich', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_run_only: lastRunOnly, force: force })
    });
    const data = await res.json();
    if (!res.ok) {
      progressEl.style.display = 'none';
      statusEl.textContent = data.error || 'Failed to start enrichment';
      statusEl.className = 'action-status error';
      statusEl.style.display = 'block';
      btn.classList.remove('loading');
      document.getElementById('enrichBtnText').textContent = '⚡ Run Enrichment';
      return;
    }
    // Update count display immediately from response
    const countEl = document.getElementById('enrichLastRunCount');
    if (countEl && data.total) countEl.textContent = `(${data.total.toLocaleString()} accounts)`;
    if (textEl) textEl.textContent = `Queued ${(data.total || 0).toLocaleString()} accounts…`;
    document.getElementById('enrichBtnText').textContent = 'Enriching…';
    pollEnrichment();
  } catch (e) {
    progressEl.style.display = 'none';
    statusEl.textContent = 'Request failed: ' + e.message;
    statusEl.className = 'action-status error';
    statusEl.style.display = 'block';
    btn.classList.remove('loading');
    document.getElementById('enrichBtnText').textContent = '⚡ Run Enrichment';
  }
}

async function pollEnrichment() {
  const btn = document.getElementById('btnEnrich');
  const statusEl = document.getElementById('enrichStatus');
  const progressEl = document.getElementById('enrichProgress');
  const fillEl = document.getElementById('enrichProgressFill');
  const textEl = document.getElementById('enrichProgressText');
  const pctEl = document.getElementById('enrichProgressPct');
  const hintEl = document.getElementById('enrichHint');

  clearTimeout(_enrichPollTimer);

  try {
    const res = await fetch('/api/enrich/status');
    const data = await res.json();
    const status = data.status || 'idle';
    const backlog = data.backlog ?? null;

    // Always update backlog hint
    if (hintEl && backlog !== null) {
      if (backlog === 0) {
        hintEl.textContent = 'All accounts enriched.';
      } else {
        hintEl.textContent = `${backlog.toLocaleString()} account${backlog !== 1 ? 's' : ''} waiting to be enriched. High-risk accounts are processed first.`;
      }
    }
    // Show last-run count if available
    const countEl = document.getElementById('enrichLastRunCount');
    if (countEl && data.total && (data.status === 'running' || data.last_run_only)) {
      countEl.textContent = `(${data.total.toLocaleString()} accounts)`;
    }

    if (status === 'running') {
      const total = data.total || 0;
      const done = data.done || 0;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      progressEl.style.display = 'block';
      statusEl.style.display = 'none';
      if (fillEl) fillEl.style.width = pct + '%';
      if (textEl) textEl.textContent = total > 0 ? `Enriching ${done} / ${total}…` : 'Waiting for accounts…';
      if (pctEl) pctEl.textContent = pct + '%';
      document.getElementById('enrichBtnText').textContent = 'Enriching…';
      _enrichPollTimer = setTimeout(pollEnrichment, 2000);

    } else if (status === 'completed') {
      progressEl.style.display = 'none';
      const remaining = backlog !== null && backlog > 0 ? ` — ${backlog.toLocaleString()} still in queue` : '';
      statusEl.textContent = `✓ Pass complete — ${data.enriched ?? 0} enriched, ${data.errors ?? 0} errors${remaining}`;
      statusEl.className = 'action-status success';
      statusEl.style.display = 'block';
      btn.classList.remove('loading');
      document.getElementById('enrichBtnText').textContent = '⚡ Run Enrichment';

    } else if (status === 'error') {
      progressEl.style.display = 'none';
      statusEl.textContent = '✗ Enrichment failed: ' + (data.error || 'unknown error');
      statusEl.className = 'action-status error';
      statusEl.style.display = 'block';
      btn.classList.remove('loading');
      document.getElementById('enrichBtnText').textContent = '⚡ Run Enrichment';

    } else {
      // idle — if button is still in loading state, we just started: keep polling briefly
      if (btn && btn.classList.contains('loading')) {
        _enrichPollTimer = setTimeout(pollEnrichment, 1000);
      } else {
        progressEl.style.display = 'none';
        btn.classList.remove('loading');
        document.getElementById('enrichBtnText').textContent = '⚡ Run Enrichment';
      }
    }
  } catch (e) {
    _enrichPollTimer = setTimeout(pollEnrichment, 3000);
  }
}

// Resume polling if enrichment was running on page load
(async () => {
  try {
    const res = await fetch('/api/enrich/status');
    const data = await res.json();
    if (data.status === 'running') pollEnrichment();
    else if (data.status === 'completed') {
      const statusEl = document.getElementById('enrichStatus');
      if (statusEl) {
        statusEl.textContent = `✓ Last enrichment: ${data.enriched ?? 0} accounts enriched`;
        statusEl.className = 'action-status success';
        statusEl.style.display = 'block';
      }
    }
  } catch (_) {}
})();

// ═══ INIT ═══
initTheme();
initNavGroups();
loadActivityLog();
(async () => {
  await loadHouseAffiliates();
  loadTabData('overview');
})();
api('/api/scheduler/status')
  .then((res) => {
    if (res.data) updateSchedulerHealthBanner(res.data);
  })
  .catch(() => {});

// Close shortcuts panel on outside click
document.addEventListener('click', e => {
  const panel = document.getElementById('shortcutsPanel');
  const toggle = e.target.closest('.shortcuts-toggle');
  if (!toggle && panel.classList.contains('open') && !panel.contains(e.target)) {
    panel.classList.remove('open');
  }
});