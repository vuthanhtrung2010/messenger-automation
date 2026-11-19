function initStreamClient() {
    if (window.__streamClientInitialized) return;
    window.__streamClientInitialized = true;

    const scriptMeta = document.getElementById('stream-meta');
    const accountId = scriptMeta ? scriptMeta.getAttribute('data-account-id') : null;
    if (!accountId) return;

    const canvas = document.getElementById('stream-canvas');
    const ctx = canvas.getContext('2d', { alpha: false });
    const loadingOverlay = document.getElementById('loading-overlay');
    const statusBadge = document.getElementById('status-badge');
    const statusText = document.getElementById('status-text');
    const btnPaste = document.getElementById('btn-paste');
    const btnDone = document.getElementById('btn-done');

    function setBadgeStatus(state, label) {
        if (statusText) statusText.textContent = label;
        if (!statusBadge) return;
        const base = 'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ring-black/5';
        if (state === 'active') {
            statusBadge.className = `${base} bg-emerald-50 text-emerald-700`;
        } else if (state === 'error') {
            statusBadge.className = `${base} bg-red-50 text-red-700`;
        } else if (state === 'closed') {
            statusBadge.className = `${base} bg-zinc-100 text-zinc-600`;
        } else {
            statusBadge.className = `${base} bg-amber-50 text-amber-700`;
        }
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/accounts/${accountId}/stream/`;
    const socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';

    let firstFrameReceived = false;
    let isDrawing = false;

    socket.onopen = () => {
        setBadgeStatus('starting', 'Starting browser');
    };

    socket.onclose = () => {
        setBadgeStatus('closed', 'Disconnected');
    };

    socket.onerror = () => {
        setBadgeStatus('error', 'Connection error');
    };

    socket.onmessage = async (event) => {
        if (typeof event.data === 'string') {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'status') {
                    setBadgeStatus(msg.state || 'active', msg.message || 'Live stream');
                } else if (msg.type === 'login_success') {
                    setBadgeStatus('active', `Authenticated (${msg.fb_user_id || 'Active'})`);
                    try { socket.close(); } catch (e) {}
                    setTimeout(() => {
                        window.location.href = '/accounts/';
                    }, 800);
                } else if (msg.type === 'error') {
                    setBadgeStatus('error', msg.message || 'Session error');
                }
            } catch (e) {
                console.error('Error parsing JSON message:', e);
            }
        } else {
            if (isDrawing) return;
            isDrawing = true;
            const blob = new Blob([event.data], { type: 'image/jpeg' });
            try {
                const bitmap = await createImageBitmap(blob);
                ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                bitmap.close();
                if (!firstFrameReceived) {
                    firstFrameReceived = true;
                    setBadgeStatus('active', 'Live stream');
                    if (loadingOverlay) loadingOverlay.classList.add('hidden');
                }
            } catch (err) {
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    URL.revokeObjectURL(img.src);
                    if (!firstFrameReceived) {
                        firstFrameReceived = true;
                        setBadgeStatus('active', 'Live stream');
                        if (loadingOverlay) loadingOverlay.classList.add('hidden');
                    }
                };
                img.src = URL.createObjectURL(blob);
            } finally {
                isDrawing = false;
            }
        }
    };

    function getCanvasCoordinates(e) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        return {
            x: Math.round((e.clientX - rect.left) * scaleX),
            y: Math.round((e.clientY - rect.top) * scaleY),
        };
    }

    canvas.addEventListener('click', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const { x, y } = getCanvasCoordinates(e);
        socket.send(JSON.stringify({ type: 'mouse', action: 'click', x, y, button: e.button === 2 ? 'right' : 'left' }));
        canvas.focus();
    });

    let lastMoveTime = 0;
    canvas.addEventListener('mousemove', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const now = Date.now();
        if (now - lastMoveTime < 80) return;
        lastMoveTime = now;
        const { x, y } = getCanvasCoordinates(e);
        socket.send(JSON.stringify({ type: 'mouse', action: 'move', x, y }));
    });

    canvas.addEventListener('wheel', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        e.preventDefault();
        socket.send(JSON.stringify({
            type: 'mouse',
            action: 'wheel',
            deltaX: Math.round(e.deltaX),
            deltaY: Math.round(e.deltaY),
        }));
    }, { passive: false });

    canvas.addEventListener('keydown', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        if ((e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V')) {
            return;
        }
        socket.send(JSON.stringify({ type: 'keyboard', action: 'down', key: e.key }));
        if (['Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Backspace', 'Enter'].includes(e.key)) {
            e.preventDefault();
        }
    });

    canvas.addEventListener('keyup', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        if ((e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V')) {
            return;
        }
        socket.send(JSON.stringify({ type: 'keyboard', action: 'up', key: e.key }));
    });

    window.addEventListener('paste', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const text = (e.clipboardData || window.clipboardData)?.getData('text');
        if (text) {
            socket.send(JSON.stringify({ type: 'paste', text: text }));
        }
    });

    if (btnPaste) {
        btnPaste.addEventListener('click', async () => {
            if (socket.readyState !== WebSocket.OPEN) return;
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    socket.send(JSON.stringify({ type: 'paste', text: text }));
                }
            } catch (err) {
                const text = prompt('Paste text to insert into the browser:');
                if (text) {
                    socket.send(JSON.stringify({ type: 'paste', text: text }));
                }
            }
        });
    }

    if (btnDone) {
        btnDone.addEventListener('click', () => {
            if (socket.readyState !== WebSocket.OPEN) return;
            socket.send(JSON.stringify({ type: 'done' }));
        });
    }

    function closeSocketOnUnload() {
        if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
            try { socket.close(); } catch (e) {}
        }
    }
    window.addEventListener('pagehide', closeSocketOnUnload);
    window.addEventListener('beforeunload', closeSocketOnUnload);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStreamClient);
} else {
    initStreamClient();
}
