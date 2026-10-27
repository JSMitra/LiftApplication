// State and Configuration
let floorCount = 20;
let minFloor = 0;
let liftCount = 16;
let selectedDirection = 'UP';
let ws = null;
let pollInterval = null;

// DOM Elements
const shaftsGrid = document.getElementById('shafts-grid');
const floorRuler = document.getElementById('floor-ruler');
const floorSelect = document.getElementById('floor-select');
const btnDirUp = document.getElementById('btn-dir-up');
const btnDirDown = document.getElementById('btn-dir-down');
const hallCallForm = document.getElementById('hall-call-form');
const pendingList = document.getElementById('pending-requests-list');
const pendingCountBadge = document.getElementById('pending-count');
const logStream = document.getElementById('log-stream');
const wsStatus = document.getElementById('ws-status');
const metricPending = document.getElementById('metric-pending');
const metricLifts = document.getElementById('metric-lifts');
const metricFloors = document.getElementById('metric-floors');

// Preset Buttons
const btnRandom = document.getElementById('btn-random-call');
const btnMorning = document.getElementById('btn-morning-rush');
const btnEvening = document.getElementById('btn-evening-rush');
const btnReset = document.getElementById('btn-reset');
const btnClearLogs = document.getElementById('btn-clear-logs');

// Initialize Dashboard
async function init() {
  try {
    const resp = await fetch('/api/config');
    if (resp.ok) {
      const cfg = await resp.json();
      floorCount = cfg.floor_count || 20;
      minFloor = cfg.min_floor || 0;
      liftCount = cfg.lift_count || 16;
      metricLifts.textContent = liftCount;
      metricFloors.textContent = floorCount;

      const badgePods = document.getElementById('badge-lift-pods');
      if (badgePods) {
        badgePods.textContent = `${liftCount} Active StatefulSet Pod${liftCount > 1 ? 's' : ''}`;
      }
      if (shaftsGrid) {
        shaftsGrid.style.setProperty('--lift-cols', liftCount);
      }
    }
  } catch (err) {
    console.warn('Using default config:', err);
  }

  buildFloorRuler();
  buildFloorSelector();
  buildShaftsGrid();
  setupEventListeners();
  connectWebSocket();
}

function buildFloorRuler() {
  floorRuler.innerHTML = '';
  // Top floor down to minFloor
  for (let f = minFloor; f < minFloor + floorCount; f++) {
    const mark = document.createElement('div');
    mark.className = 'ruler-mark' + (f % 5 === 0 ? ' highlight' : '');
    mark.textContent = `F${f}`;
    floorRuler.appendChild(mark);
  }
}

function buildFloorSelector() {
  floorSelect.innerHTML = '';
  for (let f = minFloor; f < minFloor + floorCount; f++) {
    const opt = document.createElement('option');
    opt.value = f;
    opt.textContent = `Floor ${f}`;
    if (f === 0) opt.selected = true;
    floorSelect.appendChild(opt);
  }
}

function buildShaftsGrid() {
  shaftsGrid.innerHTML = '';
  for (let i = 0; i < liftCount; i++) {
    const lid = `lift-service-${i}`;
    const col = document.createElement('div');
    col.className = 'shaft-column';
    col.id = `col-${lid}`;

    col.innerHTML = `
      <div class="shaft-header">
        <div class="shaft-name">L-${String(i).padStart(2, '0')}</div>
        <span class="shaft-status-badge badge-idle" id="badge-${lid}">IDLE</span>
      </div>
      <div class="shaft-track" id="track-${lid}">
        <div class="elevator-car" id="car-${lid}" style="bottom: 0px;">
          <span class="car-floor" id="floor-val-${lid}">0</span>
          <span class="car-arrow" id="arrow-${lid}">⏸</span>
        </div>
      </div>
      <div class="shaft-footer" id="queue-${lid}">
        <!-- Queued floor chips -->
      </div>
    `;
    shaftsGrid.appendChild(col);
  }
}

