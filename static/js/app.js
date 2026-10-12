const app = document.querySelector("#app");
const letters = ["B", "O", "M", "B"];
const colors = ["#1f6feb", "#13c9d7", "#f04487", "#0ca678", "#7c3aed", "#ffbc42"];

const gameCards = {
  bomb_party: {
    title: "Bomb Party",
    tag: "Say something before it blows.",
    accent: "var(--pink)",
    description: "Fast word rounds with a hidden fuse.",
  },
  truth_or_dare: {
    title: "Truth or Dare",
    tag: "Tailored prompts, your intensity.",
    accent: "var(--teal)",
    description: "Scenario-based truths and dares.",
  },
};

const state = {
  socket: null,
  room: null,
  viewerId: localStorage.getItem("party_games_player_id") || "",
  nickname: localStorage.getItem("party_games_nickname") || "",
  roomCode: new URLSearchParams(location.search).get("room") || "",
  selectedGame: localStorage.getItem("party_games_selected_game") || "bomb_party",
  serverOffsetMs: 0,
  soundEnabled: localStorage.getItem("party_games_sound") !== "0",
  error: "",
};

let countdownTimer = null;
let lastFlashEventId = "";
let lastAudioEventId = "";
let lastTickSecond = null;
let audioContext = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function currentGame() {
  return gameCards[state.room?.game_type || state.selectedGame] || gameCards.bomb_party;
}

function isBombParty() {
  return (state.room?.game_type || state.selectedGame) === "bomb_party";
}

function isTruthOrDare() {
  return (state.room?.game_type || state.selectedGame) === "truth_or_dare";
}

function bombSvg(color = "var(--pink)") {
  return `
    <svg class="bomb-mark" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="30" cy="38" r="20" fill="${color}"></circle>
      <path d="M40 22 L49 11" stroke="var(--cyan)" stroke-width="5" stroke-linecap="round" fill="none"></path>
      <circle class="spark" cx="51" cy="9" r="6" fill="var(--cyan)"></circle>
    </svg>
  `;
}

function todSvg() {
  return `
    <svg class="bomb-mark" viewBox="0 0 64 64" aria-hidden="true">
      <rect x="7" y="10" width="34" height="28" rx="8" fill="var(--teal)"></rect>
      <rect x="23" y="27" width="34" height="28" rx="8" fill="#7c3aed"></rect>
      <text x="18" y="30" font-size="15" font-weight="900" fill="#fff" font-family="sans-serif">T</text>
      <text x="35" y="48" font-size="15" font-weight="900" fill="#fff" font-family="sans-serif">D</text>
    </svg>
  `;
}

function miniBombSvg(color) {
  return `
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="15" cy="20" r="10" fill="var(--navy)"></circle>
      <path d="M19 11 L25 5" stroke="${color}" stroke-width="3" stroke-linecap="round" fill="none"></path>
      <circle class="spark" cx="26" cy="4" r="3" fill="${color}"></circle>
    </svg>
  `;
}

function starSvg() {
  return `
    <svg class="winner-star" viewBox="0 0 64 64" aria-hidden="true">
      <polygon points="32,4 40,24 62,24 44,38 50,60 32,47 14,60 20,38 2,24 24,24" fill="var(--cyan)"></polygon>
    </svg>
  `;
}

function renderConfetti(count = 16) {
  return `
    <div class="confetti" aria-hidden="true">
      ${Array.from({ length: count }, (_, index) => {
        const left = Math.round(Math.random() * 100);
        const size = 6 + Math.round(Math.random() * 8);
        const duration = (2.4 + Math.random() * 2.2).toFixed(2);
        const delay = (Math.random() * 2.8).toFixed(2);
        const color = colors[index % colors.length];
        return `<span style="left:${left}%;width:${size}px;height:${size}px;background:${color};animation-duration:${duration}s;animation-delay:${delay}s"></span>`;
      }).join("")}
    </div>
  `;
}

function ensureAudio() {
  if (!state.soundEnabled || !isBombParty()) return null;
  if (!audioContext) {
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) return null;
    audioContext = new AudioCtor();
  }
  if (audioContext.state === "suspended") audioContext.resume();
  return audioContext;
}

