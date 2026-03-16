/* ===== Auth helpers ===== */

function getKey() {
  const key = sessionStorage.getItem('adminKey');
  if (!key) {
    window.location.href = '/dashboard/login.html';
    return null;
  }
  return key;
}

async function apiFetch(path, params = {}, method = 'GET', queryParams = {}) {
  const key = getKey();
  if (!key) return null;

  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  });
  Object.entries(queryParams).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  });

  const res = await fetch(url.toString(), {
    method,
    headers: { 'X-Api-Key': key },
  });

  if (res.status === 403 || res.status === 401) {
    sessionStorage.removeItem('adminKey');
    window.location.href = '/dashboard/login.html';
    return null;
  }

  if (!res.ok) {
    let detail = `API error ${res.status}`;
    try { const body = await res.json(); detail = body.detail || detail; } catch {}
    throw new Error(detail);
  }
  if (res.status === 204 || res.headers.get('content-length') === '0') return null;
  return res.json();
}

async function apiJson(path, body, method = 'POST') {
  const key = getKey();
  if (!key) return null;

  const res = await fetch(new URL(path, window.location.origin).toString(), {
    method,
    headers: { 'X-Api-Key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (res.status === 403 || res.status === 401) {
    sessionStorage.removeItem('adminKey');
    window.location.href = '/dashboard/login.html';
    return null;
  }

  if (!res.ok) {
    let detail = `API error ${res.status}`;
    try { const b = await res.json(); detail = b.detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function apiUpload(path, formData) {
  const key = getKey();
  if (!key) return null;

  const res = await fetch(new URL(path, window.location.origin).toString(), {
    method: 'POST',
    headers: { 'X-Api-Key': key },
    body: formData,
  });

  if (res.status === 403 || res.status === 401) {
    sessionStorage.removeItem('adminKey');
    window.location.href = '/dashboard/login.html';
    return null;
  }

  if (!res.ok) {
    let detail = `API error ${res.status}`;
    try { const body = await res.json(); detail = body.detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/* ===== Nav ===== */

function renderNav(active) {
  document.body.classList.add('has-sidebar');
  const sidebar = document.createElement('aside');
  sidebar.className = 'sidebar';
  sidebar.innerHTML = `
    <div class="sidebar-brand">HVAC Admin</div>
    <nav class="sidebar-nav">
      <a href="/dashboard/index.html" class="sidebar-link ${active === 'overview' ? 'active' : ''}">Overview</a>

      <div class="sidebar-section">Calls</div>
      <a href="/dashboard/calls.html" class="sidebar-link ${active === 'calls' ? 'active' : ''}">Call Log</a>
      <a href="/dashboard/metrics.html" class="sidebar-link ${active === 'metrics' ? 'active' : ''}">Metrics</a>

      <div class="sidebar-section">Customers</div>
      <a href="/dashboard/customers.html" class="sidebar-link ${active === 'customers' ? 'active' : ''}">Customers</a>
      <a href="/dashboard/deletion-requests.html" class="sidebar-link ${active === 'deletion-requests' ? 'active' : ''}">Deletion Requests</a>

      <div class="sidebar-section">Agent</div>
      <a href="/dashboard/knowledge.html" class="sidebar-link ${active === 'knowledge' ? 'active' : ''}">Knowledge Base</a>
      <a href="/dashboard/locations.html" class="sidebar-link ${active === 'locations' ? 'active' : ''}">Service Directory</a>
      <a href="/dashboard/chat.html" class="sidebar-link ${active === 'chat' ? 'active' : ''}">Chat</a>
      <a href="/dashboard/prompt.html" class="sidebar-link ${active === 'prompt' ? 'active' : ''}">Prompt</a>
      <a href="/dashboard/settings.html" class="sidebar-link ${active === 'settings' ? 'active' : ''}">Settings</a>
    </nav>
    <div class="sidebar-footer">
      <button class="sidebar-signout" onclick="logout()">Sign out</button>
    </div>
  `;
  document.body.prepend(sidebar);
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
