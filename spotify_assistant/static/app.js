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

// Telas que não são playlists: a chave vira o # da URL.
const VIEWS = {
  sensacoes: "Sensações",
  descobrir: "Descobrir",
};
const HUNT_KINDS = { sensacoes: ["sense"], descobrir: ["roulette", "rabbit"] };
const ROOM_LIGHT = "#EEE7D7";
const compactNumber = new Intl.NumberFormat("pt-BR", { notation: "compact" });

const state = {
  overview: null,
  view: "playlist",
  initialKey: decodeURIComponent(location.hash.slice(1)) || memory.get("selected"),
  selected: null,
  detail: null,
  sensations: null,
  hunt: null,
  huntTimer: 0,
  huntSignature: "",
  lastHunt: null,
  seed: "",
  kept: new Set(),
  openDetails: new Set(),
  landed: new Set(),
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
  if (state.view === "playlist" && current()) renderSleeve();
}

/** Abre uma playlist pelo nome ou uma das telas de VIEWS pela chave. */
function go(key) {
  return key in VIEWS ? openView(key) : select(key);
}

function shelfKeys() {
  return [...state.overview.playlists.map((playlist) => playlist.name), ...Object.keys(VIEWS)];
}

async function select(name) {
  const playlists = state.overview.playlists;
  state.view = "playlist";
  state.selected = playlists.some((playlist) => playlist.name === name) ? name : playlists[0].name;
  memory.set("selected", state.selected);
  history.replaceState(null, "", `#${encodeURIComponent(state.selected)}`);
  state.detail = null;
  state.addingOpen = false;
  $("#hunt").hidden = true;
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
  if (state.view !== "playlist" || state.selected !== name) return;
  state.detail = detail;
  renderSleeve();
  renderTracks();
}

