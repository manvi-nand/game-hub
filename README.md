# Party Games

A local-network phone party-game hub. One person runs the server on a laptop, everyone joins from a phone browser with a room code or share link, and all games reuse the same room, players, QR, reconnect, lobby admin, and WebSocket plumbing.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` on the host machine. Phones on the same Wi-Fi can join with:

```text
http://<laptop-local-ip>:8000
```

## Gemini Prompt Generation

Truth or Dare uses Gemini for batched prompt generation when `GEMINI_API_KEY` is set. At session start it fills server-side queues, then turns consume from those queues so players are not waiting on an LLM call. When a queue drops to 10 prompts, the backend refills it. Without a key, it falls back to bundled static prompts so the app still works locally.

Create a local `.env` file:

```env
GEMINI_API_KEY=your-api-key
GEMINI_MODEL=gemini-3.1-flash-lite
```

`.env` is ignored by git. Use `.env.example` as the template.

## Current Scope

- FastAPI backend with native WebSockets.
- In-memory rooms only; restarting the server clears games.
- Plain HTML/CSS/JS frontend with no build step.
- Game picker with Bomb Party and Truth or Dare.
- Shared room/player infrastructure across games.
- Bomb Party: server-owned turn order, fuse deadlines, letters, eliminations, categories, and game-over state.
- Truth or Dare: host scenario setup, intensity, mode, turn rotation, choose truth/dare, skip/reroll, and Gemini-generated text-only prompts.
- QR code join from the lobby.
- Bomb Party browser-generated ticking, pass, miss, start, and winner sounds with a per-device toggle.
- Host controls for fuse min/max and custom categories.
- Lobby-only admin controls: lock room, rename/remove players, shuffle or reorder players, and transfer host.
- Phone-first v1; the shared-screen mockup is kept as design reference only.

## Reference Files

- PRD: `docs/prd/bomb-party-prd.md.pdf`
- Truth or Dare PRD: `docs/prd/truth-or-dare-prd.md.pdf`
- Design export: `docs/design-reference/Bomb-Party.dc.html`
- Game hub design export: `docs/design-reference/game-hub/Bomb-Party.dc.html`

## Tests

```bash
pytest
```
