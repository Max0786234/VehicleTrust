const input = document.getElementById('sql-input');
const navigation = document.querySelector('.main-nav');
if (navigation && !navigation.querySelector('a[href="audit.html"]')) navigation.insertAdjacentHTML('beforeend', '<a href="audit.html">History</a>');
const output = document.getElementById('sql-output');
const count = document.getElementById('result-count');
const escapeHtml = (value) => String(value ?? '—').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
const renderTable = (rows) => {
  if (!rows.length) return '<p class="empty-state">The query returned no rows.</p>';
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return `<div class="table-scroll"><table class="data-table"><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
};
document.getElementById('run-sql').addEventListener('click', async () => {
  output.textContent = 'Running query...';
  count.textContent = 'RUNNING';
  try {
    if (!input.value.trim()) throw new Error('Enter a SELECT or WITH query first.');
    const response = await fetch(`/api/query?sql=${encodeURIComponent(input.value)}`);
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
    if (!Array.isArray(payload.rows)) throw new Error('The gateway returned an invalid query response.');
    output.innerHTML = renderTable(payload.rows); count.textContent = `${payload.rows.length} ROWS`;
  } catch (error) {
    output.textContent = error.message || 'Query failed. Check the gateway and source services.'; count.textContent = 'ERROR';
  }
});