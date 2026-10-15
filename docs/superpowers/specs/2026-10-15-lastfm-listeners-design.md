# Last.fm listeners filter: design

Date: 2026-10-15. Approved section by section in conversation with the owner; this file is the written record.

Part 1 of 2. Part 2 (achievements: monthly titles and personal medals among friends) gets its own spec and
reuses this client for the "Rare song" medal.

## Why

The owner wants discoveries narrowed down to really niche songs. What exists today is the artist's size in
Deezer fans (minimum and maximum). Spotify's monthly listeners are not in the Web API, and getting them means
scraping Spotify's internal API: against Spotify's terms, it breaks without notice, and a block would hit the
same server and Client ID the whole room depends on. Rejected.

Last.fm counts **people who listened to each track** (Last.fm users who scrobbled it), through a documented
API with a free key. That is the measure this spec adds.

## Decisions

- The key is optional, one per installation (`LASTFM_API_KEY` in `.env`). Without it nothing about Last.fm shows.
- One filter, "Song listeners: at most", in every discovery that has the fans filter: Sensations, Discover
  (roulette and rabbit hole) and New releases. Both filters apply together.
- A track Last.fm doesn't know **passes** the filter and its card says "no record on Last.fm". Very niche songs
  often have no record; requiring one would empty the small caps.
- The filter is never skipped silently: when Last.fm can't answer, the discovery stops with a message.
- Every lookup happens before searching the track on Spotify, so a rejected track never costs a Spotify request.
- Last.fm is credited wherever its numbers show (its terms require it). Deezer is still never mentioned.

## Configuration

- `LASTFM_API_KEY=` in `.env` and `.env.example`, with a comment pointing to https://www.last.fm/api/account/create.
- `config.Settings` gains `lastfm_key: str = ""`, read by `load_settings()`.
- `/api/overview` gains `"lastfm": bool`, so the panel knows whether to show the filter.
- Without a key, a request with `max_listeners` is refused (400, `t("lastfm.no_key")`). A favorite whose recipe has
  `max_listeners` fails its update with that message (status `error`, songs kept) instead of ignoring the filter.

## Client: `spotify_assistant/lastfm.py`

Standard library only, in the style of `deezer.py`.

```python
@dataclass(frozen=True)
class Listeners:
    count: int | None  # None: Last.fm has no record of the track
    url: str | None    # the track's Last.fm page

class LastFmError(RuntimeError):
    kind: str  # "key" | "limit" | "down"

class LastFm:
    def __init__(self, key: str, opener=urllib.request.urlopen) -> None: ...
    def track(self, artist: str, title: str) -> Listeners: ...
```

- Request: `GET https://ws.audioscrobbler.com/2.0/?method=track.getInfo&artist=…&track=…&autocorrect=1&format=json&api_key=…`,
  10 s timeout, a User-Agent naming the project.
- The title goes through `curation.base_title()` ("So What - Remastered 2005 (Live)" becomes "So What"); the artist is the
  first credited one.
- `listeners` comes as a string in the JSON and is turned into an int.
- Last.fm error codes: 6 (not found) returns `Listeners(None, None)`; 10 and 26 (invalid or suspended key) raise
  `kind="key"`; 29 (rate limit) raises `kind="limit"` and pauses the client for 10 minutes (every call during the
  pause raises `limit` right away, without a request); 8, 11, 16, HTTP 5xx, timeouts and network errors raise
  `kind="down"`.