function tone(frequency, duration, type = "sine", gain = 0.06, delay = 0) {
  const context = ensureAudio();
  if (!context) return;
  const start = context.currentTime + delay;
  const oscillator = context.createOscillator();
  const volume = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  volume.gain.setValueAtTime(0.0001, start);
  volume.gain.exponentialRampToValueAtTime(gain, start + 0.01);
  volume.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(volume);
  volume.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.02);
}

function playSound(kind) {
  if (!state.soundEnabled || !isBombParty()) return;
  if (kind === "tick") tone(880, 0.045, "square", 0.025);
  if (kind === "pass") {
    tone(560, 0.07, "triangle", 0.05);
    tone(820, 0.08, "triangle", 0.045, 0.06);
  }
  if (kind === "miss") {
    tone(150, 0.24, "sawtooth", 0.08);
    tone(70, 0.28, "square", 0.05, 0.08);
  }
  if (kind === "win") {
    tone(523, 0.12, "triangle", 0.05);
    tone(659, 0.12, "triangle", 0.05, 0.12);
    tone(784, 0.18, "triangle", 0.05, 0.24);
  }
  if (kind === "start") {
    tone(220, 0.1, "square", 0.04);
    tone(330, 0.12, "square", 0.04, 0.12);
  }
}

function eventId(event) {
  if (!event) return "";
  return `${event.kind || ""}:${event.player_id || ""}:${event.next_player_id || ""}:${event.winner_id || ""}:${event.letters || ""}:${event.prompt_type || ""}`;
}

function handleRoomEvent(room) {
  const id = eventId(room.last_event);
  if (!id || id === lastAudioEventId) return;
  lastAudioEventId = id;
  if (room.game_type !== "bomb_party") return;
  if (room.last_event.kind === "started") playSound("start");
  if (room.last_event.kind === "passed") playSound("pass");
  if (room.last_event.kind === "missed") playSound("miss");
  if (room.last_event.kind === "gameover") playSound("win");
}

function getViewer() {
  return state.room?.players.find((player) => player.id === state.viewerId) || null;
}

function getCurrentPlayer() {
  return state.room?.players.find((player) => player.id === state.room.current_player_id) || null;
}

function getWinner() {
  return state.room?.players.find((player) => player.id === state.room.winner_id) || null;
}

function currentClientTimeMs() {
  return Date.now() + state.serverOffsetMs;
}

function remainingMs() {
  if (!state.room?.deadline_timestamp_ms) return 0;
  return Math.max(0, state.room.deadline_timestamp_ms - currentClientTimeMs());
}

function fuseFraction() {
  if (!state.room?.fuse_duration_ms) return 1;
  return Math.max(0, Math.min(1, remainingMs() / state.room.fuse_duration_ms));
}

function fuseColor() {
  const fraction = fuseFraction();
  if (fraction > 0.5) return "var(--blue)";
  if (fraction > 0.22) return "var(--yellow)";
  return "var(--red)";
}

function roomLink() {
  return `${location.origin}/?room=${state.room.code}`;
}

function renderLetterBoxes(player) {
  const count = player?.letters?.length || 0;
  return `
    <div class="letter-row">
      ${letters.map((letter, index) => (
        `<div class="letter-box ${index < count ? "filled" : ""}">${letter}</div>`
      )).join("")}
    </div>
  `;
}

function playerColor(index) {
  return colors[index % colors.length];
}

function renderPlayersGrid(players) {
  return `
    <div class="player-grid">
      ${players.map((player, index) => `
        <div class="avatar-cell">
          <div class="avatar ${player.connected ? "" : "disconnected"}" style="background:${playerColor(index)}">
            ${escapeHtml(player.initials)}
          </div>
          <div class="avatar-name">${escapeHtml(player.nickname)}</div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderSoundButton(extraClass = "") {
  if (!isBombParty()) return "";
  return `
    <button class="sound-toggle ${extraClass}" id="sound-toggle" type="button" aria-pressed="${state.soundEnabled}">
      ${state.soundEnabled ? "Sound on" : "Sound off"}
    </button>
  `;
}

function wireSoundButton() {
  const button = document.querySelector("#sound-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    state.soundEnabled = !state.soundEnabled;
    localStorage.setItem("party_games_sound", state.soundEnabled ? "1" : "0");
    if (state.soundEnabled) playSound("pass");
    render();
  });
}

