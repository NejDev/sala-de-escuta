"use strict";

// Sala de escuta panel. Every text comes from i18n.js (STRINGS) through t(); each person picks the language.

const FALLBACK_COLORS = ["#5CC8C0", "#D4A84B", "#E3909E", "#E6D5AA", "#9DB4E6"];
const STAR_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.8l2.5 5.1 5.6.8-4.05 3.95.95 5.6L12 16.6l-5 2.65.95-5.6L3.9 9.7l5.6-.8z"/></svg>';
const PLAY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="solid" d="M8 5v14l11-7z"/></svg>';
const CLOSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';

const $ = (selector) => document.querySelector(selector);

// localStorage throws when the browser blocks storage; remembering things is only a convenience.
const memory = {
  get(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* no storage: carry on without remembering */ }
  },
};

// ---------- Language

const LANGS = ["pt", "en"];
const LANG = pickLanguage();
const LOCALE = LANG === "pt" ? "pt-BR" : "en";
const listFormat = new Intl.ListFormat(LOCALE, { type: "conjunction" });
const compactNumber = new Intl.NumberFormat(LOCALE, { notation: "compact" });

function pickLanguage() {
  const saved = memory.get("lang");
  if (LANGS.includes(saved)) return saved;
  return (navigator.language || "").toLowerCase().startsWith("pt") ? "pt" : "en";
}

// The server reads the same choice from this cookie, so its messages come in the same language.
document.cookie = `lang=${LANG}; path=/; max-age=31536000; samesite=lax`;
document.documentElement.lang = LOCALE;

/** Text in the current language. Arrays are [singular, plural], chosen by vars.count. */
function t(key, vars = {}) {
  let text = STRINGS[LANG][key] ?? STRINGS.en[key] ?? key;
  if (Array.isArray(text)) text = text[vars.count === 1 ? 0 : 1];
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

function setLanguage(lang) {
  if (lang === LANG) return;
  memory.set("lang", lang);
  document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
  location.reload();
}

/** Fixed texts in index.html: data-i18n (text) and data-i18n-attr ("aria-label:key;title:key"). */
function translatePage() {
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of el.dataset.i18nAttr.split(";")) {
      const [attr, key] = pair.split(":");
      el.setAttribute(attr, t(key));
    }
  }
  for (const box of document.querySelectorAll("[data-lang-switch]")) {
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", t("lang.label"));
    box.replaceChildren(...langOptions());
  }
}

function langOptions() {
  return [["pt", "PT", "Português"], ["en", "EN", "English"]].map(([code, short, name]) => h("button", {
    class: "lang-option",
    type: "button",
    lang: code === "pt" ? "pt-BR" : "en",
    "aria-pressed": String(code === LANG),
    "aria-label": name,
    title: name,
    onclick: () => setLanguage(code),
  }, short));
}

// ---------- Screens and filters

// Screens that aren't playlists: the key becomes the URL #.
const VIEWS = {
  home: "view.home", sensations: "view.sensations", discover: "view.discover", news: "view.news", artists: "view.artists",
  reviews: "view.reviews", friends: "view.friends", achievements: "view.achievements",
};
const VIEW_ALIASES = {
  inicio: "home", sensacoes: "sensations", descobrir: "discover", novidades: "news", artistas: "artists",
  resenhas: "reviews", amigos: "friends", conquistas: "achievements",
};
const MAX_HIGHLIGHTS = 10;  // the server's achievements.MAX_HIGHLIGHTS
const EVERY = ["daily", "weekly", "monthly"];
// Home: the ready-made sensation suggested for each time of day (hour it starts -> preset id).
const MOMENTS = [[5, "work-groove"], [9, "deep-focus"], [12, "work-groove"], [14, "deep-focus"], [18, "workout"], [21, "wind-down"]];
const HUNT_KINDS = { sensations: ["sense"], discover: ["roulette", "rabbit"], news: ["news"], artists: ["artist"] };
const RELEASE_TYPES = ["album", "single", "feature", "compilation"];

// Artist size is measured in fans: no free API says how many times a song was played.
const SIZE_MIN = ["", "100", "1000", "10000", "100000", "1000000"];
const SIZE_MAX = ["", "200", "500", "1000", "10000", "100000", "1000000", "10000000"];
// Song listeners are counted on Last.fm, only in rooms that have a Last.fm key.
const LISTENERS_MAX = ["", "50", "100", "500", "1000", "10000"];
const PERIODS = ["0", "3", "7", "14", "30", "90"];
const GENRE_SUGGESTIONS = [
  "K-pop", "J-pop", "Funk", "Trap", "Rap", "Drill", "Phonk", "Sertanejo", "Pagode", "Samba", "MPB", "Forró",
  "Piseiro", "Rock", "Indie", "Pop", "Emo", "Metal", "Punk", "genre.electronic", "House", "Techno", "Lo-fi", "Jazz",
  "R&B", "Soul", "Reggaeton", "Afrobeats", "Amapiano", "City pop", "Shoegaze", "Hyperpop", "Bossa nova", "genre.classical",
];
const ROOM_LIGHT = "#EEE7D7";

const state = {
  overview: null,
  view: "playlist",
  initialKey: decodeURIComponent(location.hash.slice(1)) || "home",
  selected: null,
  detail: null,
  sensations: null,
  hunt: null,
  huntTimer: 0,
  huntSignature: "",
  lastHunt: null,
  seed: "",
  artistName: "",
  friends: null,
  confirmLeave: false,
  reviews: null,
  review: null,
  artistFilters: { who: "", type: "", order: "new" },
  filters: { rouletteGenre: "", newsGenre: "", min: "", max: "", days: "30", ...savedFilters() },
  added: new Set(),
  openDetails: new Set(),
  landed: new Set(),
  blocked: [],
  showBlocked: false,
  addingOpen: false,
  myPlaylists: null,
  recent: null,
  watching: new Set(),
  confirmRemove: null,
  picker: null,
  tourStep: 0,
  player: null,
  playerSyncedAt: 0,
  seeking: false,
  refreshTimer: 0,
  searchTimer: 0,
  searchSeq: 0,
};

// ---------- Utilities

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

function icon(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup;
  return template.content.firstChild;
}

function playIcon() {
  return icon(PLAY_ICON);
}

async function api(path, body) {
  const init = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error(t("error.offline"));
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && data.login) showGate(data);
  if (!response.ok) {
    const restarting = !data.error && [502, 503, 504].includes(response.status);
    const error = new Error(data.error || t(restarting ? "error.restarting" : "error.status", { status: response.status }));
    error.data = data;
    throw error;
  }
  return data;
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
  if (days <= 0) return t("day.today");
  if (days === 1) return t("day.yesterday");
  if (days < 7) return t("day.ago", { count: days });
  return date.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" });
}

