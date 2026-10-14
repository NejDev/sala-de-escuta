"use strict";

const FALLBACK_COLORS = ["#5CC8C0", "#D4A84B", "#E3909E", "#E6D5AA", "#9DB4E6"];
const PLAY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="solid" d="M8 5v14l11-7z"/></svg>';
const listFormat = new Intl.ListFormat("pt-BR", { type: "conjunction" });

const $ = (selector) => document.querySelector(selector);

// localStorage lança exceção quando o navegador bloqueia armazenamento; lembrar a playlist é só conveniência.
const memory = {
  get(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* sem armazenamento: segue sem lembrar */ }
  },
};

const state = {
  overview: null,
  selected: decodeURIComponent(location.hash.slice(1)) || memory.get("selected"),
  detail: null,
  addingOpen: false,
  player: null,
  playerSyncedAt: 0,
  seeking: false,
  refreshTimer: 0,
  searchTimer: 0,
  searchSeq: 0,
};

// ---------- Utilidades

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style") el.style.cssText = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false && child !== "") el.append(child);
  }
  return el;
}

function playIcon() {
  const template = document.createElement("template");
  template.innerHTML = PLAY_ICON;
  return template.content.firstChild;
}

async function api(path, body) {
  const init = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("O painel parou de responder. A janela do servidor ainda está aberta?");
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && data.login) showGate(data.error);
  if (!response.ok) throw new Error(data.error || `Erro ${response.status}`);
  return data;
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

