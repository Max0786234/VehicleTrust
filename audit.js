const historyList = document.getElementById('history-list');
const status = document.getElementById('history-status');
const nav = document.querySelector('.main-nav');
if (nav && !nav.querySelector('a[href="audit.html"]')) nav.insertAdjacentHTML('beforeend', '<a class="active" href="audit.html">History</a>');
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
const readableTime = (value) => value ? new Date(value).toLocaleString() : 'Unknown time';
const canUndo = (record) => ['INSERT', 'DELETE'].includes(record.operation) && Boolean(record.undo_sql) && !record.undone;

function render(records) {
  if (!records.length) { historyList.innerHTML = '<p class="empty-state">No activity has been recorded yet.</p>'; return; }
  historyList.innerHTML = records.slice().reverse().map((record) => `<article class="history-item">
    <div class="history-meta"><span class="source-badge">${escapeHtml(record.operation)}</span><time>${escapeHtml(readableTime(record.timestamp))}</time><span class="history-status ${record.status === 'SUCCESS' ? 'success' : 'failure'}">${escapeHtml(record.undone ? 'UNDONE' : record.status)}</span></div>
    <h3>${escapeHtml(record.database || 'Unknown database')}</h3>
    <p>${escapeHtml(record.source || 'federated')} · ${record.rows ?? record.changes ?? 0} ${record.operation === 'READ' ? 'rows' : 'change(s)'}</p>
    <code>${escapeHtml(record.sql || '')}</code>
    ${canUndo(record) ? `<button class="undo-action" data-id="${escapeHtml(record.id)}">Undo change</button>` : ''}
  </article>`).join('');
  historyList.querySelectorAll('.undo-action').forEach((button) => button.addEventListener('click', () => undo(button.dataset.id, button)));
}

async function loadHistory() {
  status.textContent = 'Loading activity...';
  try {
    const response = await fetch('/api/audit');
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
    render(Array.isArray(payload.records) ? payload.records : []);
    status.textContent = `${payload.records.length} recorded event(s).`;
  } catch (error) {
    historyList.innerHTML = `<p class="empty-state">${escapeHtml(error.message || 'History is unavailable.')}</p>`;
    status.textContent = 'Could not load history.';
  }
}

async function undo(id, button) {
  button.disabled = true;
  button.textContent = 'Undoing...';
  try {
    const response = await fetch('/api/audit/undo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
    await loadHistory();
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Undo change';
    status.textContent = error.message || 'Undo failed.';
  }
}

document.getElementById('refresh-history').addEventListener('click', loadHistory);
loadHistory();
