// office.js -- Pixel art agent office (Tab 1)
//
// Severed-floor inspired layout: a sterile institutional space with a green
// institutional carpet, white drop-ceiling with fluorescent panels, two
// cubicle quartets in the centre, and a Memory kiosk on the right.
//
// Eight agents are organised into two thematic teams:
//
//   Reasoning Quartet (left)        Records Quartet (right)
//     orch    scan                    port    pm
//     ta      senti                   learn   roster
//
// Each quartet is a 2x2 grid of desks separated by a + cross of dark green
// acoustic privacy panels, with the team facing outward. The whole room is
// drawn in a flat side-on style, so every agent faces the viewer.
//
// Animation pipeline (back-to-front each frame):
//   ceiling -> wall -> carpet -> back panels of top row -> top row desks
//     -> top row sitting agents -> back panels of bottom row -> bottom row
//     -> walking agents -> runner sprites -> packets -> flashes
//
// Socket events consumed (emitted by the Python agents through ui/events.py):
//   agent_state {agent_id, state}     desk monitor color + speech bubble
//   packet      {from_id, to_id, color}   8x8 pixel arc between desks
//   runner      {from_id, to_id, color}   small clipboard sprite walks the floor
//   agent_walk  {from_id, to_id, collab_ms}   the agent leaves their desk,
//                                              walks to the collaborator,
//                                              stands for collab_ms, returns
//   log         {agent_id, message}    appends a line to the HUD log
//   scan_complete {}                   resets the "Run morning scan" button
//
// Dev helper exposed on window: window.testWalk('orch', 'ta')

