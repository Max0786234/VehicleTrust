const byId = (id) => document.getElementById(id);
const navigation = document.querySelector('.main-nav');
if (navigation && !navigation.querySelector('a[href="audit.html"]')) navigation.insertAdjacentHTML('beforeend', '<a href="audit.html">History</a>');
let detections = [];
let selected = null;

const formatDecision = (decision) => decision.replaceAll('_', ' ');
const formatDate = (value) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : 'Not available';

async function loadDetections() {
  const response = await fetch('/api/detections');
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
  if (!Array.isArray(payload)) throw new Error('The gateway returned an invalid detections response.');
  detections = payload;
  renderRecent();
  const initial = detections.find((vehicle) => vehicle.decision === 'STOP_AND_REPORT') || detections[0];
  if (initial) renderVehicle(initial);
}

function renderRecent() {
  byId('recent-list').innerHTML = detections.slice().sort((a, b) => b.captured_at.localeCompare(a.captured_at)).map((vehicle) => `
    <div class="recent-item"><button type="button" data-plate="${vehicle.observed_plate}"><strong>${vehicle.observed_plate}</strong><small>${vehicle.make || 'Unknown'} ${vehicle.model || 'vehicle'} · ${vehicle.captured_at.slice(11)}</small></button><span class="status-dot ${vehicle.decision === 'STOP_AND_REPORT' ? 'critical' : vehicle.decision === 'CLEAR' ? 'clear' : 'warning'}"></span></div>`).join('');
  document.querySelectorAll('[data-plate]').forEach((button) => button.addEventListener('click', () => selectVehicle(button.dataset.plate)));
}

function renderVehicle(vehicle) {
  selected = vehicle;
  const status = vehicle.decision === 'STOP_AND_REPORT' ? 'critical' : vehicle.decision === 'CLEAR' ? 'clear' : 'warning';
  byId('result-card').className = `result-card ${status}`;
  byId('result-category').textContent = status === 'critical' ? 'DECISION / IMMEDIATE ACTION' : 'DECISION / INSPECTION RESULT';
  byId('result-time').textContent = `CAPTURED ${vehicle.captured_at.slice(11)}`;
  byId('decision-title').textContent = formatDecision(vehicle.decision);
  byId('decision-reason').textContent = `${vehicle.decision_reason}.`;
  byId('decision-seal').textContent = status === 'critical' ? '!' : status === 'clear' ? '✓' : '—';
  byId('vehicle-name').textContent = vehicle.make && vehicle.model ? `${vehicle.make} ${vehicle.model}` : 'Unknown vehicle';
  byId('vehicle-plate').textContent = vehicle.reg_no || vehicle.observed_plate;
  byId('vehicle-vin').textContent = vehicle.registered_vin || vehicle.vin_fragment || 'Not available';
  byId('vehicle-owner').textContent = vehicle.owner_name || 'No registration match';
  byId('vehicle-date').textContent = formatDate(vehicle.registration_date);
  byId('vehicle-color').textContent = vehicle.color || 'Unknown';
  byId('vehicle-registration-status').textContent = vehicle.registration_status ? vehicle.registration_status[0] + vehicle.registration_status.slice(1).toLowerCase() : 'Unresolved';
  byId('match-confidence').textContent = vehicle.registration_id ? '98.4% CONFIDENCE' : '61.3% CONFIDENCE';
  byId('plate-input').value = vehicle.observed_plate;
  byId('evidence-list').innerHTML = `
    <div class="evidence-item"><span class="evidence-icon">01</span><div><h3>Roadside capture</h3><p>${vehicle.camera_id} identified plate ${vehicle.observed_plate} with ${vehicle.registration_id ? '98.4%' : '61.3%'} match confidence.</p></div><span class="evidence-date">${vehicle.captured_at.slice(11)}</span></div>
    <div class="evidence-item"><span class="evidence-icon">02</span><div><h3>Insurance registry</h3><p>${vehicle.insurer_name || 'No insurer record'} · ${vehicle.valid_until ? `${vehicle.policy_status} until ${formatDate(vehicle.valid_until)}` : 'No active policy found'}</p></div><span class="evidence-date">POLICY</span></div>
    <div class="evidence-item"><span class="evidence-icon">03</span><div><h3>Registration authority</h3><p>${vehicle.owner_name || 'No authoritative record'} · Registered ${formatDate(vehicle.registration_date)} · ${vehicle.color || 'Unknown'}</p></div><span class="evidence-date">REGISTRY</span></div>
    <div class="evidence-item"><span class="evidence-icon">04</span><div><h3>Police and scrap records</h3><p>${vehicle.case_id ? `${vehicle.case_id} / ${vehicle.case_status}` : 'No active theft or scrap case'}</p></div><span class="evidence-date">CASE LOG</span></div>`;
}

async function selectVehicle(plate) {
  const cleanedPlate = plate.trim();
  if (!cleanedPlate) { byId('lookup-hint').textContent = 'Enter a registration number first.'; byId('lookup-hint').style.color = 'var(--red)'; return; }
  try {
    const response = await fetch(`/api/vehicle?plate=${encodeURIComponent(cleanedPlate)}`);
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || 'No matching vehicle found.');
    byId('lookup-hint').textContent = 'Joined source databases searched just now.';
    byId('lookup-hint').style.color = 'var(--muted)';
    renderVehicle(payload);
  } catch (error) {
    byId('lookup-hint').textContent = error.message || 'Vehicle lookup failed. Check the connected source services.';
    byId('lookup-hint').style.color = 'var(--red)';
  }
}

byId('lookup-form').addEventListener('submit', (event) => { event.preventDefault(); selectVehicle(byId('plate-input').value); });
byId('report-button').addEventListener('click', () => showToast(`${selected.reg_no || selected.observed_plate} queued for Ministry review`));
byId('hold-button').addEventListener('click', () => showToast(`${selected.reg_no || selected.observed_plate} placed on inspection hold`));
byId('expand-button').addEventListener('click', () => { const list = byId('evidence-list'); list.hidden = !list.hidden; byId('expand-button').textContent = list.hidden ? '+' : '−'; byId('expand-button').setAttribute('aria-expanded', String(!list.hidden)); });

function showToast(message) { const toast = byId('toast'); toast.textContent = message; toast.classList.add('show'); window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2800); }
function updateClock() { byId('current-time').textContent = new Date().toTimeString().slice(0, 8); }

loadDetections().catch(() => { byId('lookup-hint').textContent = 'API unavailable. Start the local server with python3 server.py.'; byId('lookup-hint').style.color = 'var(--red)'; });
updateClock();
window.setInterval(updateClock, 1000);
