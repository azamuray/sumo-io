import asyncio
import json
import math
import random
import string
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Sumo.io API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Game constants
ARENA_RADIUS = 300
PLAYER_RADIUS = 25
FRICTION = 0.98
BOUNCE_FORCE = 15
TICK_RATE = 1 / 60  # 60 FPS
MAX_PLAYERS_PER_ROOM = 8
MIN_PLAYERS_TO_START = 2
COUNTDOWN_SECONDS = 5


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
        }


@dataclass
class Room:
    id: str
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting, countdown, playing, finished
    countdown: int = COUNTDOWN_SECONDS
    winner: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "players": {pid: p.to_dict() for pid, p in self.players.items()},
            "state": self.state,
            "countdown": self.countdown,
            "winner": self.winner,
            "arena_radius": ARENA_RADIUS,
            "player_radius": PLAYER_RADIUS,
        }


class GameManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_rooms: dict[str, str] = {}  # player_id -> room_id
        self.colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
            "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"
        ]

    def generate_room_id(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    def generate_player_id(self) -> str:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

    def find_or_create_room(self) -> Room:
        # Find room with space
        for room in self.rooms.values():
            if room.state == "waiting" and len(room.players) < MAX_PLAYERS_PER_ROOM:
                return room

        # Create new room
        room_id = self.generate_room_id()
        room = Room(id=room_id)
        self.rooms[room_id] = room
        return room

    def spawn_position(self, room: Room) -> tuple[float, float]:
        """Generate spawn position on the edge of arena"""
        angle = random.uniform(0, 2 * math.pi)
        distance = ARENA_RADIUS * 0.7
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
        return player

    def remove_player(self, player_id: str):
        if player_id not in self.player_rooms:
            return

        room_id = self.player_rooms[player_id]
        if room_id in self.rooms:
            room = self.rooms[room_id]
            if player_id in room.players:
                del room.players[player_id]

            # Clean up empty rooms
            if len(room.players) == 0:
                del self.rooms[room_id]

        del self.player_rooms[player_id]

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
            player.vx += dx * 2
            player.vy += dy * 2

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

                    # Bounce velocity
                    p1.vx -= nx * BOUNCE_FORCE
                    p1.vy -= ny * BOUNCE_FORCE
                    p2.vx += nx * BOUNCE_FORCE
                    p2.vy += ny * BOUNCE_FORCE

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
        while room.id in self.rooms and len(room.players) > 0:
            if room.state == "waiting":
                if len(room.players) >= MIN_PLAYERS_TO_START:
                    room.state = "countdown"
                    room.countdown = COUNTDOWN_SECONDS
                else:
                    await asyncio.sleep(0.1)  # Wait for more players

            elif room.state == "countdown":
                await self.broadcast(room, {
                    "type": "countdown",
                    "countdown": room.countdown,
                })
                await asyncio.sleep(1)
                room.countdown -= 1

                if room.countdown <= 0:
                    room.state = "playing"
                    # Reset positions
                    for player in room.players.values():
                        x, y = self.spawn_position(room)
                        player.x = x
                        player.y = y
                        player.vx = 0
                        player.vy = 0
                        player.alive = True

            elif room.state == "playing":
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
                await asyncio.sleep(3)

                # Reset for new round
                room.state = "waiting"
                room.winner = None
                for player in room.players.values():
                    player.alive = True
                    x, y = self.spawn_position(room)
                    player.x = x
                    player.y = y
                    player.vx = 0
                    player.vy = 0

            else:
                await asyncio.sleep(0.1)


game_manager = GameManager()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    player: Optional[Player] = None
    room: Optional[Room] = None

    try:
        # Wait for join message
        data = await websocket.receive_text()
        message = json.loads(data)

        if message.get("type") != "join":
            await websocket.close()
            return

        name = message.get("name", "Player")[:15]

        # Find or create room
        room = game_manager.find_or_create_room()
        player = game_manager.add_player(room, name, websocket)

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
        if room.state == "waiting" and len(room.players) == 1:
            asyncio.create_task(game_manager.run_game_loop(room))

        # Handle messages
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "input":
                dx = float(message.get("dx", 0))
                dy = float(message.get("dy", 0))
                game_manager.apply_input(player.id, dx, dy)

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