(function () {
  'use strict';

  // ── Canvas geometry ─────────────────────────────────────────────────────
  const W = 580;
  const H = 205;
  const SCALE = 3;
  const CEILING_HEIGHT = 22;
  const WALL_HEIGHT = 44;            // ceiling + wall band
  const FLOOR_LANE_Y = 196;          // y where walkers/runners stand
  const FLOOR_LANE_OFFSET = 3;
  const WALK_TOTAL_MS = 2200;
  const WALK_SEG_FRAC = [0.22, 0.56, 0.22];

  // ── Severance palette ───────────────────────────────────────────────────
  const CARPET = '#7a9070';          // institutional green
  const CARPET_DARK = '#6d8362';     // very subtle floor variation
  const WALL_WHITE = '#f5f5ee';
  const WALL_TRIM = '#d8d8cc';
  const CEILING = '#f8f8f0';
  const CEILING_GRID = '#dcdcd0';
  const FLUORESCENT = '#ffffff';
  const FLUORESCENT_GLOW = '#fffce8';
  const DESK_TOP = '#f0f0e6';        // off-white desk
  const DESK_FRONT = '#d8d8ce';
  const DESK_EDGE = '#9a9a8e';
  const PANEL_BACK = '#3e5c4a';      // dark muted green privacy panel
  const PANEL_TOP = '#5e7a68';       // panel highlight edge
  const PANEL_FRAME = '#252525';
  const CHAIR_BODY = '#2a2a2e';
  const CHAIR_DARK = '#1a1a1e';
  const CHAIR_MAT = '#5a6e54';       // chair mat — slightly darker than carpet
  const CHAIR_MAT_EDGE = '#4a5e44';
  const PEDESTAL = '#e8e8de';
  const PEDESTAL_HANDLE = '#b8b8ae';
  const CRT_HOUSING = '#e8e8de';
  const CRT_BEZEL = '#b8b8ae';
  const CRT_SCREEN_OFF = '#1a3050';
  const CRT_SCREEN_GLOW = '#3060a0';
  const KIOSK_BODY = '#f0f0e6';
  const KIOSK_TRIM = '#9a9a8e';
  const SUIT = '#1a1a26';
  const SUIT_SHADOW = '#0e0e16';
  const SHIRT_WHITE = '#f0f0e8';
  const SKIN = '#e8c89a';
  const HAIR = '#3a2a18';
  const SIGN_INK = '#1a1a26';

  const STATE_SCREEN = {
    idle:    '#1a3050',     // CRT off-blue
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

  // ── Agents and pseudo-stations ──────────────────────────────────────────
  // Two quartets, each a 2x2 grid. x is the desk's left edge, dy is the
  // desk's top edge. Desk width = 60, height (top+front) = 22.
  // Quartet 1 spans x=46-180, Quartet 2 spans x=216-350.
  const AGENTS = [
    // Reasoning quartet (left)
    {id: 'orch',   nm: 'Orchestrator', x:  46, dy:  72, c: '#8B7FDD'},
    {id: 'scan',   nm: 'Scanner',      x: 116, dy:  72, c: '#2DAE85'},
    {id: 'ta',     nm: 'TA Agent',     x:  46, dy: 152, c: '#4A8ADD'},
    {id: 'senti',  nm: 'Sentiment',    x: 116, dy: 152, c: '#D86A40'},
    // Records quartet (right)
    {id: 'port',   nm: 'Portfolio',    x: 216, dy:  72, c: '#D4637E'},
    {id: 'pm',     nm: 'Post-mortem',  x: 286, dy:  72, c: '#9A9790'},
    {id: 'learn',  nm: 'Learning',     x: 216, dy: 152, c: '#72AA32'},
    {id: 'roster', nm: 'Roster',       x: 286, dy: 152, c: '#CA8527'}
  ];

  // Layout constants for the cubicle furniture
  const DESK_W = 60;
  const DESK_H_TOP = 7;
  const DESK_H_FRONT = 14;
  const PANEL_RISE_TOP = 24;       // how high panels rise above the top-row desks
  const PANEL_RISE_BOT = 26;       // and the bottom-row desks
  const CHAIR_OFFSET_Y = 26;       // chair top relative to desk top

  // The Memory DB is a kiosk on the right
  const MEMORY_DB = {id: 'memory_db', x: 444, y: 110};

  function getAgent(id) {
    return AGENTS.find(a => a.id === id) || null;
  }

  function getDeskCenterX(agent) { return agent.x + DESK_W / 2; }
  function getCharacterY(agent) { return agent.dy - 6; }

  // The "front" of the desk where a walker enters/leaves.
  function getDeskFront(agent) {
    return {x: agent.x + DESK_W / 2, y: agent.dy + 30};
  }

  function getStation(id) {
    if (id === 'memory_db') return MEMORY_DB;
    const agent = getAgent(id);
    if (agent) return {x: getDeskCenterX(agent), y: getCharacterY(agent), agent};
    return {x: 0, y: 0};
  }

  // ── Mutable state ───────────────────────────────────────────────────────
  const agentStates = {};
  AGENTS.forEach(a => { agentStates[a.id] = 'idle'; });

  const agentPos = {};
  const packets = [];
  const flashes = [];
  const runners = [];
  const logs = [];

  let scanRunning = false;

  // ── Canvas setup ────────────────────────────────────────────────────────
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
    setTimeout(function () {
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

  // First-run banner. Hidden by default; shown if /api/onboarding/status
  // reports has_holdings: false. Sits above the canvas.
  const banner = document.createElement('div');
  banner.id = 'office-onboarding-banner';
  banner.style.cssText = 'display:none;background:#3e5c4a;color:#f5f5ee;border:1px solid #5e7a68;border-radius:6px;margin-bottom:8px;padding:10px 14px;font-family:monospace;font-size:13px;line-height:1.5;';
  panel.appendChild(banner);
  panel.appendChild(canvas);
  panel.appendChild(hud);

  fetch('/api/onboarding/status')
    .then(response => response.ok ? response.json() : null)
    .then(status => {
      if (!status) return;
      if (!status.has_holdings) {
        banner.innerHTML =
          '<strong>Welcome to The Refinery.</strong> ' +
          'Add your first holding to get a morning report tomorrow. ' +
          '<a href="#" id="office-banner-link" style="color:#fbbf24;text-decoration:underline;">Open the Portfolio tab</a>.';
        banner.style.display = 'block';
        const link = document.getElementById('office-banner-link');
        if (link) {
          link.addEventListener('click', function (event) {
            event.preventDefault();
            const portfolioBtn = Array.from(document.querySelectorAll('.tab-btn'))
              .find(btn => btn.textContent.trim() === 'Portfolio');
            if (portfolioBtn) portfolioBtn.click();
          });
        }
      }
    })
    .catch(function () { /* fail silent: a missing endpoint just hides the banner */ });

  const ctx = canvas.getContext('2d');

  // ── Drawing primitives ──────────────────────────────────────────────────
  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), w, h);
  }

  // ── Room ────────────────────────────────────────────────────────────────
  function drawCeiling() {
    px(0, 0, W, CEILING_HEIGHT, CEILING);
    // Drop-ceiling grid: 30px columns x 11px rows
    for (let gx = 0; gx <= W; gx += 30) {
      px(gx, 0, 1, CEILING_HEIGHT, CEILING_GRID);
    }
    for (let gy = 0; gy <= CEILING_HEIGHT; gy += 11) {
      px(0, gy, W, 1, CEILING_GRID);
    }
    // Recessed fluorescent panels every other column
    for (let fx = 30; fx < W; fx += 60) {
      px(fx + 6, 2, 18, 7, FLUORESCENT);
      px(fx + 7, 3, 16, 5, FLUORESCENT_GLOW);
      px(fx + 6, 13, 18, 7, FLUORESCENT);
      px(fx + 7, 14, 16, 5, FLUORESCENT_GLOW);
    }
  }

  function drawWall() {
    px(0, CEILING_HEIGHT, W, WALL_HEIGHT - CEILING_HEIGHT, WALL_WHITE);
    px(0, CEILING_HEIGHT, W, 1, WALL_TRIM);
    px(0, WALL_HEIGHT - 1, W, 1, WALL_TRIM);
  }

  function drawRefinerySign() {
    // A sober Lumon-style sign across the back wall.
    const sx = 218, sy = 26;
    px(sx, sy, 142, 14, WALL_WHITE);
    px(sx, sy, 142, 1, WALL_TRIM);
    px(sx, sy + 13, 142, 1, WALL_TRIM);
    ctx.fillStyle = SIGN_INK;
    ctx.font = '10px monospace';
    const prevAlign = ctx.textAlign;
    const prevBaseline = ctx.textBaseline;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('THE REFINERY', sx + 71, sy + 7);
    ctx.textAlign = prevAlign;
    ctx.textBaseline = prevBaseline;
  }

  function drawCarpet() {
    px(0, WALL_HEIGHT, W, H - WALL_HEIGHT, CARPET);
    // Subtle floor variation: fine 2px noise stripes every ~12px
    for (let cy = WALL_HEIGHT + 8; cy < H; cy += 12) {
      for (let cx = 4; cx < W; cx += 18) {
        px(cx, cy, 4, 1, CARPET_DARK);
      }
    }
  }

  // ── Cubicle furniture ───────────────────────────────────────────────────
  function drawPrivacyPanelVertical(px_, py, height) {
    px(px_, py, 4, height, PANEL_BACK);
    px(px_, py, 4, 2, PANEL_TOP);
    px(px_, py + height - 1, 4, 1, PANEL_FRAME);
  }

  function drawPrivacyPanelHorizontal(px_, py, width) {
    px(px_, py, width, 4, PANEL_BACK);
    px(px_, py, width, 2, PANEL_TOP);
    px(px_ + width - 1, py + 1, 1, 3, PANEL_FRAME);
  }

  function drawQuartetPanels(quartetLeft, topRowDy, botRowDy) {
    // The + cross of panels in the centre of a quartet:
    //   - one vertical panel down the middle
    //   - one horizontal panel between top and bottom rows
    const q = quartetLeft;
    const quartetWidth = 2 * DESK_W + 14;   // 60 + gap + 60 + outer margin
    const middleX = q + DESK_W + 5;          // between left and right desks
    // Vertical panel for the top row (sits behind the top-row desks)
    drawPrivacyPanelVertical(middleX, topRowDy - PANEL_RISE_TOP, PANEL_RISE_TOP + DESK_H_TOP);
    // Vertical panel for the bottom row
    drawPrivacyPanelVertical(middleX, botRowDy - PANEL_RISE_BOT, PANEL_RISE_BOT + DESK_H_TOP);
    // Horizontal panel separating top row from bottom row
    const panelY = topRowDy + DESK_H_TOP + DESK_H_FRONT + CHAIR_OFFSET_Y - 4;
    drawPrivacyPanelHorizontal(q - 4, panelY, quartetWidth);
  }

  function drawChairMat(agent) {
    const mx = agent.x + 14, my = agent.dy + CHAIR_OFFSET_Y - 2;
    px(mx, my, 32, 18, CHAIR_MAT);
    px(mx, my, 32, 1, CHAIR_MAT_EDGE);
    px(mx, my + 17, 32, 1, CHAIR_MAT_EDGE);
    px(mx, my, 1, 18, CHAIR_MAT_EDGE);
    px(mx + 31, my, 1, 18, CHAIR_MAT_EDGE);
  }

  function drawFilePedestal(agent) {
    // White file pedestal under the right side of each desk.
    const px_ = agent.x + DESK_W - 14;
    const py = agent.dy + DESK_H_TOP;
    px(px_, py, 12, DESK_H_FRONT, PEDESTAL);
    px(px_, py + 4, 12, 1, PEDESTAL_HANDLE);
    px(px_, py + 9, 12, 1, PEDESTAL_HANDLE);
    px(px_ + 5, py + 5, 2, 1, '#7a7a70');
    px(px_ + 5, py + 10, 2, 1, '#7a7a70');
  }

  function drawDesk(agent) {
    const dx = agent.x, dy = agent.dy;
    // White desk surface
    px(dx, dy, DESK_W, DESK_H_TOP, DESK_TOP);
    // Desk front skirt
    px(dx, dy + DESK_H_TOP, DESK_W, DESK_H_FRONT, DESK_FRONT);
    // Desk top edge highlight
    px(dx, dy, DESK_W, 1, '#ffffff');
    // Desk bottom edge shadow
    px(dx, dy + DESK_H_TOP + DESK_H_FRONT - 1, DESK_W, 1, DESK_EDGE);
    // Desk legs
    px(dx + 3, dy + DESK_H_TOP + DESK_H_FRONT, 3, 6, DESK_EDGE);
    px(dx + DESK_W - 6, dy + DESK_H_TOP + DESK_H_FRONT, 3, 6, DESK_EDGE);

    // CRT monitor: chunky white housing, dark blue screen
    const monX = dx + 22, monY = dy - 16;
    // Housing
    px(monX, monY, 22, 14, CRT_HOUSING);
    px(monX, monY, 22, 1, '#ffffff');
    px(monX, monY + 13, 22, 1, CRT_BEZEL);
    px(monX, monY, 1, 14, '#ffffff');
    px(monX + 21, monY, 1, 14, CRT_BEZEL);
    // Screen with state-driven colour and a flash override
    const flash = flashes.find(f => f.agentId === agent.id);
    let screenColor;
    if (flash && Date.now() - flash.start < 150) {
      screenColor = '#ffffff';
    } else {
      screenColor = STATE_SCREEN[agentStates[agent.id]] || STATE_SCREEN.idle;
    }
    px(monX + 3, monY + 3, 16, 8, screenColor);
    // Subtle scanline highlight
    if (agentStates[agent.id] !== 'idle') {
      px(monX + 3, monY + 5, 16, 1, 'rgba(255,255,255,0.15)');
    }
    // Monitor stand
    px(dx + 30, dy - 2, 6, 2, CRT_BEZEL);
    px(dx + 28, dy, 10, 1, CRT_BEZEL);
    // Keyboard
    px(dx + 6, dy + 1, 14, 3, '#7a7a70');
    px(dx + 6, dy + 1, 14, 1, '#9a9a90');

    // Tighter, centered desk label on the front skirt
    px(dx + 2, dy + DESK_H_TOP + 3, DESK_W - 4, 8, '#1a1a1e');
    ctx.fillStyle = '#e0e0d8';
    ctx.font = '7px monospace';
    const prevAlign = ctx.textAlign;
    const prevBaseline = ctx.textBaseline;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(agent.nm, dx + DESK_W / 2, dy + DESK_H_TOP + 7);
    ctx.textAlign = prevAlign;
    ctx.textBaseline = prevBaseline;
  }

  function drawChair(agent) {
    const isEmpty = agentPos[agent.id] && agentPos[agent.id].state !== 'sitting';
    const offsetX = isEmpty ? 4 : 0;
    const offsetY = isEmpty ? 2 : 0;
    const cx_ = agent.x + 22 + offsetX;
    const cy = agent.dy + CHAIR_OFFSET_Y + offsetY;
    // Seat back
    px(cx_ + 3, cy - 6, 14, 6, CHAIR_BODY);
    px(cx_ + 3, cy - 6, 14, 1, CHAIR_DARK);
    // Seat
    px(cx_, cy, 20, 4, CHAIR_BODY);
    px(cx_, cy, 20, 1, '#3a3a3e');
    // Stem
    px(cx_ + 8, cy + 4, 4, 5, CHAIR_DARK);
    // Wheelbase (5-prong simplified)
    px(cx_ - 1, cy + 9, 22, 2, CHAIR_DARK);
    px(cx_ + 2, cy + 11, 2, 1, CHAIR_DARK);
    px(cx_ + 8, cy + 11, 4, 1, CHAIR_DARK);
    px(cx_ + 16, cy + 11, 2, 1, CHAIR_DARK);
  }

  // ── Memory DB kiosk ─────────────────────────────────────────────────────
  function drawMemoryKiosk() {
    // White floor-to-ceiling pillar with a CRT in the middle.
    const kx = 430, ky = WALL_HEIGHT, kw = 60, kh = H - WALL_HEIGHT - 14;
    // Body
    px(kx, ky, kw, kh, KIOSK_BODY);
    px(kx, ky, kw, 2, '#ffffff');
    px(kx, ky + kh - 2, kw, 2, KIOSK_TRIM);
    px(kx, ky, 1, kh, '#ffffff');
    px(kx + kw - 1, ky, 1, kh, KIOSK_TRIM);

    // Subtle horizontal panel seams
    px(kx, ky + 22, kw, 1, KIOSK_TRIM);
    px(kx, ky + 100, kw, 1, KIOSK_TRIM);

    // CRT screen midway down
    const monX = kx + 12, monY = ky + 38;
    px(monX, monY, 36, 28, CRT_HOUSING);
    px(monX, monY, 36, 1, '#ffffff');
    px(monX, monY + 27, 36, 1, CRT_BEZEL);
    px(monX + 3, monY + 3, 30, 22, CRT_SCREEN_OFF);
    // Scrolling pixel scanlines (animated by frame time)
    const offset = Math.floor(Date.now() / 80) % 4;
    for (let line = 0; line < 22; line += 4) {
      const yy = monY + 3 + ((line + offset) % 22);
      px(monX + 3, yy, 30, 1, CRT_SCREEN_GLOW);
    }
    // "RECORDS" plate
    ctx.fillStyle = '#1a1a26';
    ctx.font = '7px monospace';
    const prevAlign = ctx.textAlign;
    const prevBaseline = ctx.textBaseline;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('RECORDS', kx + kw / 2, monY + 36);
    ctx.textAlign = prevAlign;
    ctx.textBaseline = prevBaseline;

    // Floor base shadow
    px(kx - 3, ky + kh, kw + 6, 2, '#5a6e54');
  }

  // ── Sprites ─────────────────────────────────────────────────────────────
  // Severance-style: dark suit, white shirt collar peek, colored tie strip.
  // Sprite is 8w x 16h centered on (x, y) where (x, y) is the head's top-left.
  function drawSuitChar(x, y, agentColor, faceState, includeFace) {
    // Head
    px(x, y, 8, 8, SKIN);
    // Hair
    px(x, y, 8, 3, HAIR);
    // Suit body
    px(x, y + 9, 8, 6, SUIT);
    px(x, y + 9, 8, 1, SUIT_SHADOW);
    // White shirt collar (V-shape)
    px(x + 3, y + 9, 2, 2, SHIRT_WHITE);
    // Tie (colored strip)
    px(x + 3, y + 11, 2, 4, agentColor);
    px(x + 3, y + 11, 1, 4, agentColor);
    // Suit lapels (tiny dark V on top of collar)
    px(x + 2, y + 9, 1, 3, SUIT_SHADOW);
    px(x + 5, y + 9, 1, 3, SUIT_SHADOW);

    // Face
    if (includeFace !== false) {
      if (faceState === 'done') {
        px(x + 2, y + 4, 1, 1, '#222');
        px(x + 5, y + 4, 1, 1, '#222');
        px(x + 2, y + 6, 4, 1, '#222');
      } else {
        px(x + 2, y + 4, 1, 1, '#222');
        px(x + 5, y + 4, 1, 1, '#222');
      }
    }
  }

  function drawSittingChar(agent) {
    const cx_ = agent.x + 26, cy = agent.dy - 22;
    const state = agentStates[agent.id];
    drawSuitChar(cx_, cy, agent.c, state, true);

    // Speech bubble (typewriter dots when active)
    let bubble = STATE_BUBBLE[state];
    if (state === 'active') {
      const dotCount = (Math.floor(Date.now() / 300) % 3) + 1;
      bubble = '.'.repeat(dotCount);
    }
    if (bubble) {
      const bw = bubble.length * 5 + 4;
      px(cx_ - 2, cy - 12, bw, 9, '#fff');
      px(cx_ - 2, cy - 12, bw, 1, '#d8d8cc');
      px(cx_ + 1, cy - 3, 2, 2, '#fff');
      ctx.fillStyle = '#1a1a26';
      ctx.font = '7px monospace';
      ctx.fillText(bubble, cx_, cy - 5);
    }

    // "+1" pop on flash arrival
    const flash = flashes.find(f => f.agentId === agent.id);
    if (flash && Date.now() - flash.start < 500) {
      ctx.fillStyle = '#fbbf24';
      ctx.font = '8px monospace';
      ctx.fillText('+1', cx_ + 10, cy - 6);
    }
  }

  function drawWalkingChar(agent, x, y, frame, facingLeft) {
    drawSuitChar(x, y, agent.c, agentStates[agent.id], true);
    // Override eyes to look in the walking direction.
    if (facingLeft) {
      px(x + 1, y + 4, 1, 1, '#222');
      px(x + 4, y + 4, 1, 1, '#222');
    } else {
      px(x + 3, y + 4, 1, 1, '#222');
      px(x + 6, y + 4, 1, 1, '#222');
    }
    // Walking legs (two-frame cycle)
    if (frame === 0) {
      px(x + 1, y + 15, 2, 3, SUIT_SHADOW);
      px(x + 5, y + 15, 2, 2, SUIT_SHADOW);
    } else {
      px(x + 1, y + 15, 2, 2, SUIT_SHADOW);
      px(x + 5, y + 15, 2, 3, SUIT_SHADOW);
    }
  }

  function drawRunner(x, y, frame, color) {
    // Smaller messenger sprite: 6px head, 5px body, manila folder.
    px(x, y, 6, 6, SKIN);
    px(x, y, 6, 2, HAIR);
    px(x, y + 7, 6, 5, SUIT);
    px(x, y + 7, 6, 1, SUIT_SHADOW);
    // White collar peek
    px(x + 2, y + 7, 2, 1, SHIRT_WHITE);
    // Tie tip
    px(x + 2, y + 8, 2, 3, color);
    // Manila folder
    px(x + 6, y + 8, 4, 4, '#d8c890');
    px(x + 6, y + 8, 4, 1, '#a89860');
    // Eye
    px(x + 1, y + 3, 1, 1, '#222');
    px(x + 4, y + 3, 1, 1, '#222');
    // Walking legs
    if (frame === 0) {
      px(x + 1, y + 12, 1, 2, SUIT_SHADOW);
      px(x + 4, y + 12, 1, 1, SUIT_SHADOW);
    } else {
      px(x + 1, y + 12, 1, 1, SUIT_SHADOW);
      px(x + 4, y + 12, 1, 2, SUIT_SHADOW);
    }
  }

  // ── Animation: packets, runners, walkers ────────────────────────────────
  function drawPackets() {
    const now = Date.now();
    for (let i = packets.length - 1; i >= 0; i--) {
      const packet = packets[i];
      const elapsed = now - packet.start;
      const dur = 800;
      if (elapsed > dur) {
        if (packet.toId) flashes.push({agentId: packet.toId, start: now});
        packets.splice(i, 1);
        continue;
      }
      const t = elapsed / dur;
      const x = packet.x1 + (packet.x2 - packet.x1) * t;
      const y = packet.y1 + (packet.y2 - packet.y1) * t + Math.sin(t * Math.PI) * -18;
      px(x - 4, y - 4, 8, 8, packet.color);
      px(x - 2, y - 2, 4, 4, '#ffffff88');
    }
    for (let i = flashes.length - 1; i >= 0; i--) {
      if (now - flashes[i].start > 500) flashes.splice(i, 1);
    }
  }

  function drawRunners() {
    const now = Date.now();
    for (let i = runners.length - 1; i >= 0; i--) {
      const runner = runners[i];
      const elapsed = now - runner.start;
      if (elapsed > runner.dur) {
        runners.splice(i, 1);
        continue;
      }
      const point = computeWalkPoint(runner, elapsed);
      const frame = Math.floor(now / 150) % 2;
      drawRunner(point.x - 3, point.y - 6, frame, runner.color);
    }
  }

  function drawWalkers() {
    const now = Date.now();
    Object.keys(agentPos).forEach(id => {
      const pos = agentPos[id];
      if (pos.state === 'sitting') return;
      const agent = getAgent(id);
      if (!agent) return;

      if (pos.state === 'walking') {
        const elapsed = now - pos.start;
        if (elapsed >= pos.dur) {
          if (pos.phase === 'out') {
            const target = getStation(pos.targetId);
            pos.state = 'standing';
            pos.x = target.x;
            pos.y = target.y + 6;
            pos.standingStart = now;
          } else {
            pos.state = 'sitting';
            return;
          }
        } else {
          const point = computeWalkPoint(pos, elapsed);
          pos.x = point.x;
          pos.y = point.y;
          const frame = Math.floor(now / 180) % 2;
          drawWalkingChar(agent, pos.x - 4, pos.y - 8, frame, pos.dir < 0);
          return;
        }
      }

      if (pos.state === 'standing') {
        const target = getStation(pos.targetId);
        const standX = target.x + 14;
        const standY = target.y + 6;
        drawWalkingChar(agent, standX - 4, standY - 8, 0, true);
        // Thought bubble
        ctx.fillStyle = '#fff';
        ctx.fillRect(standX - 6, standY - 22, 16, 9);
        ctx.fillRect(standX - 4, standY - 13, 2, 2);
        ctx.fillStyle = '#1a1a26';
        ctx.font = '7px monospace';
        ctx.fillText('hi', standX - 4, standY - 15);

        if (now - pos.standingStart >= pos.collabMs) {
          const home = getDeskFront(agent);
          pos.phase = 'in';
          pos.state = 'walking';
          pos.start = now;
          pos.dur = WALK_TOTAL_MS;
          pos.legs = buildPath({x: standX, y: standY}, home, pos.lane);
          pos.legDurations = WALK_SEG_FRAC.map(f => f * WALK_TOTAL_MS);
          pos.dir = (home.x - standX) >= 0 ? 1 : -1;
        }
        return;
      }
    });
  }

  function buildPath(start, end, lane) {
    return [
      {x1: start.x, y1: start.y, x2: start.x, y2: lane},
      {x1: start.x, y1: lane,    x2: end.x,   y2: lane},
      {x1: end.x,   y1: lane,    x2: end.x,   y2: end.y}
    ];
  }

  function computeWalkPoint(entity, elapsed) {
    const legs = entity.legs;
    const durations = entity.legDurations;
    let acc = 0;
    for (let i = 0; i < legs.length; i++) {
      if (elapsed <= acc + durations[i]) {
        const localT = (elapsed - acc) / durations[i];
        const leg = legs[i];
        return {
          x: leg.x1 + (leg.x2 - leg.x1) * localT,
          y: leg.y1 + (leg.y2 - leg.y1) * localT
        };
      }
      acc += durations[i];
    }
    const last = legs[legs.length - 1];
    return {x: last.x2, y: last.y2};
  }

  // ── Main draw ───────────────────────────────────────────────────────────
  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Room shell
    drawCeiling();
    drawWall();
    drawRefinerySign();
    drawCarpet();

    // Memory kiosk lives on the right wall, drawn behind both quartets
    drawMemoryKiosk();

    // Quartet 1 (left): privacy panels behind the desks
    drawQuartetPanels(46, 72, 152);
    // Quartet 2 (right)
    drawQuartetPanels(216, 72, 152);

    // Top-row chair mats and chairs (drawn before desks so the chair backs
    // sit behind the desk skirt, then character heads pop above).
    AGENTS.filter(a => a.dy === 72).forEach(a => {
      drawChairMat(a);
      drawChair(a);
    });
    AGENTS.filter(a => a.dy === 72).forEach(a => {
      drawDesk(a);
      drawFilePedestal(a);
    });
    AGENTS.filter(a => a.dy === 72).forEach(a => {
      const sitting = !agentPos[a.id] || agentPos[a.id].state === 'sitting';
      if (sitting) drawSittingChar(a);
    });

    // Bottom row
    AGENTS.filter(a => a.dy === 152).forEach(a => {
      drawChairMat(a);
      drawChair(a);
    });
    AGENTS.filter(a => a.dy === 152).forEach(a => {
      drawDesk(a);
      drawFilePedestal(a);
    });
    AGENTS.filter(a => a.dy === 152).forEach(a => {
      const sitting = !agentPos[a.id] || agentPos[a.id].state === 'sitting';
      if (sitting) drawSittingChar(a);
    });

    // Walking agents (above all furniture)
    drawWalkers();

    // Top-layer animations
    drawRunners();
    drawPackets();

    requestAnimationFrame(draw);
  }

  // ── HUD updates ─────────────────────────────────────────────────────────
  function addLog(agentId, message) {
    const line = document.createElement('div');
    line.style.cssText = 'font-size:13px;padding:1px 0;';
    const agentColor = (getAgent(agentId) || {c: '#8a8a60'}).c;
    line.innerHTML = '<span style="color:' + agentColor + '">[' + agentId + ']</span> ' + escapeHtml(message);
    logList.appendChild(line);
    logBox.scrollTop = logBox.scrollHeight;
    while (logList.children.length > 50) logList.removeChild(logList.firstChild);
    logs.push({agent: agentId, msg: message});
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  function updateStatusHud() {
    statusList.innerHTML = AGENTS.map(a => {
      const state = agentStates[a.id];
      const color = state === 'idle' ? '#444' : state === 'error' ? '#f87171' : a.c;
      return '<div style="font-size:13px;padding:1px 0;color:' + color + '">' + a.id + ': ' + state + '</div>';
    }).join('');
  }

  // ── Animation triggers ──────────────────────────────────────────────────
  function addPacket(x1, y1, x2, y2, color, toId) {
    packets.push({x1, y1, x2, y2, color, toId, start: Date.now()});
  }

  function addRunner(fromId, toId, color) {
    const from = getStation(fromId);
    const to = getStation(toId);
    const fromPoint = from.agent ? getDeskFront(from.agent) : {x: from.x, y: from.y};
    const toPoint = to.agent ? getDeskFront(to.agent) : {x: to.x, y: to.y};
    const lane = pickFreeLane(fromPoint.x, toPoint.x, runners.map(r => ({x1: r.legs[1].x1, x2: r.legs[1].x2, lane: r.lane})));
    const legs = buildPath(fromPoint, toPoint, lane);
    runners.push({
      fromId, toId, color: color || '#c8a050',
      start: Date.now(), dur: WALK_TOTAL_MS, lane,
      legs, legDurations: WALK_SEG_FRAC.map(f => f * WALK_TOTAL_MS)
    });
  }

  function pickFreeLane(x1, x2, others) {
    const myMin = Math.min(x1, x2), myMax = Math.max(x1, x2);
    let lane = FLOOR_LANE_Y;
    let attempts = 0;
    while (attempts < 4) {
      const collision = others.some(other => {
        if (other.lane !== lane) return false;
        const otherMin = Math.min(other.x1, other.x2);
        const otherMax = Math.max(other.x1, other.x2);
        return !(myMax < otherMin || myMin > otherMax);
      });
      if (!collision) return lane;
      lane -= FLOOR_LANE_OFFSET;
      attempts++;
    }
    return lane;
  }

  function startWalk(fromId, toId, collabMs) {
    const agent = getAgent(fromId);
    if (!agent) return;
    if (agentPos[fromId] && agentPos[fromId].state !== 'sitting') return;
    const home = getDeskFront(agent);
    const target = getStation(toId);
    const targetPoint = target.agent ? getDeskFront(target.agent) : {x: target.x, y: target.y};
    const lane = pickFreeLane(home.x, targetPoint.x, []);
    const legs = buildPath(home, targetPoint, lane);
    agentPos[fromId] = {
      state: 'walking',
      phase: 'out',
      targetId: toId,
      start: Date.now(),
      dur: WALK_TOTAL_MS,
      lane,
      collabMs: collabMs || 1500,
      legs,
      legDurations: WALK_SEG_FRAC.map(f => f * WALK_TOTAL_MS),
      dir: (targetPoint.x - home.x) >= 0 ? 1 : -1,
      x: home.x,
      y: home.y
    };
  }

  function setAgentState(id, state) {
    agentStates[id] = state;
    updateStatusHud();
  }

  // ── Socket.IO ───────────────────────────────────────────────────────────
  const socket = io();

  socket.on('agent_state', function (data) {
    setAgentState(data.agent_id, data.state);
  });

  socket.on('packet', function (data) {
    const from = getStation(data.from_id);
    const to = getStation(data.to_id);
    addPacket(from.x, from.y, to.x, to.y, data.color, data.to_id);
  });

  socket.on('runner', function (data) {
    addRunner(data.from_id, data.to_id, data.color);
  });

  socket.on('agent_walk', function (data) {
    startWalk(data.from_id, data.to_id, data.collab_ms);
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

  // ── Dev helpers (browser console) ───────────────────────────────────────
  window.testWalk = function (fromId, toId, collabMs) {
    startWalk(fromId, toId || 'ta', collabMs || 1500);
  };
  window.testRunner = function (fromId, toId) {
    addRunner(fromId || 'orch', toId || 'memory_db');
  };
  window.testFlash = function (toId) {
    flashes.push({agentId: toId || 'ta', start: Date.now()});
  };
  window.testPacket = function (fromId, toId) {
    const from = getStation(fromId || 'orch');
    const to = getStation(toId || 'ta');
    addPacket(from.x, from.y, to.x, to.y, (getAgent(fromId || 'orch') || {c: '#fff'}).c, toId || 'ta');
  };

  // ── Init ────────────────────────────────────────────────────────────────
  updateStatusHud();
  draw();
})();
