import asyncio
import json
import math
import random
import string
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Forward declaration for lifespan
game_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start bot rooms on app startup"""
    global game_manager
    game_manager = GameManager()
    # Start maintaining bot rooms
    asyncio.create_task(game_manager.maintain_bot_rooms())
    yield


app = FastAPI(title="Sumo.io API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Game constants
ARENA_RADIUS = 400
PLAYER_RADIUS = 25
FRICTION = 0.96
BOUNCE_FORCE = 8
TICK_RATE = 1 / 60  # 60 FPS
MAX_PLAYERS_PER_ROOM = 8
MIN_PLAYERS_TO_START = 2
COUNTDOWN_SECONDS = 3

# Bot constants
BOT_ROOMS_MIN = 2
BOT_ROOMS_MAX = 5
BOT_NAMES = [
    "Борец", "Силач", "Толкач", "Сумоист", "Чемпион",
    "Гром", "Молния", "Скала", "Титан", "Воин",
    "Буря", "Вихрь", "Танк", "Медведь", "Бык",
    "Самурай", "Ниндзя", "Дракон", "Феникс", "Лев"
]


@dataclass
class Player:
    id: str
    name: str
    x: float = 0
    y: float = 0
    vx: float = 0
    vy: float = 0
    color: str = "#FF6B6B"
    alive: bool = True
    score: int = 0
    websocket: Optional[WebSocket] = None
    is_bot: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "vx": self.vx,
            "vy": self.vy,
            "color": self.color,
            "alive": self.alive,
            "score": self.score,
            "is_bot": self.is_bot,
        }


@dataclass
class Room:
    id: str
    owner_id: Optional[str] = None  # Creator of the room
    is_public: bool = False  # Public rooms visible in lobby
    is_bot_room: bool = False  # Room with bots
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting, countdown, playing, finished
    countdown: int = COUNTDOWN_SECONDS
    winner: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "is_public": self.is_public,
            "is_bot_room": self.is_bot_room,
            "players": {pid: p.to_dict() for pid, p in self.players.items()},
            "player_count": len(self.players),
            "state": self.state,
            "countdown": self.countdown,
            "winner": self.winner,
            "arena_radius": ARENA_RADIUS,
            "player_radius": PLAYER_RADIUS,
        }

    def to_lobby_dict(self):
        """Minimal info for lobby list"""
        owner_name = None
        if self.owner_id and self.owner_id in self.players:
            owner_name = self.players[self.owner_id].name
        return {
            "id": self.id,
            "player_count": len(self.players),
            "max_players": MAX_PLAYERS_PER_ROOM,
            "owner_name": owner_name,
            "state": self.state,
            "is_bot_room": self.is_bot_room,
        }

    def has_real_players(self) -> bool:
        """Check if room has any non-bot players"""
        return any(not p.is_bot for p in self.players.values())

    def get_real_player_count(self) -> int:
        """Count non-bot players"""
        return sum(1 for p in self.players.values() if not p.is_bot)


class GameManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_rooms: dict[str, str] = {}  # player_id -> room_id
        self.colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
            "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"
        ]

    def generate_room_id(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase, k=4))

    def generate_player_id(self) -> str:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

    def create_room(self, is_public: bool = False, is_bot_room: bool = False) -> Room:
        """Create a new room"""
        room_id = self.generate_room_id()
        while room_id in self.rooms:
            room_id = self.generate_room_id()
        room = Room(id=room_id, is_public=is_public, is_bot_room=is_bot_room)
        self.rooms[room_id] = room
        return room

    def add_bot(self, room: Room) -> Player:
        """Add a bot player to the room"""
        bot_id = "bot_" + self.generate_player_id()
        x, y = self.spawn_position(room)
        color = self.colors[len(room.players) % len(self.colors)]
        name = random.choice(BOT_NAMES)

        bot = Player(
            id=bot_id,
            name=name,
            x=x,
            y=y,
            color=color,
            is_bot=True,
        )

        room.players[bot_id] = bot
        self.player_rooms[bot_id] = room.id

        if room.owner_id is None:
            room.owner_id = bot_id

        return bot

    def create_bot_room(self) -> Room:
        """Create a public room with bots"""
        room = self.create_room(is_public=True, is_bot_room=True)

        # Add 2-7 bots (leave space for real player)
        num_bots = random.randint(2, 7)
        for _ in range(num_bots):
            self.add_bot(room)

        # Start game loop
        asyncio.create_task(self.run_game_loop(room))
        return room

    def update_bot_ai(self, room: Room):
        """Update bot movements"""
        if room.state != "playing":
            return

        alive_bots = [p for p in room.players.values() if p.alive and p.is_bot]
        alive_players = [p for p in room.players.values() if p.alive]

        for bot in alive_bots:
            # Find nearest non-bot player or nearest player
            targets = [p for p in alive_players if p.id != bot.id and not p.is_bot]
            if not targets:
                targets = [p for p in alive_players if p.id != bot.id]

            if targets:
                # Move toward nearest target
                nearest = min(targets, key=lambda p: math.sqrt((p.x - bot.x)**2 + (p.y - bot.y)**2))
                dx = nearest.x - bot.x
                dy = nearest.y - bot.y
            else:
                # Move toward center if alone
                dx = -bot.x
                dy = -bot.y

            # Normalize and apply force (with some randomness)
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > 0:
                dx = dx / distance
                dy = dy / distance
                # Add randomness to make bots less predictable
                dx += random.uniform(-0.3, 0.3)
                dy += random.uniform(-0.3, 0.3)
                # Bots don't push every frame - random chance
                if random.random() < 0.15:  # 15% chance per tick
                    bot.vx += dx * 1.2
                    bot.vy += dy * 1.2

    def get_bot_room_count(self) -> int:
        """Count active bot rooms in waiting state"""
        return sum(1 for r in self.rooms.values()
                   if r.is_bot_room and r.state == "waiting")

    async def maintain_bot_rooms(self):
        """Background task to maintain bot rooms"""
        while True:
            try:
                current_count = self.get_bot_room_count()

                # Create more bot rooms if needed
                while current_count < BOT_ROOMS_MIN:
                    self.create_bot_room()
                    current_count += 1

                # Occasionally create extra rooms up to max
                if current_count < BOT_ROOMS_MAX and random.random() < 0.1:
                    self.create_bot_room()

            except Exception as e:
                print(f"Error maintaining bot rooms: {e}")

            await asyncio.sleep(5)  # Check every 5 seconds

    def get_public_rooms(self) -> list[dict]:
        """Get list of public rooms that can be joined"""
        public_rooms = []
        for room in self.rooms.values():
            if (room.is_public and
                room.state == "waiting" and
                len(room.players) < MAX_PLAYERS_PER_ROOM):
                public_rooms.append(room.to_lobby_dict())
        return public_rooms

    def get_room(self, room_id: str) -> Optional[Room]:
        """Get room by ID (case insensitive)"""
        return self.rooms.get(room_id.upper())

    def spawn_position(self, room: Room) -> tuple[float, float]:
        """Generate spawn position on the edge of arena"""
        num_players = len(room.players)
        # Distribute players evenly around the arena
        angle = (2 * math.pi * num_players / max(8, num_players + 1)) + random.uniform(-0.2, 0.2)
        distance = ARENA_RADIUS * 0.6
        x = math.cos(angle) * distance
        y = math.sin(angle) * distance
        return x, y

    def add_player(self, room: Room, name: str, websocket: WebSocket) -> Player:
        player_id = self.generate_player_id()
        x, y = self.spawn_position(room)
        color = self.colors[len(room.players) % len(self.colors)]

        player = Player(
            id=player_id,
            name=name[:15],  # Limit name length
            x=x,
            y=y,
            color=color,
            websocket=websocket,
        )

        room.players[player_id] = player
        self.player_rooms[player_id] = room.id

        # First player becomes owner
        if room.owner_id is None:
            room.owner_id = player_id

        return player

    def remove_player(self, player_id: str):
        if player_id not in self.player_rooms:
            return

        room_id = self.player_rooms[player_id]
        if room_id in self.rooms:
            room = self.rooms[room_id]
            if player_id in room.players:
                del room.players[player_id]

            # Transfer ownership if owner left
            if room.owner_id == player_id and len(room.players) > 0:
                room.owner_id = next(iter(room.players.keys()))

            # Clean up empty rooms
            if len(room.players) == 0:
                del self.rooms[room_id]

        del self.player_rooms[player_id]

    def start_game(self, player_id: str) -> bool:
        """Start game - only owner can do this"""
        if player_id not in self.player_rooms:
            return False

        room_id = self.player_rooms[player_id]
        room = self.rooms.get(room_id)

        if not room:
            return False

        # Only owner can start
        if room.owner_id != player_id:
            return False

        # Need at least 2 players
        if len(room.players) < MIN_PLAYERS_TO_START:
            return False

        # Can only start from waiting state
        if room.state != "waiting":
            return False

        room.state = "countdown"
        room.countdown = COUNTDOWN_SECONDS
        return True

    def rematch(self, player_id: str) -> bool:
        """Start rematch - only owner can do this"""
        if player_id not in self.player_rooms:
            return False

        room_id = self.player_rooms[player_id]
        room = self.rooms.get(room_id)

        if not room:
            return False

        # Only owner can start rematch
        if room.owner_id != player_id:
            return False

        # Need at least 2 players
        if len(room.players) < MIN_PLAYERS_TO_START:
            return False

        # Can only rematch from finished state
        if room.state != "finished":
            return False

        # Reset for new round
        room.state = "countdown"
        room.winner = None
        room.countdown = COUNTDOWN_SECONDS
        for i, player in enumerate(room.players.values()):
            player.alive = True
            angle = 2 * math.pi * i / len(room.players)
            distance = ARENA_RADIUS * 0.6
            player.x = math.cos(angle) * distance
            player.y = math.sin(angle) * distance
            player.vx = 0
            player.vy = 0

        return True

    def apply_input(self, player_id: str, dx: float, dy: float):
        if player_id not in self.player_rooms:
            return

        room_id = self.player_rooms[player_id]
        room = self.rooms.get(room_id)
        if not room or room.state != "playing":
            return

        player = room.players.get(player_id)
        if not player or not player.alive:
            return

        # Normalize and apply force
        magnitude = math.sqrt(dx * dx + dy * dy)
        if magnitude > 0:
            dx = dx / magnitude
            dy = dy / magnitude
            player.vx += dx * 1.5  # Reduced from 2
            player.vy += dy * 1.5

    def update_physics(self, room: Room):
        if room.state != "playing":
            return

        alive_players = [p for p in room.players.values() if p.alive]

        for player in alive_players:
            # Apply velocity
            player.x += player.vx
            player.y += player.vy

            # Apply friction
            player.vx *= FRICTION
            player.vy *= FRICTION

            # Check if out of arena
            distance = math.sqrt(player.x ** 2 + player.y ** 2)
            if distance > ARENA_RADIUS + PLAYER_RADIUS:
                player.alive = False

        # Check collisions between players
        for i, p1 in enumerate(alive_players):
            for p2 in alive_players[i + 1:]:
                dx = p2.x - p1.x
                dy = p2.y - p1.y
                distance = math.sqrt(dx * dx + dy * dy)

                if distance < PLAYER_RADIUS * 2 and distance > 0:
                    # Collision!
                    nx = dx / distance
                    ny = dy / distance

                    # Push apart
                    overlap = PLAYER_RADIUS * 2 - distance
                    p1.x -= nx * overlap / 2
                    p1.y -= ny * overlap / 2
                    p2.x += nx * overlap / 2
                    p2.y += ny * overlap / 2

                    # Calculate relative velocity
                    dvx = p1.vx - p2.vx
                    dvy = p1.vy - p2.vy
                    dvn = dvx * nx + dvy * ny

                    # Only bounce if moving towards each other
                    if dvn > 0:
                        p1.vx -= nx * dvn * 0.8
                        p1.vy -= ny * dvn * 0.8
                        p2.vx += nx * dvn * 0.8
                        p2.vy += ny * dvn * 0.8

                        # Add small bounce
                        p1.vx -= nx * BOUNCE_FORCE * 0.5
                        p1.vy -= ny * BOUNCE_FORCE * 0.5
                        p2.vx += nx * BOUNCE_FORCE * 0.5
                        p2.vy += ny * BOUNCE_FORCE * 0.5

        # Check for winner
        alive_players = [p for p in room.players.values() if p.alive]
        if len(alive_players) <= 1 and len(room.players) >= MIN_PLAYERS_TO_START:
            room.state = "finished"
            if alive_players:
                winner = alive_players[0]
                winner.score += 1
                room.winner = winner.id

    async def broadcast(self, room: Room, message: dict):
        data = json.dumps(message)
        disconnected = []

        for player in room.players.values():
            if player.websocket:
                try:
                    await player.websocket.send_text(data)
                except:
                    disconnected.append(player.id)

        for pid in disconnected:
            self.remove_player(pid)

    async def run_game_loop(self, room: Room):
        rematch_timer = 0  # For auto-rematch in bot rooms

        while room.id in self.rooms and len(room.players) > 0:
            # For bot rooms: if no real players, stay in waiting
            if room.is_bot_room and not room.has_real_players():
                if room.state != "waiting":
                    # Reset room if all real players left
                    room.state = "waiting"
                    room.winner = None
                    room.countdown = COUNTDOWN_SECONDS
                    for i, player in enumerate(room.players.values()):
                        player.alive = True
                        angle = 2 * math.pi * i / len(room.players)
                        distance = ARENA_RADIUS * 0.6
                        player.x = math.cos(angle) * distance
                        player.y = math.sin(angle) * distance
                        player.vx = 0
                        player.vy = 0
                await asyncio.sleep(0.1)
                continue

            if room.state == "waiting":
                # Auto-start bot rooms when real player joins
                if room.is_bot_room and room.has_real_players():
                    room.state = "countdown"
                    room.countdown = COUNTDOWN_SECONDS
                    await self.broadcast(room, {
                        "type": "game_starting",
                        "room": room.to_dict(),
                    })
                await asyncio.sleep(0.1)

            elif room.state == "countdown":
                await self.broadcast(room, {
                    "type": "countdown",
                    "countdown": room.countdown,
                    "room": room.to_dict(),
                })
                await asyncio.sleep(1)
                room.countdown -= 1

                if room.countdown <= 0:
                    room.state = "playing"
                    # Reset positions
                    for i, player in enumerate(room.players.values()):
                        angle = 2 * math.pi * i / len(room.players)
                        distance = ARENA_RADIUS * 0.6
                        player.x = math.cos(angle) * distance
                        player.y = math.sin(angle) * distance
                        player.vx = 0
                        player.vy = 0
                        player.alive = True

            elif room.state == "playing":
                self.update_bot_ai(room)  # Update bot movements
                self.update_physics(room)
                await self.broadcast(room, {
                    "type": "state",
                    "room": room.to_dict(),
                })
                await asyncio.sleep(TICK_RATE)

            elif room.state == "finished":
                await self.broadcast(room, {
                    "type": "finished",
                    "winner": room.winner,
                    "room": room.to_dict(),
                })

                # Auto-rematch in bot rooms after 3 seconds
                if room.is_bot_room and room.has_real_players():
                    rematch_timer += 0.1
                    if rematch_timer >= 3.0:
                        rematch_timer = 0
                        room.state = "countdown"
                        room.winner = None
                        room.countdown = COUNTDOWN_SECONDS
                        for i, player in enumerate(room.players.values()):
                            player.alive = True
                            angle = 2 * math.pi * i / len(room.players)
                            distance = ARENA_RADIUS * 0.6
                            player.x = math.cos(angle) * distance
                            player.y = math.sin(angle) * distance
                            player.vx = 0
                            player.vy = 0
                        await self.broadcast(room, {
                            "type": "rematch_starting",
                            "room": room.to_dict(),
                        })

                await asyncio.sleep(0.1)

            else:
                await asyncio.sleep(0.1)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/rooms")
async def get_public_rooms():
    """Get list of public rooms"""
    return {"rooms": game_manager.get_public_rooms()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    player: Optional[Player] = None
    room: Optional[Room] = None

    try:
        # Wait for join message
        data = await websocket.receive_text()
        message = json.loads(data)

        msg_type = message.get("type")
        name = message.get("name", "Player")[:15]

        if msg_type == "create":
            # Create new room
            is_public = message.get("is_public", False)
            room = game_manager.create_room(is_public=is_public)
            player = game_manager.add_player(room, name, websocket)

        elif msg_type == "join":
            room_id = message.get("room_id", "").upper()
            if room_id:
                # Join specific room
                room = game_manager.get_room(room_id)
                if not room:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Комната не найдена"
                    }))
                    await websocket.close()
                    return
                if len(room.players) >= MAX_PLAYERS_PER_ROOM:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Комната заполнена"
                    }))
                    await websocket.close()
                    return
                if room.state != "waiting":
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Игра уже началась"
                    }))
                    await websocket.close()
                    return
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Укажите код комнаты"
                }))
                await websocket.close()
                return

            player = game_manager.add_player(room, name, websocket)

        else:
            await websocket.close()
            return

        # Send welcome
        await websocket.send_text(json.dumps({
            "type": "welcome",
            "player_id": player.id,
            "room": room.to_dict(),
        }))

        # Notify others
        await game_manager.broadcast(room, {
            "type": "player_joined",
            "player": player.to_dict(),
            "room": room.to_dict(),
        })

        # Start game loop if not running
        if len(room.players) == 1:
            asyncio.create_task(game_manager.run_game_loop(room))

        # Handle messages
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "input":
                dx = float(message.get("dx", 0))
                dy = float(message.get("dy", 0))
                game_manager.apply_input(player.id, dx, dy)

            elif message.get("type") == "start":
                if game_manager.start_game(player.id):
                    await game_manager.broadcast(room, {
                        "type": "game_starting",
                        "room": room.to_dict(),
                    })

            elif message.get("type") == "rematch":
                if game_manager.rematch(player.id):
                    await game_manager.broadcast(room, {
                        "type": "rematch_starting",
                        "room": room.to_dict(),
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if player:
            game_manager.remove_player(player.id)
            if room and room.id in game_manager.rooms:
                await game_manager.broadcast(room, {
                    "type": "player_left",
                    "player_id": player.id,
                    "room": room.to_dict(),
                })