/** "today at 14:30", "tomorrow at 07:00", "Mon, 20/10, 07:00"; a past due time is "soon". */
function whenText(ms, future = true) {
  if (future && ms <= Date.now()) return t("when.soon");
  const date = new Date(ms);
  const time = date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date(ms).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return t("when.today", { time });
  if (days === 1) return t("when.tomorrow", { time });
  if (days === -1) return t("when.yesterday", { time });
  return t("when.date", { date: date.toLocaleDateString(LOCALE, { weekday: "short", day: "2-digit", month: "2-digit" }), time });
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** A short notice; with an action (label + link) it stays a little longer and can be clicked. */
function toast(message, isError = false, action = null) {
  const classes = ["toast", isError && "is-error", action && "has-action"].filter(Boolean).join(" ");
  const el = h("div", { class: classes }, message,
    action && (action.href
      ? h("a", { class: "toast-action", href: action.href }, action.label)
      : h("button", {
        class: "toast-action",
        type: "button",
        onclick: () => { el.remove(); action.onclick(); },
      }, action.label)));
  $("#toasts").append(el);
  setTimeout(() => el.remove(), action ? 9000 : isError ? 6500 : 4000);
}

function showGate(data) {
  document.body.classList.add("is-gated");
  $("#gate").hidden = false;
  if (data?.expired) $("#gate-text").textContent = t("gate.expired");
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
  const before = state.overview?.achievements?.new ?? 0;
  state.overview = await api("/api/overview");
  const fresh = state.overview.achievements?.new || 0;
  if (fresh > before && state.view !== "achievements") toast(t("ach.new_toast"));
  renderShelf();
  renderAccount();
  if (state.view === "playlist" && current()) renderSleeve();
  if (state.view === "home") renderIntro();
  // A favorite rebuilding right now (by the button or on schedule): follow it until it ends.
  for (const playlist of state.overview.playlists) {
    if (playlist.favorite.running) watchFavorite(playlist.favorite.id);
  }
}

/** Who is in the room now, the language, the tour and the sign-out button (each friend uses their own Spotify). */
function renderAccount() {
  const me = state.overview?.me;
  if (!me) return;
  $("#account").replaceChildren(
    h("span", { class: "account-name", title: me.is_owner ? t("account.owner") : null }, me.name),
    h("div", { class: "lang-switch", role: "group", "aria-label": t("lang.label") }, langOptions()),
    h("button", { class: "text-button", type: "button", onclick: () => openTour(0) }, t("tour.open")),
    h("button", { class: "text-button", type: "button", onclick: logout }, t("account.logout")),
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

/** Opens a playlist by key or one of the VIEWS screens. */
function go(key) {
  key = VIEW_ALIASES[key] || key;
  if ((key === "friends" || key === "achievements") && state.overview && !state.overview.friends) key = "home";
  return key in VIEWS ? openView(key) : select(key);
}

function shelfKeys() {
  return [...state.overview.playlists.map((playlist) => playlist.key), ...Object.keys(VIEWS)];
}

async function select(key) {
  if (!state.overview.playlists.some((playlist) => playlist.key === key)) return openView("home");
  state.view = "playlist";
  state.selected = key;
  state.confirmRemove = null;
  memory.set("selected", state.selected);
  history.replaceState(null, "", `#${encodeURIComponent(state.selected)}`);
  state.detail = null;
  state.addingOpen = false;
  closePicker({ restoreFocus: false });
  $("#hunt").hidden = true;
  renderShelf();
  renderSleeve();
  renderAdder();
  renderTracks();
  scrollToTop();
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
  // A dot in the playlist's color; it becomes an equalizer while that playlist is playing.
  const item = ({ key, label, color, uri, current, explore, number, badge }) => h("button", {
    class: explore ? "nav-item is-explore" : "nav-item",
    type: "button",
    style: color ? `--spine: ${color}` : null,
    "aria-current": current ? "page" : null,
    "data-uri": uri,
    title: t("nav.key", { label, number }),
    onclick: () => go(key),
  },
    h("span", { class: "nav-mark", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
    h("span", null, label),
    badge > 0 && h("span", { class: "nav-badge", "aria-label": t("ach.new_badge", { count: badge }) }, String(badge)));
  const playlists = state.overview.playlists.map((playlist, index) => item({
    key: playlist.key,
    label: playlist.name,
    color: colorOf(playlist),
    uri: playlist.uri,
    current: onPlaylist && playlist.key === state.selected,
    number: index + 1,
  }));
  const views = Object.entries(VIEWS).filter(([key]) => (key !== "friends" && key !== "achievements") || state.overview.friends);
  const room = views.map(([key, label], index) => item({
    key,
    badge: key === "achievements" ? state.overview.achievements?.new : 0,
    label: t(label),
    explore: true,
    current: state.view === key,
    number: playlists.length + index + 1,
  }));
  const group = (label, items) => h("div", { class: "nav-group", role: "group", "aria-label": label },
    h("span", { class: "nav-label", "aria-hidden": "true" }, label),
    items);
  const emptyShelf = !playlists.length && h("span", { class: "nav-empty" }, t("nav.none_yet"));
  const add = h("button", {
    class: "nav-item nav-add",
    type: "button",
    "aria-haspopup": "dialog",
    "aria-label": t("pin.open"),
    title: t("pin.open"),
    onclick: (event) => openPinPicker(event.currentTarget),
  }, "+");
  $("#shelf").replaceChildren(
    group(t("nav.favorites"), [...(playlists.length ? playlists : [emptyShelf]), add]),
    group(t("nav.room"), room),
  );
  markPlaying();
}

/** Back to the top: on a computer the stage scrolls; on a phone, the whole page. */
function scrollToTop() {
  $("#stage").scrollTo({ top: 0 });
  window.scrollTo({ top: 0 });
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
  const count = items ? items.length : playlist.total;
  const meta = [t(playlist.kind === "podcasts" ? "count.episodes" : "count.tracks", { count })];
  if (items?.length) meta.push(longDuration(items.reduce((sum, item) => sum + item.duration_ms, 0)));
  const lines = [h("p", { class: "meta" }, meta.join(", ")), ...favoriteLines(playlist.favorite)];
  if (playlist.kind === "mix") {
    lines.push(h("p", { class: "meta" }, t("sleeve.mix", { sources: listFormat.format(playlist.sources) })));
  }

  const cover = playlist.image
    ? h("img", { class: "cover", src: playlist.image, alt: t("sleeve.cover", { name: playlist.name }) })
    : h("div", { class: "cover cover-empty", "aria-hidden": "true" }, playlist.name.charAt(0));

  const fav = playlist.favorite;
  const curated = fav.curated;
  const pinned = fav.kind === "pinned";
  // Curated playlists keep a base selection (playlists.json) and pinned ones are plain playlists;
  // the ones made from discoveries get new songs on every update, so adding by hand wouldn't stick.
  const canAdd = playlist.uri && (pinned || (curated && ["music", "podcasts"].includes(playlist.kind)));
  const actions = h("div", { class: "actions" },
    h("button", { class: "play-button", type: "button", disabled: !playlist.uri, onclick: () => play(playlist.uri) },
      playIcon(), t("action.play")),
    playlist.uri && h("a", { class: "ghost-button", href: playlist.uri }, t("sleeve.open_app")),
    curated && h("button", { class: "ghost-button", type: "button", onclick: () => startJob(false) }, refreshLabel(playlist)),
    fav.kind === "discovery" && h("button", {
      class: "ghost-button",
      type: "button",
      disabled: Boolean(fav.running),
      onclick: () => refreshFavorite(fav),
    }, t("sleeve.update_now")),
    curated && h("button", { class: "text-button", type: "button", onclick: () => startJob(true) }, t("sleeve.preview")),
    !pinned && everyControl(fav),
    canAdd && h("button", {
      class: "text-button",
      type: "button",
      "aria-expanded": String(state.addingOpen),
      "aria-controls": "adder",
      onclick: toggleAdder,
    }, t(playlist.kind === "podcasts" ? "sleeve.follow_show" : "sleeve.add_track")),
    h("button", { class: "text-button", type: "button", onclick: () => removeFavorite(fav) },
      t(state.confirmRemove === fav.id ? "fav.remove_confirm" : "fav.remove")),
  );

  $("#sleeve").replaceChildren(cover, h("div", { class: "sleeve-text" },
    h("h1", { class: "title" }, playlist.name),
    playlist.description && h("p", { class: "description" }, playlist.description),
    lines,
    actions,
  ));
}

/** When it updates, how the last update went, or what it is doing right now. */
function favoriteLines(fav) {
  if (fav.kind === "pinned") return [h("p", { class: "meta" }, t("pin.line"))];
  if (fav.running) {
    const percent = fav.running.total ? Math.max(4, Math.round((fav.running.progress / fav.running.total) * 100)) : 4;
    return [
      h("p", { class: "meta" }, t("fav.running", { message: fav.running.message })),
      h("div", { class: "progress", "aria-hidden": "true" }, h("i", { style: `width: ${percent}%` })),
    ];
  }
  const lines = [h("p", { class: "meta" }, t("fav.line", { every: t(`every.${fav.every}`), when: whenText(fav.next_run) }))];
  if (fav.status !== "ok" && fav.message) lines.push(h("p", { class: "meta is-warning" }, fav.message));
  else if (fav.last_run) lines.push(h("p", { class: "meta" }, t("fav.last", { when: whenText(fav.last_run, false) })));
  return lines;
}

function everyControl(fav) {
  const select = h("select", { class: "filter-control every-select", id: "every-select" },
    EVERY.map((every) => h("option", { value: every, selected: every === fav.every }, capitalize(t(`every.${every}`)))));
  select.addEventListener("change", () => setEvery(fav.id, select.value));
  return h("label", { class: "every-control", for: "every-select" }, t("fav.every_label"), select);
}

function favoriteChanged(id, view) {
  const playlist = state.overview?.playlists.find((item) => item.favorite.id === id);
  if (!playlist) return;
  playlist.favorite = view;
  if (state.view === "playlist" && current() === playlist) renderSleeve();
  if (state.view === "home") renderIntro();
}

async function refreshFavorite(fav) {
  try {
    favoriteChanged(fav.id, await api(`/api/favorites/${fav.id}/refresh`, {}));
  } catch (error) {
    toast(error.message, true);
    return;
  }
  watchFavorite(fav.id);
}

/** Follows a favorite's update until it ends, then shows the result and the new songs. */
async function watchFavorite(id) {
  if (state.watching.has(id)) return;
  state.watching.add(id);
  try {
    for (;;) {
      await sleep(1500);
      const view = await api(`/api/favorites/${id}`);
      favoriteChanged(id, view);
      if (!view.running) {
        if (view.message) toast(view.message, view.status !== "ok");
        break;
      }
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.watching.delete(id);
  }
  await loadOverview();
  if (state.view === "playlist" && current()?.favorite.id === id) loadDetail();
}

async function setEvery(id, every) {
  try {
    const view = await api(`/api/favorites/${id}`, { every });
    favoriteChanged(id, view);
    toast(view.notice);
  } catch (error) {
    toast(error.message, true);
  }
}

/** Two clicks: the first asks, the second takes it off the bar (the playlist stays on Spotify). */
async function removeFavorite(fav) {
  if (state.confirmRemove !== fav.id) {
    state.confirmRemove = fav.id;
    renderSleeve();
    return;
  }
  const playlist = current();
  try {
    const { message } = await api(`/api/favorites/${fav.id}/remove`, {});
    toast(message, false, { label: t("fav.undo"), onclick: () => putBack(fav, playlist) });
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.confirmRemove = null;
  await loadOverview();
  go("home");
}

/** Undo "Remove from the bar": a pinned shortcut is pinned again, the others come back as they were. */
async function putBack(fav, playlist) {
  const id = playlist?.uri?.split(":").pop();
  try {
    toast((fav.kind === "pinned"
      ? await api("/api/favorites/pin", { playlist: id })
      : await api(`/api/favorites/${fav.id}/show`, {})).message);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  await loadOverview();
}

function refreshLabel(playlist) {
  if (!playlist.uri) return t("sleeve.create");
  return t(playlist.kind === "podcasts" ? "sleeve.update_now" : "sleeve.redo");
}

function renderTracks() {
  const list = $("#tracks");
  const playlist = current();
  if (!state.detail) {
    list.replaceChildren(h("li", { class: "tracks-empty" }, t("common.loading")));
    return;
  }
  const items = state.detail.items;
  if (!items.length) {
    let message = playlist.kind === "favorite"
      ? t("tracks.empty_favorite", { button: t("sleeve.update_now") })
      : playlist.kind === "pinned"
        ? t("tracks.empty_pinned", { button: t("sleeve.add_track") })
        : t("tracks.empty_curated", { button: t("sleeve.redo") });
    if (!playlist.uri) message = t("tracks.not_created", { button: t("sleeve.create") });
    else if (playlist.kind === "podcasts") message = t("tracks.no_episodes", { button: t("sleeve.update_now") });
    list.replaceChildren(h("li", { class: "tracks-empty" }, message));
    return;
  }
  list.replaceChildren(...items.map((item, index) => {
    const subtitle = item.type === "episode"
      ? [item.subtitle, relativeDay(item.release_date)].filter(Boolean).join(", ")
      : item.subtitle;
    return h("li", { class: "track", "data-uri": item.uri },
      h("button", {
        class: "track-button",
        type: "button",
        title: t("action.play_title", { title: item.title }),
        onclick: () => play(playlist.uri, item.uri),
      },
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

// ---------- Adding tracks and shows

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
  $("#adder-label").textContent = t(podcasts ? "adder.show_label" : "adder.track_label", { name: playlist.name });
  const input = $("#adder-input");
  input.value = "";
  input.placeholder = t(podcasts ? "adder.show_placeholder" : "adder.track_placeholder");
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
      : [h("li", { class: "results-empty" }, t("adder.none"))]));
  } catch (error) {
    toast(error.message, true);
  }
}

function resultRow(result, playlist) {
  const verb = t(playlist.kind === "podcasts" ? "adder.follow" : "adder.add");
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
    button.textContent = t(playlist.kind === "podcasts" ? "adder.following" : "adder.added");
    toast(message);
    await Promise.all([loadOverview(), loadDetail()]);
  } catch (error) {
    button.disabled = false;
    toast(error.message, true);
  }
}

// ---------- Sensations, Discover and New releases

async function openView(key) {
  state.view = key;
  state.addingOpen = false;
  closePicker({ restoreFocus: false });
  memory.set("selected", key);
  history.replaceState(null, "", `#${key}`);
  document.title = `Sala de escuta: ${t(VIEWS[key])}`;
  $("#adder").hidden = true;
  scrollToTop();
  renderShelf();
  if (key === "home") loadRecent();
  if (key === "friends") loadFriends();
  if (key === "reviews") loadReviews();
  if (key === "achievements") loadAchievements();
  if ((key === "sensations" || key === "home") && !state.sensations) {
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
  if (key !== "home") loadBlocked();
}

async function loadFriends() {
  try {
    state.friends = await api("/api/friends");
  } catch (error) {
    state.friends = { error: error.message };
  }
  if (state.view === "friends") renderIntro();
}

async function loadRecent() {
  try {
    state.recent = (await api("/api/recent")).finds;
  } catch {
    state.recent = [];  // the list is an extra on the home screen
  }
  if (state.view === "home") renderIntro();
}

async function loadBlocked() {
  try {
    state.blocked = (await api("/api/blocked")).artists;
  } catch {
    return;  // the list is an extra; everything else works without it
  }
  state.huntSignature = "";
  renderHunt();
}

/** The discovery in progress, if it belongs to the open screen. */
function huntHere() {
  const hunt = state.hunt;
  return hunt && (HUNT_KINDS[state.view] || []).includes(hunt.kind) ? hunt : null;
}

function renderIntro() {
  const sleeve = $("#sleeve");
  sleeve.className = "sleeve is-plain";
  const moment = state.view === "home" ? momentPreset() : null;
  setMood(huntHere()?.color || moment?.color || ROOM_LIGHT);
  const intro = {
    home: homeView, sensations: senseIntro, discover: discoverIntro, news: newsIntro, artists: artistsIntro,
    reviews: reviewsView, friends: friendsView, achievements: achievementsView,
  }[state.view];
  sleeve.replaceChildren(...intro());
}

/** Notice when Spotify paused searches: Sensations, Discover and New releases depend on them. */
function pauseNotice() {
  const seconds = state.overview?.search_paused_s;
  if (!seconds) return null;
  const back = new Date(Date.now() + seconds * 1000);
  const days = Math.round((new Date(back).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  const day = days === 0 ? t("day.today") : days === 1 ? t("day.tomorrow")
    : t("day.on", { date: back.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" }) });
  const time = back.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
  return h("p", { class: "meta is-warning pause-notice" },
    h("img", { class: "notice-art", src: "/mascot-sleep.webp?v=2", alt: "", width: "44", height: "48" }),
    h("span", null, t("pause.notice", { time, day })));
}

/** The screen's title with the mascot beside it, like a playlist's cover. */
function viewHead(art, title, description, ...extra) {
  return h("div", { class: "view-head" },
    h("div", { class: "sleeve-text" },
      h("h1", { class: "title" }, title),
      h("p", { class: "description" }, description),
      extra),
    h("img", { class: "view-art", src: `/mascot-${art}.webp?v=2`, alt: "", width: "150", height: "150" }));
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
    placeholder: t("sense.placeholder"),
    disabled: !ready,
  });
  if (active?.kind === "sense" && !sensations.some((s) => s.name === active.label)) feeling.value = active.label;
  const submit = (event) => {
    event.preventDefault();
    const text = feeling.value.trim();
    if (text) startHunt({ kind: "sense", text, ...sizeBody() });
  };
  // Wide screen: title, free field and filters on the left; the ready-made moments on the right.
  const main = h("div", { class: "sense-main" },
    viewHead("sensations", t("view.sensations"), t("sense.description"),
      !ready && h("p", { class: "meta is-warning" }, t("sense.tempo_missing")),
      pauseNotice()),
    h("form", { class: "feeling", onsubmit: submit },
      h("label", { class: "feeling-label", for: "feeling-input" }, t("sense.label")),
      h("div", { class: "feeling-row" },
        feeling,
        h("button", { class: "play-button", type: "submit", disabled: !ready }, t("sense.build"))),
      h("p", { class: "feeling-hint" }, t("sense.hint"))),
    h("div", { class: "filters" },
      ...sizeFilters(),
      h("p", { class: "filter-hint" }, t("sense.size_hint")),
      listenersHint()));
  const moods = h("div", { class: "sense-moods" },
    h("p", { class: "moods-label" }, t("sense.moods")),
    h("ul", { class: "moods" }, sensations.map((sensation) => h("li", null,
      h("button", {
        class: "mood",
        type: "button",
        style: `--tone: ${sensation.color}`,
        "aria-pressed": String(active?.label === sensation.name),
        disabled: !ready,
        onclick: () => startHunt({ kind: "sense", id: sensation.id, ...sizeBody() }),
      },
        h("span", { class: "mood-name" }, sensation.name),
        h("span", { class: "mood-bpm" }, `${sensation.bpm[0]}–${sensation.bpm[1]} BPM`),
        h("span", { class: "mood-text" }, sensation.description))))));
  return [h("div", { class: "sense-layout" }, main, moods)];
}

function discoverIntro() {
  if (rouletteGenre().rare) state.filters.rouletteGenre = t("genre.rare");  // in the current language
  const seed = h("input", {
    class: "adder-input",
    id: "seed-input",
    type: "search",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: t("discover.seed_placeholder"),
  });
  seed.value = state.seed;
  seed.addEventListener("input", () => { state.seed = seed.value; });
  seed.addEventListener("keydown", (event) => {
    if (event.key === "Enter") startHunt({ kind: "rabbit", seed: seed.value, ...sizeBody() });
  });
  return [
    viewHead("roulette", t("view.discover"), t("discover.description"), pauseNotice()),
    h("div", { class: "filters" },
      genreField("roulette-genre", "rouletteGenre", t("discover.genre_label"), t("discover.genre_any"), false,
        "roulette-genre-list"),
      ...sizeFilters(),
      h("p", { class: "filter-hint" }, t("discover.size_hint")),
      listenersHint(),
      genreList("roulette-genre-list", [t("genre.rare")])),
    h("div", { class: "paths" },
      h("section", { class: "path path-roulette", style: "--tone: #F2C14E" },
        h("h2", { class: "path-name" }, t("discover.roulette")),
        h("p", { class: "path-text" }, t("discover.roulette_text")),
        h("button", {
          class: "play-button",
          type: "button",
          onclick: () => startHunt({ kind: "roulette", ...rouletteGenre(), ...sizeBody() }),
        }, t("discover.spin")),
        digger()),
      h("section", { class: "path", style: "--tone: #9DB4E6" },
        h("h2", { class: "path-name" }, t("discover.rabbit")),
        h("p", { class: "path-text" }, t("discover.rabbit_text")),
        h("label", { class: "adder-label", for: "seed-input" }, t("discover.seed_label")),
        seed,
        h("button", { class: "play-button", type: "button", onclick: () => startHunt({ kind: "rabbit", seed: seed.value, ...sizeBody() }) },
          t("discover.enter")))),
  ];
}

function savedFilters() {
  try {
    return JSON.parse(memory.get("filters") || memory.get("filtros") || "{}");
  } catch {
    return {};
  }
}

function saveFilters() {
  memory.set("filters", JSON.stringify(state.filters));
}

function sizeBody() {
  // A cap saved while the room had a Last.fm key is left out once it no longer has one.
  const listeners = state.overview?.lastfm ? state.filters.listeners || null : null;
  return { min_fans: state.filters.min || null, max_fans: state.filters.max || null, max_listeners: listeners };
}

function choice(id, label, options, key) {
  const control = h("select", { class: "filter-control", id },
    options.map(([value, text]) => h("option", { value, selected: String(state.filters[key] ?? "") === value }, text)));
  control.addEventListener("change", () => { state.filters[key] = control.value; saveFilters(); });
  return h("label", { class: "filter", for: id }, h("span", { class: "filter-label" }, label), control);
}

function genreField(id, key, label, placeholder, required = false, list = "genre-list") {
  const input = h("input", {
    class: "filter-control filter-genre",
    id,
    type: "text",
    list,
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
  const options = (values, empty) => values.map((value) => [value, value ? compactNumber.format(Number(value)) : t(empty)]);
  return [
    choice("min-fans", t("filter.min"), options(SIZE_MIN, "size.any"), "min"),
    choice("max-fans", t("filter.max"), options(SIZE_MAX, "size.no_cap"), "max"),
    state.overview?.lastfm && choice("max-listeners", t("filter.listeners"), options(LISTENERS_MAX, "size.no_cap"), "listeners"),
  ];
}

/** Credit for the listener numbers: Last.fm's terms ask for it wherever they show. */
function listenersHint() {
  return state.overview?.lastfm && h("p", { class: "filter-hint" },
    h("a", { class: "text-button", href: "https://www.last.fm/", target: "_blank", rel: "noopener" }, t("filter.listeners_hint")));
}

function genreList(id = "genre-list", first = []) {
  const genres = GENRE_SUGGESTIONS.map((genre) => (genre.startsWith("genre.") ? t(genre) : genre));
  return h("datalist", { id }, [...first, ...genres].map((genre) => h("option", { value: genre })));
}

/** The roulette's genre, or "little-known genre" (matched in either language, so a saved choice survives a switch). */
function rouletteGenre() {
  const typed = (state.filters.rouletteGenre || "").trim();
  const rare = LANGS.some((lang) => STRINGS[lang]["genre.rare"].toLowerCase() === typed.toLowerCase());
  return rare ? { rare: true } : { genre: typed };
}

// ---------- Friends: musical affinity and matches (only who joins)

function friendsView() {
  const data = state.friends;
  const head = viewHead("friends", t("view.friends"), t("friends.description"));
  if (!data) return [head, h("p", { class: "meta" }, t("common.loading"))];
  if (data.error) return [head, h("p", { class: "meta is-warning" }, data.error)];
  if (!data.sharing) {
    return [head, h("section", { class: "friends-join" },
      h("p", null, t("friends.join_text")),
      h("button", { class: "play-button", type: "button", onclick: joinFriends }, t("friends.join"))),
      accessSection(data.access)];
  }
  const card = (friend) => h("li", { class: "friend-card" },
    h("p", { class: "friend-name" }, friend.name),
    friend.medals?.length > 0 && h("ul", { class: "highlight-row" }, friend.medals.map(highlightChip)),
    friend.affinity
      ? h("p", { class: "friend-percent" }, `${friend.affinity.percent}%`, h("small", null, t("friends.percent_label")))
      : h("p", { class: "friend-percent is-empty" }, "—", h("small", null, t("friends.little"))),
    friend.affinity?.shared.length > 0 && h("p", { class: "meta" }, t("friends.shared", { names: listFormat.format(friend.affinity.shared) })),
    h("p", { class: "meta" }, t("friends.week", { count: friend.plays_7d })));
  return [
    head,
    h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("friends.affinity"))),
      data.friends.length ? h("ul", { class: "friend-grid" }, data.friends.map(card)) : h("p", { class: "meta" }, t("friends.alone")),
      h("p", { class: "meta friends-hint" }, t("friends.affinity_hint")),
      !data.me.taste && h("p", { class: "meta" }, t("friends.building")),
      !data.me.top && h("p", { class: "meta" }, t("friends.top_authorize"), " ",
        h("a", { class: "text-button", href: "/login" }, t("player.auth_button")))),
    h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("friends.feed"))),
      feedList(data.feed)),
    achievementsSwitch(),
    h("p", { class: "meta friends-me" }, t("friends.me", { count: data.me.plays_7d }), " ", t("friends.updates"), " ",
      h("button", { class: "text-button", type: "button", onclick: leaveFriends },
        t(!state.confirmLeave ? "friends.leave"
          : state.overview?.achievements?.on ? "friends.leave_confirm_medals" : "friends.leave_confirm"))),
    accessSection(data.access),
  ];
}

// ---------- Reviews: albums rated and written about, Letterboxd style (private or open to the room)

async function loadReviews() {
  try {
    state.reviews = await api("/api/reviews");
  } catch (error) {
    state.reviews = { error: error.message };
  }
  if (state.view === "reviews") renderIntro();
}

function reviewsView() {
  const data = state.reviews;
  const head = viewHead("reviews", t("view.reviews"), t("reviews.description"));
  const playing = state.player?.item;
  const start = h("section", { class: "home-section review-start" },
    h("form", { class: "review-link", onsubmit: openFromLink },
      h("label", { class: "field-label", for: "review-link" }, t("reviews.link_label")),
      h("div", { class: "review-link-row" },
        h("input", {
          class: "filter-control", id: "review-link", type: "text", inputmode: "url", autocomplete: "off",
          spellcheck: "false", placeholder: "https://open.spotify.com/album/…",
        }),
        h("button", { class: "play-button", type: "submit" }, t("reviews.open")))),
    playing?.album_id && h("p", { class: "meta" },
      h("button", { class: "text-button", type: "button", onclick: () => openReview(playing.album_id) },
        t("reviews.now_playing", { title: playing.title }))),
    h("p", { class: "meta" }, t("reviews.hint_more")));
  if (!data) return [head, start, h("p", { class: "meta" }, t("common.loading"))];
  if (data.error) return [head, start, h("p", { class: "meta is-warning" }, data.error)];
  const section = (title, items, empty) => h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, title)),
    items.length ? h("ul", { class: "review-list" }, items.map((review) => reviewCard(review))) : h("p", { class: "meta" }, empty));
  return [
    head,
    start,
    section(t("reviews.room_title"), data.room, t("reviews.room_empty")),
    section(t("reviews.mine_title"), data.mine, t("reviews.mine_empty")),
  ];
}

function openFromLink(event) {
  event.preventDefault();
  const text = $("#review-link").value.trim();
  const found = text.match(/(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?album\/|spotify:album:)([A-Za-z0-9]{22})/)
    || text.match(/^([A-Za-z0-9]{22})$/);
  if (!found) {
    toast(t("reviews.link_invalid"), true);
    return;
  }
  openReview(found[1]);
}

function ratingText(rating) {
  return rating.toLocaleString(LOCALE, { maximumFractionDigits: 1 });
}

/** Five stars, filled up to the rating (halves included). */
function stars(rating, large = false) {
  return h("span", { class: large ? "stars is-large" : "stars", role: "img", "aria-label": t("reviews.stars", { value: ratingText(rating) }) },
    h("span", { class: "stars-base", "aria-hidden": "true" }, "★★★★★"),
    h("span", { class: "stars-fill", "aria-hidden": "true", style: `width: ${rating * 20}%` }, "★★★★★"));
}

/** Click a star's left half for half a star, its right half for the whole one (again to clear); arrows work too. */
function starsInput(draft) {
  const fill = h("span", { class: "stars-fill", "aria-hidden": "true" }, "★★★★★");
  const value = h("span", { class: "stars-value" });
  const input = h("input", {
    class: "stars-range", type: "range", min: "0", max: "10", step: "1", value: String(draft.rating * 2),
    "aria-labelledby": "rating-label",
    oninput: () => show(Number(input.value) / 2),
  });
  function show(rating) {
    draft.rating = rating;
    input.value = String(rating * 2);
    fill.style.width = `${rating * 20}%`;
    const label = rating ? t("reviews.stars", { value: ratingText(rating) }) : t("reviews.no_rating");
    value.textContent = rating ? ratingText(rating) : t("reviews.no_rating");
    input.setAttribute("aria-valuetext", label);
  }
  const box = h("span", {
    class: "stars is-large is-input",
    onclick: (event) => {
      const rect = box.getBoundingClientRect();
      const halves = Math.min(10, Math.max(1, Math.ceil(((event.clientX - rect.left) / rect.width) * 10)));
      show(halves / 2 === draft.rating ? 0 : halves / 2);
      input.focus({ preventScroll: true });
    },
  }, h("span", { class: "stars-base", "aria-hidden": "true" }, "★★★★★"), fill, input);
  show(draft.rating);
  return h("span", { class: "stars-input" }, box, value);
}

function reviewCard(review, compact = false) {
  const album = review.album;
  const who = t("reviews.by", { name: review.own ? t("reviews.you") : review.author, when: whenText(review.updated * 1000, false) });
  return h("li", { class: compact ? "review-card is-compact" : "review-card" },
    !compact && h("button", {
      class: "review-cover", type: "button", tabindex: "-1", "aria-hidden": "true", onclick: () => openReview(album.id),
    }, album.image ? h("img", { src: album.image, alt: "", loading: "lazy" }) : h("span")),
    h("div", { class: "review-body" },
      !compact && h("p", { class: "review-album" },
        h("button", { class: "review-album-name", type: "button", onclick: () => openReview(album.id) }, album.name),
        h("span", { class: "meta" }, albumLine(album))),
      h("p", { class: "review-head" },
        review.rating ? stars(review.rating) : null,
        h("span", { class: "meta" }, who),
        review.own && !review.public && h("span", { class: "review-private" }, t("reviews.private"))),
      review.text && h("p", { class: "review-text" }, review.text)));
}

function albumLine(album) {
  const artists = album.artists.join(", ");
  return album.year ? t("reviews.album_line", { artists, year: album.year }) : artists;
}

async function openReview(albumId) {
  closeReview();
  const dialog = h("dialog", {
    class: "review-sheet", id: "review-sheet", "aria-labelledby": "review-title",
    onclose: () => {
      dialog.remove();
      state.review = null;
    },
    onclick: (event) => event.target === dialog && dialog.close(),
  }, h("div", { class: "review-inner" }, h("p", { class: "meta" }, t("common.loading"))));
  document.body.append(dialog);
  dialog.showModal();
  try {
    const data = await api(`/api/reviews/album?id=${encodeURIComponent(albumId)}`);
    if (!dialog.isConnected) return;
    const mine = data.mine;
    state.review = {
      ...data,
      busy: false,
      confirmDelete: false,
      draft: { rating: mine?.rating || 0, text: mine?.text || "", public: mine ? mine.public : localStorage.getItem("review-public") === "1" },
    };
    renderReview();
    $("#review-sheet .stars-range")?.focus();
  } catch (error) {
    dialog.firstChild.replaceChildren(
      h("p", { class: "meta is-warning" }, error.message),
      h("button", { class: "text-button", type: "button", onclick: () => dialog.close() }, t("reviews.close")));
  }
}

function closeReview() {
  $("#review-sheet")?.close();
}

function renderReview() {
  const dialog = $("#review-sheet");
  const review = state.review;
  if (!dialog || !review) return;
  const { album, draft } = review;
  const hint = h("p", { class: "meta review-visibility-hint" });
  const choices = [[true, t("reviews.public")], [false, t("reviews.only_me")]].map(([value, label]) =>
    h("button", { class: "who-chip", type: "button", "data-public": String(value), onclick: () => setVisibility(value) }, label));
  function setVisibility(value) {
    draft.public = value;
    for (const chip of choices) chip.setAttribute("aria-pressed", String(chip.dataset.public === String(value)));
    hint.textContent = t(value ? "reviews.public_hint" : "reviews.only_me_hint");
  }
  setVisibility(draft.public);
  dialog.firstChild.replaceChildren(
    h("header", { class: "review-sheet-head" },
      album.image ? h("img", { class: "review-sheet-cover", src: album.image, alt: "" }) : h("span", { class: "review-sheet-cover" }),
      h("div", { class: "review-sheet-text" },
        h("h2", { class: "review-title", id: "review-title" }, album.name),
        h("p", { class: "meta" }, albumLine(album)),
        h("button", { class: "text-button", type: "button", onclick: () => play(album.uri) }, t("reviews.play"))),
      h("button", { class: "icon-button review-close", type: "button", "aria-label": t("reviews.close"), title: t("reviews.close"), onclick: closeReview }, "×")),
    h("form", { class: "review-form", onsubmit: saveReview },
      h("div", { class: "review-field" }, h("span", { class: "field-label", id: "rating-label" }, t("reviews.rating")), starsInput(draft)),
      h("div", { class: "review-field" },
        h("label", { class: "field-label", for: "review-text" }, t("reviews.text_label")),
        h("textarea", {
          class: "review-textarea", id: "review-text", rows: "6", maxlength: "2000", placeholder: t("reviews.text_placeholder"),
          oninput: (event) => { draft.text = event.target.value; },
        }, draft.text)),
      h("div", { class: "review-field" },
        h("span", { class: "field-label" }, t("reviews.visibility")),
        h("div", { class: "review-visibility", role: "group", "aria-label": t("reviews.visibility") }, choices),
        hint),
      h("div", { class: "review-actions" },
        h("button", { class: "play-button", type: "submit", disabled: review.busy }, t("reviews.save")),
        review.mine && h("button", { class: "text-button review-delete", type: "button", onclick: deleteReview },
          t(review.confirmDelete ? "reviews.delete_confirm" : "reviews.delete")),
        h("button", { class: "text-button", type: "button", onclick: closeReview }, t("reviews.cancel")))),
    h("section", { class: "review-room" },
      h("h3", { class: "review-room-title" }, t("reviews.others")),
      review.average != null && h("p", { class: "review-average" }, stars(review.average), " ",
        t("reviews.average", { value: ratingText(review.average), count: review.count })),
      review.room.length
        ? h("ul", { class: "review-list" }, review.room.map((other) => reviewCard(other, true)))
        : h("p", { class: "meta" }, t("reviews.others_empty"))));
}

async function saveReview(event) {
  event.preventDefault();
  const review = state.review;
  if (!review || review.busy) return;
  if (!review.draft.rating && !review.draft.text.trim()) {
    toast(t("reviews.need_something"), true);
    return;
  }
  review.busy = true;
  try {
    const result = await api("/api/reviews", {
      album: review.album.id, rating: review.draft.rating || null, text: review.draft.text, public: review.draft.public,
    });
    localStorage.setItem("review-public", review.draft.public ? "1" : "0");
    toast(result.message);
    closeReview();
    loadReviews();
  } catch (error) {
    review.busy = false;
    toast(error.message, true);
  }
}

async function deleteReview() {
  const review = state.review;
  if (!review.confirmDelete) {
    review.confirmDelete = true;
    renderReview();
    $("#review-sheet .review-delete")?.focus();
    return;
  }
  try {
    const result = await api("/api/reviews/delete", { album: review.album.id });
    toast(result.message);
    closeReview();
    loadReviews();
  } catch (error) {
    toast(error.message, true);
  }
}

/** Owner only: who may use Friends, one switch per person, and the default for people who join later. */
function accessSection(access) {
  if (!access) return null;
  const toggle = (pressed, label, onclick) => h("button", {
    class: "who-chip", type: "button", "aria-pressed": String(pressed), onclick,
  }, label);
  return h("section", { class: "home-section friends-access" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("friends.access_title"))),
    h("p", { class: "meta" }, t("friends.access_hint")),
    access.people.length
      ? h("ul", { class: "access-list" }, access.people.map((person) => h("li", null,
        h("span", null, person.name),
        toggle(person.allowed, t(person.allowed ? "friends.access_allowed" : "friends.access_blocked"),
          () => saveAccess({ user: person.id, allowed: !person.allowed })))))
      : h("p", { class: "meta" }, t("friends.access_nobody")),
    h("label", { class: "access-new" },
      h("input", { type: "checkbox", checked: access.new, onchange: (event) => saveAccess({ new: event.target.checked }) }),
      " ", t("friends.access_new")));
}

async function saveAccess(body) {
  try {
    state.friends = await api("/api/friends/access", body);
    toast(state.friends.message);
  } catch (error) {
    toast(error.message, true);
  }
  renderIntro();
}

function gapText(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes < 60 ? t("friends.gap_min", { count: minutes }) : t("friends.gap_h", { count: Math.round(minutes / 60) });
}

function feedList(events) {
  if (!events.length) return h("p", { class: "meta" }, t("friends.feed_empty"));
  return h("ol", { class: "tracks feed" }, events.map((event) => {
    const track = event.track;
    const artist = track.artists[0]?.name || "";
    const text = t("friends.match", { friend: event.friend, title: track.title, artist, gap: gapText(event.gap_s) });
    return h("li", { class: "track feed-item", "data-uri": track.uri },
      h("button", {
        class: "track-button",
        type: "button",
        title: t("action.play_title", { title: track.title }),
        onclick: () => command({ action: "play", uris: [track.uri] }),
      },
        track.image ? h("img", { class: "track-art", src: track.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
        h("span", { class: "track-text" },
          h("span", { class: "feed-text" }, text),
          h("span", { class: "track-sub" }, whenText(event.at * 1000, false)))));
  }));
}

async function joinFriends() {
  if (state.friends && !state.friends.ready) {
    toast(t("friends.join_authorize"), false, { label: t("player.auth_button"), href: "/login" });
    return;
  }
  try {
    state.friends = await api("/api/friends", { share: true });
    toast(state.friends.message);
  } catch (error) {
    toast(error.message, true);
  }
  renderIntro();
}

/** Two clicks: the first asks, the second leaves and deletes the history. */
async function leaveFriends() {
  if (!state.confirmLeave) {
    state.confirmLeave = true;
    renderIntro();
    return;
  }
  state.confirmLeave = false;
  try {
    state.friends = await api("/api/friends", { share: false, forget: true });
    toast(state.friends.message);
  } catch (error) {
    toast(error.message, true);
  }
  renderIntro();
}

// ---------- Achievements: hidden medals and monthly titles among the people taking part (inside Friends)

async function loadAchievements() {
  try {
    state.achievements = await api("/api/achievements");
  } catch (error) {
    state.achievements = { error: error.message };
  }
  if (state.view === "achievements") renderIntro();
}

/** New medals show as a number on the tab; the server works them out every 15 minutes. */
async function pollMedals() {
  if (!state.overview?.friends || document.hidden) return;
  let summary;
  try {
    summary = await api("/api/achievements/summary");
  } catch {
    return;
  }
  const before = state.overview.achievements?.new || 0;
  state.overview.achievements = summary;
  if (summary.new > before && state.view !== "achievements") toast(t("ach.new_toast"));
  if (summary.new !== before) renderShelf();
}

function achievementsView() {
  const data = state.achievements;
  const head = viewHead("keep", t("view.achievements"), t("ach.description"));
  if (!data) return [head, h("p", { class: "meta" }, t("common.loading"))];
  if (data.error) return [head, h("p", { class: "meta is-warning" }, data.error)];
  if (!data.sharing) {
    return [head, h("section", { class: "friends-join" },
      h("p", null, t("ach.need_friends")),
      h("button", { class: "play-button", type: "button", onclick: () => go("friends") }, t("ach.go_friends")))];
  }
  if (!data.on) {
    return [head, h("section", { class: "friends-join" },
      h("p", null, t("ach.invite")),
      h("p", { class: "meta" }, t("ach.notice")),
      h("button", { class: "play-button", type: "button", onclick: joinAchievements }, t("ach.join")))];
  }
  return [
    head,
    revealSection(data),
    profileSection(data),
    raceSection(data.race, t("ach.race"), t("ach.race_empty")),
    h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.mine"))),
      data.me.medals.length ? h("ul", { class: "medal-grid" }, data.me.medals.map((medal) => medalCard(medal, data, true)))
        : h("p", { class: "meta" }, t("ach.none_yet"))),
    roomSection(data),
    data.months.length > 0 && h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.months"))),
      data.months.map((month) => raceSection(month.titles, monthLabel(month.month), "", true))),
    listenersHint(),
    h("p", { class: "meta friends-me" }, t("ach.leave_text"), " ",
      h("button", { class: "text-button", type: "button", onclick: () => leaveAchievements(false) }, t("ach.leave")), " ",
      h("button", { class: "text-button", type: "button", onclick: () => leaveAchievements(true) },
        t(state.confirmForgetMedals ? "ach.forget_confirm" : "ach.forget"))),
  ].filter(Boolean);  // renderIntro spreads the list into the DOM: a false or null would show as text
}

/** Inside Friends: the switch, or a way to the tab. */
function achievementsSwitch() {
  const on = state.overview?.achievements?.on;
  return h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("view.achievements"))),
    on ? h("p", { class: "meta" }, t("ach.leave_text"), " ",
      h("button", { class: "text-button", type: "button", onclick: () => go("achievements") }, t("ach.open_tab")))
      : [h("p", { class: "meta" }, t("ach.invite"), " ", t("ach.notice")),
        h("button", { class: "play-button", type: "button", onclick: joinAchievements }, t("ach.join"))]);
}

async function joinAchievements() {
  try {
    state.achievements = await api("/api/achievements", { on: true });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  await loadOverview();
  if (state.view === "friends") renderIntro();
  else go("achievements");
}

/** Leaving keeps the medals for a return; erasing takes two clicks. */
async function leaveAchievements(forget) {
  if (forget && !state.confirmForgetMedals) {
    state.confirmForgetMedals = true;
    renderIntro();
    return;
  }
  state.confirmForgetMedals = false;
  try {
    state.achievements = await api("/api/achievements", { on: false, forget });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
  }
  renderIntro();
  loadOverview();
}

/** A badge whose shape and colors come from the medal's id: nothing in it hints at the rule. */
function medalEmblem(medal) {
  let hash = 0;
  for (const char of medal.id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  const shapes = ["is-round", "is-hex", "is-shield", "is-star"];
  return h("span", { class: `medal-emblem ${shapes[hash % shapes.length]}`, style: `--hue: ${hash % 360}`, "aria-hidden": "true" },
    medal.name.slice(0, 1));
}

function songLine(song) {
  return h("span", { class: "medal-song" },
    song.image ? h("img", { class: "track-art", src: song.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
    h("span", { class: "track-text" },
      h("span", { class: "track-title" }, song.title),
      h("span", { class: "track-sub" }, song.artist)));
}

function medalCard(medal, data, own) {
  const rarity = own && medal.holders === 1 ? t("ach.only_you")
    : t("ach.holders", { count: medal.holders, total: data.participants });
  return h("li", { class: "medal-card" },
    medalEmblem(medal),
    h("div", { class: "medal-text" },
      h("p", { class: "medal-name" }, medal.name),
      own && medal.how && h("p", { class: "meta" }, medal.how),
      h("p", { class: "meta" }, t("ach.earned_on", { date: new Date(medal.at * 1000).toLocaleDateString(LOCALE) }), " · ", rarity),
      own && medal.lastfm && h("p", { class: "meta" }, lastfmLine(medal.lastfm)),
      medal.song && h("button", {
        class: "medal-song-button",
        type: "button",
        title: t("action.play_title", { title: medal.song.title }),
        onclick: () => command({ action: "play", uris: [medal.song.uri] }),
      }, songLine(medal.song))));
}

/** New medals one at a time: the card turns over to show what was earned (and how). */
function revealSection(data) {
  const fresh = data.new.map((id) => data.me.medals.find((medal) => medal.id === id)).filter(Boolean);
  if (!fresh.length) return null;
  const index = Math.min(state.reveal || 0, fresh.length - 1);
  const medal = fresh[index];
  const open = state.revealOpen === medal.id;
  const last = index === fresh.length - 1;
  return h("section", { class: "home-section reveal" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.new_title", { count: fresh.length }))),
    h("button", {
      class: `reveal-card${open ? " is-open" : ""}`,
      type: "button",
      "aria-label": open ? medal.name : t("ach.reveal"),
      onclick: () => { state.revealOpen = medal.id; renderIntro(); },
    },
      h("span", { class: "reveal-face reveal-back", "aria-hidden": "true" }, "?"),
      h("span", { class: "reveal-face reveal-front", "aria-hidden": open ? null : "true" },
        medalEmblem(medal),
        h("strong", { class: "medal-name" }, medal.name),
        h("span", { class: "meta" }, medal.how),
        medal.song && songLine(medal.song))),
    !open && h("p", { class: "meta" }, t("ach.reveal")),
    open && h("button", { class: "play-button", type: "button", onclick: () => nextReveal(fresh, last) },
      t(last ? "ach.done" : "ach.next")));
}

async function nextReveal(fresh, last) {
  if (!last) {
    state.reveal = (state.reveal || 0) + 1;
    renderIntro();
    return;
  }
  try {
    state.overview.achievements = await api("/api/achievements/seen", { ids: fresh.map((medal) => medal.id) });
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.reveal = 0;
  state.revealOpen = null;
  renderShelf();
  await loadAchievements();
}

function highlightChip(medal) {
  return h("li", { class: "highlight-chip", title: medal.name }, medalEmblem(medal), h("span", null, medal.name));
}

function profileSection(data) {
  const me = data.me;
  const editing = Boolean(state.highlightDraft);
  return h("section", { class: "home-section profile-card" },
    h("div", { class: "section-head" },
      h("h2", { class: "section-title" }, me.name),
      h("p", { class: "meta" }, t("ach.count", { count: me.count, total: data.total }))),
    editing ? highlightPicker(me)
      : me.highlights.length ? h("ul", { class: "highlight-row" }, me.highlights.map(highlightChip))
        : h("p", { class: "meta" }, t("ach.no_highlights")),
    !editing && me.medals.length > 0 && h("button", {
      class: "text-button",
      type: "button",
      onclick: () => { state.highlightDraft = me.highlights.map((medal) => medal.id); renderIntro(); },
    }, t("ach.pick_highlights")));
}

function highlightPicker(me) {
  const toggle = (id, input) => {
    const draft = state.highlightDraft;
    if (!input.checked) {
      state.highlightDraft = draft.filter((other) => other !== id);
    } else if (draft.length >= MAX_HIGHLIGHTS) {
      input.checked = false;
      toast(t("ach.highlights_hint", { max: MAX_HIGHLIGHTS }));
    } else {
      draft.push(id);
    }
  };
  return h("div", { class: "highlight-picker" },
    h("p", { class: "meta" }, t("ach.highlights_hint", { max: MAX_HIGHLIGHTS })),
    h("ul", { class: "highlight-options" }, me.medals.map((medal) => h("li", null,
      h("label", { class: "highlight-option" },
        h("input", { type: "checkbox", checked: state.highlightDraft.includes(medal.id), onchange: (event) => toggle(medal.id, event.target) }),
        medalEmblem(medal),
        h("span", null, medal.name))))),
    h("div", { class: "actions" },
      h("button", { class: "play-button", type: "button", onclick: saveHighlights }, t("ach.save_highlights")),
      h("button", { class: "text-button", type: "button", onclick: () => { state.highlightDraft = null; renderIntro(); } },
        t("ach.cancel"))));
}

async function saveHighlights() {
  try {
    state.achievements = await api("/api/achievements/highlights", { ids: state.highlightDraft });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.highlightDraft = null;
  renderIntro();
}

function raceSection(titles, heading, empty, past = false) {
  return h("section", { class: past ? "race is-past" : "home-section race" },
    h("div", { class: "section-head" }, h(past ? "h3" : "h2", { class: "section-title" }, heading)),
    titles.length ? h("ul", { class: "race-list" }, titles.map((title) => h("li", { class: "race-item" },
      h("p", { class: "race-title" }, title.name),
      h("p", { class: "meta" }, listFormat.format(title.holders), " · ", title.value))))
      : h("p", { class: "meta" }, empty));
}

function monthLabel(month) {
  const [year, number] = month.split("-").map(Number);
  return new Date(year, number - 1, 1).toLocaleDateString(LOCALE, { month: "long", year: "numeric" });
}

function roomSection(data) {
  const card = (person) => {
    const open = state.openPerson === person.id;
    return h("li", { class: open ? "friend-card is-open" : "friend-card" },
      h("p", { class: "friend-name" }, person.name),
      h("p", { class: "meta" }, t("ach.count", { count: person.count, total: data.total })),
      person.highlights.length > 0 && h("ul", { class: "highlight-row" }, person.highlights.map(highlightChip)),
      person.medals.length > 0 && h("button", {
        class: "text-button",
        type: "button",
        "aria-expanded": String(open),
        onclick: () => { state.openPerson = open ? null : person.id; renderIntro(); },
      }, t(open ? "ach.hide_medals" : "ach.see_medals")),
      open && h("ul", { class: "medal-grid is-compact" }, person.medals.map((medal) => medalCard(medal, data, false))));
  };
  return h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.room"))),
    data.people.length ? h("ul", { class: "friend-grid" }, data.people.map(card)) : h("p", { class: "meta" }, t("ach.room_empty")));
}

// ---------- Artists: a band's or artist's releases, with members' solo work and features

function artistsIntro() {
  const input = h("input", {
    class: "filter-control filter-genre",
    id: "artist-name",
    type: "search",
    maxlength: "60",
    autocomplete: "off",
    spellcheck: "false",
    required: true,
    placeholder: t("artists.placeholder"),
  });
  input.value = state.artistName;
  input.addEventListener("input", () => { state.artistName = input.value; });
  const submit = (event) => {
    event.preventDefault();
    state.artistFilters = { ...state.artistFilters, who: "" };
    startHunt({ kind: "artist", name: input.value.trim() });
  };
  return [
    viewHead("artists", t("view.artists"), t("artists.description")),
    h("form", { class: "filters", onsubmit: submit },
      h("label", { class: "filter", for: "artist-name" }, h("span", { class: "filter-label" }, t("artists.label")), input),
      h("button", { class: "play-button", type: "submit" }, t("artists.search"))),
  ];
}

function releaseDate(date) {
  const [year, month, day] = (date || "").split("-").map(Number);
  if (!year) return "";
  if (!month) return String(year);
  const value = new Date(year, month - 1, day || 1);
  return day
    ? value.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit", year: "numeric" })
    : value.toLocaleDateString(LOCALE, { month: "2-digit", year: "numeric" });
}

function renderArtist(hunt, panel, list) {
  const filters = state.artistFilters;
  const signature = JSON.stringify(["artist", hunt.status, hunt.progress, hunt.message, hunt.releases.length, filters]);
  if (!panel.hidden && signature === state.huntSignature) return;
  state.huntSignature = signature;
  panel.hidden = false;
  if (hunt.candidates?.length) {
    renderCandidates(hunt, panel, list);
    return;
  }
  const artist = hunt.artist;
  const people = artist?.people || [];
  const running = hunt.status === "running";
  const percent = hunt.total ? Math.max(4, Math.round((hunt.progress / hunt.total) * 100)) : 4;
  const counts = RELEASE_TYPES
    .map((type) => [type, hunt.releases.filter((release) => release.type === type).length])
    .filter(([, count]) => count)
    .map(([type, count]) => t(`artists.count.${type}`, { count }));
  const choice = (id, label, options, key) => {
    const control = h("select", { class: "filter-control", id },
      options.map(([value, text]) => h("option", { value, selected: filters[key] === value }, text)));
    control.addEventListener("change", () => {
      state.artistFilters = { ...state.artistFilters, [key]: control.value };
      renderHunt();
    });
    return h("label", { class: "filter", for: id }, h("span", { class: "filter-label" }, label), control);
  };
  const chip = (id, label, note) => h("button", {
    class: "who-chip",
    type: "button",
    "aria-pressed": String(filters.who === id),
    onclick: () => { state.artistFilters = { ...state.artistFilters, who: id }; renderHunt(); },
  }, label, note && h("small", null, note));
  panel.replaceChildren(...[
    h("div", { class: "artist-head" },
      artist?.image && h("img", { class: "artist-photo", src: artist.image, alt: "" }),
      h("div", null,
        h("h2", { class: "hunt-title" }, hunt.label),
        h("p", { class: "meta" }, hunt.message),
        counts.length > 0 && h("p", { class: "meta" }, listFormat.format(counts)))),
    running && h("div", { class: "progress", "aria-hidden": "true" }, h("i", { style: `width: ${percent}%` })),
    h("div", { class: "actions" },
      artist && h("a", { class: "ghost-button", href: artist.uri }, t("artists.open_artist")),
      h("button", { class: "text-button", type: "button", onclick: () => startHunt(state.lastHunt) }, t("hunt.again.artist"))),
    people.length > 1 && h("div", { class: "who-chips", role: "group", "aria-label": t("artists.who_label") },
      chip("", t("artists.all")),
      people.map((person) => chip(person.spotify, person.name,
        person.role === "subgroup" ? t("artists.subgroup") : person.former ? t("artists.former") : null))),
    hunt.releases.length > 0 && h("div", { class: "filters artist-filters" },
      choice("release-type", t("artists.type_label"),
        [["", t("artists.type.all")], ...RELEASE_TYPES.map((type) => [type, t(`artists.type.${type}`)])], "type"),
      choice("release-order", t("artists.order_label"),
        ["new", "old"].map((order) => [order, t(`artists.order.${order}`)]), "order")),
  ].filter(Boolean));

  const shown = hunt.releases
    .filter((release) => !filters.type || release.type === filters.type)
    .filter((release) => !filters.who || release.who.some((person) => person.id === filters.who))
    .sort((a, b) => (filters.order === "old" ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)));
  if (!shown.length) {
    list.replaceChildren(hunt.releases.length ? h("li", { class: "tracks-empty" }, t("artists.empty_filter")) : "");
    return;
  }
  const main = people[0]?.spotify;
  list.replaceChildren(...shown.map((release, index) => {
    // Who from this artist is on it, when it isn't simply the artist's own release.
    const others = release.who.filter((person) => person.id !== main).map((person) => person.name);
    return h("li", { class: "track release", "data-uri": release.uri },
      h("button", {
        class: "track-button",
        type: "button",
        title: t("action.play_title", { title: release.name }),
        onclick: () => playRelease(release),
      },
        h("span", { class: "track-index" }, String(index + 1)),
        release.image ? h("img", { class: "track-art", src: release.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
        h("span", { class: "track-text" },
          h("span", { class: "track-title" }, release.name),
          h("span", { class: "track-sub" },
            h("span", { class: "release-type" }, t(`artists.badge.${release.type}`)),
            release.artists.join(", "),
            others.length > 0 && release.type !== "single" && release.type !== "album"
              ? ` ${t("artists.with", { names: listFormat.format(others) })}` : "")),
        h("span", { class: "release-date" }, releaseDate(release.date))),
      h("button", {
        class: "icon-button release-review",
        type: "button",
        title: t("reviews.review_album", { name: release.name }),
        "aria-label": t("reviews.review_album", { name: release.name }),
        onclick: () => openReview(release.id),
      }, icon(STAR_ICON)),
      h("a", { class: "text-button release-open", href: release.uri }, t("artists.open")));
  }));
  markPlaying();
}

/** Several artists share the name: photo, genres and latest release, so the person picks theirs. */
function renderCandidates(hunt, panel, list) {
  panel.replaceChildren(
    h("h2", { class: "hunt-title" }, hunt.label),
    h("p", { class: "meta" }, hunt.message));
  list.replaceChildren(h("li", { class: "candidates-row" }, h("ul", { class: "candidates" }, hunt.candidates.map((artist) =>
    h("li", null, h("button", {
      class: "candidate",
      type: "button",
      onclick: () => startHunt({ kind: "artist", name: artist.name, spotify: artist.id }),
    },
      artist.image
        ? h("img", { class: "candidate-photo", src: artist.image, alt: "" })
        : h("span", { class: "candidate-photo is-empty", "aria-hidden": "true" }, artist.name.charAt(0)),
      h("span", { class: "candidate-name" }, artist.name),
      artist.genres.length > 0 && h("span", { class: "candidate-meta" }, artist.genres.join(", ")),
      artist.latest && h("span", { class: "candidate-meta" },
        t("artists.latest", { name: artist.latest.name, year: artist.latest.year }))))))));
}

/** Own releases play from the start; on someone else's album, from the track where they appear. */
async function playRelease(release) {
  if (release.type === "feature" || release.type === "compilation") {
    try {
      const { uri } = await api("/api/artists/track", { album: release.id, artists: release.who.map((person) => person.id) });
      return command({ action: "play", context_uri: release.uri, offset_uri: uri });
    } catch {
      // not found on the album: play it from the start
    }
  }
  return play(release.uri);
}

function newsIntro() {
  const submit = (event) => {
    event.preventDefault();
    startHunt({ kind: "news", genre: state.filters.newsGenre, days: state.filters.days, ...sizeBody() });
  };
  return [
    viewHead("news", t("view.news"), t("news.description"), pauseNotice()),
    h("form", { class: "filters", onsubmit: submit },
      genreField("news-genre", "newsGenre", t("news.genre"), t("news.genre_placeholder"), true),
      ...sizeFilters(),
      choice("news-days", t("news.period"), PERIODS.map((days) => [days, t(`period.${days}`)]), "days"),
      h("button", { class: "play-button", type: "submit" }, t("news.search")),
      listenersHint(),
      genreList()),
  ];
}

// ---------- Home

/** The ready-made sensation for this time of day (Friday and Saturday evenings are for a party). */
function momentPreset(now = new Date()) {
  const presets = state.sensations?.sensations || [];
  const hour = now.getHours();
  let id = "wind-down";
  for (const [from, preset] of MOMENTS) if (hour >= from) id = preset;
  if (hour >= 18 && hour < 21 && [5, 6].includes(now.getDay())) id = "house-party";
  return presets.find((preset) => preset.id === id) || null;
}

function homeView() {
  const hour = new Date().getHours();
  const greeting = hour >= 5 && hour < 12 ? "home.morning" : hour >= 12 && hour < 18 ? "home.afternoon" : "home.evening";
  const section = (title, body, extra) => h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, title), extra), body);
  return [h("div", { class: "home" },
    h("h1", { class: "title home-title" }, t(greeting, { name: state.overview.me.name })),
    h("div", { class: "home-top" }, momentCard(), nowCard()),
    section(t("home.favorites"), h("div", null, favoriteCards(), offBarLine()),
      h("button", { class: "text-button", type: "button", "aria-haspopup": "dialog", onclick: (event) => openPinPicker(event.currentTarget) },
        t("pin.open"))),
    section(t("home.discover"), shortcutCards()),
    section(t("home.recent"), recentList()))];
}

/** "For right now": the sensation for this time of day; plays it at once if it's already a favorite. */
function momentCard() {
  const preset = momentPreset();
  if (!preset) return h("section", { class: "moment" }, h("p", { class: "meta" }, t("common.loading")));
  const made = state.overview.playlists.find((playlist) =>
    playlist.uri && playlist.favorite.recipe?.kind === "sense" && playlist.favorite.recipe.id === preset.id);
  const action = made
    ? h("button", { class: "play-button", type: "button", onclick: () => play(made.uri) },
      playIcon(), t("home.play_fav", { name: made.name }))
    : h("button", {
      class: "play-button",
      type: "button",
      disabled: !state.sensations.tempo_ready,
      onclick: () => go("sensations").then(() => startHunt({ kind: "sense", id: preset.id, ...sizeBody() })),
    }, t("home.build"));
  return h("section", { class: "moment", style: `--tone: ${preset.color}` },
    h("div", null,
      h("p", { class: "home-label" }, t("home.now_label")),
      h("h2", { class: "moment-name" }, preset.name),
      h("p", { class: "moment-text" }, preset.description),
      h("div", { class: "actions" }, action,
        h("button", { class: "text-button", type: "button", onclick: () => go("sensations") }, t("home.other_moment")))),
    h("img", { class: "moment-art", src: "/mascot-sensations.webp?v=2", alt: "", width: "150", height: "140" }));
}

function nowCard() {
  const player = state.player || {};
  const item = player.item;
  if (!item) {
    return h("section", { class: "now-card is-empty", id: "home-now" },
      h("div", { class: "now-card-text" },
        h("p", { class: "home-label" }, t("home.playing_label")),
        h("p", { class: "now-card-title" }, t("home.nothing")),
        h("p", { class: "meta" }, t(player.needs_scope ? "player.auth_text" : "home.nothing_hint"))));
  }
  return h("section", { class: "now-card", id: "home-now" },
    item.image ? h("img", { class: "now-card-art", src: item.image, alt: "" }) : h("span", { class: "now-card-art" }),
    h("div", { class: "now-card-text" },
      h("p", { class: "home-label" }, t("home.playing_label")),
      h("p", { class: "now-card-title" }, item.title),
      h("p", { class: "meta" }, item.subtitle),
      player.device?.name && h("p", { class: "meta" }, t("player.on_device", { name: player.device.name })),
      h("button", { class: "ghost-button is-small", type: "button", onclick: togglePlay },
        t(player.is_playing ? "player.pause" : "player.play"))));
}

/** What was taken off the bar, one click away from coming back. */
function offBarLine() {
  const hidden = state.overview.hidden || [];
  if (!hidden.length) return null;
  return h("p", { class: "home-hidden" }, t("home.hidden"),
    hidden.map((fav) => h("button", {
      class: "text-button",
      type: "button",
      title: t("home.bring_back", { name: fav.name }),
      onclick: () => putBack(fav, null),
    }, fav.name)));
}

function favoriteCards() {
  const playlists = state.overview.playlists;
  if (!playlists.length) {
    return h("div", { class: "home-empty" },
      h("img", { class: "home-empty-art", src: "/mascot-shelf.webp?v=2", alt: "", width: "90", height: "150" }),
      h("div", null,
        h("p", null, t("home.favorites_empty")),
        h("button", { class: "ghost-button is-small", type: "button", onclick: () => go("sensations") }, t("home.go_sense"))));
  }
  return h("ul", { class: "fav-grid" }, playlists.map((playlist) => {
    const fav = playlist.favorite;
    const meta = fav.kind === "pinned" ? t("pin.card")
      : `${capitalize(t(`every.${fav.every}`))}. ${fav.running ? t("home.updating") : t("fav.next_short", { when: whenText(fav.next_run) })}`;
    return h("li", { class: "fav-card", style: `--spine: ${colorOf(playlist)}` },
      h("button", { class: "fav-card-open", type: "button", onclick: () => go(playlist.key) },
        playlist.image
          ? h("img", { class: "fav-card-art", src: playlist.image, alt: "", loading: "lazy" })
          : h("span", { class: "fav-card-art is-empty", "aria-hidden": "true" }, playlist.name.charAt(0)),
        h("span", { class: "fav-card-name" }, playlist.name),
        h("span", { class: "fav-card-meta" }, meta)),
      playlist.uri && h("button", {
        class: "fav-card-play",
        type: "button",
        "aria-label": t("action.play_title", { title: playlist.name }),
        onclick: () => play(playlist.uri),
      }, playIcon()));
  }));
}

function shortcutCards() {
  const genre = (state.filters.newsGenre || "").trim();
  const card = (tone, name, text, label, onclick) => h("section", { class: "shortcut", style: `--tone: ${tone}` },
    h("h3", { class: "shortcut-name" }, name),
    h("p", { class: "shortcut-text" }, text),
    h("button", { class: "ghost-button is-small", type: "button", onclick }, label));
  const startIn = (view, body) => () => go(view).then(() => startHunt({ ...body, ...sizeBody() }));
  return h("div", { class: "shortcuts" },
    card("#F2C14E", t("discover.roulette"), t("home.roulette_text"), t("discover.spin"),
      startIn("discover", { kind: "roulette", ...rouletteGenre() })),
    card("#9DB4E6", t("discover.rabbit"), t("home.rabbit_text"), t("discover.enter"),
      startIn("discover", { kind: "rabbit", seed: "" })),
    genre
      ? card("#E3909E", t("home.news_title", { genre }), t(`period.${state.filters.days || "30"}`), t("news.search"),
        startIn("news", { kind: "news", genre, days: state.filters.days }))
      : card("#E3909E", t("view.news"), t("home.news_pick_text"), t("home.news_pick"), () => go("news")));
}

function recentList() {
  const finds = state.recent;
  if (!finds) return h("p", { class: "meta" }, t("common.loading"));
  if (!finds.length) return h("p", { class: "meta" }, t("home.recent_empty"));
  const shown = finds.slice(0, 8);
  return h("ol", { class: "tracks recent-list" }, shown.map((find, index) => h("li", { class: "track", "data-uri": find.uri },
    h("button", {
      class: "track-button",
      type: "button",
      title: t("action.play_title", { title: find.title }),
      onclick: () => playFinds(shown, find.uri),
    },
      h("span", { class: "track-index" }, String(index + 1)),
      find.image ? h("img", { class: "track-art", src: find.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
      h("span", { class: "track-text" },
        h("span", { class: "track-title" }, find.title),
        h("span", { class: "track-sub" }, find.subtitle)),
      h("span", { class: "recent-where" }, t("home.recent_in", { playlist: find.playlist })),
      h("span", { class: "track-time" }, clock(find.duration_ms || 0))))));
}

// ---------- The roulette's crate digger
// The mascot with a magnifying glass, going through a crate of records. Each song found goes
// onto the pile beside him, which starts empty and fills up; at the end he raises a record.

const PILE_SLOTS = 12;
const PILE_COLORS = ["#5CC8C0", "#D4A84B", "#E3909E", "#E6D5AA", "#9DB4E6", "#F06A4F"];
const SVG_NS = "http://www.w3.org/2000/svg";
const MASCOT = { hoodie: "#353C50", hoodieEdge: "#4A5470", pants: "#2A2F3B", hair: "#3B2A22", skin: "#E8B98F", green: "#45D483" };

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
  const sleeve = { stroke: MASCOT.hoodie, "stroke-width": 7, "stroke-linecap": "round" };
  const person = svg("g", { class: "person" },
    // cargo pants and sneakers
    svg("rect", { x: 41, y: 100, width: 9, height: 34, rx: 4, fill: MASCOT.pants }),
    svg("rect", { x: 53, y: 100, width: 9, height: 34, rx: 4, fill: MASCOT.pants }),
    svg("ellipse", { cx: 47, cy: 135, rx: 7, ry: 3.5, fill: "#EEE7D7" }),
    svg("ellipse", { cx: 59, cy: 135, rx: 7, ry: 3.5, fill: "#EEE7D7" }),
    // back arm, sweeping the records with the magnifying glass
    svg("g", { class: "arm-glass" },
      svg("line", { x1: 66, y1: 76, x2: 98, y2: 66, ...sleeve }),
      svg("line", { x1: 98, y1: 66, x2: 104, y2: 62, stroke: "#EEE7D7", "stroke-width": 3, "stroke-linecap": "round" }),
      svg("circle", { cx: 110, cy: 57, r: 8, fill: "rgba(157,180,230,.25)", stroke: "#EEE7D7", "stroke-width": 2.5 })),
    // hoodie leaning toward the crate; messy hair and green headphones
    svg("g", { class: "torso", transform: "rotate(22 50 102)" },
      svg("rect", { x: 37, y: 66, width: 27, height: 40, rx: 10, fill: MASCOT.hoodie, stroke: MASCOT.hoodieEdge, "stroke-width": 1 }),
      svg("circle", { cx: 51, cy: 84, r: 4, fill: MASCOT.green }),
      svg("g", { class: "head" },
        svg("circle", { cx: 51, cy: 54, r: 11, fill: MASCOT.skin }),
        svg("path", { d: "M39.5 54 Q39 41.5 51 41.5 Q63 41.5 62.5 52 Q59 47.5 54.5 49.5 Q51 46 47 49.5 Q43 48.5 39.5 54 Z", fill: MASCOT.hair }),
        svg("path", { d: "M40 54 A11.5 11.5 0 0 1 62 50", fill: "none", stroke: MASCOT.green, "stroke-width": 2.2 }),
        svg("circle", { cx: 44.5, cy: 56, r: 4, fill: "#1B1F27", stroke: MASCOT.green, "stroke-width": 1.6 }),
        svg("circle", { cx: 57.5, cy: 56, r: 1.5, fill: "#0E1525" }))),
    // front arm going through the records
    svg("g", { class: "arm-dig" },
      svg("line", { x1: 70, y1: 78, x2: 95, y2: 90, ...sleeve }),
      svg("circle", { cx: 96, cy: 91, r: 4, fill: MASCOT.skin })),
    // celebration: arm up holding the record he found
    svg("g", { class: "arm-cheer" },
      svg("line", { x1: 70, y1: 78, x2: 93, y2: 45, ...sleeve }),
      svg("rect", { x: 83, y: 20, width: 22, height: 22, rx: 2, fill: "#F2C14E" }),
      svg("circle", { cx: 94, cy: 31, r: 6, fill: "#0E1525" }),
      svg("circle", { cx: 93, cy: 45, r: 4, fill: MASCOT.skin }),
      svg("path", { d: "M111 20 l6 -4 M113 31 l7 0 M78 16 l-6 -4", stroke: MASCOT.green, "stroke-width": 2, "stroke-linecap": "round" })));
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

/** The mascot digs while the roulette draws; the pile grows with each song found. */
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
    const vars = { found: finds.length, total: roulette?.total || PILE_SLOTS };
    count.textContent = roulette ? t(roulette.status === "running" ? "digger.running" : "digger.done", vars) : "";
  }
}

async function startHunt(body) {
  if (!body) return;
  state.lastHunt = body;
  closePicker({ restoreFocus: false });
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
  if (hunt.kind === "artist") {
    renderArtist(hunt, panel, list);
    return;
  }
  const signature = JSON.stringify([
    hunt.status, hunt.progress, hunt.finds.length, hunt.message, state.added.size, state.openDetails.size,
    state.blocked.length, state.showBlocked,
  ]);
  if (!panel.hidden && signature === state.huntSignature) return;
  state.huntSignature = signature;
  if (hunt.color) setMood(hunt.color);

  const running = hunt.status === "running";
  const empty = !hunt.finds.length;
  const percent = hunt.total ? Math.max(4, Math.round((hunt.progress / hunt.total) * 100)) : 4;
  const picker = (mode) => (event) => openPicker(event.currentTarget, hunt.finds, mode);
  panel.hidden = false;
  const header = [
    h("h2", { class: "hunt-title" }, hunt.label),
    h("p", { class: "meta" }, hunt.message),
    running && h("div", { class: "progress", "aria-hidden": "true" }, h("i", { style: `width: ${percent}%` })),
    h("div", { class: "actions" },
      h("button", { class: "play-button", type: "button", disabled: empty, onclick: () => playFinds(hunt.finds) },
        playIcon(), t("hunt.play_all")),
      h("button", { class: "ghost-button", type: "button", disabled: empty, "aria-haspopup": "dialog", onclick: picker("new") },
        t("hunt.create")),
      h("button", { class: "ghost-button", type: "button", disabled: empty, "aria-haspopup": "dialog", onclick: picker("list") },
        t("hunt.add_all")),
      h("button", { class: "text-button", type: "button", onclick: () => startHunt(state.lastHunt || { kind: hunt.kind }) },
        t(`hunt.again.${hunt.kind}`)),
      state.blocked.length > 0 && h("button", {
        class: "text-button",
        type: "button",
        "aria-expanded": String(state.showBlocked),
        "aria-controls": "blocked-list",
        onclick: () => { state.showBlocked = !state.showBlocked; renderHunt(); },
      }, t("hunt.blocked", { count: state.blocked.length })),
    ),
    state.showBlocked && state.blocked.length > 0 && h("ul", { class: "blocked-list", id: "blocked-list" },
      state.blocked.map((artist) => h("li", null,
        h("span", null, artist),
        h("button", { class: "text-button", type: "button", onclick: () => setBlocked(artist, false) }, t("hunt.unblock"))))),
  ];
  panel.replaceChildren(...header.filter(Boolean));

  // Only songs that just arrived get the "falling" animation in the list.
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
    return t("find.bpm", { bpm: find.bpm, energy: Math.round((find.energy || 0) * 100) });
  }
  const parts = [find.reason];
  if (find.fans != null && !/fãs|fans/.test(find.reason || "")) parts.push(t("find.fans", { fans: fans(find.fans) }));
  return parts.filter(Boolean).join(" ");
}

/** "123 listeners on Last.fm", linked to the track's page there (Last.fm's terms ask for the link). */
function lastfmLine(info) {
  if (info.listeners == null) return h("span", null, t("find.no_listeners"));
  const text = t("find.listeners", { count: info.listeners, n: compactNumber.format(info.listeners) });
  return info.url ? h("a", { class: "text-button", href: info.url, target: "_blank", rel: "noopener" }, text)
    : h("span", null, text);
}

function findRow(find, finds, index, isNew) {
  const added = state.added.has(find.uri);
  const details = findDetails(find);
  const artist = (find.artists || [])[0];
  const open = state.openDetails.has(find.uri);
  const classes = ["track", "find", open && "is-open", isNew && "is-new"].filter(Boolean).join(" ");
  return h("li", { class: classes, "data-uri": find.uri },
    h("button", {
      class: "track-button",
      type: "button",
      title: t("action.play_title", { title: find.title }),
      onclick: () => playFinds(finds, find.uri),
    },
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
      "aria-label": t("find.details_of", { title: find.title }),
      title: t("find.why"),
      onclick: () => toggleDetails(find.uri),
    }, infoIcon()),
    h("button", {
      class: added ? "add-button is-added" : "add-button",
      type: "button",
      "aria-haspopup": "dialog",
      "aria-label": t("find.add_title", { title: find.title }),
      onclick: (event) => openPicker(event.currentTarget, [find], "list"),
    }, t(added ? "find.added" : "find.add")),
    open && h("div", { class: "find-details" },
      details && h("span", null, details),
      find.lastfm && lastfmLine(find.lastfm),
      artist && h("button", { class: "text-button", type: "button", onclick: () => setBlocked(artist, true) },
        t("find.block", { artist }))),
  );
}

async function setBlocked(artist, blocked) {
  try {
    const { message, artists } = await api("/api/blocked", { artist, blocked });
    state.blocked = artists;
    if (!artists.length) state.showBlocked = false;
    toast(message);
    // The server already took the artist out of the result; fetch the updated version.
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
  const el = svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  el.append(svg("circle", { cx: 12, cy: 12, r: 9 }), svg("path", { d: "M12 11v5M12 7.5v.5" }));
  return el;
}

function fans(count) {
  if (count == null) return t("fans.few");
  return t("fans.count", { count, n: compactNumber.format(count) });
}

function chainRow(chain) {
  const last = chain.path[chain.path.length - 1];
  return h("li", { class: "chain" },
    h("ol", { class: "chain-path", "aria-label": t("chain.label") },
      chain.path.map((artist) => h("li", null, artist.name))),
    h("p", { class: "meta", title: t("chain.fans_hint") }, `${last.name}: ${fans(last.fans)}.`));
}

// ---------- Keeping what you liked: a new playlist, or adding to one you already have

function defaultPlaylistName(hunt) {
  if (hunt.kind === "sense") return t("save.default_sense", { name: hunt.label });
  const day = new Date().toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" });
  return t("save.default_name", { label: hunt.label, day });
}

/** Small panel next to the button (a bottom sheet on phones) to pick where the songs go. */
function openPicker(anchor, finds, mode) {
  closePicker({ restoreFocus: false });
  const hunt = huntHere();
  state.picker = {
    anchor,
    mode,
    from: mode,
    uris: finds.map((find) => find.uri),
    label: finds.length === 1 ? finds[0].title : t("count.songs", { count: finds.length }),
    name: finds.length > 1 && hunt ? defaultPlaylistName(hunt) : "",
    // Only the whole discovery can update itself: the recipe rebuilds all of it.
    canRepeat: Boolean(hunt) && finds.length > 1 && finds.length === hunt.finds.length,
    every: "weekly",
    busy: false,
    conflict: null,
    rect: anchor.getBoundingClientRect(),
  };
  document.body.append(h("div", { class: "picker", id: "picker", role: "dialog", "aria-labelledby": "picker-title" }));
  if (mode === "list" && !state.myPlaylists?.playlists && !state.myPlaylists?.loading) loadMyPlaylists();
  renderPicker();
  placePicker();
  focusPicker();
  document.addEventListener("pointerdown", pickerOutside, true);
}

function closePicker({ restoreFocus = true } = {}) {
  const picker = state.picker;
  if (!picker) return;
  $("#picker")?.remove();
  document.removeEventListener("pointerdown", pickerOutside, true);
  state.picker = null;
  if (!restoreFocus) return;
  // The button may have been redrawn meanwhile: look for the same song's button.
  const row = picker.uris.length === 1 && document.querySelector(`.find[data-uri="${CSS.escape(picker.uris[0])}"] .add-button`);
  (picker.anchor.isConnected ? picker.anchor : row)?.focus();
}

function pickerOutside(event) {
  if (!state.picker || event.target.closest("#picker") || state.picker.anchor.contains(event.target)) return;
  closePicker({ restoreFocus: false });
}

function focusPicker() {
  $("#picker")?.querySelector("input, .picker-option, .play-button")?.focus();
}

function switchPicker(changes) {
  Object.assign(state.picker, changes);
  renderPicker();
  placePicker();
  focusPicker();
}

async function loadMyPlaylists() {
  state.myPlaylists = { loading: true };
  try {
    state.myPlaylists = await api("/api/my-playlists");
  } catch (error) {
    state.myPlaylists = { error: error.message };
  }
  renderPicker();
  placePicker();
}

function renderPicker() {
  const panel = $("#picker");
  const picker = state.picker;
  if (!panel || !picker) return;
  const title = t({ list: "picker.title_add", new: "picker.title_new", pin: "pin.title" }[picker.mode]);
  const body = picker.conflict ? conflictView(picker)
    : picker.mode === "new" ? newPlaylistForm(picker)
      : picker.mode === "pin" ? pinChoices(picker)
        : playlistChoices(picker);
  panel.classList.toggle("is-busy", picker.busy);
  panel.replaceChildren(
    h("header", { class: "picker-head" },
      h("h2", { class: "picker-title", id: "picker-title" }, title),
      h("p", { class: "picker-sub" }, picker.label),
      h("button", { class: "picker-close", type: "button", "aria-label": t("common.close"), onclick: () => closePicker() },
        icon(CLOSE_ICON))),
    ...body);
}

/** "+" on the bar: one of your playlists as a shortcut, or a curated one back from outside the bar. */
async function openPinPicker(anchor) {
  closePicker({ restoreFocus: false });
  state.picker = {
    anchor, mode: "pin", from: "pin", uris: [], label: t("pin.sub"), busy: false, conflict: null,
    rect: anchor.getBoundingClientRect(), extras: null,
  };
  document.body.append(h("div", { class: "picker", id: "picker", role: "dialog", "aria-labelledby": "picker-title" }));
  renderPicker();
  placePicker();
  document.addEventListener("pointerdown", pickerOutside, true);
  const picker = state.picker;
  try {
    picker.extras = await api("/api/favorites/extras");
  } catch (error) {
    picker.extras = { error: error.message };
  }
  if (state.picker !== picker) return;
  renderPicker();
  placePicker();
  focusPicker();
}

function pinChoices(picker) {
  const extras = picker.extras;
  if (!extras) return [h("p", { class: "picker-note" }, t("common.loading"))];
  if (extras.error) return [h("p", { class: "picker-note is-error" }, extras.error)];
  const option = (item, sub, onclick) => h("li", null,
    h("button", { class: "picker-option", type: "button", disabled: picker.busy, onclick },
      item.image
        ? h("img", { class: "picker-art", src: item.image, alt: "", loading: "lazy" })
        : h("span", { class: "picker-art is-empty", "aria-hidden": "true" }, item.name.charAt(0)),
      h("span", { class: "picker-option-text" },
        h("span", { class: "picker-option-name" }, item.name),
        h("span", { class: "picker-option-sub" }, sub))));
  const rows = [
    ...extras.hidden.map((item) => option(item, t(item.kind === "curated" ? "pin.curated" : "pin.hidden"),
      () => pinAction(`/api/favorites/${item.fav}/show`, {}))),
    ...extras.playlists.map((item) => option(item, t("count.tracks", { count: item.total }),
      () => pinAction("/api/favorites/pin", { playlist: item.id }))),
  ];
  return [rows.length ? h("ul", { class: "picker-list" }, rows) : h("p", { class: "picker-note" }, t("pin.none"))];
}

async function pinAction(path, body) {
  const picker = state.picker;
  if (!picker || picker.busy) return;
  picker.busy = true;
  renderPicker();
  try {
    toast((await api(path, body)).message);
    closePicker();
    await loadOverview();
  } catch (error) {
    picker.busy = false;
    renderPicker();
    toast(error.message, true);
  }
}

function playlistChoices(picker) {
  const mine = state.myPlaylists || {};
  const option = (target, name, sub, art) => h("li", null,
    h("button", { class: "picker-option", type: "button", disabled: picker.busy, onclick: () => addToPlaylist(target) },
      art,
      h("span", { class: "picker-option-text" },
        h("span", { class: "picker-option-name" }, name),
        h("span", { class: "picker-option-sub" }, sub))));
  const rows = [option("finds", mine.finds || t("picker.finds"), t("picker.finds_sub"),
    h("img", { class: "picker-art is-round", src: "/mascot-head.webp?v=2", alt: "" }))];
  if (mine.loading) rows.push(h("li", { class: "picker-note" }, t("picker.loading")));
  else if (mine.error) rows.push(h("li", { class: "picker-note is-error" }, mine.error));
  for (const playlist of mine.playlists || []) {
    const art = playlist.image
      ? h("img", { class: "picker-art", src: playlist.image, alt: "", loading: "lazy" })
      : h("span", { class: "picker-art is-empty", "aria-hidden": "true" }, playlist.name.charAt(0));
    rows.push(option(playlist.id, playlist.name, t("count.tracks", { count: playlist.total }), art));
  }
  return [
    h("ul", { class: "picker-list" }, rows),
    h("button", { class: "picker-new", type: "button", disabled: picker.busy, onclick: () => switchPicker({ mode: "new" }) },
      t("picker.new")),
  ];
}

function newPlaylistForm(picker) {
  const input = h("input", {
    class: "picker-input",
    id: "picker-name",
    type: "text",
    maxlength: "100",
    autocomplete: "off",
    required: true,
    placeholder: t("picker.name_placeholder"),
  });
  input.value = picker.name;
  input.addEventListener("input", () => { picker.name = input.value; });
  const submit = (event) => {
    event.preventDefault();
    createPlaylist(false);
  };
  const every = picker.canRepeat && h("select", { class: "picker-input", id: "picker-every" },
    [["", t("picker.every_never")], ...EVERY.map((value) => [value, capitalize(t(`every.${value}`))])]
      .map(([value, label]) => h("option", { value, selected: value === picker.every }, label)));
  every?.addEventListener("change", () => { picker.every = every.value; });
  return [h("form", { class: "picker-form", onsubmit: submit },
    h("label", { class: "filter-label", for: "picker-name" }, t("picker.name_label")),
    input,
    every && h("label", { class: "filter-label", for: "picker-every" }, t("picker.every_label")),
    every,
    every && h("p", { class: "picker-hint" }, t("picker.every_hint")),
    h("div", { class: "picker-actions" },
      h("button", { class: "play-button is-small", type: "submit", disabled: picker.busy }, t("picker.create")),
      picker.from === "list"
        ? h("button", { class: "text-button", type: "button", onclick: () => switchPicker({ mode: "list" }) }, t("common.back"))
        : h("button", { class: "text-button", type: "button", onclick: () => closePicker() }, t("common.cancel"))))];
}

function conflictView(picker) {
  return [h("div", { class: "picker-form" },
    h("p", { class: "picker-conflict" }, picker.conflict, " ", t("picker.replace_question")),
    h("div", { class: "picker-actions" },
      h("button", { class: "play-button is-small is-danger", type: "button", disabled: picker.busy, onclick: () => createPlaylist(true) },
        t("picker.replace")),
      h("button", { class: "text-button", type: "button", onclick: () => switchPicker({ conflict: null }) }, t("picker.rename"))))];
}

async function addToPlaylist(target) {
  const picker = state.picker;
  if (!picker || picker.busy) return;
  picker.busy = true;
  renderPicker();
  try {
    const { message } = await api("/api/playlists/add", { playlist: target, uris: picker.uris });
    markAdded(picker.uris);
    toast(message);
    closePicker();
  } catch (error) {
    picker.busy = false;
    renderPicker();
    toast(error.message, true);
  }
}

async function createPlaylist(replace) {
  const picker = state.picker;
  if (!picker || picker.busy) return;
  const name = picker.name.trim();
  if (!name) {
    $("#picker-name")?.focus();
    return;
  }
  picker.busy = true;
  renderPicker();
  try {
    const every = picker.canRepeat ? picker.every || null : null;
    const { message, favorite } = await api("/api/playlists/new", { name, uris: picker.uris, replace, every });
    markAdded(picker.uris);
    state.myPlaylists = null;
    toast(message);
    closePicker();
    if (favorite) loadOverview();  // it's on the bar now
  } catch (error) {
    picker.busy = false;
    if (error.data?.exists) {
      switchPicker({ conflict: error.message });
      return;
    }
    renderPicker();
    toast(error.message, true);
  }
}

function markAdded(uris) {
  uris.forEach((uri) => state.added.add(uri));
  state.huntSignature = "";
  renderHunt();
}

/** Next to the button, below it, or above it when there's no room before the player. */
function placePicker() {
  const panel = $("#picker");
  const picker = state.picker;
  if (!panel || !picker) return;
  const sheet = window.matchMedia("(max-width: 760px)").matches;
  panel.classList.toggle("is-sheet", sheet);
  if (sheet) {
    panel.style.left = panel.style.top = "";
    return;
  }
  if (picker.anchor.isConnected) picker.rect = picker.anchor.getBoundingClientRect();
  const { rect } = picker;
  const bottom = window.innerHeight - $("#player").offsetHeight - 12;
  let top = rect.bottom + 8;
  if (top + panel.offsetHeight > bottom) top = Math.max(12, rect.top - 8 - panel.offsetHeight);
  // Starts at the button's left edge; buttons near the right edge (each song's "Add") get it aligned to their right.
  const fits = rect.left + panel.offsetWidth <= window.innerWidth - 12;
  const left = Math.max(12, fits ? rect.left : rect.right - panel.offsetWidth);
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}

// ---------- How it works: a short tour with the mascot

const TOUR = [
  { key: "welcome", art: "hero", focus: "50% 50%" },
  { key: "shelf", art: "shelf", focus: "50% 50%" },
  { key: "sense", art: "sensations", focus: "50% 50%" },
  { key: "discover", art: "roulette", focus: "50% 50%" },
  { key: "news", art: "news", focus: "50% 50%" },
  { key: "keep", art: "keep", focus: "50% 50%" },
];

function openTour(step = 0) {
  let dialog = $("#tour");
  if (!dialog) {
    dialog = h("dialog", { class: "tour", id: "tour", "aria-labelledby": "tour-title" });
    dialog.addEventListener("close", () => memory.set("tour-seen", "1"));
    // A click on the dimmed backdrop lands on the dialog itself.
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    document.body.append(dialog);
  }
  closePicker({ restoreFocus: false });
  showTourStep(step);
  if (!dialog.open) dialog.showModal();
  dialog.querySelector(".tour-next")?.focus();
}

function showTourStep(step) {
  const dialog = $("#tour");
  state.tourStep = step;
  const { key, art, focus } = TOUR[step];
  const last = step === TOUR.length - 1;
  const goTo = (next) => {
    showTourStep(next);
    dialog.querySelector(".tour-next")?.focus();
  };
  dialog.replaceChildren(
    h("img", { class: "tour-art", src: `/mascot-${art}.webp?v=2`, alt: "", style: `object-position: ${focus}` }),
    h("div", { class: "tour-body" },
      h("p", { class: "tour-step" }, t("tour.step", { n: step + 1, total: TOUR.length })),
      h("h2", { class: "tour-title", id: "tour-title" }, t(`tour.${key}.title`, { name: state.overview?.me?.name || "" })),
      h("p", { class: "tour-text" }, t(`tour.${key}.text`)),
      h("ol", { class: "tour-dots", "aria-hidden": "true" },
        TOUR.map((_, index) => h("li", { class: index === step ? "is-current" : null }))),
      h("div", { class: "tour-actions" },
        step > 0 && h("button", { class: "text-button", type: "button", onclick: () => goTo(step - 1) }, t("common.back")),
        h("button", { class: "play-button tour-next", type: "button", onclick: () => (last ? dialog.close() : goTo(step + 1)) },
          t(last ? "tour.start" : "tour.next")))),
    h("button", { class: "tour-close", type: "button", "aria-label": t("tour.skip"), title: t("tour.skip"), onclick: () => dialog.close() },
      icon(CLOSE_ICON)),
  );
}

// ---------- Curated playlist updates (setup / preview)

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
    toast(t("job.failed"), true);
    return;
  }
  if (job.dry_run) {
    toast(t("job.preview_ready"));
    return;
  }
  const outcome = job.lines.filter((line) => /gravada no Spotify|saved to Spotify|ficou vazia|came out empty/.test(line)).pop();
  toast(outcome ? outcome.trim() : t("job.done"));
  await Promise.all([loadOverview(), loadDetail()]);
}

function renderConsole(job) {
  const panel = $("#console");
  panel.hidden = false;
  panel.dataset.status = job.status;
  const name = job.name;
  $("#console-title").textContent = {
    running: `${job.label}…`,
    done: t(job.dry_run ? "job.title_preview_done" : "job.title_done", { name }),
    error: t("job.title_error", { name }),
  }[job.status];
  const box = $("#console-lines");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...job.lines.map((line) => h("p", { class: lineClass(line) }, line.trim())));
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function lineClass(line) {
  if (/não encontrado|not found/.test(line)) return "line is-warning";
  if (line.startsWith("   ")) return "line is-item";
  if (/: \d+ (itens|items)$/.test(line)) return "line is-heading";
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

/** Polls the player without waste: 5 s while playing, 15 s when stopped, nothing with the tab hidden. */
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
  $("#btn-play").setAttribute("aria-label", t(player.is_playing ? "player.pause" : "player.play"));
  $("#now-title").textContent = item ? item.title : t("player.nothing");
  $("#now-sub").textContent = item ? item.subtitle : (player.error || t("player.hint"));
  const art = $("#now-art");
  if (item?.image) {
    if (art.getAttribute("src") !== item.image) art.src = item.image;
    art.hidden = false;
  } else {
    art.hidden = true;
  }
  $("#btn-shuffle").setAttribute("aria-pressed", String(Boolean(player.shuffle)));
  const like = $("#btn-like");
  const likeLabel = t(player.liked ? "player.unlike" : "player.like");
  like.hidden = !item || !/^spotify:(track|episode):/.test(item.uri);
  like.setAttribute("aria-pressed", String(Boolean(player.liked)));
  like.setAttribute("aria-label", likeLabel);
  like.title = likeLabel;
  $("#btn-review").hidden = !item?.album_id;
  const repeat = $("#btn-repeat");
  const mode = player.repeat || "off";
  repeat.dataset.mode = mode;
  repeat.setAttribute("aria-pressed", String(mode !== "off"));
  repeat.setAttribute("aria-label", t(`player.repeat_${mode}`));
  repeat.title = t(`player.repeat_${mode}`);
  const volume = $("#volume");
  volume.disabled = player.device?.volume == null;
  if (!volume.disabled && document.activeElement !== volume) {
    volume.value = player.device.volume;
    paintRange(volume);
  }
  $("#device").textContent = player.device?.name ? t("player.on_device", { name: player.device.name }) : "";
  $("#home-now")?.replaceWith(nowCard());
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
  // The track ended: fetch the next one without waiting for the normal cycle.
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
    toast(t("player.authorize_first"), true);
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

/** Plays a loose list of tracks (a sensation or discovery result) without creating a playlist. */
function playFinds(finds, offsetUri) {
  return command({ action: "play", uris: finds.map((find) => find.uri), offset_uri: offsetUri });
}

/** The heart: saves the song (or episode) playing in the person's Spotify library, or takes it out. */
async function toggleLike() {
  const player = state.player;
  const item = player?.item;
  if (!item) return;
  if (!player.library_ready) {
    toast(t("player.like_authorize"), false, { label: t("player.auth_button"), href: "/login" });
    return;
  }
  const liked = !player.liked;
  player.liked = liked;
  renderPlayer();
  try {
    toast((await api("/api/player", { action: "like", uri: item.uri, value: liked })).message);
  } catch (error) {
    if (state.player?.item?.uri === item.uri) state.player.liked = !liked;
    renderPlayer();
    toast(error.message, true);
  }
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
  $("#btn-like").addEventListener("click", toggleLike);
  $("#btn-review").addEventListener("click", () => state.player?.item?.album_id && openReview(state.player.item.album_id));
  $("#btn-prev").addEventListener("click", () => command({ action: "previous" }));
  $("#btn-next").addEventListener("click", () => command({ action: "next" }));
  $("#btn-shuffle").addEventListener("click", () => {
    const enabled = !state.player?.shuffle;
    command({ action: "shuffle", value: enabled }, (p) => { p.shuffle = enabled; });
  });
  // Repeat goes around like in Spotify: off -> the whole list -> this track -> off.
  $("#btn-repeat").addEventListener("click", () => {
    const next = { off: "context", context: "track", track: "off" }[state.player?.repeat || "off"];
    command({ action: "repeat", value: next }, (p) => { p.repeat = next; });
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

// ---------- Start

function bindGlobal() {
  $("#console-close").addEventListener("click", () => { $("#console").hidden = true; });
  $(".brand").addEventListener("click", (event) => {
    event.preventDefault();
    go("home");
  });
  $("#adder-input").addEventListener("input", (event) => {
    clearTimeout(state.searchTimer);
    const query = event.target.value;
    state.searchTimer = setTimeout(() => search(query), 300);
  });
  // The picker follows its button when the page scrolls or the window changes size.
  $("#stage").addEventListener("scroll", placePicker, { passive: true });
  window.addEventListener("scroll", placePicker, { passive: true });
  window.addEventListener("resize", placePicker);

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "Escape") {
      if (state.picker) closePicker();
      else $("#console").hidden = true;
      return;
    }
    const typing = event.target.closest?.("input, textarea, select");
    if (typing || state.picker || $("#tour")?.open || document.body.classList.contains("is-gated")) return;
    if (event.code === "Space") {
      if (event.target.closest?.("button, a")) return;  // space presses the focused button
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

  // Bookmarks and the back button only change the #; replaceState in select() doesn't fire this event.
  window.addEventListener("hashchange", () => {
    const key = decodeURIComponent(location.hash.slice(1));
    const showing = state.view === "playlist" ? state.selected : state.view;
    if (state.overview && key && (VIEW_ALIASES[key] || key) !== showing) go(key);
  });
}

async function init() {
  translatePage();
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
  // pollHunt resumes a discovery that was running when the page was reloaded.
  await Promise.all([go(state.initialKey), refreshPlayer(), pollHunt()]);
  schedulePlayerPoll();
  setInterval(tick, 500);
  setInterval(pollMedals, 120_000);
  if (!memory.get("tour-seen")) openTour(0);
}

init();
