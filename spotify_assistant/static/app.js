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
  novidades: "Novidades",
};
const HUNT_KINDS = { sensacoes: ["sense"], descobrir: ["roulette", "rabbit"], novidades: ["news"] };

// Filtros de Descobrir e Novidades. O tamanho do artista é medido em fãs: nenhuma API gratuita
// diz quantas vezes uma música foi tocada.
const SIZE_MIN = [["", "Qualquer"], ["100", "100"], ["1000", "1 mil"], ["10000", "10 mil"], ["100000", "100 mil"], ["1000000", "1 milhão"]];
const SIZE_MAX = [["", "Sem teto"], ["1000", "1 mil"], ["10000", "10 mil"], ["100000", "100 mil"], ["1000000", "1 milhão"], ["10000000", "10 milhões"]];
const PERIODS = [["7", "Na última semana"], ["14", "Nas últimas 2 semanas"], ["30", "No último mês"], ["90", "Nos últimos 3 meses"]];
const GENRE_SUGGESTIONS = [
  "K-pop", "J-pop", "Funk", "Trap", "Rap", "Drill", "Phonk", "Sertanejo", "Pagode", "Samba", "MPB", "Forró",
  "Piseiro", "Rock", "Indie", "Pop", "Emo", "Metal", "Punk", "Eletrônica", "House", "Techno", "Lo-fi", "Jazz",
  "R&B", "Soul", "Reggaeton", "Afrobeats", "Amapiano", "City pop", "Shoegaze", "Hyperpop", "Bossa nova", "Clássica",
];
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
  filters: { rouletteGenre: "", newsGenre: "", min: "", max: "", days: "30", ...savedFilters() },
  kept: new Set(),
  openDetails: new Set(),
  landed: new Set(),
  blocked: [],
  showBlocked: false,
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
    $("#gate-text").textContent = "Sua sessão do Spotify expirou. Entre de novo para continuar.";
  }
}

// ---------- Playlists

function current() {
  return state.overview?.playlists.find((playlist) => playlist.key === state.selected);
}