function renderShelf() {
  const onPlaylist = state.view === "playlist";
  // Ponto na cor da playlist; vira equalizador quando ela está tocando.
  const item = ({ key, label, color, uri, current, explore, number }) => h("button", {
    class: explore ? "nav-item is-explore" : "nav-item",
    type: "button",
    style: color ? `--spine: ${color}` : null,
    "aria-current": current ? "page" : null,
    "data-uri": uri,
    title: `${label} (tecla ${number})`,
    onclick: () => go(key),
  },
    h("span", { class: "nav-mark", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
    h("span", null, label));
  const playlists = state.overview.playlists.map((playlist, index) => item({
    key: playlist.name,
    label: playlist.name,
    color: colorOf(playlist),
    uri: playlist.uri,
    current: onPlaylist && playlist.name === state.selected,
    number: index + 1,
  }));
  const explore = Object.entries(VIEWS).map(([key, label], index) => item({
    key,
    label,
    explore: true,
    current: state.view === key,
    number: playlists.length + index + 1,
  }));
  const group = (label, items) => h("div", { class: "nav-group", role: "group", "aria-label": label },
    h("span", { class: "nav-label", "aria-hidden": "true" }, label),
    items);
  $("#shelf").replaceChildren(group("Playlists", playlists), group("Explorar", explore));
  markPlaying();
}

function setMood(color) {
  document.documentElement.style.setProperty("--mood", color);
}

function renderSleeve() {
  const playlist = current();
  if (!playlist) return;
  $("#sleeve").className = "sleeve";
  setMood(colorOf(playlist));
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

// ---------- Sensações e Descobrir

async function openView(key) {
  state.view = key;
  state.addingOpen = false;
  memory.set("selected", key);
  history.replaceState(null, "", `#${key}`);
  document.title = `Sala de escuta: ${VIEWS[key]}`;
  $("#adder").hidden = true;
  $("#stage").scrollTo({ top: 0 });
  renderShelf();
  if (key === "sensacoes" && !state.sensations) {
    try {
      state.sensations = await api("/api/sensations");
    } catch (error) {
      toast(error.message, true);
      return;
    }
  }
  if (state.view !== key) return;
  state.huntSignature = "";
  renderIntro();
  renderHunt();
}

/** A busca em andamento, se ela pertence à tela aberta. */
function huntHere() {
  const hunt = state.hunt;
  return hunt && (HUNT_KINDS[state.view] || []).includes(hunt.kind) ? hunt : null;
}

function renderIntro() {
  const sleeve = $("#sleeve");
  sleeve.className = "sleeve is-plain";
  setMood(huntHere()?.color || ROOM_LIGHT);
  sleeve.replaceChildren(...(state.view === "sensacoes" ? senseIntro() : discoverIntro()));
}

function senseIntro() {
  const { sensations, tempo_ready: ready } = state.sensations;
  const active = huntHere();
  const feeling = h("input", {
    class: "feeling-input",
    id: "feeling-input",
    type: "text",
    maxlength: "60",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "ódio, saudade, euforia…",
    disabled: !ready,
  });
  if (active?.kind === "sense" && !sensations.some((s) => s.name === active.label)) feeling.value = active.label;
  const submit = (event) => {
    event.preventDefault();
    const text = feeling.value.trim();
    if (text) startHunt({ kind: "sense", text });
  };
  // Tela larga: à esquerda o título e o campo livre; à direita os momentos prontos.
  const main = h("div", { class: "sense-main" },
    h("div", { class: "sleeve-text" },
      h("h1", { class: "title" }, "Sensações"),
      h("p", { class: "description" },
        "Escreva o que está sentindo ou escolha um momento. A sala acha músicas para isso, ouve a prévia "
        + "de cada uma e fica só com as que têm o ritmo certo."),
      !ready && h("p", { class: "meta is-warning" },
        "Para medir o BPM, instale o decodificador com pip install miniaudio e reabra o painel.")),
    h("form", { class: "feeling", onsubmit: submit },
      h("label", { class: "feeling-label", for: "feeling-input" }, "O que você está sentindo?"),
      h("div", { class: "feeling-row" },
        feeling,
        h("button", { class: "play-button", type: "submit", disabled: !ready }, "Montar")),
      h("p", { class: "feeling-hint" }, "Vale qualquer coisa: uma palavra, uma frase, um momento do dia.")));
  const moods = h("div", { class: "sense-moods" },
    h("p", { class: "moods-label" }, "Ou escolha um momento"),
    h("ul", { class: "moods" }, sensations.map((sensation) => h("li", null,
      h("button", {
        class: "mood",
        type: "button",
        style: `--tone: ${sensation.color}`,
        "aria-pressed": String(active?.label === sensation.name),
        disabled: !ready,
        onclick: () => startHunt({ kind: "sense", name: sensation.name }),
      },
        h("span", { class: "mood-name" }, sensation.name),
        h("span", { class: "mood-bpm" }, `${sensation.bpm[0]}–${sensation.bpm[1]} BPM`),
        h("span", { class: "mood-text" }, sensation.description))))));
  return [h("div", { class: "sense-layout" }, main, moods)];
}

function discoverIntro() {
  const seed = h("input", {
    class: "adder-input",
    id: "seed-input",
    type: "search",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "Vazio: sorteia um artista das suas playlists",
  });
  seed.value = state.seed;
  seed.addEventListener("input", () => { state.seed = seed.value; });
  seed.addEventListener("keydown", (event) => {
    if (event.key === "Enter") startHunt({ kind: "rabbit", seed: seed.value });
  });
  return [
    h("div", { class: "sleeve-text" },
      h("h1", { class: "title" }, "Descobrir"),
      h("p", { class: "description" }, "Duas formas de chegar em músicas que você nunca ouviu.")),
    h("div", { class: "paths" },
      h("section", { class: "path path-roulette", style: "--tone: #F2C14E" },
        h("h2", { class: "path-name" }, "Roleta"),
        h("p", { class: "path-text" },
          "Sorteia álbuns pouco ouvidos de qualquer ano e faixas de gêneros do mundo todo, do zamrock ao enka."),
        h("button", { class: "play-button", type: "button", onclick: () => startHunt({ kind: "roulette" }) },
          "Girar a roleta"),
        wheel()),
      h("section", { class: "path", style: "--tone: #9DB4E6" },
        h("h2", { class: "path-name" }, "Toca do coelho"),
        h("p", { class: "path-text" },
          "Parte de um artista e pula de relacionado em relacionado, sempre para os menos conhecidos."),
        h("label", { class: "adder-label", for: "seed-input" }, "Artista de partida"),
        seed,
        h("button", { class: "play-button", type: "button", onclick: () => startHunt({ kind: "rabbit", seed: seed.value }) },
          "Entrar na toca"))),
  ];
}

// ---------- Roda da roleta
// Começa vazia; cada música sorteada pinta uma fatia com o gênero ou o ano que saiu.

const WHEEL_SLICES = 12;
const WHEEL_COLORS = ["#5CC8C0", "#D4A84B", "#E3909E", "#E6D5AA", "#9DB4E6", "#F06A4F"];
const WHEEL_LABEL_MAX = 10;
const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  return el;
}

function wheel() {
  const size = 100;
  const radius = 48;
  const center = size / 2;
  const slice = 360 / WHEEL_SLICES;
  const root = svg("svg", { class: "wheel", id: "wheel", viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true" });
  for (let index = 0; index < WHEEL_SLICES; index++) {
    const start = (index * slice - 90) * (Math.PI / 180);
    const end = ((index + 1) * slice - 90) * (Math.PI / 180);
    const path = `M${center},${center} L${center + radius * Math.cos(start)},${center + radius * Math.sin(start)} `
      + `A${radius},${radius} 0 0 1 ${center + radius * Math.cos(end)},${center + radius * Math.sin(end)} Z`;
    root.append(svg("path", { class: "wheel-slice", d: path }));
    root.append(svg("text", {
      class: "wheel-label",
      x: center + 15,
      y: center,
      "dominant-baseline": "middle",
      transform: `rotate(${index * slice + slice / 2 - 90} ${center} ${center})`,
    }));
  }
  return h("div", { class: "wheel-wrap" },
    h("span", { class: "wheel-pointer", "aria-hidden": "true" }),
    root,
    h("span", { class: "wheel-hub", id: "wheel-hub", "aria-hidden": "true" }));
}

function shorten(text) {
  return text.length > WHEEL_LABEL_MAX ? `${text.slice(0, WHEEL_LABEL_MAX - 1)}…` : text;
}

function currentAngle(el) {
  const matrix = getComputedStyle(el).transform;
  if (!matrix || matrix === "none") return 0;
  const [a, b] = matrix.slice(7, -1).split(",").map(Number);
  return (Math.atan2(b, a) * 180) / Math.PI;
}

/** Pinta as fatias já sorteadas, gira enquanto sorteia e desacelera até parar no fim. */
function updateWheel(hunt) {
  const el = $("#wheel");
  if (!el) return;
  const roulette = hunt?.kind === "roulette" ? hunt : null;
  const finds = roulette ? roulette.finds : [];
  const slices = el.querySelectorAll(".wheel-slice");
  const labels = el.querySelectorAll(".wheel-label");
  slices.forEach((slice, index) => {
    const find = finds[index];
    slice.classList.toggle("is-filled", Boolean(find));
    slice.style.fill = find ? WHEEL_COLORS[index % WHEEL_COLORS.length] : "";
    labels[index].textContent = find ? shorten(find.tag || "") : "";
  });
  const hub = $("#wheel-hub");
  if (hub) hub.textContent = roulette ? `${finds.length}/${roulette.total || WHEEL_SLICES}` : "";

  const spinning = roulette?.status === "running";
  if (spinning && !el.classList.contains("is-spinning")) {
    el.style.transition = "none";
    el.style.transform = "";
    el.classList.add("is-spinning");
  } else if (!spinning && el.classList.contains("is-spinning")) {
    const angle = currentAngle(el);
    el.classList.remove("is-spinning");
    el.style.transition = "none";
    el.style.transform = `rotate(${angle}deg)`;
    el.getBoundingClientRect(); // aplica o ângulo atual antes de animar a parada
    el.style.transition = "transform 2.2s cubic-bezier(.12, .8, .2, 1)";
    el.style.transform = `rotate(${angle + 540 + Math.random() * 360}deg)`;
  }
}

async function startHunt(body) {
  if (!body) return;
  state.lastHunt = body;
  try {
    state.hunt = await api("/api/hunts", body);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.huntSignature = "";
  renderIntro();
  renderHunt();
  $("#hunt").scrollIntoView({ behavior: "smooth", block: "start" });
  pollHunt();
}

async function pollHunt() {
  clearTimeout(state.huntTimer);
  let hunt;
  try {
    hunt = await api("/api/hunts/current");
  } catch (error) {
    toast(error.message, true);
    return;
  }
  if (!hunt) return;
  const finished = state.hunt?.status === "running" && hunt.status !== "running";
  state.hunt = hunt;
  if (huntHere()) renderHunt();
  if (hunt.status === "running") {
    state.huntTimer = setTimeout(pollHunt, 800);
  } else if (finished && hunt.status === "error") {
    toast(hunt.message, true);
  }
}

function renderHunt() {
  const panel = $("#hunt");
  const list = $("#tracks");
  const hunt = huntHere();
  updateWheel(hunt);
  if (!hunt) {
    panel.hidden = true;
    list.replaceChildren();
    return;
  }
  const signature = JSON.stringify([
    hunt.status, hunt.progress, hunt.finds.length, hunt.message, state.kept.size, state.openDetails.size,
  ]);
  if (!panel.hidden && signature === state.huntSignature) return;
  state.huntSignature = signature;
  if (hunt.color) setMood(hunt.color);

  const running = hunt.status === "running";
  const uris = hunt.finds.map((find) => find.uri);
  const again = { sense: "Gerar de novo", roulette: "Girar de novo", rabbit: "Descer de novo" }[hunt.kind];
  const percent = hunt.total ? Math.max(4, Math.round((hunt.progress / hunt.total) * 100)) : 4;
  panel.hidden = false;
  const header = [
    h("h2", { class: "hunt-title" }, hunt.label),
    h("p", { class: "meta" }, hunt.message),
    running && h("div", { class: "progress", "aria-hidden": "true" }, h("i", { style: `width: ${percent}%` })),
    h("div", { class: "actions" },
      h("button", { class: "play-button", type: "button", disabled: !uris.length, onclick: () => playFinds(hunt.finds) },
        playIcon(), "Tocar tudo"),
      hunt.kind === "sense"
        ? h("button", { class: "ghost-button", type: "button", disabled: running || !uris.length, onclick: saveHunt },
          "Salvar como playlist")
        : h("button", {
          class: "ghost-button",
          type: "button",
          disabled: !uris.length || uris.every((uri) => state.kept.has(uri)),
          onclick: (event) => keep(uris, event.currentTarget),
        }, "Guardar todas"),
      h("button", { class: "text-button", type: "button", onclick: () => startHunt(state.lastHunt || { kind: hunt.kind }) },
        again),
    ),
  ];
  panel.replaceChildren(...header.filter(Boolean));

  // Só as músicas que acabaram de chegar ganham a animação de "cair" na lista.
  const fresh = (find) => {
    const isNew = !state.landed.has(find.uri);
    state.landed.add(find.uri);
    return isNew && hunt.kind === "roulette";
  };
  if (hunt.kind === "rabbit") {
    list.replaceChildren(...hunt.chains.flatMap((chain) => [
      chainRow(chain),
      ...chain.finds.map((find, index) => findRow(find, hunt.finds, index, fresh(find))),
    ]));
  } else {
    list.replaceChildren(...hunt.finds.map((find, index) => findRow(find, hunt.finds, index, fresh(find))));
  }
  markPlaying();
}

function findDetails(find) {
  if (!find.bpm) return find.reason;
  const energy = Math.round((find.energy || 0) * 100);
  return `BPM medido na prévia: ${find.bpm}. Energia: ${energy} de 100.`;
}

function findRow(find, finds, index, isNew) {
  const kept = state.kept.has(find.uri);
  const details = findDetails(find);
  const open = state.openDetails.has(find.uri);
  const classes = ["track", "find", open && "is-open", isNew && "is-new"].filter(Boolean).join(" ");
  return h("li", { class: classes, "data-uri": find.uri },
    h("button", { class: "track-button", type: "button", title: `Tocar ${find.title}`, onclick: () => playFinds(finds, find.uri) },
      h("span", { class: "track-index" }, String(index + 1)),
      find.image ? h("img", { class: "track-art", src: find.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
      h("span", { class: "track-text" },
        h("span", { class: "track-title" }, find.title),
        h("span", { class: "track-sub" }, find.subtitle),
        details && h("span", { class: "find-details" }, details)),
      find.bpm ? h("span", { class: "bpm" }, h("b", null, String(find.bpm)), " BPM") : h("span"),
      h("span", { class: "track-time" }, clock(find.duration_ms)),
    ),
    details ? h("button", {
      class: "info-button",
      type: "button",
      "aria-expanded": String(open),
      "aria-label": `Detalhes de ${find.title}`,
      title: "Por que essa música?",
      onclick: () => toggleDetails(find.uri),
    }, infoIcon()) : h("span"),
    h("button", {
      class: "keep-button",
      type: "button",
      disabled: kept,
      title: "Guardar na playlist Achados da Sala",
      "aria-label": `Guardar ${find.title} nos Achados da Sala`,
      onclick: (event) => keep([find.uri], event.currentTarget),
    }, kept ? "Guardada" : "Guardar"),
  );
}

function toggleDetails(uri) {
  if (state.openDetails.has(uri)) state.openDetails.delete(uri);
  else state.openDetails.add(uri);
  renderHunt();
}

function infoIcon() {
  const icon = svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  icon.append(svg("circle", { cx: 12, cy: 12, r: 9 }), svg("path", { d: "M12 11v5M12 7.5v.5" }));
  return icon;
}

function fans(count) {
  if (count == null) return "poucos fãs";
  return `${compactNumber.format(count)} ${count === 1 ? "fã" : "fãs"}`;
}

function chainRow(chain) {
  const last = chain.path[chain.path.length - 1];
  return h("li", { class: "chain" },
    h("ol", { class: "chain-path", "aria-label": "Caminho entre artistas" },
      chain.path.map((artist) => h("li", null, artist.name))),
    h("p", { class: "meta", title: "Fãs no catálogo que a sala consulta para achar artistas pouco conhecidos." },
      `${last.name}: ${fans(last.fans)}.`));
}

async function keep(uris, button) {
  button.disabled = true;
  try {
    const { message } = await api("/api/finds/keep", { uris });
    uris.forEach((uri) => state.kept.add(uri));
    toast(message);
    renderHunt();
  } catch (error) {
    button.disabled = false;
    toast(error.message, true);
  }
}

async function saveHunt(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const { message } = await api("/api/hunts/save", {});
    toast(message);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
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
  for (const item of document.querySelectorAll(".nav-item")) {
    const active = Boolean(item.dataset.uri) && item.dataset.uri === player.context_uri;
    item.classList.toggle("is-playing", active && Boolean(player.is_playing));
    item.classList.toggle("is-paused", active && !player.is_playing);
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

/** Toca uma lista solta de faixas (resultado de sensação/descoberta), sem criar playlist. */
function playFinds(finds, offsetUri) {
  return command({ action: "play", uris: finds.map((find) => find.uri), offset_uri: offsetUri });
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
    } else if (/^[1-9]$/.test(event.key) && state.overview) {
      const key = shelfKeys()[Number(event.key) - 1];
      if (key) go(key);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshPlayer();
  });

  // Favoritos e o botão voltar mudam só o #; replaceState em select() não dispara este evento.
  window.addEventListener("hashchange", () => {
    const key = decodeURIComponent(location.hash.slice(1));
    const showing = state.view === "playlist" ? state.selected : state.view;
    if (state.overview && key && key !== showing) go(key);
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
  // pollHunt retoma uma busca que estava rodando quando a página foi recarregada.
  await Promise.all([go(state.initialKey), refreshPlayer(), pollHunt()]);
  setInterval(() => { if (!document.hidden) refreshPlayer(); }, 3000);
  setInterval(tick, 500);
}

init();
