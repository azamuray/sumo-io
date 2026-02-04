.PHONY: up down logs restart clean build dev

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

restart: down up

clean:
	docker compose down -v --remove-orphans

build:
	docker compose build

# Local development without Docker
dev-backend:
	cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

dev-frontend:
	cd frontend && python -m http.server 8080