function clock(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function longDuration(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return rest ? `${Math.floor(minutes / 60)} h ${rest} min` : `${minutes / 60} h`;
}

function relativeDay(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day || 1);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((today - date) / 86400000);
  if (days <= 0) return "hoje";
  if (days === 1) return "ontem";
  if (days < 7) return `há ${days} dias`;
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function scheduleLine(schedule) {
  if (!schedule) return null;
  if (!schedule.scheduled) {
    return { text: "Sem atualização automática. Rode scripts\\agendar-semanal.ps1 para agendar.", warning: true };
  }
  if (!schedule.ok) {
    return { text: "A última atualização automática falhou. Detalhes em data/assistant.log.", warning: true };
  }
  if (!schedule.next) return { text: "Atualização automática agendada." };
  const next = new Date(schedule.next).toLocaleString("pt-BR", {
    weekday: "long", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
  return { text: `Atualiza sozinha toda semana. Próxima vez: ${next}.` };
}

function toast(message, isError = false) {
  const el = h("div", { class: isError ? "toast is-error" : "toast" }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), isError ? 6500 : 4000);
}

function showGate(message) {
  document.body.classList.add("is-gated");
  $("#gate").hidden = false;
  if (message && message.includes("expirou")) {
    $("#gate-text").textContent = "Sua sessão do Spotify expirou. Conecte de novo para continuar.";
  }
}

// ---------- Playlists

function current() {
  return state.overview?.playlists.find((playlist) => playlist.name === state.selected);
}

function colorOf(playlist) {
  const index = state.overview.playlists.indexOf(playlist);
  return playlist.color || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

async function loadOverview() {
  state.overview = await api("/api/overview");
  renderShelf();
  if (current()) renderSleeve();
}

async function select(name) {
  const playlists = state.overview.playlists;
  state.selected = playlists.some((playlist) => playlist.name === name) ? name : playlists[0].name;
  memory.set("selected", state.selected);
  history.replaceState(null, "", `#${encodeURIComponent(state.selected)}`);
  state.detail = null;
  state.addingOpen = false;
  renderShelf();
  renderSleeve();
  renderAdder();
  renderTracks();
  $("#stage").scrollTo({ top: 0 });
  await loadDetail();
}

async function loadDetail() {
  const name = state.selected;
  let detail;
  try {
    detail = await api(`/api/playlists/${encodeURIComponent(name)}`);
  } catch (error) {
    detail = { items: [] };
    toast(error.message, true);
  }
  if (state.selected !== name) return;
  state.detail = detail;
  renderSleeve();
  renderTracks();
}

function renderShelf() {
  const spines = state.overview.playlists.map((playlist, index) => h("button", {
    class: "spine",
    type: "button",
    style: `--spine: ${colorOf(playlist)}`,
    "aria-current": playlist.name === state.selected ? "true" : null,
    "data-uri": playlist.uri,
    title: `${playlist.name} (tecla ${index + 1})`,
    onclick: () => select(playlist.name),
  },
    h("span", { class: "spine-eq", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
    h("span", { class: "spine-name" }, playlist.name),
    h("span", { class: "spine-count", "aria-label": `${playlist.total} itens` }, String(playlist.total)),
  ));
  $("#shelf").replaceChildren(...spines);
  markPlaying();
}

function renderSleeve() {
  const playlist = current();
  if (!playlist) return;
  document.documentElement.style.setProperty("--mood", colorOf(playlist));
  document.title = `Sala de escuta: ${playlist.name}`;

  const items = state.detail?.items;
  const unit = playlist.kind === "podcasts" ? ["episódio", "episódios"] : ["faixa", "faixas"];
  const meta = [plural(items ? items.length : playlist.total, ...unit)];
  if (items?.length) meta.push(longDuration(items.reduce((sum, item) => sum + item.duration_ms, 0)));
  const lines = [h("p", { class: "meta" }, meta.join(", "))];
  if (playlist.kind === "podcasts") {
    const line = scheduleLine(state.overview.schedule);
    if (line) lines.push(h("p", { class: line.warning ? "meta is-warning" : "meta" }, line.text));
  }
  if (playlist.kind === "mix") {
    lines.push(h("p", { class: "meta" }, `Montada com faixas de ${listFormat.format(playlist.sources)}.`));
  }

  const cover = playlist.image
    ? h("img", { class: "cover", src: playlist.image, alt: `Capa de ${playlist.name}` })
    : h("div", { class: "cover cover-empty", "aria-hidden": "true" }, playlist.name.charAt(0));

  const actions = h("div", { class: "actions" },
    h("button", { class: "play-button", type: "button", disabled: !playlist.uri, onclick: () => play(playlist.uri) },
      playIcon(), "Tocar"),
    playlist.uri && h("a", { class: "ghost-button", href: playlist.uri }, "Abrir no app"),
    h("button", { class: "ghost-button", type: "button", onclick: () => startJob(false) },
      playlist.kind === "podcasts" ? "Atualizar agora" : "Refazer seleção"),
    h("button", { class: "text-button", type: "button", onclick: () => startJob(true) }, "Ver prévia"),
    playlist.kind !== "mix" && h("button", {
      class: "text-button",
      type: "button",
      "aria-expanded": String(state.addingOpen),
      "aria-controls": "adder",
      onclick: toggleAdder,
    }, playlist.kind === "podcasts" ? "Acompanhar outro programa" : "Adicionar faixa"),
  );

  $("#sleeve").replaceChildren(cover, h("div", { class: "sleeve-text" },
    h("h1", { class: "title" }, playlist.name),
    playlist.description && h("p", { class: "description" }, playlist.description),
    lines,
    actions,
  ));
}

function renderTracks() {
  const list = $("#tracks");
  const playlist = current();
  if (!state.detail) {
    list.replaceChildren(h("li", { class: "tracks-empty" }, "Carregando…"));
    return;
  }
  const items = state.detail.items;
  if (!items.length) {
    list.replaceChildren(h("li", { class: "tracks-empty" }, playlist.kind === "podcasts"
      ? "Nenhum episódio novo nos últimos dias. Use “Atualizar agora” para procurar de novo."
      : "Esta playlist está vazia. Use “Refazer seleção” para montá-la."));
    return;
  }
  list.replaceChildren(...items.map((item, index) => {
    const subtitle = item.type === "episode"
      ? [item.subtitle, relativeDay(item.release_date)].filter(Boolean).join(", ")
      : item.subtitle;
    return h("li", { class: "track", "data-uri": item.uri },
      h("button", { class: "track-button", type: "button", title: `Tocar ${item.title}`, onclick: () => play(playlist.uri, item.uri) },
        h("span", { class: "track-index" }, String(index + 1)),
        item.image ? h("img", { class: "track-art", src: item.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
        h("span", { class: "track-text" },
          h("span", { class: "track-title" }, item.title),
          h("span", { class: "track-sub" }, subtitle)),
        h("span", { class: "track-time" }, clock(item.duration_ms)),
      ));
  }));
  markPlaying();
}

// ---------- Adicionar faixas e programas

function toggleAdder() {
  state.addingOpen = !state.addingOpen;
  renderSleeve();
  renderAdder();
  if (state.addingOpen) $("#adder-input").focus();
}

function renderAdder() {
  const playlist = current();
  const adder = $("#adder");
  adder.hidden = !state.addingOpen || !playlist || playlist.kind === "mix";
  if (adder.hidden) return;
  const podcasts = playlist.kind === "podcasts";
  $("#adder-label").textContent = podcasts ? `Buscar programa para ${playlist.name}` : `Buscar faixa para ${playlist.name}`;
  const input = $("#adder-input");
  input.value = "";
  input.placeholder = podcasts ? "Ex.: Lambda3, Os Agilistas" : "Ex.: Bill Evans Autumn Leaves";
  $("#results").replaceChildren();
}

async function search(query) {
  const playlist = current();
  const seq = ++state.searchSeq;
  if (!query.trim()) {
    $("#results").replaceChildren();
    return;
  }
  const kind = playlist.kind === "podcasts" ? "show" : "track";
  try {
    const { results } = await api(`/api/search?kind=${kind}&q=${encodeURIComponent(query)}`);
    if (seq !== state.searchSeq) return;
    $("#results").replaceChildren(...(results.length
      ? results.map((result) => resultRow(result, playlist))
      : [h("li", { class: "results-empty" }, "Nada encontrado. Tente outro nome.")]));
  } catch (error) {
    toast(error.message, true);
  }
}

function resultRow(result, playlist) {
  const verb = playlist.kind === "podcasts" ? "Acompanhar" : "Adicionar";
  return h("li", { class: "result" },
    result.image ? h("img", { class: "track-art", src: result.image, alt: "" }) : h("span", { class: "track-art" }),
    h("span", { class: "track-text" },
      h("span", { class: "track-title" }, result.title),
      h("span", { class: "track-sub" }, result.subtitle)),
    h("button", {
      class: "ghost-button is-small",
      type: "button",
      "aria-label": `${verb} ${result.title}`,
      onclick: (event) => addItem(playlist, result, event.currentTarget),
    }, verb),
  );
}

async function addItem(playlist, result, button) {
  button.disabled = true;
  try {
    const { message } = await api(`/api/playlists/${encodeURIComponent(playlist.name)}/items`, {
      uri: result.uri,
      entry: result.entry,
    });
    button.textContent = playlist.kind === "podcasts" ? "Acompanhando" : "Adicionada";
    toast(message);
    await Promise.all([loadOverview(), loadDetail()]);
  } catch (error) {
    button.disabled = false;
    toast(error.message, true);
  }
}

// ---------- Atualizações (setup / prévia)

async function startJob(dryRun) {
  try {
    renderConsole(await api("/api/jobs", { playlist: current().name, dry_run: dryRun }));
    pollJob();
  } catch (error) {
    toast(error.message, true);
  }
}

async function pollJob() {
  let job;
  try {
    job = await api("/api/jobs/current");
  } catch (error) {
    toast(error.message, true);
    return;
  }
  renderConsole(job);
  if (job.status === "running") {
    setTimeout(pollJob, 600);
    return;
  }
  if (job.status === "error") {
    toast("A atualização falhou. Veja o motivo no painel.", true);
    return;
  }
  if (job.dry_run) {
    toast("Prévia pronta. Nada foi alterado no Spotify.");
    return;
  }
  const outcome = job.lines.filter((line) => line.includes("gravada no Spotify") || line.includes("ficou vazia")).pop();
  toast(outcome ? outcome.replace("gravada no Spotify", "atualizada") : "Pronto.");
  await Promise.all([loadOverview(), loadDetail()]);
}

function renderConsole(job) {
  const panel = $("#console");
  panel.hidden = false;
  panel.dataset.status = job.status;
  const name = job.label.replace(/^(Prévia de|Atualizando) /, "");
  $("#console-title").textContent = {
    running: `${job.label}…`,
    done: job.dry_run ? `Prévia de ${name} pronta` : `${name} atualizada`,
    error: `Não foi possível atualizar ${name}`,
  }[job.status];
  const box = $("#console-lines");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...job.lines.map((line) => h("p", { class: lineClass(line) }, line.trim())));
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function lineClass(line) {
  if (line.includes("não encontrado")) return "line is-warning";
  if (line.startsWith("   ")) return "line is-item";
  if (/: \d+ itens$/.test(line)) return "line is-heading";
  return "line";
}

// ---------- Player

async function refreshPlayer() {
  try {
    state.player = await api("/api/player");
  } catch (error) {
    state.player = { item: null, error: error.message };
  }
  state.playerSyncedAt = performance.now();
  renderPlayer();
}

function refreshPlayerSoon(delay = 400) {
  clearTimeout(state.refreshTimer);
  state.refreshTimer = setTimeout(refreshPlayer, delay);
}

function position() {
  const player = state.player;
  if (!player?.item) return 0;
  const elapsed = player.is_playing ? performance.now() - state.playerSyncedAt : 0;
  return Math.min(player.progress_ms + elapsed, player.item.duration_ms);
}

function syncProgress(progressMs = position()) {
  state.player.progress_ms = progressMs;
  state.playerSyncedAt = performance.now();
}

function renderPlayer() {
  const bar = $("#player");
  const player = state.player || {};
  if (player.needs_scope) {
    bar.dataset.state = "auth";
    return;
  }
  const item = player.item;
  bar.dataset.state = item ? (player.is_playing ? "playing" : "paused") : "idle";
  $("#btn-play").setAttribute("aria-label", player.is_playing ? "Pausar" : "Tocar");
  $("#now-title").textContent = item ? item.title : "Nada tocando";
  $("#now-sub").textContent = item ? item.subtitle : (player.error || "Toque uma playlist daqui ou abra o Spotify.");
  const art = $("#now-art");
  if (item?.image) {
    if (art.getAttribute("src") !== item.image) art.src = item.image;
    art.hidden = false;
  } else {
    art.hidden = true;
  }
  $("#btn-shuffle").setAttribute("aria-pressed", String(Boolean(player.shuffle)));
  const volume = $("#volume");
  volume.disabled = player.device?.volume == null;
  if (!volume.disabled && document.activeElement !== volume) {
    volume.value = player.device.volume;
    paintRange(volume);
  }
  $("#device").textContent = player.device?.name ? `Tocando em ${player.device.name}` : "";
  tick();
  markPlaying();
}

function tick() {
  if (state.seeking) return;
  const duration = state.player?.item?.duration_ms || 0;
  const now = position();
  const seek = $("#seek");
  seek.max = String(Math.max(duration, 1));
  seek.value = String(now);
  paintRange(seek);
  $("#time-pos").textContent = clock(now);
  $("#time-dur").textContent = clock(duration);
  // Faixa acabou: busca a próxima sem esperar o ciclo normal.
  if (state.player?.is_playing && duration && now >= duration) refreshPlayerSoon(800);
}

function paintRange(input) {
  const min = Number(input.min);
  const span = (Number(input.max) - min) || 1;
  input.style.setProperty("--fill", `${((Number(input.value) - min) / span) * 100}%`);
}

function markPlaying() {
  const player = state.player || {};
  for (const spine of document.querySelectorAll(".spine")) {
    const active = Boolean(spine.dataset.uri) && spine.dataset.uri === player.context_uri;
    spine.classList.toggle("is-playing", active && Boolean(player.is_playing));
    spine.classList.toggle("is-paused", active && !player.is_playing);
  }
  for (const row of document.querySelectorAll(".track")) {
    row.classList.toggle("is-current", Boolean(player.item) && row.dataset.uri === player.item.uri);
  }
}

async function command(body, optimistic) {
  if (state.player?.needs_scope) {
    toast("Autorize o controle do player na barra de baixo.", true);
    return;
  }
  if (optimistic && state.player?.item) {
    optimistic(state.player);
    renderPlayer();
  }
  try {
    await api("/api/player", body);
  } catch (error) {
    toast(error.message, true);
  }
  refreshPlayerSoon(350);
}

function play(contextUri, offsetUri) {
  return command({ action: "play", context_uri: contextUri, offset_uri: offsetUri });
}

function togglePlay() {
  const player = state.player;
  if (player?.is_playing) {
    return command({ action: "pause" }, (p) => { syncProgress(); p.is_playing = false; });
  }
  if (player?.item) {
    return command({ action: "play" }, (p) => { syncProgress(); p.is_playing = true; });
  }
  const playlist = current();
  if (playlist?.uri) return play(playlist.uri);
}

function bindPlayer() {
  $("#btn-play").addEventListener("click", togglePlay);
  $("#btn-prev").addEventListener("click", () => command({ action: "previous" }));
  $("#btn-next").addEventListener("click", () => command({ action: "next" }));
  $("#btn-shuffle").addEventListener("click", () => {
    const enabled = !state.player?.shuffle;
    command({ action: "shuffle", value: enabled }, (p) => { p.shuffle = enabled; });
  });

  const seek = $("#seek");
  seek.addEventListener("input", () => {
    state.seeking = true;
    paintRange(seek);
    $("#time-pos").textContent = clock(Number(seek.value));
  });
  seek.addEventListener("change", () => {
    const value = Number(seek.value);
    state.seeking = false;
    command({ action: "seek", value }, () => syncProgress(value));
  });

  const volume = $("#volume");
  volume.addEventListener("input", () => paintRange(volume));
  volume.addEventListener("change", () => command({ action: "volume", value: Number(volume.value) }));
}

// ---------- Início

function bindGlobal() {
  $("#console-close").addEventListener("click", () => { $("#console").hidden = true; });
  $("#adder-input").addEventListener("input", (event) => {
    clearTimeout(state.searchTimer);
    const query = event.target.value;
    state.searchTimer = setTimeout(() => search(query), 300);
  });

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "Escape") {
      $("#console").hidden = true;
      return;
    }
    if (event.target.closest("input, textarea, select") || document.body.classList.contains("is-gated")) return;
    if (event.code === "Space") {
      event.preventDefault();
      togglePlay();
    } else if (event.key === "ArrowRight") {
      command({ action: "next" });
    } else if (event.key === "ArrowLeft") {
      command({ action: "previous" });
    } else if (/^[1-9]$/.test(event.key)) {
      const playlist = state.overview?.playlists[Number(event.key) - 1];
      if (playlist) select(playlist.name);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshPlayer();
  });

  // Favoritos e o botão voltar mudam só o #; replaceState em select() não dispara este evento.
  window.addEventListener("hashchange", () => {
    const name = decodeURIComponent(location.hash.slice(1));
    if (state.overview && name && name !== state.selected) select(name);
  });
}

async function init() {
  bindGlobal();
  bindPlayer();
  try {
    await loadOverview();
  } catch (error) {
    if (!document.body.classList.contains("is-gated")) {
      $("#sleeve").replaceChildren(h("p", { class: "tracks-empty" }, error.message));
    }
    return;
  }
  await Promise.all([select(state.selected), refreshPlayer()]);
  setInterval(() => { if (!document.hidden) refreshPlayer(); }, 3000);
  setInterval(tick, 500);
}

init();