- Pace: at most 4 requests per second for the whole panel (one lock and a minimum interval of 0.25 s, like the Deezer
  client's brake). Last.fm no longer publishes a number; the old guidance was 5 per second.

## Cache: `data/lastfm-cache.json`

- `config.LASTFM_CACHE_FILE`. Key: `curation.normalize(f"{artist}|{base_title}")`. Value: `{"n": int | null, "url": str | null, "at": epoch seconds}`.
- An entry is fresh for 30 days (listener counts grow); "no record" entries are kept and expire the same way.
- At most 100,000 entries (about 15 MB; Last.fm's terms cap stored data at 100 MB). Past that, the oldest are dropped.
- Loaded lazily, saved only when something changed, at the end of each discovery and each favorite update (like
  `TempoCache` and `MatchCache`).
- `discovery.listener_counts`: the cached lookup in front of the client, the counterpart of `fan_counts`. The
  dashboard builds the client from the settings; tests swap in a fake.

## The filter in discoveries

```python
@dataclass(frozen=True)
class ListenerCap:
    max: int | None = None

    @property
    def active(self) -> bool: ...

    def check(self, artist: str, title: str) -> Listeners | None:
        """The track's listeners when it fits (a missing record fits); None when it's over the cap."""

NO_CAP = ListenerCap()
```

- Request body: `max_listeners` (empty means no cap), validated like the fans (`err.listeners_invalid` for anything
  that isn't a whole number ≥ 0). The recipe stores it, so self-updating favorites keep the cap.
- `Find` gains `lastfm: dict | None = None`: `{"listeners": int | None, "url": str | None}` when the track was checked.
- **Roulette:** in `world_genre_pick`, each candidate is checked before `to_spotify`. In `obscure_album_pick`, the
  drawn track is checked. With a listener cap of 1,000 or less (`TIGHT_CAP`), the roulette uses genre playlists only,
  as it already does for small fan caps.
- **Rabbit hole:** hops still follow fans. `artist_picks` reads the artist's top 10 tracks instead of 5 when the cap is
  active and keeps those under it; an artist with none contributes nothing. At most about 160 lookups per run.
- **New releases:** each release's focus track is checked before `to_spotify`.
- **Sensations:** after the fans filter, `within_listeners()` checks candidates in batches until it has 72 within the
  cap (48 for the consensus mode) or has looked at 240 candidates, before any BPM is measured. Progress:
  `t("sense.checking_listeners", count=…)`. The first run can take about a minute longer; the cache speeds up later ones.
- **Errors:** `LastFmError` stops the discovery. `_run_hunt` and the favorite update (`_refresh`) catch it next to
  `SpotifyError`/`DeezerError` and show `t("lastfm.key")`, `t("lastfm.limit")` or `t("lastfm.down")`; the log records it.

## Panel

- `LISTENERS_MAX = ["", "50", "100", "500", "1000", "10000"]` and a `choice("max-listeners", …)` next to the fans
  filters wherever `sizeFilters()` is used, only when `state.overview.lastfm`. Saved in `state.filters.listeners`;
  `sizeBody()` sends `max_listeners`.
- Hint under the filters: "Listeners counted on Last.fm." (text credit with a link to last.fm; no Last.fm logo, since
  logos need Last.fm's written approval).
- Card details: "123 listeners on Last.fm" linked to the track's Last.fm page, or "no record on Last.fm"; only for
  finds that were checked.
- Every text through `t()`, in both languages (`i18n.py` and `static/i18n.js`).

## Docs

- README (en and pt-BR): a "Last.fm (optional)" section: create the key, put it in `.env`, what the filter does, why
  Last.fm shows in the panel.
- CLAUDE.md: `lastfm.py` in the map; rule "Last.fm is credited where its numbers show; Deezer never".

## Testing

Fakes only; nothing calls Last.fm or Spotify for real.

- Client, with a fake opener: reads listeners and url; "not found" becomes `Listeners(None, None)`; codes 10/26, 29
  and 8/11/16/HTTP 5xx/timeouts raise the right kind; after 29 no request goes out for 10 minutes; requests are at
  least 0.25 s apart.
- Cache: fresh for 30 days, then asked again; "no record" is cached; past 100,000 entries the oldest go.
- Each discovery with a fake Last.fm: finds stay within the cap; a track with no record passes and carries
  `lastfm.listeners = None`; rejected tracks never reach `sp.search`; a `LastFmError` ends the hunt as `error` with the
  right message; the roulette skips barely-played albums with a cap of 1,000 or less.
- Server: `max_listeners` validation; refused without a key; the recipe keeps it; a favorite with the cap and no key
  fails with the message and keeps its songs.
- i18n parity and used keys (existing tests).
- Screen: the fake panel (temporary data, fake Spotify) in headless Chrome at phone and desktop sizes, filter shown
  with `lastfm: true` and hidden with `false`, console clean.

## Rollout

1. Push and update the server (`install-linux.sh`).
2. The owner creates the key and adds `LASTFM_API_KEY` to `~/sala-de-escuta/.env` on the server (or hands it over to
   be added through SSH), then restarts the service.
3. One real check: a single roulette spin with a cap. No loops.

## Out of scope

- Achievements (part 2).
- YouTube views: finding a song's video costs a search, and the free quota allows about 100 searches a day.
- Last.fm artist listeners and tags.
- Spotify monthly listeners (not available; scraping rejected).