function renderGameHub() {
  app.innerHTML = `
    <section class="view view-dark game-hub">
      ${renderConfetti(12)}
      <div class="brand">
        <div class="eyebrow" style="color:var(--cyan)">Party Games</div>
        <h1>Pick a game</h1>
        <p class="subtitle">Same room, same phones.</p>
      </div>
      <div class="game-card-list">
        ${Object.entries(gameCards).map(([gameType, game]) => `
          <button class="game-card" type="button" data-game="${gameType}">
            <span class="game-icon">${gameType === "bomb_party" ? bombSvg("var(--pink)") : todSvg()}</span>
            <span>
              <strong>${game.title}</strong>
              <small>${game.description}</small>
            </span>
            <b>&gt;</b>
          </button>
        `).join("")}
      </div>
    </section>
  `;

  document.querySelectorAll("[data-game]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedGame = button.dataset.game;
      localStorage.setItem("party_games_selected_game", state.selectedGame);
      renderJoin();
    });
  });
}

function renderLobbyAdminControls(viewer) {
  if (!viewer?.is_host) {
    return `
      <div class="admin-panel">
        <div class="settings-title">
          <span>Lobby</span>
          <span>${state.room.locked ? "Locked" : "Open"}</span>
        </div>
        <div class="settings-summary">
          ${state.room.locked ? "The host has closed new joins." : "The host can still add players."}
        </div>
      </div>
    `;
  }

  return `
    <div class="admin-panel">
      <div class="settings-title">
        <span>Lobby admin</span>
        <span>${state.room.locked ? "Locked" : "Open"}</span>
      </div>
      <div class="admin-actions">
        <button class="mini-btn ${state.room.locked ? "mini-btn-warn" : ""}" type="button" data-action="set_room_locked" data-locked="${!state.room.locked}">
          ${state.room.locked ? "Unlock room" : "Lock room"}
        </button>
        <button class="mini-btn" type="button" data-action="shuffle_players">Shuffle order</button>
      </div>
      <div class="admin-list">
        ${state.room.players.map((player, index) => renderAdminPlayerRow(player, index)).join("")}
      </div>
    </div>
  `;
}

function renderAdminPlayerRow(player, index) {
  return `
    <div class="admin-player">
      <div class="admin-player-main">
        <div class="avatar small-avatar ${player.connected ? "" : "disconnected"}" style="background:${playerColor(index)}">
          ${escapeHtml(player.initials)}
        </div>
        <div class="admin-player-name">
          <strong>${escapeHtml(player.nickname)}</strong>
          <span>${player.is_host ? "Host" : player.connected ? "Connected" : "Disconnected"}</span>
        </div>
      </div>
      <div class="admin-controls">
        <button class="icon-btn" title="Move up" data-action="move_player" data-target="${player.id}" data-direction="up" ${index === 0 ? "disabled" : ""}>^</button>
        <button class="icon-btn" title="Move down" data-action="move_player" data-target="${player.id}" data-direction="down" ${index === state.room.players.length - 1 ? "disabled" : ""}>v</button>
        <button class="mini-btn" type="button" data-action="rename_player" data-target="${player.id}" data-name="${escapeHtml(player.nickname)}">Rename</button>
        ${player.is_host ? "" : `<button class="mini-btn" type="button" data-action="transfer_host" data-target="${player.id}">Host</button>`}
        ${player.is_host ? "" : `<button class="mini-btn mini-btn-danger" type="button" data-action="remove_player" data-target="${player.id}">Remove</button>`}
      </div>
    </div>
  `;
}

