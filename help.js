const schemas = { capture: 'road_capture', insurance: 'insurance_policy', registry: 'vehicle_registration', cases: 'theft_scrap_case', ministry: 'ministry_report' };
const navigation = document.querySelector('.main-nav');
if (navigation && !navigation.querySelector('a[href="audit.html"]')) navigation.insertAdjacentHTML('beforeend', '<a href="audit.html">History</a>');
const sourceList = document.getElementById('source-list');
const schemaList = document.getElementById('schema-list');
const guide = document.createElement('section');
guide.className = 'panel feature-guide';
guide.style.marginTop = '16px';
guide.innerHTML = '<p class="eyebrow">DEMO GUIDE / CORE FEATURES</p><h2>What you can demonstrate</h2><div class="page-grid"><div><h3>Inspect</h3><p class="muted">Enter a plate to combine roadside, registration, insurance, and case evidence into one decision.</p><h3>Run SQL</h3><p class="muted">Run read-only SELECT or WITH queries across live source snapshots, limited to 200 rows.</p><h3>Manage data</h3><p class="muted">Create or delete a row on its owning source after reviewing the generated SQL.</p></div><div><h3>History</h3><p class="muted">Review reads and writes, see the affected database, and undo a successful insert or delete once.</p><h3>Distributed flow</h3><p class="muted">The gateway forwards changes to the laptop that owns the database. The next lookup fetches fresh data.</p><h3>Decision logic</h3><p class="muted">The result explains whether the vehicle is clear, uninsured, expired, unresolved, stolen, or scrapped.</p></div></div>';
document.querySelector('main').appendChild(guide);
fetch('/api/schemas').then((response) => response.json()).then((data) => {
  sourceList.innerHTML = Object.entries(schemas).map(([alias, table]) => `<div class="source-row"><code>${alias}</code><span>${table}</span></div>`).join('');
  schemaList.innerHTML = Object.entries(data).map(([alias, columns]) => `<article class="schema-block"><div class="panel-heading"><h3><code>${alias}</code></h3><span class="source-badge">${schemas[alias]}</span></div><table class="schema-table"><thead><tr><th>ATTRIBUTE</th><th>TYPE</th><th>KEY</th></tr></thead><tbody>${columns.map((column) => `<tr><td><code>${column.name}</code></td><td>${column.type || 'TEXT'}</td><td>${column.pk ? 'PRIMARY KEY' : column.notnull ? 'REQUIRED' : 'OPTIONAL'}</td></tr>`).join('')}</tbody></table></article>`).join('');
}).catch(() => { schemaList.textContent = 'Schema metadata is unavailable. Start python3 server.py first.'; });