function setupEventListeners() {
  // Direction buttons
  btnDirUp.addEventListener('click', () => {
    selectedDirection = 'UP';
    btnDirUp.classList.add('active');
    btnDirDown.classList.remove('active');
  });

  btnDirDown.addEventListener('click', () => {
    selectedDirection = 'DOWN';
    btnDirDown.classList.add('active');
    btnDirUp.classList.remove('active');
  });

  // Submit Call Form
  hallCallForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const floor = parseInt(floorSelect.value, 10);
    await submitHallRequest(floor, selectedDirection);
  });

  // Presets
  btnRandom.addEventListener('click', async () => {
    const randFloor = Math.floor(Math.random() * floorCount);
    let dir = 'UP';
    if (randFloor === floorCount - 1) dir = 'DOWN';
    else if (randFloor === 0) dir = 'UP';
    else dir = Math.random() > 0.5 ? 'UP' : 'DOWN';
    await submitHallRequest(randFloor, dir);
  });

  btnMorning.addEventListener('click', async () => {
    addLogEntry('call', '🌅 Morning rush triggered: Multiple passengers at Ground Floor going UP');
    for (let i = 0; i < 4; i++) {
      await submitHallRequest(0, 'UP');
    }
  });

  btnEvening.addEventListener('click', async () => {
    addLogEntry('call', '🌆 Evening rush triggered: Multiple passengers from upper floors going DOWN');
    const upperFloors = [18, 15, 12, 9];
    for (const f of upperFloors) {
      await submitHallRequest(f, 'DOWN');
    }
  });

  btnReset.addEventListener('click', async () => {
    if (confirm('Reset all elevator queues and requests to Ground Floor IDLE?')) {
      try {
        await fetch('/api/reset', { method: 'POST' });
        addLogEntry('info', '🧹 System reset triggered: Queues cleared.');
      } catch (err) {
        console.error(err);
      }
    }
  });

  btnClearLogs.addEventListener('click', () => {
    logStream.innerHTML = '';
  });
}

async function submitHallRequest(floor, direction) {
  try {
    const resp = await fetch('/api/requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ floor, direction })
    });
    const data = await resp.json();
    if (resp.ok) {
      addLogEntry('call', `🛎️ Hall Call: Floor ${floor} [${direction}] registered`);
      if (data.immediate_assignments && data.immediate_assignments.length > 0) {
        data.immediate_assignments.forEach(a => {
          addLogEntry('assign', `🎯 Assigned to ${a.lift_id} (${a.reason})`);
        });
      }
    } else {
      addLogEntry('info', `⚠️ Error: ${data.detail || 'Could not place request'}`);
    }
  } catch (err) {
    addLogEntry('info', `⚠️ Network error: ${err.message}`);
  }
}

// WebSocket Connection
function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    setOnlineStatus(true);
    addLogEntry('info', '🟢 Connected to live orchestrator stream');
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'TELEMETRY_UPDATE') {
        renderTelemetry(data);
      }
    } catch (e) {
      console.error('Error parsing WS message:', e);
    }
  };

  ws.onclose = () => {
    setOnlineStatus(false);
    // Start fallback polling if not already started
    if (!pollInterval) {
      pollInterval = setInterval(fetchTelemetryFallback, 800);
    }
    // Attempt reconnect in 2 seconds
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => {
    setOnlineStatus(false);
  };
}

function setOnlineStatus(online) {
  if (online) {
    wsStatus.className = 'status-indicator';
    wsStatus.querySelector('.status-text').textContent = 'LIVE';
  } else {
    wsStatus.className = 'status-indicator offline';
    wsStatus.querySelector('.status-text').textContent = 'POLLING';
  }
}

// Fallback polling if WS unavailable
async function fetchTelemetryFallback() {
  try {
    const [liftsResp, reqsResp, eventsResp] = await Promise.all([
      fetch('/api/lifts'),
      fetch('/api/requests'),
      fetch('/api/events?limit=5')
    ]);
    if (liftsResp.ok && reqsResp.ok) {
      const liftsData = await liftsResp.json();
      const reqsData = await reqsResp.json();
      const evData = eventsResp.ok ? await eventsResp.json() : { events: [] };
      renderTelemetry({
        lifts: liftsData.lifts,
        hall_requests: reqsData.requests.map(r => JSON.stringify(r)),
        recent_events: evData.events || []
      });
    }
  } catch (e) {
    console.debug('Polling error:', e);
  }
}

