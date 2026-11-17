document.addEventListener('DOMContentLoaded', () => {
    const scriptMeta = document.getElementById('stream-meta');
    const accountId = scriptMeta ? scriptMeta.getAttribute('data-account-id') : null;
    if (!accountId) return;

    const canvas = document.getElementById('stream-canvas');
    const ctx = canvas.getContext('2d');
    const loadingOverlay = document.getElementById('loading-overlay');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const btnPaste = document.getElementById('btn-paste');
    const btnDone = document.getElementById('btn-done');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/accounts/${accountId}/stream/`;
    const socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';

    let firstFrameReceived = false;

    socket.onopen = () => {
        statusText.textContent = 'Live Streaming';
        statusDot.className = 'w-3 h-3 rounded-full bg-emerald-500 animate-pulse';
    };

    socket.onclose = () => {
        statusText.textContent = 'Disconnected';
        statusDot.className = 'w-3 h-3 rounded-full bg-slate-500';
    };

    socket.onerror = (err) => {
        statusText.textContent = 'Connection Error';
        statusDot.className = 'w-3 h-3 rounded-full bg-red-500';
    };

    socket.onmessage = async (event) => {
        if (typeof event.data === 'string') {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'login_success') {
                    statusText.textContent = `Logged in (FB ID: ${msg.fb_user_id || 'Active'})`;
                    statusDot.className = 'w-3 h-3 rounded-full bg-emerald-400';
                    setTimeout(() => {
                        window.location.href = '/accounts/';
                    }, 1500);
                } else if (msg.type === 'error') {
                    alert(`Streaming error: ${msg.message}`);
                }
            } catch (e) {
                console.error('Error parsing JSON message:', e);
            }
        } else {
            // Binary JPEG frame
            const blob = new Blob([event.data], { type: 'image/jpeg' });
            try {
                const bitmap = await createImageBitmap(blob);
                ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                bitmap.close();
                if (!firstFrameReceived) {
                    firstFrameReceived = true;
                    if (loadingOverlay) loadingOverlay.classList.add('hidden');
                }
            } catch (err) {
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    if (!firstFrameReceived) {
                        firstFrameReceived = true;
                        if (loadingOverlay) loadingOverlay.classList.add('hidden');
                    }
                };
                img.src = URL.createObjectURL(blob);
            }
        }
    };

    // Coordinate conversion
    function getCanvasCoordinates(e) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        return {
            x: Math.round((e.clientX - rect.left) * scaleX),
            y: Math.round((e.clientY - rect.top) * scaleY),
        };
    }

    // Pointer events
    canvas.addEventListener('mousedown', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const { x, y } = getCanvasCoordinates(e);
        socket.send(JSON.stringify({ type: 'mouse', action: 'down', x, y, button: e.button === 2 ? 'right' : 'left' }));
    });

    canvas.addEventListener('mouseup', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const { x, y } = getCanvasCoordinates(e);
        socket.send(JSON.stringify({ type: 'mouse', action: 'up', x, y, button: e.button === 2 ? 'right' : 'left' }));
    });

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
        if (now - lastMoveTime < 40) return; // 25 fps throttle on move
        lastMoveTime = now;
        const { x, y } = getCanvasCoordinates(e);
        socket.send(JSON.stringify({ type: 'mouse', action: 'move', x, y }));
    });

    // Keyboard events
    canvas.addEventListener('keydown', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        // Allow paste event to fire for Ctrl+V
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

    // Native Ctrl+V / Clipboard Paste Event Listener
    window.addEventListener('paste', (e) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const text = (e.clipboardData || window.clipboardData)?.getData('text');
        if (text) {
            socket.send(JSON.stringify({ type: 'paste', text: text }));
        }
    });

    // Quick-Paste Button Action
    if (btnPaste) {
        btnPaste.addEventListener('click', async () => {
            if (socket.readyState !== WebSocket.OPEN) return;
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    socket.send(JSON.stringify({ type: 'paste', text: text }));
                }
            } catch (err) {
                const text = prompt('Paste your text / password here:');
                if (text) {
                    socket.send(JSON.stringify({ type: 'paste', text: text }));
                }
            }
        });
    }

    // Done Button Action
    if (btnDone) {
        btnDone.addEventListener('click', () => {
            if (socket.readyState !== WebSocket.OPEN) return;
            socket.send(JSON.stringify({ type: 'done' }));
        });
    }
});
