// office.js -- Pixel Art Agent Office (Tab 1)
(function () {
  'use strict';

  // ── Constants ────────────────────────────────────────────────────────
  const W = 580, H = 205, SCALE = 3;
  const WH = 42; // wall height
  const FLOOR_A = '#F0E4AE', FLOOR_B = '#E4D49A';
  const WALL = '#D4AA6A', BRICK_A = '#C47B50', BRICK_B = '#B86840';
  const DESK_TOP = '#B08A5C', DESK_FRONT = '#7A4F2E';
  const SHELF_COL = '#7A4F2E';
  const RACK_BG = '#161E2C', RACK_LED = '#00FF41';
  const RUG_COL = '#C8A060';
  const HUD_BG = '#111108';

  const STATE_SCREEN = {
    idle:    '#162410',
    active:  '#4ade80',
    reading: '#60a5fa',
    writing: '#fbbf24',
    done:    '#86efac',
    error:   '#ef4444'
  };

  const STATE_BUBBLE = {
    active: '...',
    reading: 'READ',
    writing: 'SAVE',
    error: '!'
  };

  const AGENTS = [
    {id:'orch',   nm:'Orchestrator', x:8,   dy:62,  c:'#8B7FDD'},
    {id:'scan',   nm:'Scanner',      x:88,  dy:62,  c:'#2DAE85'},
    {id:'ta',     nm:'TA Agent',     x:168, dy:62,  c:'#4A8ADD'},
    {id:'senti',  nm:'Sentiment',    x:248, dy:62,  c:'#D86A40'},
    {id:'port',   nm:'Portfolio',    x:328, dy:62,  c:'#D4637E'},
    {id:'pm',     nm:'Post-mortem',  x:8,   dy:143, c:'#9A9790'},
    {id:'learn',  nm:'Learning',     x:88,  dy:143, c:'#72AA32'},
    {id:'roster', nm:'Roster',       x:208, dy:143, c:'#CA8527'}
  ];

  const MEMORY_DB = {x: 505, y: 115};

  function getDeskCenterX(agent) { return agent.x + 33; }
  function getCharacterY(agent) { return agent.dy - 6; }

  // ── State ────────────────────────────────────────────────────────────
  const agentStates = {};
  AGENTS.forEach(a => agentStates[a.id] = 'idle');

  const packets = [];
  const logs = [];
  let scanRunning = false;

  // ── Canvas setup ─────────────────────────────────────────────────────
  const panel = document.getElementById('tab-office');
  if (!panel) return;

  const canvas = document.createElement('canvas');
  canvas.id = 'office-canvas';
  canvas.width = W;
  canvas.height = H;
  canvas.style.width = (W * SCALE) + 'px';
  canvas.style.height = (H * SCALE) + 'px';
  canvas.style.maxWidth = '100%';
  canvas.style.height = 'auto';
  canvas.style.imageRendering = 'pixelated';

  // HUD below the canvas
  const hud = document.createElement('div');
  hud.style.cssText = 'background:#111108;border:0.5px solid #2a2a1a;border-radius:6px;margin-top:8px;padding:10px;font-family:monospace;font-size:13px;display:flex;gap:16px;max-width:100%;margin-left:auto;margin-right:auto;';

  const logBox = document.createElement('div');
  logBox.style.cssText = 'flex:1;max-height:120px;overflow-y:auto;color:#8a8a60;';
  logBox.innerHTML = '<div style="color:#6a6040;margin-bottom:4px;font-size:13px;letter-spacing:.05em;">DAILY LOG</div>';
  const logList = document.createElement('div');
  logList.id = 'hud-log';
  logBox.appendChild(logList);

  const statusBox = document.createElement('div');
  statusBox.style.cssText = 'width:140px;';
  statusBox.innerHTML = '<div style="color:#6a6040;margin-bottom:4px;font-size:13px;letter-spacing:.05em;">AGENT STATUS</div>';
  const statusList = document.createElement('div');
  statusList.id = 'hud-status';
  statusBox.appendChild(statusList);

  const ctrlBox = document.createElement('div');
  ctrlBox.style.cssText = 'width:140px;display:flex;flex-direction:column;gap:6px;';
  const scanBtn = document.createElement('button');
  scanBtn.className = 'btn';
  scanBtn.textContent = 'RUN MORNING SCAN';
  scanBtn.style.cssText = 'font-size:13px;padding:6px 8px;white-space:nowrap;';
  scanBtn.onclick = function () {
    if (scanRunning) return;
    scanRunning = true;
    scanBtn.textContent = 'SCANNING...';
    scanBtn.style.opacity = '0.5';
    socket.emit('trigger_scan', {scan_type: 'daily'});
    setTimeout(function() {
      if (scanRunning) {
        scanRunning = false;
        scanBtn.textContent = 'RUN MORNING SCAN';
        scanBtn.style.opacity = '1';
        clockEl.textContent = 'timeout';
      }
    }, 300000);
  };
  ctrlBox.appendChild(scanBtn);

  const clockEl = document.createElement('div');
  clockEl.id = 'poClk';
  clockEl.style.cssText = 'color:#6a6040;font-size:13px;';
  clockEl.textContent = 'idle';
  ctrlBox.appendChild(clockEl);

  hud.appendChild(logBox);
  hud.appendChild(statusBox);
  hud.appendChild(ctrlBox);

  panel.appendChild(canvas);
  panel.appendChild(hud);

  const ctx = canvas.getContext('2d');

  // ── Drawing helpers ──────────────────────────────────────────────────
  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), w, h);
  }

  function drawWall() {
    px(0, 0, W, WH, WALL);
    // Brick rows
    for (let row = 0; row < 3; row++) {
      const y = 4 + row * 12;
      const col = row % 2 === 0 ? BRICK_A : BRICK_B;
      for (let bx = 0; bx < W; bx += 24) {
        const offset = row % 2 === 0 ? 0 : 12;
        px(bx + offset, y, 20, 8, col);
      }
    }
    // Top trim
    px(0, 0, W, 2, '#9B7040');
  }

  function drawFloor() {
    const tileSize = 14;
    for (let ty = WH; ty < H; ty += tileSize) {
      for (let tx = 0; tx < W; tx += tileSize) {
        const odd = ((tx / tileSize | 0) + (ty / tileSize | 0)) % 2;
        px(tx, ty, tileSize, tileSize, odd ? FLOOR_B : FLOOR_A);
      }
    }
  }

  function drawShelf(sx, sy) {
    // Bookshelf frame
    px(sx, sy, 50, 36, SHELF_COL);
    px(sx + 2, sy + 2, 46, 10, '#1a1208');
    px(sx + 2, sy + 14, 46, 10, '#1a1208');
    px(sx + 2, sy + 26, 46, 8, '#1a1208');
    // Books
    const bookColors = ['#D44', '#4A8ADD', '#72AA32', '#D86A40', '#8B7FDD', '#CA8527', '#D4637E'];
    for (let i = 0; i < 6; i++) {
      px(sx + 4 + i * 7, sy + 3, 5, 8, bookColors[i % bookColors.length]);
    }
    for (let i = 0; i < 6; i++) {
      px(sx + 4 + i * 7, sy + 15, 5, 8, bookColors[(i + 3) % bookColors.length]);
    }
    for (let i = 0; i < 5; i++) {
      px(sx + 4 + i * 8, sy + 27, 6, 6, bookColors[(i + 1) % bookColors.length]);
    }
  }

  function drawLamp(lx, ly) {
    px(lx, ly, 2, 24, '#9B7040');       // pole
    px(lx - 3, ly - 2, 8, 4, '#CA8527'); // shade
    px(lx - 1, ly + 24, 6, 2, '#7A4F2E'); // base
    px(lx, ly, 2, 2, '#FFE4A0');        // glow
  }

  function drawPoster(px_, py) {
    px(px_, py, 28, 20, '#1a1208');
    px(px_ + 1, py + 1, 26, 18, '#0e0e0a');
    // Mini chart lines
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px_ + 3, py + 14);
    ctx.lineTo(px_ + 8, py + 8);
    ctx.lineTo(px_ + 14, py + 12);
    ctx.lineTo(px_ + 20, py + 5);
    ctx.lineTo(px_ + 25, py + 9);
    ctx.stroke();
  }

  function drawPlant(plx, ply) {
    px(plx, ply + 8, 8, 10, '#7A4F2E');  // pot
    px(plx + 1, ply + 6, 6, 3, '#7A4F2E'); // rim
    px(plx + 2, ply, 4, 8, '#3a6a20');   // stem
    px(plx - 1, ply - 2, 4, 4, '#4a8a30'); // leaf L
    px(plx + 5, ply - 2, 4, 4, '#4a8a30'); // leaf R
    px(plx + 1, ply - 4, 6, 4, '#5aa040'); // leaf top
  }

  function drawServerRack(rx, ry, rw, rh) {
    px(rx, ry, rw, rh, RACK_BG);
    px(rx + 1, ry + 1, rw - 2, rh - 2, '#0e1420');
    // Server units
    for (let i = 0; i < 5; i++) {
      const uy = ry + 4 + i * 16;
      px(rx + 3, uy, rw - 6, 12, '#1a2438');
      // LEDs
      px(rx + 5, uy + 3, 2, 2, RACK_LED);
      px(rx + 9, uy + 3, 2, 2, i % 2 === 0 ? RACK_LED : '#FF4444');
      // Ventilation lines
      for (let v = 0; v < 4; v++) {
        px(rx + 16 + v * 6, uy + 4, 4, 1, '#2a3a50');
      }
    }
    // "MEM DB" label
    ctx.fillStyle = '#6a8a60';
    ctx.font = '7px monospace';
    ctx.fillText('MEM', rx + 6, ry + rh - 4);
  }

  function drawCabinet(cx_, cy) {
    px(cx_, cy, 40, 30, '#2a2018');
    px(cx_ + 2, cy + 2, 36, 12, '#3a3020');
    px(cx_ + 2, cy + 16, 36, 12, '#3a3020');
    px(cx_ + 18, cy + 6, 4, 2, '#9B7040'); // handle
    px(cx_ + 18, cy + 20, 4, 2, '#9B7040'); // handle
  }

  function drawRug(rx, ry, rw, rh) {
    px(rx, ry, rw, rh, RUG_COL);
    px(rx + 2, ry + 2, rw - 4, rh - 4, '#B89050');
    // Border pattern
    for (let i = 0; i < rw - 8; i += 6) {
      px(rx + 4 + i, ry + 3, 4, 1, '#9A7040');
      px(rx + 4 + i, ry + rh - 5, 4, 1, '#9A7040');
    }
  }

  function drawCouch(cx_, cy) {
    px(cx_, cy, 50, 22, '#6a4a2a');      // body
    px(cx_ + 2, cy + 2, 46, 14, '#8a6a40'); // cushion
    px(cx_, cy, 6, 18, '#5a3a1a');       // arm L
    px(cx_ + 44, cy, 6, 18, '#5a3a1a');  // arm R
    px(cx_ + 2, cy - 4, 46, 6, '#5a3a1a'); // back
    // Cushion lines
    px(cx_ + 16, cy + 3, 1, 12, '#7a5a30');
    px(cx_ + 32, cy + 3, 1, 12, '#7a5a30');
  }

  function drawCoffee(cx_, cy) {
    px(cx_, cy, 12, 18, '#3a3030');       // machine body
    px(cx_ + 2, cy + 2, 8, 6, '#222');   // screen
    px(cx_ + 4, cy + 10, 4, 6, '#8a6040'); // cup
    px(cx_ + 3, cy + 9, 6, 1, '#9a7050'); // saucer
  }

  function drawDesk(a) {
    const dx = a.x, dy = a.dy;
    // Desk surface
    px(dx, dy, 66, 8, DESK_TOP);
    // Desk front
    px(dx, dy + 8, 66, 14, DESK_FRONT);
    // Desk legs
    px(dx + 2, dy + 22, 4, 6, DESK_FRONT);
    px(dx + 60, dy + 22, 4, 6, DESK_FRONT);
    // Monitor
    px(dx + 22, dy - 16, 22, 14, '#1a1a1a');
    const screenColor = STATE_SCREEN[agentStates[a.id]] || STATE_SCREEN.idle;
    px(dx + 24, dy - 14, 18, 10, screenColor);
    // Monitor stand
    px(dx + 30, dy - 2, 6, 3, '#333');
    // Keyboard
    px(dx + 18, dy + 2, 16, 3, '#2a2a2a');
    // Name label
    ctx.fillStyle = '#1a1208';
    ctx.fillRect(dx + 2, dy + 10, 62, 10);
    ctx.fillStyle = '#ffffff';
    ctx.font = '8px monospace';
    ctx.fillText(a.nm, dx + 4, dy + 18);
  }

  function drawChair(a) {
    const cx_ = a.x + 28, cy = a.dy + 26;
    px(cx_, cy, 14, 4, '#3a3a3a');        // seat
    px(cx_ + 5, cy + 4, 4, 6, '#333');   // stem
    px(cx_ + 2, cy + 10, 10, 2, '#2a2a2a'); // base
  }

  function drawChar(a) {
    const cx_ = a.x + 30, cy = a.dy - 22;
    const state = agentStates[a.id];
    // Head
    px(cx_, cy, 8, 8, '#E8C89A');
    // Hair
    px(cx_, cy, 8, 3, '#5a4020');
    // Shirt (agent color)
    px(cx_, cy + 9, 8, 6, a.c);
    // Eyes
    if (state === 'done') {
      // Smile
      px(cx_ + 2, cy + 4, 1, 1, '#333');
      px(cx_ + 5, cy + 4, 1, 1, '#333');
      px(cx_ + 2, cy + 6, 4, 1, '#333');
    } else {
      px(cx_ + 2, cy + 4, 1, 1, '#333');
      px(cx_ + 5, cy + 4, 1, 1, '#333');
    }

    // Speech bubble
    const bubble = STATE_BUBBLE[state];
    if (bubble) {
      const bw = bubble.length * 5 + 4;
      px(cx_ - 2, cy - 12, bw, 9, '#fff');
      px(cx_ + 1, cy - 3, 2, 2, '#fff'); // tail
      ctx.fillStyle = '#111';
      ctx.font = '7px monospace';
      ctx.fillText(bubble, cx_, cy - 5);
    }
  }

  function drawPackets() {
    const now = Date.now();
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i];
      const elapsed = now - p.start;
      const dur = 800;
      if (elapsed > dur) {
        packets.splice(i, 1);
        continue;
      }
      const t = elapsed / dur;
      const x = p.x1 + (p.x2 - p.x1) * t;
      const y = p.y1 + (p.y2 - p.y1) * t + Math.sin(t * Math.PI) * -18;
      px(x - 4, y - 4, 8, 8, p.color);
      px(x - 2, y - 2, 4, 4, '#ffffff88'); // white highlight
    }
  }

  // ── Main draw ────────────────────────────────────────────────────────
  function draw() {
    ctx.clearRect(0, 0, W, H);
    drawWall();
    drawFloor();
    drawShelf(8, 3);
    drawLamp(68, 20);
    drawPoster(140, 5);
    drawPoster(270, 5);
    // "Investment Analyst" sign
    px(183, 18, 80, 3, '#B08040');
    ctx.fillStyle = '#FFE4A0';
    ctx.font = '8px monospace';
    ctx.fillText('Investment Analyst', 185, 17);
    drawPlant(400, 28);
    drawLamp(420, 20);
    // Server room divider
    px(438, WH, 2, H - WH, '#9B7040');
    drawServerRack(443, 64, 46, 88);
    drawServerRack(493, 64, 44, 88);
    drawCabinet(443, 158);
    drawPlant(495, 150);
    drawRug(296, 148, 130, 46);
    drawCouch(304, 156);
    drawCoffee(362, 160);
    // Agents
    AGENTS.forEach(a => {
      drawChair(a);
      drawDesk(a);
      drawChar(a);
    });
    drawPackets();
    requestAnimationFrame(draw);
  }

  // ── HUD updates ──────────────────────────────────────────────────────
  function addLog(agentId, message) {
    const line = document.createElement('div');
    line.style.cssText = 'font-size:13px;padding:1px 0;';
    const agentColor = (AGENTS.find(a => a.id === agentId) || {}).c || '#8a8a60';
    line.innerHTML = '<span style="color:' + agentColor + '">[' + agentId + ']</span> ' + message;
    logList.appendChild(line);
    logBox.scrollTop = logBox.scrollHeight;
    // Keep max 50 lines
    while (logList.children.length > 50) logList.removeChild(logList.firstChild);
    logs.push({agent: agentId, msg: message});
  }

  function updateStatusHud() {
    statusList.innerHTML = AGENTS.map(a => {
      const state = agentStates[a.id];
      const color = state === 'idle' ? '#444' : state === 'error' ? '#f87171' : a.c;
      return '<div style="font-size:13px;padding:1px 0;color:' + color + '">' + a.id + ': ' + state + '</div>';
    }).join('');
  }

  function addPacket(x1, y1, x2, y2, color) {
    packets.push({x1, y1, x2, y2, color, start: Date.now()});
  }

  function getStation(id) {
    if (id === 'memory_db') return MEMORY_DB;
    return AGENTS.find(a => a.id === id) || AGENTS[0];
  }

  function setAgentState(id, state) {
    agentStates[id] = state;
    updateStatusHud();
  }

  // ── Socket.IO ────────────────────────────────────────────────────────
  const socket = io();

  socket.on('agent_state', function (data) {
    setAgentState(data.agent_id, data.state);
  });

  socket.on('packet', function (data) {
    const from = getStation(data.from_id);
    const to = getStation(data.to_id);
    const fx = from.x !== undefined ? getDeskCenterX(from) : from.x;
    const fy = from.dy !== undefined ? getCharacterY(from) : from.y;
    const tx = to.x !== undefined ? getDeskCenterX(to) : to.x;
    const ty = to.dy !== undefined ? getCharacterY(to) : to.y;
    addPacket(fx, fy, tx, ty, data.color);
  });

  socket.on('log', function (data) {
    addLog(data.agent_id, data.message);
  });

  socket.on('scan_complete', function () {
    scanRunning = false;
    scanBtn.textContent = 'RUN MORNING SCAN';
    scanBtn.style.opacity = '1';
    clockEl.textContent = 'done';
  });

  // ── Init ─────────────────────────────────────────────────────────────
  updateStatusHud();
  draw();
})();
