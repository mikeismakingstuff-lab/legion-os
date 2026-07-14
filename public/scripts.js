// public/scripts.js

document.addEventListener('DOMContentLoaded', () => {
    console.log("scripts.js: DOMContentLoaded triggered");

    // DOM Elements - Telemetry
    const cpuFill = document.getElementById('cpu-fill');
    const cpuVal = document.getElementById('cpu-val');
    const ramFill = document.getElementById('ram-fill');
    const ramVal = document.getElementById('ram-val');
    const latencyCanvas = document.getElementById('latency-canvas');
    const latencyVal = document.getElementById('latency-val');
    const cpuTemp = document.getElementById('cpu-temp');
    const ramTemp = document.getElementById('ram-temp');
    const diskTemp = document.getElementById('disk-temp');

    // DOM Elements - File Explorer
    const fileTreeEl = document.getElementById('file-tree');
    const previewContent = document.getElementById('preview-content');

    // DOM Elements - Chat
    const nmt3sInput = document.getElementById('nmt3s-input');
    const nmt3sSend = document.getElementById('nmt3s-send');
    const nmt3sLog = document.getElementById('nmt3s-log');

    const combinedInput = document.getElementById('combined-input');
    const combinedSend = document.getElementById('combined-send');
    const combinedLog = document.getElementById('combined-log');

    const agvl1Input = document.getElementById('agvl1-input');
    const agvl1Send = document.getElementById('agvl1-send');
    const agvl1Log = document.getElementById('agvl1-log');

    // State
    const openFolders = new Set();
    let activeFilePath = null;
    const latencyHistory = Array(20).fill(42);

    // ──────────────────────────────────────────────────────────────────────────
    // Telemetry Polling
    // ──────────────────────────────────────────────────────────────────────────
    function pollTelemetry() {
        fetch('/api/telemetry')
            .then(res => res.json())
            .then(data => {
                updateGauge(cpuFill, cpuVal, data.cpu);
                updateGauge(ramFill, ramVal, data.ram);
                updateLatency(data.latency);

                // Simulate temps based on CPU/RAM load
                cpuTemp.textContent = (30 + (data.cpu * 0.2)).toFixed(2) + '°C';
                ramTemp.textContent = (35 + (data.ram * 0.1)).toFixed(2) + '°C';
                diskTemp.textContent = (38 + (Math.random() * 2)).toFixed(2) + '°C';
            })
            .catch(err => console.error('Telemetry polling error:', err));
    }

    function updateGauge(fillEl, valEl, percent) {
        if (fillEl && valEl) {
            fillEl.setAttribute('stroke-dasharray', `${percent}, 100`);
            valEl.textContent = `${Math.round(percent)}%`;
        }
    }

    function updateLatency(newLatency) {
        if (latencyVal) latencyVal.textContent = `${newLatency}ms`;
        latencyHistory.push(newLatency);
        if (latencyHistory.length > 20) {
            latencyHistory.shift();
        }
        if (latencyCanvas) drawSparkline(latencyCanvas, latencyHistory);
    }

    function drawSparkline(canvas, data) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.strokeStyle = '#c9425a'; // Crimson for network line
        ctx.lineWidth = 1.5;
        ctx.beginPath();

        const step = canvas.width / (data.length - 1);
        const max = 100;

        data.forEach((val, index) => {
            const x = index * step;
            const y = canvas.height - (val / max) * canvas.height;
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();

        // Fill under line
        ctx.lineTo(canvas.width, canvas.height);
        ctx.lineTo(0, canvas.height);
        ctx.fillStyle = 'rgba(201, 66, 90, 0.2)';
        ctx.fill();
    }

    pollTelemetry();
    setInterval(pollTelemetry, 2000);

    // ──────────────────────────────────────────────────────────────────────────
    // File Tree Rendering & Preview
    // ──────────────────────────────────────────────────────────────────────────
    function loadFileTree() {
        fetch('/api/files')
            .then(res => res.json())
            .then(data => {
                if (fileTreeEl) {
                    fileTreeEl.innerHTML = '';
                    renderNode(data, fileTreeEl, '');
                }
            })
            .catch(err => {
                if (fileTreeEl) fileTreeEl.innerHTML = '<div class="tree-error">Failed to load workspace.</div>';
            });
    }

    function renderNode(node, parentEl, currentPath = '', depth = 0) {
        const nodePath = currentPath ? `${currentPath}/${node.name}` : node.name;
        const indentClass = depth > 0 ? `indent${Math.min(depth, 3)}` : '';

        if (node.type === 'directory') {
            const folderDiv = document.createElement('div');
            folderDiv.className = `tree-item ${indentClass}`;
            folderDiv.innerHTML = `📁 ${node.name}`;

            const childrenContainer = document.createElement('div');
            childrenContainer.style.display = openFolders.has(nodePath) || currentPath === '' ? 'block' : 'none';

            if (currentPath === '') openFolders.add(nodePath);

            folderDiv.addEventListener('click', () => {
                const isOpen = childrenContainer.style.display === 'block';
                childrenContainer.style.display = isOpen ? 'none' : 'block';
                if (isOpen) openFolders.delete(nodePath);
                else openFolders.add(nodePath);
            });

            parentEl.appendChild(folderDiv);
            parentEl.appendChild(childrenContainer);

            node.children.forEach(child => renderNode(child, childrenContainer, nodePath, depth + 1));
        } else {
            const fileDiv = document.createElement('div');
            fileDiv.className = `tree-item ${indentClass}`;
            fileDiv.innerHTML = `📄 ${node.name}`;

            if (node.path === activeFilePath) fileDiv.classList.add('active');

            fileDiv.addEventListener('click', () => {
                document.querySelectorAll('.tree-item').forEach(item => item.classList.remove('active'));
                fileDiv.classList.add('active');
                activeFilePath = node.path;
                fetchPreview(node.path);
            });

            parentEl.appendChild(fileDiv);
        }
    }

    function fetchPreview(filePath) {
        if (!previewContent) return;
        previewContent.innerHTML = '<div class="preview-placeholder">Loading preview...</div>';

        fetch('/api/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath })
        })
            .then(res => {
                if (!res.ok) throw new Error('Failed to load file preview.');
                return res.json();
            })
            .then(data => {
                previewContent.textContent = data.content;
            })
            .catch(err => {
                previewContent.innerHTML = `<div style="color:var(--crimson)">Error: ${err.message}</div>`;
            });
    }

    loadFileTree();
    setInterval(loadFileTree, 5000);

    // ──────────────────────────────────────────────────────────────────────────
    // Chat Handlers
    // ──────────────────────────────────────────────────────────────────────────
    function getTimestamp() {
        const now = new Date();
        return `[${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}]`;
    }

    function appendLog(logEl, text, isError = false) {
        if (!logEl) return;
        const div = document.createElement('div');
        if (isError) div.style.color = 'var(--crimson)';
        div.innerHTML = `<span class="ts">${getTimestamp()}</span> ${text}`;
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
    }

    // NMT3S (Ollama)
    function sendNmt3s() {
        if (!nmt3sInput || !nmt3sLog) return;
        const text = nmt3sInput.value.trim();
        if (!text) return;

        appendLog(nmt3sLog, `> ${text}`);
        nmt3sInput.value = '';

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        })
            .then(res => res.json())
            .then(data => appendLog(nmt3sLog, data.response))
            .catch(err => appendLog(nmt3sLog, `Error: ${err.message}`, true));
    }

    if (nmt3sSend) nmt3sSend.addEventListener('click', sendNmt3s);
    if (nmt3sInput) nmt3sInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendNmt3s(); });

    // AGVL1 (Antigravity)
    function sendAgvl1() {
        if (!agvl1Input || !agvl1Log) return;
        const text = agvl1Input.value.trim();
        if (!text) return;

        appendLog(agvl1Log, `> ${text}`);
        agvl1Input.value = '';

        fetch('/api/antigravity', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        })
            .then(res => res.json())
            .then(data => appendLog(agvl1Log, data.response))
            .catch(err => appendLog(agvl1Log, `Error: ${err.message}`, true));
    }

    if (agvl1Send) agvl1Send.addEventListener('click', sendAgvl1);
    if (agvl1Input) agvl1Input.addEventListener('keydown', e => { if (e.key === 'Enter') sendAgvl1(); });

    // Combined Session (Committee Protocol)
    let committeePollingInterval = null;

    function pollCommittee() {
        fetch('/api/deliberation')
            .then(res => res.json())
            .then(data => {
                if (!combinedLog) return;

                let liveDiv = document.getElementById('committee-live-content');
                if (!liveDiv) {
                    liveDiv = document.createElement('div');
                    liveDiv.id = 'committee-live-content';
                    liveDiv.style.whiteSpace = 'pre-wrap';
                    liveDiv.style.marginTop = '10px';
                    combinedLog.appendChild(liveDiv);
                }

                const isScrolledToBottom = combinedLog.scrollHeight - combinedLog.scrollTop - combinedLog.clientHeight < 20;

                liveDiv.textContent = data.content;

                if (isScrolledToBottom) {
                    combinedLog.scrollTop = combinedLog.scrollHeight;
                }

                if (data.content.includes('Final Verified Plan') || data.content.includes('Error running committee')) {
                    clearInterval(committeePollingInterval);
                    committeePollingInterval = null;
                }
            })
            .catch(err => console.error('Polling error:', err));
    }

    function sendCombined() {
        if (!combinedInput || !combinedLog) return;
        const text = combinedInput.value.trim();
        if (!text) return;

        const existingLive = document.getElementById('committee-live-content');
        if (existingLive) existingLive.remove();

        appendLog(combinedLog, `> ${text}`);
        combinedInput.value = '';

        fetch('/api/committee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'started') {
                    if (committeePollingInterval) clearInterval(committeePollingInterval);
                    committeePollingInterval = setInterval(pollCommittee, 1000);
                }
            })
            .catch(err => appendLog(combinedLog, `Error: ${err.message}`, true));
    }

    if (combinedSend) combinedSend.addEventListener('click', sendCombined);
    if (combinedInput) combinedInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendCombined(); });

    // ──────────────────────────────────────────────────────────────────────────
    // Resizable Frames Logic
    // ──────────────────────────────────────────────────────────────────────────
    const resizers = document.querySelectorAll('.resizer');
    let isDragging = false;
    let currentResizer = null;
    let startX, startY;
    let startPrevSize, startNextSize;

    resizers.forEach(resizer => {
        resizer.addEventListener('mousedown', (e) => {
            isDragging = true;
            currentResizer = resizer;
            resizer.classList.add('dragging');

            startX = e.clientX;
            startY = e.clientY;

            const targetId = resizer.dataset.target;
            const targetEl = document.getElementById(targetId);

            // Get current grid template
            const computedStyle = window.getComputedStyle(targetEl);
            const isCol = resizer.classList.contains('resizer-col');

            const tracks = isCol ? computedStyle.gridTemplateColumns.split(' ') : computedStyle.gridTemplateRows.split(' ');

            const index = parseInt(resizer.dataset.index);
            startPrevSize = parseFloat(tracks[index - 1]);
            startNextSize = parseFloat(tracks[index + 1]);

            document.body.style.cursor = isCol ? 'col-resize' : 'row-resize';
            e.preventDefault(); // Prevent text selection
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging || !currentResizer) return;

        const isCol = currentResizer.classList.contains('resizer-col');
        const delta = isCol ? e.clientX - startX : e.clientY - startY;

        const targetId = currentResizer.dataset.target;
        const index = parseInt(currentResizer.dataset.index);

        // Calculate new sizes in pixels
        let newPrevSize = startPrevSize + delta;
        let newNextSize = startNextSize - delta;

        // Minimum size constraint (e.g., 100px)
        if (newPrevSize < 100) {
            newNextSize -= (100 - newPrevSize);
            newPrevSize = 100;
        }
        if (newNextSize < 100) {
            newPrevSize -= (100 - newNextSize);
            newNextSize = 100;
        }

        // Apply via CSS variables
        if (targetId === 'main-grid') {
            if (index === 1) {
                document.documentElement.style.setProperty('--col-left', `${newPrevSize}px`);
                document.documentElement.style.setProperty('--col-center', `${newNextSize}px`);
            } else if (index === 3) {
                document.documentElement.style.setProperty('--col-center', `${newPrevSize}px`);
                document.documentElement.style.setProperty('--col-right', `${newNextSize}px`);
            }
        } else if (targetId === 'col-left') {
            if (index === 1) {
                document.documentElement.style.setProperty('--row-left-top', `${newPrevSize}px`);
                document.documentElement.style.setProperty('--row-left-mid', `${newNextSize}px`);
            } else if (index === 3) {
                document.documentElement.style.setProperty('--row-left-mid', `${newPrevSize}px`);
                document.documentElement.style.setProperty('--row-left-bottom', `${newNextSize}px`);
            }
        } else if (targetId === 'col-right') {
            if (index === 1) {
                document.documentElement.style.setProperty('--row-right-top', `${newPrevSize}px`);
                document.documentElement.style.setProperty('--row-right-bottom', `${newNextSize}px`);
            }
        }
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            if (currentResizer) currentResizer.classList.remove('dragging');
            currentResizer = null;
            document.body.style.cursor = 'default';
        }
    });

});