function renderJoin() {
  const game = currentGame();
  app.innerHTML = `
    <section class="view view-dark">
      ${renderConfetti(14)}
      ${renderSoundButton("sound-toggle-dark")}
      ${state.roomCode ? "" : `<button class="back-link" id="back-to-games" type="button">&lt; Games</button>`}
      <div class="brand">
        ${state.selectedGame === "truth_or_dare" ? todSvg() : bombSvg()}
        <div class="eyebrow" style="color:var(--cyan)">${escapeHtml(game.title)}</div>
        <h1>${escapeHtml(game.title)}</h1>
        <p class="subtitle">${escapeHtml(game.tag)}</p>
      </div>
      <form id="join-form" class="form-stack">
        <label class="field">
          <span>Your name</span>
          <input id="nickname" name="nickname" maxlength="24" placeholder="Nickname" value="${escapeHtml(state.nickname)}" autocomplete="nickname" required>
        </label>
        <label class="field">
          <span>Room code</span>
          <input id="room-code" name="roomCode" maxlength="6" placeholder="Leave blank to create" value="${escapeHtml(state.roomCode)}" autocomplete="off">
        </label>
        <div class="action-row">
          <button class="btn btn-secondary" type="button" id="create-room">Create room</button>
          <button class="btn btn-primary" type="submit">Join room</button>
        </div>
        <div class="message">${escapeHtml(state.error)}</div>
      </form>
    </section>
  `;

  wireSoundButton();
  const backButton = document.querySelector("#back-to-games");
  if (backButton) backButton.addEventListener("click", renderGameHub);
  document.querySelector("#join-form").addEventListener("submit", (event) => {
    event.preventDefault();
    ensureAudio();
    const form = new FormData(event.currentTarget);
    connectToRoom(form.get("roomCode"), form.get("nickname"));
  });
  document.querySelector("#create-room").addEventListener("click", () => {
    ensureAudio();
    createRoom();
  });
}

function renderBombLobbySettings(viewer) {
  const settings = state.room.settings;
  if (!viewer?.is_host) {
    const customCount = settings.custom_categories.length;
    return `
      <div class="settings-panel">
        <div class="settings-title">
          <span>Bomb controls</span>
          <span>${settings.fuse_min_seconds}-${settings.fuse_max_seconds}s</span>
        </div>
        <div class="settings-summary">
          ${customCount ? `${customCount} custom categories added` : "Default categories only"}
        </div>
      </div>
    `;
  }

  return `
    <form id="settings-form" class="settings-panel">
      <div class="settings-title">
        <span>Bomb controls</span>
        <span>${settings.custom_categories.length} custom</span>
      </div>
      <div class="settings-grid">
        <label class="field compact-field">
          <span>Min fuse</span>
          <input name="fuseMin" type="number" min="5" max="90" value="${settings.fuse_min_seconds}" required>
        </label>
        <label class="field compact-field">
          <span>Max fuse</span>
          <input name="fuseMax" type="number" min="5" max="90" value="${settings.fuse_max_seconds}" required>
        </label>
      </div>
      <label class="field compact-field">
        <span>Custom categories</span>
        <textarea name="customCategories" rows="4" placeholder="One category per line">${escapeHtml(settings.custom_categories.join("\n"))}</textarea>
      </label>
      <button class="btn btn-muted" type="submit">Save controls</button>
    </form>
  `;
}

function renderTodLobbySettings(viewer) {
  const tod = state.room.truth_or_dare;
  if (!viewer?.is_host) {
    return `
      <div class="settings-panel tod-panel">
        <div class="settings-title">
          <span>Truth or Dare</span>
          <span>${escapeHtml(tod.intensity)} / ${escapeHtml(tod.mode)}</span>
        </div>
        <div class="settings-summary">${escapeHtml(tod.scenario || "Waiting for the host to set the scene.")}</div>
      </div>
    `;
  }

  return `
    <form id="tod-settings-form" class="settings-panel tod-panel">
      <div class="settings-title">
        <span>Set the scene</span>
        <span>No audio</span>
      </div>
      <label class="field compact-field">
        <span>Group scenario</span>
        <textarea name="scenario" rows="4" maxlength="180" placeholder="College reunion, couples game night, coworkers celebrating a launch...">${escapeHtml(tod.scenario)}</textarea>
      </label>
      <div>
        <div class="eyebrow">Intensity</div>
        <div class="segmented" data-group="intensity">
          ${["mild", "medium", "wild"].map((item) => `
            <button type="button" class="${tod.intensity === item ? "active" : ""}" data-value="${item}">${item}</button>
          `).join("")}
        </div>
      </div>
      <div>
        <div class="eyebrow">Mode</div>
        <div class="segmented stacked" data-group="mode">
          ${[
            ["mixed", "Truth or Dare"],
            ["truth", "Truth only"],
            ["dare", "Dare only"],
          ].map(([value, label]) => `
            <button type="button" class="${tod.mode === value ? "active" : ""}" data-value="${value}">${label}</button>
          `).join("")}
        </div>
      </div>
      <input type="hidden" name="intensity" value="${escapeHtml(tod.intensity)}">
      <input type="hidden" name="mode" value="${escapeHtml(tod.mode)}">
      <div class="action-row">
        <button class="btn btn-muted" type="submit">Save setup</button>
        <button class="btn btn-secondary" id="start-tod" type="button" ${state.room.players.length >= 2 ? "" : "disabled"}>Start</button>
      </div>
    </form>
  `;
}

