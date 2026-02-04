class SumoGame {
    constructor() {
        this.ws = null;
        this.playerId = null;
        this.room = null;
        this.isOwner = false;
        this.isPublicRoom = false;
        this.canvas = document.getElementById('game-canvas');
        this.ctx = this.canvas.getContext('2d');

        // Touch/mouse input
        this.inputActive = false;
        this.inputStart = { x: 0, y: 0 };
        this.inputCurrent = { x: 0, y: 0 };

        this.init();
    }

    init() {
        // Telegram Web App integration
        if (window.Telegram?.WebApp) {
            const tg = Telegram.WebApp;
            tg.ready();
            tg.expand();

            // Get user name from Telegram
            const user = tg.initDataUnsafe?.user;
            if (user?.first_name) {
                document.getElementById('player-name').value = user.first_name;
            }

            // Apply Telegram theme
            document.body.style.backgroundColor = tg.backgroundColor || '#1a1a2e';
        }

        // Event listeners - Menu
        document.getElementById('create-private-btn').addEventListener('click', () => this.createRoom(false));
        document.getElementById('create-public-btn').addEventListener('click', () => this.createRoom(true));
        document.getElementById('join-btn').addEventListener('click', () => this.joinRoom());
        document.getElementById('refresh-lobby-btn').addEventListener('click', () => this.refreshLobby());

        document.getElementById('room-code').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.joinRoom();
        });

        // Load public rooms on start
        this.refreshLobby();

        // Event listeners - Waiting room
        document.getElementById('start-btn').addEventListener('click', () => this.startGame());
        document.getElementById('copy-code-btn').addEventListener('click', () => this.copyRoomCode());
        document.getElementById('share-btn').addEventListener('click', () => this.shareRoom());

        // Event listeners - Result screen
        document.getElementById('rematch-btn').addEventListener('click', () => this.rematch());

        // Canvas resize
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());

        // Input handlers
        this.canvas.addEventListener('mousedown', (e) => this.onInputStart(e.clientX, e.clientY));
        this.canvas.addEventListener('mousemove', (e) => this.onInputMove(e.clientX, e.clientY));
        this.canvas.addEventListener('mouseup', () => this.onInputEnd());
        this.canvas.addEventListener('mouseleave', () => this.onInputEnd());

        this.canvas.addEventListener('touchstart', (e) => {
            e.preventDefault();
            const touch = e.touches[0];
            this.onInputStart(touch.clientX, touch.clientY);
        }, { passive: false });

        this.canvas.addEventListener('touchmove', (e) => {
            e.preventDefault();
            const touch = e.touches[0];
            this.onInputMove(touch.clientX, touch.clientY);
        }, { passive: false });

        this.canvas.addEventListener('touchend', () => this.onInputEnd());
        this.canvas.addEventListener('touchcancel', () => this.onInputEnd());

        // Start render loop
        this.render();

        console.log('Game initialized');
    }

    resizeCanvas() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        document.getElementById(screenId).classList.add('active');
    }

    getName() {
        return document.getElementById('player-name').value.trim() || 'Игрок';
    }

    createRoom(isPublic = false) {
        this.isPublicRoom = isPublic;
        this.connect('create');
    }

    async refreshLobby() {
        try {
            const response = await fetch('/api/rooms');
            const data = await response.json();
            this.renderLobby(data.rooms || []);
        } catch (e) {
            console.error('Failed to fetch public rooms:', e);
        }
    }

    renderLobby(rooms) {
        const container = document.getElementById('lobby-list');

        if (rooms.length === 0) {
            container.innerHTML = '<div class="lobby-empty">Нет публичных комнат</div>';
            return;
        }

        container.innerHTML = rooms.map(room => `
            <div class="lobby-item">
                <div class="lobby-info">
                    <div class="lobby-host">${room.owner_name || 'Комната'} (${room.id})</div>
                    <div class="lobby-players">${room.player_count}/${room.max_players} игроков</div>
                </div>
                <button class="lobby-join-btn" data-room-id="${room.id}">Войти</button>
            </div>
        `).join('');

        // Add click handlers for join buttons
        container.querySelectorAll('.lobby-join-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const roomId = btn.dataset.roomId;
                this.connect('join', roomId);
            });
        });
    }

    joinRoom() {
        const roomCode = document.getElementById('room-code').value.trim().toUpperCase();
        if (!roomCode) {
            alert('Введите код комнаты');
            return;
        }
        this.connect('join', roomCode);
    }

    connect(action, roomId = null) {
        const name = this.getName();
        console.log(`${action} room as:`, name);

        // Determine WebSocket URL
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/api/ws`;

        console.log('WebSocket URL:', wsUrl);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                const message = {
                    type: action,
                    name: name
                };
                if (roomId) {
                    message.room_id = roomId;
                }
                if (action === 'create' && this.isPublicRoom) {
                    message.is_public = true;
                }
                this.ws.send(JSON.stringify(message));
            };

            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                this.handleMessage(message);
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                this.showScreen('menu-screen');
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.showScreen('menu-screen');
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
        }
    }

    handleMessage(message) {
        console.log('Received:', message.type);

        switch (message.type) {
            case 'error':
                alert(message.message);
                this.showScreen('menu-screen');
                break;

            case 'welcome':
                this.playerId = message.player_id;
                this.room = message.room;
                this.isOwner = this.room.owner_id === this.playerId;
                this.showScreen('waiting-screen');
                this.updateWaitingRoom();
                break;

            case 'player_joined':
            case 'player_left':
                this.room = message.room;
                this.isOwner = this.room.owner_id === this.playerId;
                this.updateWaitingRoom();
                break;

            case 'game_starting':
                this.room = message.room;
                break;

            case 'countdown':
                this.room = message.room;
                this.showScreen('countdown-screen');
                document.getElementById('countdown-number').textContent = message.countdown;
                // Haptic feedback
                if (window.Telegram?.WebApp?.HapticFeedback) {
                    Telegram.WebApp.HapticFeedback.impactOccurred('medium');
                }
                break;

            case 'state':
                this.room = message.room;
                this.showScreen('game-screen');
                break;

            case 'finished':
                this.room = message.room;
                this.isOwner = this.room.owner_id === this.playerId;
                this.showResult(message.winner);
                break;

            case 'rematch_starting':
                this.room = message.room;
                break;
        }
    }

    updateWaitingRoom() {
        // Update room code
        document.getElementById('room-code-value').textContent = this.room.id;

        // Update players list
        const container = document.getElementById('players-list');
        container.innerHTML = '';

        for (const player of Object.values(this.room.players)) {
            const tag = document.createElement('div');
            tag.className = 'player-tag';
            tag.style.backgroundColor = player.color;

            let html = player.name;
            if (player.id === this.playerId) html += ' (ты)';
            if (player.id === this.room.owner_id) html += '<span class="owner-badge">Хост</span>';
            tag.innerHTML = html;

            container.appendChild(tag);
        }

        // Show/hide start button
        const startBtn = document.getElementById('start-btn');
        const waitingHint = document.getElementById('waiting-hint');

        if (this.isOwner) {
            startBtn.style.display = 'block';
            if (Object.keys(this.room.players).length >= 2) {
                startBtn.disabled = false;
                waitingHint.textContent = 'Нажми СТАРТ когда все готовы';
            } else {
                startBtn.disabled = true;
                waitingHint.textContent = 'Нужно минимум 2 игрока';
            }
        } else {
            startBtn.style.display = 'none';
            waitingHint.textContent = 'Ожидайте, пока хост начнёт игру';
        }
    }

    startGame() {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'start' }));
        }
    }

    copyRoomCode() {
        const code = this.room?.id || '';
        navigator.clipboard.writeText(code).then(() => {
            // Haptic feedback
            if (window.Telegram?.WebApp?.HapticFeedback) {
                Telegram.WebApp.HapticFeedback.notificationOccurred('success');
            }
        });
    }

    shareRoom() {
        const code = this.room?.id || '';
        const text = `Играем в Sumo.io! Заходи: @sumo_io_bot\nКод комнаты: ${code}`;

        navigator.clipboard.writeText(text).then(() => {
            if (window.Telegram?.WebApp?.HapticFeedback) {
                Telegram.WebApp.HapticFeedback.notificationOccurred('success');
            }
            if (window.Telegram?.WebApp?.showAlert) {
                Telegram.WebApp.showAlert('Скопировано! Отправь это сообщение другу');
            } else {
                alert('Скопировано! Отправь это сообщение другу');
            }
        });
    }

    showResult(winnerId) {
        this.showScreen('result-screen');
        const resultText = document.getElementById('result-text');
        const rematchBtn = document.getElementById('rematch-btn');
        const resultHint = document.getElementById('result-hint');

        if (winnerId === this.playerId) {
            resultText.textContent = 'Победа!';
            resultText.className = 'result-text win';
            if (window.Telegram?.WebApp?.HapticFeedback) {
                Telegram.WebApp.HapticFeedback.notificationOccurred('success');
            }
        } else if (winnerId) {
            const winner = this.room.players[winnerId];
            resultText.textContent = `${winner?.name || 'Игрок'} победил!`;
            resultText.className = 'result-text lose';
        } else {
            resultText.textContent = 'Ничья!';
            resultText.className = 'result-text';
        }

        // Show rematch button for owner
        if (this.isOwner && Object.keys(this.room.players).length >= 2) {
            rematchBtn.style.display = 'block';
            resultHint.textContent = 'Нажми РЕВАНШ для новой игры';
        } else {
            rematchBtn.style.display = 'none';
            resultHint.textContent = 'Ожидание реванша от хоста...';
        }
    }

    rematch() {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'rematch' }));
        }
    }

    onInputStart(x, y) {
        this.inputActive = true;
        this.inputStart = { x, y };
        this.inputCurrent = { x, y };
    }

    onInputMove(x, y) {
        if (!this.inputActive) return;
        this.inputCurrent = { x, y };

        // Calculate direction
        const dx = this.inputCurrent.x - this.inputStart.x;
        const dy = this.inputCurrent.y - this.inputStart.y;

        // Send input if significant movement
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance > 10 && this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'input',
                dx: dx,
                dy: dy
            }));

            // Reset start for continuous control
            this.inputStart = { x, y };
        }
    }

    onInputEnd() {
        this.inputActive = false;
    }

    render() {
        requestAnimationFrame(() => this.render());

        if (!this.room || this.room.state !== 'playing') return;

        const ctx = this.ctx;
        const width = this.canvas.width;
        const height = this.canvas.height;
        const centerX = width / 2;
        const centerY = height / 2;
        const scale = Math.min(width, height) / (this.room.arena_radius * 2.5);

        // Clear
        ctx.fillStyle = '#1a1a2e';
        ctx.fillRect(0, 0, width, height);

        // Draw arena
        ctx.beginPath();
        ctx.arc(centerX, centerY, this.room.arena_radius * scale, 0, Math.PI * 2);
        ctx.fillStyle = '#2a2a4e';
        ctx.fill();
        ctx.strokeStyle = '#4ECDC4';
        ctx.lineWidth = 3;
        ctx.stroke();

        // Draw danger zone (edge)
        ctx.beginPath();
        ctx.arc(centerX, centerY, this.room.arena_radius * scale, 0, Math.PI * 2);
        const gradient = ctx.createRadialGradient(
            centerX, centerY, this.room.arena_radius * scale * 0.8,
            centerX, centerY, this.room.arena_radius * scale
        );
        gradient.addColorStop(0, 'transparent');
        gradient.addColorStop(1, 'rgba(255, 107, 107, 0.3)');
        ctx.fillStyle = gradient;
        ctx.fill();

        // Draw players
        for (const player of Object.values(this.room.players)) {
            if (!player.alive) continue;

            const px = centerX + player.x * scale;
            const py = centerY + player.y * scale;
            const radius = this.room.player_radius * scale;

            // Shadow
            ctx.beginPath();
            ctx.arc(px + 3, py + 3, radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
            ctx.fill();

            // Player circle
            ctx.beginPath();
            ctx.arc(px, py, radius, 0, Math.PI * 2);
            ctx.fillStyle = player.color;
            ctx.fill();

            // Highlight for current player
            if (player.id === this.playerId) {
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 3;
                ctx.stroke();
            }

            // Name
            ctx.fillStyle = '#fff';
            ctx.font = `bold ${Math.max(10, 12 * scale)}px sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(player.name, px, py);
        }

        // Draw input indicator
        if (this.inputActive) {
            const dx = this.inputCurrent.x - this.inputStart.x;
            const dy = this.inputCurrent.y - this.inputStart.y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            if (distance > 10) {
                ctx.beginPath();
                ctx.moveTo(this.inputStart.x, this.inputStart.y);
                ctx.lineTo(this.inputCurrent.x, this.inputCurrent.y);
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
                ctx.lineWidth = 3;
                ctx.stroke();

                // Arrow head
                const angle = Math.atan2(dy, dx);
                ctx.beginPath();
                ctx.moveTo(this.inputCurrent.x, this.inputCurrent.y);
                ctx.lineTo(
                    this.inputCurrent.x - 15 * Math.cos(angle - 0.3),
                    this.inputCurrent.y - 15 * Math.sin(angle - 0.3)
                );
                ctx.lineTo(
                    this.inputCurrent.x - 15 * Math.cos(angle + 0.3),
                    this.inputCurrent.y - 15 * Math.sin(angle + 0.3)
                );
                ctx.closePath();
                ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
                ctx.fill();
            }
        }

        // Update scoreboard
        this.updateScoreboard();
    }

    updateScoreboard() {
        const container = document.getElementById('scoreboard');
        const players = Object.values(this.room.players)
            .sort((a, b) => b.score - a.score);

        container.innerHTML = players.map(p => `
            <div class="score-item" style="opacity: ${p.alive ? 1 : 0.4}">
                <div class="score-dot" style="background: ${p.color}"></div>
                <span class="score-name">${p.name}${p.id === this.playerId ? ' (ты)' : ''}</span>
                <span class="score-value">${p.score}</span>
            </div>
        `).join('');
    }
}

// Start game when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, starting game...');
    window.game = new SumoGame();
});
