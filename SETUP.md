# Local dev setup

## Prerequisites (one-time)

- Docker Desktop installed and running (`docker ps` should print an empty table, not an error).
- Python 3.11+ venv at repo root: `python3 -m venv .venv`
- `backend/.env` (gitignored, not committed) with at least:
  ```
  POSTGRES_USER=postgres
  POSTGRES_PASSWORD=postgres
  POSTGRES_DB=pathfinder
  POSTGRES_PORT=5433
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/pathfinder?ssl=disable
  GEMINI_API_KEY=<your key>
  ```
  `POSTGRES_PORT`/the `5433` in `DATABASE_URL` only matter if something else on the machine
  already holds 5432 (that was the case here — a native Postgres was already listening on it).
  If 5432 is free on your machine, both can just be `5432`.
- Install backend dependencies into the venv (see `pyproject.toml`'s `dependencies` list):
  ```
  source .venv/bin/activate
  pip install -e .  # or: pip install <each dependency in pyproject.toml>
  ```

## Restart commands (every new session)

1. Start Postgres:
   ```
   cd /Users/shinaanafi/pathfinder
   docker compose --env-file backend/.env up -d
   ```
2. Start the backend:
   ```
   cd /Users/shinaanafi/pathfinder/backend
   source ../.venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8003
   ```
   Add `--reload` while actively editing backend code.
3. Confirm it's up:
   ```
   curl http://localhost:8003/health
   ```
   Should return `{"status":"ok","version":"0.1.0"}`. The extension's side panel "Backend" card
   should show green/Connected once this responds — its default backend URL is
   `http://localhost:8003`, set in `extension/src/background/api.js`.

## Stopping

- Backend: `Ctrl+C` the uvicorn process (or `pkill -f "uvicorn app.main:app"` if it's backgrounded).
- Postgres: `docker compose down` (add `-v` to also wipe the database volume).

## Notes

- `docker-compose.yml` only runs Postgres — there's no Dockerfile for the FastAPI app itself; it
  runs directly via `uvicorn` against the containerized database.
- Redis is declared in `core/config.py` but not actually used anywhere in the codebase yet — no
  Redis container needed.
- The AI provider is Google Gemini (`google-genai`), not Anthropic/OpenAI, despite those key
  fields existing in `Settings` — they're unused placeholders.