function renderGameSwitcher(viewer) {
  if (!viewer?.is_host || state.room.phase !== "lobby") return "";
  return `
    <div class="game-switcher">
      ${Object.entries(gameCards).map(([gameType, game]) => `
        <button type="button" class="${state.room.game_type === gameType ? "active" : ""}" data-action="set_game_type" data-game-type="${gameType}">
          ${game.title}
        </button>
      `).join("")}
    </div>
  `;
}

function renderLobby() {
  const viewer = getViewer();
  const game = currentGame();
  const link = roomLink();
  const qrSrc = `/api/qr?data=${encodeURIComponent(link)}`;
  app.innerHTML = `
    <section class="view">
      <div class="room-header">
        <div>
          <div class="eyebrow">${escapeHtml(game.title)}</div>
          <div class="room-code">${escapeHtml(state.room.code)}</div>
        </div>
        ${renderSoundButton()}
      </div>
      ${renderGameSwitcher(viewer)}
      ${renderPlayersGrid(state.room.players)}
      <div class="qr-panel">
        <img class="qr-image" src="${qrSrc}" alt="QR code for joining room ${escapeHtml(state.room.code)}">
        <button class="copy-link" id="copy-link" type="button">${escapeHtml(link)}</button>
      </div>
      ${renderLobbyAdminControls(viewer)}
      ${isTruthOrDare() ? renderTodLobbySettings(viewer) : renderBombLobbySettings(viewer)}
      <div class="lobby-card">
        <strong>${viewer?.is_host ? "Ready when you are." : "Waiting for the host."}</strong>
        <div>${viewer?.is_host ? "Start once everyone has joined." : "Keep this screen open."}</div>
      </div>
      ${isBombParty() ? `
        <button class="btn btn-secondary" id="start-game" ${viewer?.is_host && state.room.players.length >= 2 ? "" : "disabled"}>Light the fuse</button>
      ` : ""}
      <div class="screen-error">${escapeHtml(state.error)}</div>
    </section>
  `;

  wireSoundButton();
  wireLobbyAdminControls();
  wireGameSwitcher();
  wireCopyLink(link);
  wireBombSettings();
  wireTodSettings();
}

function wireCopyLink(link) {
  document.querySelector("#copy-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(link);
      state.error = "Link copied.";
    } catch {
      state.error = "Copy failed. Long-press the link instead.";
    }
    render();
  });
}

function wireGameSwitcher() {
  document.querySelectorAll("[data-action='set_game_type']").forEach((button) => {
    button.addEventListener("click", () => sendAction("set_game_type", { game_type: button.dataset.gameType }));
  });
}

function wireBombSettings() {
  const settingsForm = document.querySelector("#settings-form");
  if (settingsForm) {
    settingsForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      sendAction("update_settings", {
        settings: {
          fuse_min_seconds: Number(form.get("fuseMin")),
          fuse_max_seconds: Number(form.get("fuseMax")),
          custom_categories: parseCategories(form.get("customCategories")),
        },
      });
    });
  }

  const startButton = document.querySelector("#start-game");
  if (startButton) {
    startButton.addEventListener("click", () => {
      ensureAudio();
      sendAction("start_game");
    });
  }
}

function wireTodSettings() {
  const form = document.querySelector("#tod-settings-form");
  if (!form) return;

  form.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.closest(".segmented").dataset.group;
      form.elements[group].value = button.dataset.value;
      form.querySelectorAll(`[data-group='${group}'] button`).forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
    });
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendTodSetup(false);
  });

  document.querySelector("#start-tod").addEventListener("click", () => sendTodSetup(true));
}

function sendTodSetup(shouldStart) {
  const form = document.querySelector("#tod-settings-form");
  const data = new FormData(form);
  sendAction("configure_truth_or_dare", {
    settings: {
      scenario: data.get("scenario"),
      intensity: data.get("intensity"),
      mode: data.get("mode"),
    },
  });
  if (shouldStart) sendAction("start_truth_or_dare");
}

