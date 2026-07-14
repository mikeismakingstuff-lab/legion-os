// LEGION OS local dashboard server
// Zero dependencies - uses Node's built-in http module only.
// Run:  node server.js
// Then open:  http://localhost:4173

const http = require('http');

const PORT = 4173;

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LEGION OS — Analytic Console</title>
<style>
  :root {
    --bg: #0a0e17;
    --panel: #0d1620;
    --border: #1c2c3d;
    --cyan: #5fd4e3;
    --crimson: #c9425a;
    --text: #e6edf3;
    --muted: #7d93a3;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    height: 100%;
    overflow: hidden;
  }
  body { display: flex; flex-direction: column; }
  header {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: baseline;
    gap: 14px;
    flex-shrink: 0;
  }
  header .title { font-size: 20px; font-weight: 700; letter-spacing: 1px; }
  header .sub { color: var(--muted); font-size: 13px; }
  main {
    flex: 1;
    display: grid;
    grid-template-rows: 1fr 1fr;
    gap: 1px;
    background: var(--border);
    overflow: hidden;
  }
  .row { display: grid; gap: 1px; background: var(--border); overflow: hidden; }
  .row-top { grid-template-columns: 1.1fr 1.1fr 1.4fr; }
  .row-bottom { grid-template-columns: 1fr 2fr; }
  .panel {
    background: var(--panel);
    padding: 14px 16px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .panel h2 {
    margin: 0 0 10px 0;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--cyan);
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    flex-shrink: 0;
  }
  .gauges { display: flex; gap: 14px; margin-bottom: 10px; }
  .gauge {
    width: 68px; height: 68px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 600; text-align: center;
    background: conic-gradient(var(--cyan) 0deg 230deg, var(--crimson) 230deg 260deg, var(--border) 260deg 360deg);
  }
  .gauge span {
    background: var(--panel);
    width: 50px; height: 50px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
  }
  .stat-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin: 3px 0; }
  .stat-row b { color: var(--text); }
  .bars { display: flex; align-items: flex-end; gap: 4px; height: 40px; margin: 10px 0; }
  .bars div { width: 8px; background: linear-gradient(var(--cyan), var(--crimson)); border-radius: 2px 2px 0 0; }
  .net { font-size: 12px; margin-top: auto; }
  .net .ok { color: var(--cyan); }
  .tree { font-size: 12px; line-height: 1.9; color: var(--muted); overflow-y: auto; }
  .tree .active { color: var(--cyan); background: var(--border); padding: 2px 6px; border-radius: 3px; }
  .tree .indent1 { padding-left: 16px; }
  .globe-wrap { position: relative; flex: 1; display: flex; align-items: center; justify-content: center; }
  .status-line { font-size: 11px; color: var(--crimson); margin-bottom: 4px; }
  .status-line b { color: var(--text); display: block; font-size: 12px; }
  .integrity { text-align: right; font-size: 12px; margin-top: 8px; }
  .integrity b { color: var(--cyan); }
  .convergence { flex: 1; display: flex; align-items: center; justify-content: center; }
  .node-label { font-size: 11px; fill: var(--text); }
  .chat-group { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); overflow: hidden; }
  .chat { background: var(--panel); padding: 10px 12px; display: flex; flex-direction: column; min-height: 0; }
  .chat h3 { margin: 0 0 8px 0; font-size: 12px; color: var(--cyan); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .log { flex: 1; overflow-y: auto; font-size: 10px; color: var(--muted); font-family: 'Consolas', monospace; line-height: 1.6; }
  .log .ts { color: var(--crimson); }
  .chat input {
    margin-top: 8px; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 6px 8px; border-radius: 4px; font-size: 11px;
  }
  footer {
    border-top: 1px solid var(--border);
    padding: 8px 20px;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    flex-shrink: 0;
  }
  footer b { color: var(--cyan); }
</style>
</head>
<body>

<header>
  <span class="title">LEGION OS — ANALYTIC CONSOLE</span>
  <span class="sub">Greetings, Architect. Welcome. We are LEGION.</span>
</header>

<main>
  <div class="row row-top">

    <div class="panel">
      <h2>System Performance Monitor</h2>
      <div class="gauges">
        <div class="gauge"><span>CPU<br>34%</span></div>
        <div class="gauge"><span>RAM<br>62%</span></div>
        <div class="gauge"><span>I/O<br>18%</span></div>
      </div>
      <div class="stat-row"><span>CPU Temp</span><b>33.4°C</b></div>
      <div class="stat-row"><span>RAM Temp</span><b>38.5°C</b></div>
      <div class="stat-row"><span>Disk Temp</span><b style="color:var(--crimson)">39.5°C</b></div>
      <div class="bars">
        <div style="height:40%"></div><div style="height:70%"></div><div style="height:55%"></div>
        <div style="height:90%"></div><div style="height:35%"></div><div style="height:60%"></div>
        <div style="height:48%"></div><div style="height:75%"></div>
      </div>
      <div class="net">NETWORK: <span class="ok">ESTABLISHED</span> &nbsp; LATENCY: 12ms</div>
    </div>

    <div class="panel">
      <h2>File Explorer — LEGION-FS</h2>
      <div class="tree">
        <div>📁 /SYSTEM</div>
        <div>📁 /LOGS</div>
        <div>📁 /CONFIGS</div>
        <div class="indent1 active">📄 legion_config_v1.0.cfg</div>
        <div>📁 /ASSETS</div>
        <div class="indent1">📄 compression_engine.py</div>
        <div class="indent1">📄 headroom_client.py</div>
        <div class="indent1">📄 pipeline_stage5.py</div>
        <div>📁 /TESTS</div>
        <div class="indent1">📄 test_results_81_28.log</div>
      </div>
    </div>

    <div class="panel">
      <div class="status-line">STATUS:<b>COLLECTIVE INGEST [ACTIVE]</b></div>
      <div class="globe-wrap">
        <svg viewBox="0 0 200 200" width="100%" height="100%" style="max-height:180px">
          <circle cx="100" cy="100" r="70" fill="none" stroke="#5fd4e3" stroke-width="0.5" opacity="0.5"/>
          <ellipse cx="100" cy="100" rx="90" ry="30" fill="none" stroke="#5fd4e3" stroke-width="0.5" opacity="0.6" transform="rotate(-20 100 100)"/>
          <ellipse cx="100" cy="100" rx="90" ry="30" fill="none" stroke="#c9425a" stroke-width="0.5" opacity="0.5" transform="rotate(30 100 100)"/>
          <circle cx="70" cy="80" r="3" fill="#c9425a"><animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite"/></circle>
          <circle cx="130" cy="110" r="3" fill="#c9425a"><animate attributeName="opacity" values="0.3;1;0.3" dur="2.5s" repeatCount="indefinite"/></circle>
          <circle cx="110" cy="60" r="2" fill="#5fd4e3"/>
        </svg>
      </div>
      <div class="integrity">PIPELINE INTEGRITY <b>[OPTIMAL] [99.7%]</b></div>
    </div>

  </div>

  <div class="row row-bottom">

    <div class="panel">
      <h2>Convergence Logic</h2>
      <div class="convergence">
        <svg viewBox="0 0 220 200" width="100%" height="100%" style="max-height:220px">
          <line x1="110" y1="100" x2="40" y2="40" stroke="#5fd4e3" stroke-width="3"/>
          <line x1="110" y1="100" x2="180" y2="40" stroke="#c9425a" stroke-width="3"/>
          <line x1="110" y1="100" x2="110" y2="180" stroke="#5fd4e3" stroke-width="3" opacity="0.6"/>
          <circle cx="110" cy="100" r="30" fill="#0d1620" stroke="#5fd4e3" stroke-width="2"/>
          <circle cx="40" cy="40" r="18" fill="#0d1620" stroke="#5fd4e3" stroke-width="2"/>
          <circle cx="180" cy="40" r="18" fill="#0d1620" stroke="#c9425a" stroke-width="2"/>
          <circle cx="110" cy="180" r="16" fill="#0d1620" stroke="#5fd4e3" stroke-width="2" opacity="0.7"/>
          <text x="110" y="104" text-anchor="middle" class="node-label" font-size="9">CORE</text>
          <text x="40" y="66" text-anchor="middle" class="node-label">USER</text>
          <text x="180" y="66" text-anchor="middle" class="node-label">NMT3S</text>
          <text x="110" y="198" text-anchor="middle" class="node-label">AGVL1</text>
        </svg>
      </div>
    </div>

    <div class="chat-group">
      <div class="chat">
        <h3>CHAT [NEMOTRON]</h3>
        <div class="log">
          <div><span class="ts">[12:00:01]</span> Nemotron analysis module online.</div>
          <div><span class="ts">[12:00:15]</span> Data feed sync complete.</div>
          <div><span class="ts">[12:00:22]</span> Awaiting router dispatch...</div>
        </div>
        <input placeholder="Message Nemotron..." />
      </div>
      <div class="chat">
        <h3>COMBINED SESSION</h3>
        <div class="log">
          <div><span class="ts">[12:00:25]</span> CONVERGENCE LOGIC: datastreams synced.</div>
          <div><span class="ts">[12:00:25]</span> Commencing deliberation.</div>
        </div>
        <input placeholder="Entry text here..." />
      </div>
      <div class="chat">
        <h3>CHAT [ANTIGRAVITY]</h3>
        <div class="log">
          <div><span class="ts">[12:00:02]</span> Antigravity sync initiated.</div>
          <div><span class="ts">[12:00:09]</span> Scope online.</div>
          <div><span class="ts">[12:00:20]</span> Data parity confirmed.</div>
        </div>
        <input placeholder="Message Antigravity..." />
      </div>
    </div>

  </div>
</main>

<footer>
  <span>SESSION ID: <b>LEGION-ANALYTICS-42</b></span>
  <span>CONSOLE STATUS: <b>OPTIMAL [100% SECURE]</b></span>
</footer>

</body>
</html>`;

const server = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(HTML);
});

server.listen(PORT, () => {
  console.log(`LEGION OS dashboard running at http://localhost:${PORT}`);
  console.log('Press Ctrl+C to stop.');
});