// Render Telemetry
function renderTelemetry(data) {
  const lifts = data.lifts || [];
  const hallReqs = data.hall_requests || [];

  // 1. Update Metrics
  const count = hallReqs.length;
  metricPending.textContent = count;
  pendingCountBadge.textContent = count;

  // 2. Render Lift Cars in Shafts
  lifts.forEach(lift => {
    const lid = lift.lift_id;
    const car = document.getElementById(`car-${lid}`);
    const track = document.getElementById(`track-${lid}`);
    const badge = document.getElementById(`badge-${lid}`);
    const floorLabel = document.getElementById(`floor-val-${lid}`);
    const arrow = document.getElementById(`arrow-${lid}`);
    const queueFooter = document.getElementById(`queue-${lid}`);

    if (!car || !track) return;

    const trackHeight = track.clientHeight || 300;
    const carHeight = car.clientHeight || 32;
    const usableHeight = Math.max(trackHeight - carHeight, 1);

    // Calculate vertical position from floor float (e.g. 7.2)
    const normFloor = Math.max(0, Math.min(lift.floor - minFloor, floorCount - 1));
    const ratio = normFloor / (floorCount - 1);
    const bottomPx = ratio * usableHeight;

    car.style.bottom = `${bottomPx}px`;

    // Floor readout
    const isInt = Math.abs(lift.floor - Math.round(lift.floor)) < 0.05;
    floorLabel.textContent = isInt ? Math.round(lift.floor) : lift.floor.toFixed(1);

    // Direction and Badge Styling
    car.classList.remove('up', 'down', 'door-open');
    badge.className = 'shaft-status-badge';

    if (lift.state === 'DOOR_OPEN') {
      car.classList.add('door-open');
      badge.classList.add('badge-door');
      badge.textContent = 'OPEN';
      arrow.textContent = '🚪';
    } else if (lift.direction === 1) {
      car.classList.add('up');
      badge.classList.add('badge-up');
      badge.textContent = 'UP';
      arrow.textContent = '▲';
    } else if (lift.direction === -1) {
      car.classList.add('down');
      badge.classList.add('badge-down');
      badge.textContent = 'DOWN';
      arrow.textContent = '▼';
    } else {
      badge.classList.add('badge-idle');
      badge.textContent = 'IDLE';
      arrow.textContent = '⏸';
    }

    // Queued Floor Chips
    if (queueFooter && lift.queue) {
      queueFooter.innerHTML = '';
      lift.queue.forEach(qf => {
        const chip = document.createElement('span');
        chip.className = 'queue-chip';
        chip.textContent = qf;
        queueFooter.appendChild(chip);
      });
    }
  });

  // 3. Render Pending Requests
  pendingList.innerHTML = '';
  if (hallReqs.length === 0) {
    pendingList.innerHTML = '<div class="empty-state">No pending hall requests</div>';
  } else {
    hallReqs.forEach(raw => {
      let r = raw;
      if (typeof raw === 'string') {
        try { r = JSON.parse(raw); } catch (e) { return; }
      }
      const item = document.createElement('div');
      const dirLower = (r.direction || 'UP').toLowerCase();
      item.className = `pending-item ${dirLower}`;
      item.innerHTML = `
        <span><strong>Floor ${r.floor}</strong> [${r.direction}]</span>
        <span style="font-size: 0.65rem; color: #64748b;">Waiting Dispatch</span>
      `;
      pendingList.appendChild(item);
    });
  }
}

function addLogEntry(type, message) {
  const item = document.createElement('div');
  item.className = `log-item ${type}`;
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  item.innerHTML = `<span class="log-time">[${timeStr}]</span> <span class="log-msg">${escapeHtml(message)}</span>`;
  logStream.prepend(item);

  // Keep log size bounded
  while (logStream.children.length > 50) {
    logStream.removeChild(logStream.lastChild);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Start application
document.addEventListener('DOMContentLoaded', init);