function wireLobbyAdminControls() {
  document.querySelectorAll("[data-action]").forEach((button) => {
    if (button.dataset.action === "set_game_type") return;
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      const target = button.dataset.target;
      if (action === "set_room_locked") {
        sendAction("set_room_locked", { locked: button.dataset.locked === "true" });
      }
      if (action === "shuffle_players") {
        sendAction("shuffle_players");
      }
      if (action === "move_player") {
        sendAction("move_player", { target_player_id: target, direction: button.dataset.direction });
      }
      if (action === "rename_player") {
        const currentName = button.dataset.name || "";
        const nickname = window.prompt("Rename player", currentName);
        if (nickname !== null) sendAction("rename_player", { target_player_id: target, nickname });
      }
      if (action === "transfer_host") {
        sendAction("transfer_host", { target_player_id: target });
      }
      if (action === "remove_player") {
        sendAction("remove_player", { target_player_id: target });
      }
    });
  });
}

function parseCategories(value) {
  const seen = new Set();
  const categories = [];
  String(value || "").split(/\r?\n/).forEach((line) => {
    const clean = line.trim();
    const key = clean.toLowerCase();
    if (clean && !seen.has(key)) {
      categories.push(clean.slice(0, 50));
      seen.add(key);
    }
  });
  return categories.slice(0, 80);
}

function renderGame() {
  if (isTruthOrDare()) {
    renderTruthOrDareGame();
  } else {
    renderBombGame();
  }
}