function colorOf(playlist) {
  const index = state.overview.playlists.indexOf(playlist);
  return playlist.color || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

async function loadOverview() {
  state.overview = await api("/api/overview");
  renderShelf();
  renderAccount();
  if (state.view === "playlist" && current()) renderSleeve();
}

/** Quem está na sala agora, e o botão de sair (cada amigo entra com o próprio Spotify). */
function renderAccount() {
  const me = state.overview?.me;
  if (!me) return;
  $("#account").replaceChildren(
    h("span", { class: "account-name", title: me.is_owner ? "Dono da sala" : null }, me.name),
    h("button", { class: "text-button", type: "button", onclick: logout }, "Sair"),
  );
}

async function logout() {
  try {
    await api("/api/logout", {});
  } catch (error) {
    toast(error.message, true);
    return;
  }
  location.reload();
}

/** Abre uma playlist pelo nome ou uma das telas de VIEWS pela chave. */
function go(key) {
  return key in VIEWS ? openView(key) : select(key);
}

function shelfKeys() {
  return [...state.overview.playlists.map((playlist) => playlist.key), ...Object.keys(VIEWS)];
}

async function select(key) {
  const playlists = state.overview.playlists;
  if (!playlists.length) return openView("sensacoes");  // amigo sem playlists ainda: começa explorando
  state.view = "playlist";
  state.selected = playlists.some((playlist) => playlist.key === key) ? key : playlists[0].key;
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
    key: playlist.key,
    label: playlist.name,
    color: colorOf(playlist),
    uri: playlist.uri,
    current: onPlaylist && playlist.key === state.selected,
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
  const emptyShelf = !playlists.length && h("span", { class: "nav-empty" }, "Nenhuma ainda");
  $("#shelf").replaceChildren(group("Playlists", playlists.length ? playlists : [emptyShelf]), group("Explorar", explore));
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

  const isOwner = Boolean(state.overview.me?.is_owner);
  const refresh = !playlist.uri ? "Criar no meu Spotify"
    : playlist.kind === "podcasts" ? "Atualizar agora" : "Refazer seleção";
  // Os programas da Tech Radar são escolhidos pelo dono; amigos adicionam faixas só na própria cópia.
  const canAdd = playlist.uri && (["music", "library"].includes(playlist.kind) || (playlist.kind === "podcasts" && isOwner));
  // Estante curada do dono tem curadoria automática; playlists da própria conta, não.
  const curated = playlist.kind !== "library";
  const actions = h("div", { class: "actions" },
    h("button", { class: "play-button", type: "button", disabled: !playlist.uri, onclick: () => play(playlist.uri) },
      playIcon(), "Tocar"),
    playlist.uri && h("a", { class: "ghost-button", href: playlist.uri }, "Abrir no app"),
    curated && h("button", { class: "ghost-button", type: "button", onclick: () => startJob(false) }, refresh),
    curated && h("button", { class: "text-button", type: "button", onclick: () => startJob(true) }, "Ver prévia"),
    canAdd && h("button", {
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
    let message = playlist.kind === "library"
      ? "Esta playlist está vazia. Use “Adicionar faixa” para começar."
      : "Esta playlist está vazia. Use “Refazer seleção” para montá-la.";
    if (!playlist.uri) message = "Esta playlist ainda não existe no seu Spotify. Use “Criar no meu Spotify” para montar a sua.";
    else if (playlist.kind === "podcasts") message = "Nenhum episódio novo nos últimos dias. Use “Atualizar agora” para procurar de novo.";
    list.replaceChildren(h("li", { class: "tracks-empty" }, message));
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
    const { message } = await api(`/api/playlists/${encodeURIComponent(playlist.key)}/items`, {
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
  loadBlocked();
}

async function loadBlocked() {
  try {
    state.blocked = (await api("/api/blocked")).artists;
  } catch {
    return;  // a lista é só um extra; sem ela o resto funciona
  }
  state.huntSignature = "";
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
  const intro = { sensacoes: senseIntro, descobrir: discoverIntro, novidades: newsIntro }[state.view];
  sleeve.replaceChildren(...intro());
}

/** Aviso quando a Spotify pausou as buscas: Sensações e Descobrir dependem delas. */
function pauseNotice() {
  const seconds = state.overview?.search_paused_s;
  if (!seconds) return null;
  const back = new Date(Date.now() + seconds * 1000);
  const days = Math.round((new Date(back).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  const day = days === 0 ? "hoje" : days === 1 ? "amanhã" : `em ${back.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}`;
  const time = back.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return h("p", { class: "meta is-warning" },
    `A Spotify pausou as buscas deste app por excesso de pedidos. Sensações, Descobrir e Novidades voltam por volta de ${time} ${day}.`);
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
        "Para medir o BPM, instale o decodificador com pip install miniaudio e reabra o painel."),
      pauseNotice()),
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
      h("p", { class: "description" }, "Duas formas de chegar em músicas que você nunca ouviu."),
      pauseNotice()),
    h("div", { class: "filters" },
      genreField("roulette-genre", "rouletteGenre", "Gênero da roleta (opcional)", "Qualquer gênero"),
      ...sizeFilters(),
      h("p", { class: "filter-hint" }, "O tamanho do artista vale para a roleta e para a toca."),
      genreList()),
    h("div", { class: "paths" },
      h("section", { class: "path path-roulette", style: "--tone: #F2C14E" },
        h("h2", { class: "path-name" }, "Roleta"),
        h("p", { class: "path-text" },
          "Sorteia álbuns pouco ouvidos de qualquer ano e faixas de gêneros do mundo todo, do zamrock ao enka."),
        h("button", {
          class: "play-button",
          type: "button",
          onclick: () => startHunt({ kind: "roulette", genre: state.filters.rouletteGenre, ...sizeBody() }),
        }, "Girar a roleta"),
        digger()),
      h("section", { class: "path", style: "--tone: #9DB4E6" },
        h("h2", { class: "path-name" }, "Toca do coelho"),
        h("p", { class: "path-text" },
          "Parte de um artista e pula de relacionado em relacionado, sempre para os menos conhecidos."),
        h("label", { class: "adder-label", for: "seed-input" }, "Artista de partida"),
        seed,
        h("button", { class: "play-button", type: "button", onclick: () => startHunt({ kind: "rabbit", seed: seed.value, ...sizeBody() }) },
          "Entrar na toca"))),
  ];
}

function savedFilters() {
  try {
    return JSON.parse(memory.get("filtros") || "{}");
  } catch {
    return {};
  }
}

function saveFilters() {
  memory.set("filtros", JSON.stringify(state.filters));
}

function sizeBody() {
  return { min_fans: state.filters.min || null, max_fans: state.filters.max || null };
}

function choice(id, label, options, key) {
  const control = h("select", { class: "filter-control", id },
    options.map(([value, text]) => h("option", { value, selected: String(state.filters[key] ?? "") === value }, text)));
  control.addEventListener("change", () => { state.filters[key] = control.value; saveFilters(); });
  return h("label", { class: "filter", for: id }, h("span", { class: "filter-label" }, label), control);
}

function genreField(id, key, label, placeholder, required = false) {
  const input = h("input", {
    class: "filter-control filter-genre",
    id,
    type: "text",
    list: "genre-list",
    maxlength: "40",
    autocomplete: "off",
    spellcheck: "false",
    required,
    placeholder,
  });
  input.value = state.filters[key] || "";
  input.addEventListener("input", () => { state.filters[key] = input.value; saveFilters(); });
  return h("label", { class: "filter", for: id }, h("span", { class: "filter-label" }, label), input);
}

function sizeFilters() {
  return [
    choice("min-fans", "Fãs do artista: no mínimo", SIZE_MIN, "min"),
    choice("max-fans", "No máximo", SIZE_MAX, "max"),
  ];
}

function genreList() {
  return h("datalist", { id: "genre-list" }, GENRE_SUGGESTIONS.map((genre) => h("option", { value: genre })));
}

function newsIntro() {
  const submit = (event) => {
    event.preventDefault();
    startHunt({ kind: "news", genre: state.filters.newsGenre, days: state.filters.days, ...sizeBody() });
  };
  return [
    h("div", { class: "sleeve-text" },
      h("h1", { class: "title" }, "Novidades"),
      h("p", { class: "description" },
        "Os lançamentos mais recentes de um gênero, só de artistas do tamanho que você escolher."),
      pauseNotice()),
    h("form", { class: "filters", onsubmit: submit },
      genreField("news-genre", "newsGenre", "Gênero", "Ex.: K-pop, funk, indie", true),
      ...sizeFilters(),
      choice("news-days", "Lançadas", PERIODS, "days"),
      h("button", { class: "play-button", type: "submit" }, "Buscar novidades"),
      genreList()),
  ];
}

// ---------- Garimpeiro da roleta
// Bonequinho com lupa revirando um caixote de discos. Cada música achada vai para
// a pilha ao lado, que começa vazia e vai enchendo; no fim ele levanta um disco.

const PILE_SLOTS = 12;
const PILE_COLORS = ["#5CC8C0", "#D4A84B", "#E3909E", "#E6D5AA", "#9DB4E6", "#F06A4F"];
const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) el.setAttribute(key, String(value));
  el.append(...children);
  return el;
}

function digger() {
  const records = svg("g", { class: "crate-records" },
    ...Array.from({ length: 7 }, (_, i) => svg("rect", {
      class: "crate-record",
      x: 86 + i * 9.5, y: 66, width: 8, height: 36, rx: 1,
      fill: PILE_COLORS[(i + 2) % PILE_COLORS.length],
    })));
  const crate = svg("g", { class: "crate" },
    svg("rect", { x: 80, y: 94, width: 76, height: 42, rx: 3, fill: "#8C5E36" }),
    svg("rect", { x: 80, y: 94, width: 76, height: 5, rx: 2, fill: "#A87444" }),
    svg("line", { x1: 80, y1: 109, x2: 156, y2: 109, stroke: "#6E4627", "stroke-width": 2 }),
    svg("line", { x1: 80, y1: 123, x2: 156, y2: 123, stroke: "#6E4627", "stroke-width": 2 }),
    svg("rect", { x: 110, y: 101, width: 16, height: 5, rx: 2.5, fill: "#5B3A20" }));
  const person = svg("g", { class: "person" },
    // pernas e tênis
    svg("rect", { x: 41, y: 100, width: 9, height: 34, rx: 4, fill: "#2A3552" }),
    svg("rect", { x: 53, y: 100, width: 9, height: 34, rx: 4, fill: "#2A3552" }),
    svg("ellipse", { cx: 47, cy: 135, rx: 7, ry: 3.5, fill: "#EEE7D7" }),
    svg("ellipse", { cx: 59, cy: 135, rx: 7, ry: 3.5, fill: "#EEE7D7" }),
    // braço de trás, com a lupa varrendo os discos
    svg("g", { class: "arm-glass" },
      svg("line", { x1: 66, y1: 76, x2: 98, y2: 66, stroke: "#D9573F", "stroke-width": 7, "stroke-linecap": "round" }),
      svg("line", { x1: 98, y1: 66, x2: 104, y2: 62, stroke: "#EEE7D7", "stroke-width": 3, "stroke-linecap": "round" }),
      svg("circle", { cx: 110, cy: 57, r: 8, fill: "rgba(157,180,230,.25)", stroke: "#EEE7D7", "stroke-width": 2.5 })),
    // tronco inclinado para o caixote, com a cabeça de gorro
    svg("g", { class: "torso", transform: "rotate(22 50 102)" },
      svg("rect", { x: 37, y: 66, width: 27, height: 40, rx: 10, fill: "#F06A4F" }),
      svg("g", { class: "head" },
        svg("circle", { cx: 51, cy: 54, r: 11, fill: "#E8B98F" }),
        svg("path", { d: "M40 52 a11 11 0 0 1 22 0 z", fill: "#5CC8C0" }),
        svg("rect", { x: 39, y: 49, width: 24, height: 4, rx: 2, fill: "#4AA9A2" }),
        svg("circle", { cx: 57.5, cy: 56, r: 1.5, fill: "#0E1525" }))),
    // braço da frente revirando os discos
    svg("g", { class: "arm-dig" },
      svg("line", { x1: 70, y1: 78, x2: 95, y2: 90, stroke: "#F06A4F", "stroke-width": 7, "stroke-linecap": "round" }),
      svg("circle", { cx: 96, cy: 91, r: 4, fill: "#E8B98F" })),
    // comemoração: braço para cima com o disco achado
    svg("g", { class: "arm-cheer" },
      svg("line", { x1: 70, y1: 78, x2: 93, y2: 45, stroke: "#F06A4F", "stroke-width": 7, "stroke-linecap": "round" }),
      svg("rect", { x: 83, y: 20, width: 22, height: 22, rx: 2, fill: "#F2C14E" }),
      svg("circle", { cx: 94, cy: 31, r: 6, fill: "#0E1525" }),
      svg("circle", { cx: 93, cy: 45, r: 4, fill: "#E8B98F" }),
      svg("path", { d: "M111 20 l6 -4 M113 31 l7 0 M78 16 l-6 -4", stroke: "#F2C14E", "stroke-width": 2, "stroke-linecap": "round" })));
  const pile = svg("g", { class: "pile" },
    ...Array.from({ length: PILE_SLOTS }, (_, i) => svg("rect", {
      class: "pile-slot",
      x: 170, y: 131 - i * 6, width: 40, height: 4.5, rx: 1,
    }, svg("title", {}))));
  const root = svg("svg", { class: "digger", id: "digger", viewBox: "0 0 220 145", "aria-hidden": "true" },
    svg("line", { x1: 18, y1: 138, x2: 216, y2: 138, stroke: "#2A3552", "stroke-width": 2 }),
    records, crate, person, pile);
  return h("div", { class: "digger-wrap" }, root, h("p", { class: "digger-count", id: "digger-count" }));
}

/** Bonequinho cavando enquanto a roleta sorteia; a pilha enche a cada música achada. */
function updateDigger(hunt) {
  const el = $("#digger");
  if (!el) return;
  const roulette = hunt?.kind === "roulette" ? hunt : null;
  const finds = roulette ? roulette.finds : [];
  el.classList.toggle("is-digging", roulette?.status === "running");
  el.classList.toggle("is-done", roulette?.status === "done" && finds.length > 0);
  const filledBefore = Number(el.dataset.filled || 0);
  el.querySelectorAll(".pile-slot").forEach((slot, index) => {
    const find = finds[index];
    slot.classList.toggle("is-filled", Boolean(find));
    slot.classList.toggle("is-new", Boolean(find) && index >= filledBefore);
    slot.style.fill = find ? PILE_COLORS[index % PILE_COLORS.length] : "";
    slot.querySelector("title").textContent = find ? (find.tag || find.title) : "";
  });
  el.dataset.filled = String(finds.length);
  const count = $("#digger-count");
  if (count) {
    count.textContent = roulette
      ? `${finds.length} de ${roulette.total || PILE_SLOTS} ${roulette.status === "running" ? "achadas até agora" : "achadas"}`
      : "";
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
  updateDigger(hunt);
  if (!hunt) {
    panel.hidden = true;
    list.replaceChildren();
    return;
  }
  const signature = JSON.stringify([
    hunt.status, hunt.progress, hunt.finds.length, hunt.message, state.kept.size, state.openDetails.size,
    state.blocked.length, state.showBlocked,
  ]);
  if (!panel.hidden && signature === state.huntSignature) return;
  state.huntSignature = signature;
  if (hunt.color) setMood(hunt.color);

  const running = hunt.status === "running";
  const uris = hunt.finds.map((find) => find.uri);
  const again = { sense: "Gerar de novo", roulette: "Girar de novo", rabbit: "Descer de novo", news: "Buscar de novo" }[hunt.kind];
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
      state.blocked.length > 0 && h("button", {
        class: "text-button",
        type: "button",
        "aria-expanded": String(state.showBlocked),
        "aria-controls": "blocked-list",
        onclick: () => { state.showBlocked = !state.showBlocked; renderHunt(); },
      }, `Artistas bloqueados (${state.blocked.length})`),
    ),
    state.showBlocked && state.blocked.length > 0 && h("ul", { class: "blocked-list", id: "blocked-list" },
      state.blocked.map((artist) => h("li", null,
        h("span", null, artist),
        h("button", { class: "text-button", type: "button", onclick: () => setBlocked(artist, false) }, "Desbloquear")))),
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
  if (find.bpm) {
    const energy = Math.round((find.energy || 0) * 100);
    return `BPM medido na prévia: ${find.bpm}. Energia: ${energy} de 100.`;
  }
  const parts = [find.reason];
  if (find.fans != null && !(find.reason || "").includes("fãs")) parts.push(`Artista com ${fans(find.fans)}.`);
  return parts.filter(Boolean).join(" ");
}

function findRow(find, finds, index, isNew) {
  const kept = state.kept.has(find.uri);
  const details = findDetails(find);
  const artist = (find.artists || [])[0];
  const open = state.openDetails.has(find.uri);
  const classes = ["track", "find", open && "is-open", isNew && "is-new"].filter(Boolean).join(" ");
  return h("li", { class: classes, "data-uri": find.uri },
    h("button", { class: "track-button", type: "button", title: `Tocar ${find.title}`, onclick: () => playFinds(finds, find.uri) },
      h("span", { class: "track-index" }, String(index + 1)),
      find.image ? h("img", { class: "track-art", src: find.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
      h("span", { class: "track-text" },
        h("span", { class: "track-title" }, find.title),
        h("span", { class: "track-sub" }, find.subtitle)),
      find.bpm ? h("span", { class: "bpm" }, h("b", null, String(find.bpm)), " BPM")
        : find.released ? h("span", { class: "bpm", title: find.released }, relativeDay(find.released))
          : h("span"),
      h("span", { class: "track-time" }, clock(find.duration_ms)),
    ),
    h("button", {
      class: "info-button",
      type: "button",
      "aria-expanded": String(open),
      "aria-label": `Detalhes de ${find.title}`,
      title: "Por que essa música?",
      onclick: () => toggleDetails(find.uri),
    }, infoIcon()),
    h("button", {
      class: "keep-button",
      type: "button",
      disabled: kept,
      title: "Guardar na playlist Achados da Sala",
      "aria-label": `Guardar ${find.title} nos Achados da Sala`,
      onclick: (event) => keep([find.uri], event.currentTarget),
    }, kept ? "Guardada" : "Guardar"),
    open && h("div", { class: "find-details" },
      details && h("span", null, details),
      artist && h("button", { class: "text-button", type: "button", onclick: () => setBlocked(artist, true) },
        `Não mostrar mais ${artist}`)),
  );
}

async function setBlocked(artist, blocked) {
  try {
    const { message, artists } = await api("/api/blocked", { artist, blocked });
    state.blocked = artists;
    if (!artists.length) state.showBlocked = false;
    toast(message);
    // O servidor já tirou o artista do resultado; busca a versão atualizada.
    const hunt = await api("/api/hunts/current");
    if (hunt) state.hunt = hunt;
  } catch (error) {
    toast(error.message, true);
  }
  state.huntSignature = "";
  renderHunt();
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

/** Consulta o player sem desperdício: 5 s tocando, 15 s parado, nada com a aba escondida. */
function schedulePlayerPoll() {
  clearTimeout(state.pollTimer);
  const delay = state.player?.is_playing ? 5000 : 15000;
  state.pollTimer = setTimeout(async () => {
    if (!document.hidden) await refreshPlayer();
    schedulePlayerPoll();
  }, delay);
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
    if (event.target.closest?.("input, textarea, select") || document.body.classList.contains("is-gated")) return;
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
  schedulePlayerPoll();
  setInterval(tick, 500);
}

init();
