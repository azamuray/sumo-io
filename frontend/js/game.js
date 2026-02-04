class SumoGame {
    constructor() {
        this.ws = null;
        this.playerId = null;
        this.room = null;
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

        // Event listeners
        const playBtn = document.getElementById('play-btn');
        const nameInput = document.getElementById('player-name');

        playBtn.addEventListener('click', () => {
            console.log('Play button clicked');
            this.connect();
        });

        nameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.connect();
        });

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

    connect() {
        const name = document.getElementById('player-name').value.trim() || 'Player';
        console.log('Connecting as:', name);

        // Determine WebSocket URL
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/api/ws`;

        console.log('WebSocket URL:', wsUrl);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.ws.send(JSON.stringify({
                    type: 'join',
                    name: name
                }));
            };

            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                this.handleMessage(message);
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                this.showScreen('join-screen');
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.showScreen('join-screen');
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
        }
    }

    handleMessage(message) {
        console.log('Received:', message.type);

        switch (message.type) {
            case 'welcome':
                this.playerId = message.player_id;
                this.room = message.room;
                this.showScreen('waiting-screen');
                this.updatePlayersList();
                break;

            case 'player_joined':
            case 'player_left':
                this.room = message.room;
                this.updatePlayersList();
                break;

            case 'countdown':
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
                this.showResult(message.winner);
                break;
        }
    }

    updatePlayersList() {
        const container = document.getElementById('players-list');
        container.innerHTML = '';

        for (const player of Object.values(this.room.players)) {
            const tag = document.createElement('div');
            tag.className = 'player-tag';
            tag.style.backgroundColor = player.color;
            tag.textContent = player.name + (player.id === this.playerId ? ' (ты)' : '');
            container.appendChild(tag);
        }
    }

    showResult(winnerId) {
        this.showScreen('result-screen');
        const resultText = document.getElementById('result-text');

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
            ctx.font = `bold ${12 * scale}px sans-serif`;
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
