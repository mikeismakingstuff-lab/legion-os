// public/scripts.js

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const cpuFill = document.getElementById('cpu-fill');
    const cpuVal = document.getElementById('cpu-val');
    const ramFill = document.getElementById('ram-fill');
    const ramVal = document.getElementById('ram-val');
    const latencyCanvas = document.getElementById('latency-canvas');
    const tokenCountEl = document.getElementById('token-count');
    const tokenLimitEl = document.getElementById('token-limit');
    const tokenProgress = document.getElementById('token-progress');
    const fileTreeEl = document.getElementById('file-tree');
    const previewContainer = document.getElementById('preview-container');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const chatSendBtn = document.getElementById('chat-send-btn');
    const notepadTextarea = document.getElementById('notepad-textarea');

    // Latency sparkline history
    const latencyHistory = Array(10).fill(42);

    // ──────────────────────────────────────────────────────────────────────────
    // Telemetry Polling
    // ──────────────────────────────────────────────────────────────────────────
    function pollTelemetry() {
        fetch('/api/telemetry')
            .then(res => res.json())
            .then(data => {
                // Update CPU Gauge
                updateGauge(cpuFill, cpuVal, data.cpu);
                // Update RAM Gauge
                updateGauge(ramFill, ramVal, data.ram);
                // Update Latency Sparkline
                updateLatency(data.latency);
                // Update Token Monitor
                updateTokenMonitor(data.token_count, data.token_limit);
            })
            .catch(err => console.error('Telemetry polling error:', err));
    }

    function updateGauge(fillEl, valEl, percent) {
        // SVG dasharray circumference is 100
        fillEl.setAttribute('stroke-dasharray', `${percent}, 100`);
        valEl.textContent = `${percent}%`;
    }

    function updateLatency(newLatency) {
        latencyHistory.push(newLatency);
        if (latencyHistory.length > 10) {
            latencyHistory.shift();
        }
        drawSparkline(latencyCanvas, latencyHistory);
    }

    function drawSparkline(canvas, data) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.strokeStyle = '#00d2ff';
        ctx.lineWidth = 1.5;
        ctx.beginPath();

        const step = canvas.width / (data.length - 1);
        const max = 100; // Max expected latency scale

        data.forEach((val, index) => {
            const x = index * step;
            // Invert Y since canvas 0,0 is top-left
            const y = canvas.height - (val / max) * canvas.height;
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();
    }

    function updateTokenMonitor(count, limit) {
        tokenCountEl.textContent = count.toLocaleString();
        tokenLimitEl.textContent = limit.toLocaleString();
        const percent = Math.min((count / limit) * 100, 100);
        tokenProgress.style.width = `${percent}%`;
    }

    // Start polling every 2 seconds
    pollTelemetry();
    setInterval(pollTelemetry, 2000);

    // ──────────────────────────────────────────────────────────────────────────
    // File Tree Rendering & Preview
    // ──────────────────────────────────────────────────────────────────────────
    function loadFileTree() {
        fetch('/api/files')
            .then(res => res.json())
            .then(data => {
                fileTreeEl.innerHTML = '';
                renderNode(data, fileTreeEl);
            })
            .catch(err => {
                console.error('File tree load error:', err);
                fileTreeEl.innerHTML = '<div class="tree-error">Failed to load workspace.</div>';
            });
    }

    function renderNode(node, parentEl) {
        if (node.type === 'directory') {
            const folderDiv = document.createElement('div');
            folderDiv.className = 'tree-folder';

            const header = document.createElement('div');
            header.className = 'folder-header';
            header.innerHTML = `<span class="folder-icon"></span> <span class="folder-name">${node.name}</span>`;

            const childrenContainer = document.createElement('div');
            childrenContainer.className = 'folder-children';

            header.addEventListener('click', () => {
                header.classList.toggle('open');
            });

            folderDiv.appendChild(header);
            folderDiv.appendChild(childrenContainer);
            parentEl.appendChild(folderDiv);

            node.children.forEach(child => renderNode(child, childrenContainer));
        } else {
            const fileDiv = document.createElement('div');
            fileDiv.className = 'file-item';
            fileDiv.dataset.path = node.path;
            fileDiv.innerHTML = `<span class="file-icon"></span> <span class="file-name">${node.name}</span>`;

            fileDiv.addEventListener('click', () => {
                document.querySelectorAll('.file-item').forEach(item => item.classList.remove('active'));
                fileDiv.classList.add('active');
                fetchPreview(node.path);
            });

            parentEl.appendChild(fileDiv);
        }
    }

    function fetchPreview(filePath) {
        previewContainer.innerHTML = '<div class="preview-placeholder">Loading preview...</div>';

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
                renderPreview(data.name, data.content);
            })
            .catch(err => {
                previewContainer.innerHTML = `<div class="preview-error">Error: ${err.message}</div>`;
            });
    }

    function renderPreview(filename, content) {
        previewContainer.innerHTML = '';

        const header = document.createElement('div');
        header.className = 'preview-header';
        header.textContent = filename;
        previewContainer.appendChild(header);

        const body = document.createElement('div');
        body.className = 'preview-body';

        if (filename.endsWith('.xlsx')) {
            // Render spreadsheet as a clean table
            body.appendChild(parseXlsxMock(content));
        } else if (filename.endsWith('.docx')) {
            // Render docx preview layout
            body.innerHTML = `<div class="docx-preview">${content}</div>`;
        } else {
            // Default plain text
            body.textContent = content;
        }

        previewContainer.appendChild(body);
    }

    function parseXlsxMock(content) {
        // Basic parser for mock xlsx representation
        const table = document.createElement('table');
        table.className = 'preview-table';

        const lines = content.split('\n');
        lines.forEach((line, index) => {
            if (!line.trim()) return;
            const row = document.createElement('tr');
            const cols = line.split('\t'); // Tab-separated mock

            cols.forEach(col => {
                const cell = document.createElement(index === 0 ? 'th' : 'td');
                cell.textContent = col;
                row.appendChild(cell);
            });
            table.appendChild(row);
        });
        return table;
    }

    loadFileTree();

    // ──────────────────────────────────────────────────────────────────────────
    // AI Chat Core
    // ──────────────────────────────────────────────────────────────────────────
    function appendMessage(sender, text, type) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${type}`;
        msgDiv.innerHTML = `
            <div class="message-sender">${sender}</div>
            <div class="message-text">${text}</div>
        `;
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sendChatMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        appendMessage('User', text, 'user');
        chatInput.value = '';

        // Show typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message system typing';
        typingDiv.innerHTML = `<div class="message-sender">Legion AI</div><div class="message-text">Thinking...</div>`;
        chatMessages.appendChild(typingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        })
            .then(res => res.json())
            .then(data => {
                typingDiv.remove();
                appendMessage('Legion AI', data.response, 'system');
            })
            .catch(err => {
                typingDiv.remove();
                appendMessage('System', `Error: ${err.message}`, 'system');
            });
    }

    chatSendBtn.addEventListener('click', sendChatMessage);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendChatMessage();
    });

    // ──────────────────────────────────────────────────────────────────────────
    // Notepad Scratchpad (Debounced Auto-Save)
    // ──────────────────────────────────────────────────────────────────────────
    let saveTimeout;

    function loadNotepad() {
        fetch('/api/notepad', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'load' })
        })
            .then(res => res.json())
            .then(data => {
                notepadTextarea.value = data.content || '';
            })
            .catch(err => console.error('Notepad load error:', err));
    }

    function saveNotepad() {
        const content = notepadTextarea.value;
        fetch('/api/notepad', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'save', content: content })
        })
            .catch(err => console.error('Notepad save error:', err));
    }

    notepadTextarea.addEventListener('input', () => {
        clearTimeout(saveTimeout);
        saveTimeout = setTimeout(saveNotepad, 1000); // Debounce 1s
    });

    // Notepad Formatting Toolbar
    document.querySelectorAll('.toolbar-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const format = btn.dataset.format;
            const start = notepadTextarea.selectionStart;
            const end = notepadTextarea.selectionEnd;
            const text = notepadTextarea.value;
            const selectedText = text.substring(start, end);

            let replacement = '';
            switch (format) {
                case 'bold':
                    replacement = `**${selectedText || 'text'}**`;
                    break;
                case 'italic':
                    replacement = `*${selectedText || 'text'}*`;
                    break;
                case 'link':
                    replacement = `[${selectedText || 'link text'}](url)`;
                    break;
                case 'code':
                    replacement = `\`${selectedText || 'code'}\``;
                    break;
                case 'list':
                    replacement = `\n- ${selectedText || 'item'}`;
                    break;
            }

            notepadTextarea.value = text.substring(0, start) + replacement + text.substring(end);
            notepadTextarea.focus();
            notepadTextarea.selectionStart = start + replacement.length;
            notepadTextarea.selectionEnd = start + replacement.length;

            // Trigger save
            saveNotepad();
        });
    });

    loadNotepad();
});