function renderBombGame() {
  const viewer = getViewer();
  const current = getCurrentPlayer();
  const isYourTurn = viewer?.id === current?.id;
  const isEliminated = Boolean(viewer?.eliminated);
  const fraction = fuseFraction();
  const color = fuseColor();
  const seconds = Math.ceil(remainingMs() / 1000);
  const circumference = 389.6;
  const offset = circumference * (1 - fraction);
  const lastEvent = state.room.last_event || {};
  const id = eventId(lastEvent);
  const showMissFlash = lastEvent.kind === "missed" && id !== lastFlashEventId;

  if (showMissFlash) {
    window.setTimeout(() => {
      lastFlashEventId = id;
      render();
    }, 1050);
  }

  app.innerHTML = `
    <section class="view" style="--timer-color:${color}">
      <div class="room-header">
        <span class="pill">${isEliminated ? "Eliminated" : isYourTurn ? "Your turn" : `${escapeHtml(current?.nickname || "Someone")}'s turn`}</span>
        ${renderSoundButton()}
      </div>
      <div class="category-card">
        <div class="eyebrow">Category</div>
        <div class="category">${escapeHtml(state.room.current_category)}</div>
      </div>
      <div class="timer-wrap">
        <svg class="timer-ring" viewBox="0 0 150 150" aria-label="${seconds} seconds remaining">
          <circle cx="75" cy="75" r="62" fill="none" stroke="var(--line)" stroke-width="12"></circle>
          <circle cx="75" cy="75" r="62" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"></circle>
        </svg>
        <div class="timer-core">
          ${miniBombSvg(color)}
          <div class="seconds">${seconds}</div>
          <div class="eyebrow">seconds</div>
        </div>
      </div>
      ${
        isYourTurn && !isEliminated
          ? `<button class="btn btn-pass" id="pass-turn">PASS!</button>`
          : `<div class="status-text">${isEliminated ? "You are out. Watch the finish." : "Get your answer ready."}</div>`
      }
      <div class="letters">
        <div class="eyebrow">Your letters</div>
        ${renderLetterBoxes(viewer)}
      </div>
      ${showMissFlash ? renderMissFlash(lastEvent) : ""}
      <div class="screen-error">${escapeHtml(state.error)}</div>
    </section>
  `;

  wireSoundButton();
  const passButton = document.querySelector("#pass-turn");
  if (passButton) {
    passButton.addEventListener("click", () => {
      ensureAudio();
      sendAction("pass_turn");
    });
  }
}

function renderTruthOrDareGame() {
  const viewer = getViewer();
  const current = getCurrentPlayer();
  const tod = state.room.truth_or_dare;
  const isYourTurn = viewer?.id === current?.id;
  const typeLabel = tod.current_prompt_type === "dare" ? "Dare" : "Truth";
  const accent = tod.current_prompt_type === "dare" ? "#7c3aed" : "var(--teal)";

  app.innerHTML = `
    <section class="view tod-game">
      <div class="room-header">
        <span class="pill">${isYourTurn ? "Your turn" : `${escapeHtml(current?.nickname || "Someone")}'s turn`}</span>
        ${getViewer()?.is_host ? `<button class="mini-btn" id="end-tod" type="button">End</button>` : ""}
      </div>
      <div class="tod-meta">${escapeHtml(tod.intensity)} intensity - ${escapeHtml(tod.scenario || "No scenario set")}</div>
      ${
        tod.waiting_for_choice
          ? renderTodChoice(isYourTurn, current)
          : renderTodPrompt(tod, isYourTurn, typeLabel, accent)
      }
      <div class="screen-error">${escapeHtml(state.error)}</div>
    </section>
  `;

  const endButton = document.querySelector("#end-tod");
  if (endButton) endButton.addEventListener("click", () => sendAction("end_truth_or_dare"));
  const truthButton = document.querySelector("#choose-truth");
  if (truthButton) truthButton.addEventListener("click", () => sendAction("choose_truth_or_dare", { prompt_type: "truth" }));
  const dareButton = document.querySelector("#choose-dare");
  if (dareButton) dareButton.addEventListener("click", () => sendAction("choose_truth_or_dare", { prompt_type: "dare" }));
  const skipButton = document.querySelector("#skip-tod");
  if (skipButton) skipButton.addEventListener("click", () => sendAction("skip_truth_or_dare_prompt"));
  const nextButton = document.querySelector("#next-tod");
  if (nextButton) nextButton.addEventListener("click", () => sendAction("next_truth_or_dare_turn"));
}

function renderTodChoice(isYourTurn, current) {
  return `
    <div class="tod-choice">
      ${todSvg()}
      <h2>Truth or Dare?</h2>
      ${
        isYourTurn
          ? `<div class="action-row"><button class="btn btn-teal" id="choose-truth">Truth</button><button class="btn btn-purple" id="choose-dare">Dare</button></div>`
          : `<div class="status-text">Waiting for ${escapeHtml(current?.nickname || "the player")} to choose.</div>`
      }
    </div>
  `;
}

function renderTodPrompt(tod, isYourTurn, typeLabel, accent) {
  return `
    <div class="tod-prompt-wrap">
      <div class="tod-prompt-card" style="border-top-color:${accent}">
        <span style="background:${accent}">${typeLabel}</span>
        <p>${escapeHtml(tod.current_prompt_text)}</p>
      </div>
      ${
        isYourTurn
          ? `<div class="action-row"><button class="btn btn-muted" id="skip-tod">Skip</button><button class="btn btn-secondary" id="next-tod">Done, next</button></div>`
          : `<div class="status-text">Watching ${escapeHtml(getCurrentPlayer()?.nickname || "the player")}'s turn.</div>`
      }
    </div>
  `;
}

function renderMissFlash(event) {
  const player = state.room.players.find((item) => item.id === event.player_id);
  const name = player?.nickname || "Player";
  return `
    <div class="flash">
      <div>
        <div class="flash-title">MISS!</div>
        <div>${escapeHtml(name)} takes a letter.</div>
      </div>
    </div>
  `;
}

function renderGameOver() {
  if (isTruthOrDare()) {
    const viewer = getViewer();
    app.innerHTML = `
      <section class="view view-dark">
        ${renderConfetti(24)}
        <div class="brand">
          ${todSvg()}
          <div class="eyebrow" style="color:var(--teal)">Session complete</div>
          <h1>Nicely played.</h1>
          <p class="subtitle">Same room, another round when ready.</p>
        </div>
        <button class="btn btn-secondary" id="play-again" ${viewer?.is_host ? "" : "disabled"}>Back to lobby</button>
        <div class="message">${viewer?.is_host ? "" : "Waiting for the host."}</div>
      </section>
    `;
  } else {
    const winner = getWinner();
    const viewer = getViewer();
    app.innerHTML = `
      <section class="view view-dark">
        ${renderConfetti(40)}
        ${renderSoundButton("sound-toggle-dark")}
        <div class="brand">
          ${starSvg()}
          <div class="eyebrow" style="color:var(--pink)">Winner</div>
          <div class="winner-name">${escapeHtml(winner?.nickname || "Winner")}</div>
          <p class="subtitle">Outlasted the room.</p>
        </div>
        <button class="btn btn-secondary" id="play-again" ${viewer?.is_host ? "" : "disabled"}>Run it back</button>
        <div class="message">${viewer?.is_host ? "" : "Waiting for the host to reset."}</div>
      </section>
    `;
    wireSoundButton();
  }

  document.querySelector("#play-again").addEventListener("click", () => sendAction("play_again"));
}

function renderRemoved() {
  app.innerHTML = `
    <section class="view view-dark">
      ${bombSvg()}
      <div class="brand">
        <h1>Removed</h1>
        <p class="subtitle">The host removed this player from the lobby.</p>
      </div>
      <button class="btn btn-secondary" id="return-join">Back to join</button>
    </section>
  `;
  document.querySelector("#return-join").addEventListener("click", () => {
    if (state.socket) state.socket.close();
    state.room = null;
    state.viewerId = "";
    localStorage.removeItem("party_games_player_id");
    render();
  });
}

function render() {
  if (!state.room) {
    if (state.roomCode) renderJoin();
    else renderGameHub();
    return;
  }
  if (!getViewer()) {
    renderRemoved();
    return;
  }
  if (state.room.phase === "lobby") {
    renderLobby();
  } else if (state.room.phase === "game") {
    renderGame();
  } else {
    renderGameOver();
  }
}

async function createRoom() {
  const nickname = document.querySelector("#nickname").value.trim();
  if (!nickname) {
    state.error = "Enter a name first.";
    renderJoin();
    return;
  }

  try {
    const response = await fetch(`/api/rooms?game_type=${encodeURIComponent(state.selectedGame)}`, { method: "POST" });
    const data = await response.json();
    connectToRoom(data.room_code, nickname);
  } catch {
    state.error = "Could not create a room.";
    renderJoin();
  }
}

function connectToRoom(roomCode, nickname) {
  const cleanCode = String(roomCode || "").trim().toUpperCase();
  const cleanName = String(nickname || "").trim();
  if (!cleanCode) {
    state.error = "Enter a room code or create a room.";
    renderJoin();
    return;
  }
  if (!cleanName) {
    state.error = "Enter a name first.";
    renderJoin();
    return;
  }

  state.error = "";
  state.nickname = cleanName;
  state.roomCode = cleanCode;
  localStorage.setItem("party_games_nickname", cleanName);

  if (state.socket) state.socket.close();

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ nickname: cleanName });
  if (state.viewerId) params.set("player_id", state.viewerId);
  state.socket = new WebSocket(`${protocol}://${location.host}/ws/${cleanCode}?${params}`);

  state.socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "error") {
      state.error = payload.message;
      render();
      return;
    }
    if (payload.type === "room_state") {
      state.serverOffsetMs = payload.server_time_ms - Date.now();
      state.viewerId = payload.viewer_id;
      localStorage.setItem("party_games_player_id", state.viewerId);
      state.room = payload.room;
      state.selectedGame = state.room.game_type;
      localStorage.setItem("party_games_selected_game", state.selectedGame);
      handleRoomEvent(state.room);
      history.replaceState(null, "", `/?room=${state.room.code}`);
      render();
    }
  });

  state.socket.addEventListener("close", () => {
    if (state.room?.phase !== "gameover") {
      state.error = "Disconnected. Reload to rejoin.";
      render();
    }
  });
}

function sendAction(action, extra = {}) {
  state.error = "";
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    state.error = "Connection is not open.";
    render();
    return;
  }
  state.socket.send(JSON.stringify({ action, ...extra }));
}

function startCountdown() {
  if (countdownTimer) window.clearInterval(countdownTimer);
  countdownTimer = window.setInterval(() => {
    if (state.room?.phase !== "game" || state.room.game_type !== "bomb_party") return;
    const seconds = Math.ceil(remainingMs() / 1000);
    if (seconds <= 5 && seconds > 0 && seconds !== lastTickSecond) {
      lastTickSecond = seconds;
      playSound("tick");
    }
    render();
  }, 200);
}

render();
startCountdown();
