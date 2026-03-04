/* ===== Auth helpers ===== */

function getKey() {
  const key = sessionStorage.getItem('adminKey');
  if (!key) {
    window.location.href = '/dashboard/login.html';
    return null;
  }
  return key;
}

async function apiFetch(path, params = {}) {
  const key = getKey();
  if (!key) return null;

  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  });

  const res = await fetch(url.toString(), {
    headers: { 'X-Api-Key': key },
  });

  if (res.status === 403 || res.status === 401) {
    sessionStorage.removeItem('adminKey');
    window.location.href = '/dashboard/login.html';
    return null;
  }

  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

/* ===== Nav ===== */

function renderNav(active) {
  const nav = document.createElement('nav');
  nav.className = 'nav';
  nav.innerHTML = `
    <span class="nav-brand">HVAC Admin</span>
    <a href="/dashboard/index.html" class="nav-link ${active === 'overview' ? 'active' : ''}">Overview</a>
    <a href="/dashboard/calls.html" class="nav-link ${active === 'calls' ? 'active' : ''}">Call Log</a>
    <span class="nav-spacer"></span>
    <button class="nav-logout" onclick="logout()">Sign out</button>
  `;
  document.body.prepend(nav);
}

function logout() {
  sessionStorage.removeItem('adminKey');
  window.location.href = '/dashboard/login.html';
}

/* ===== Formatting helpers ===== */

function fmtDuration(sec) {
  if (sec === null || sec === undefined) return '—';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function resolutionBadge(r) {
  if (!r) return '<span class="badge badge-gray">—</span>';
  const map = {
    resolved: 'badge-green',
    abandoned: 'badge-red',
    transferred: 'badge-blue',
    escalated: 'badge-yellow',
  };
  return `<span class="badge ${map[r] || 'badge-gray'}">${r}</span>`;
}

function safetyBadge(flag) {
  return flag
    ? '<span class="badge badge-red">⚠ Safety</span>'
    : '';
}
