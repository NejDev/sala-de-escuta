# Sala de escuta

Spotify listening room: a panel that runs on the owner's PC (Windows), shared with up to 4 friends.
Sensations (songs at a measured BPM), Discover (roulette, rabbit hole), New releases, and favorites
that rebuild themselves. Open source (MIT): each person self-hosts, because Spotify's Development
Mode caps an app at 5 users. Open work is in `TODO.md`.

## Working with the owner

- Talk to the user in Brazilian Portuguese. Code, comments, docs and commit messages are in English.
- The panel is bilingual (pt/en). Every text a person sees goes through `t()`.

## Commands

```powershell
python -m unittest discover -s tests       # all tests (fakes only; never hits Spotify)
python -m spotify_assistant ui             # the panel at http://127.0.0.1:8888
python -m spotify_assistant refresh        # rebuild favorites that are due (the panel does it by itself)
```

On the owner's PC the panel runs hidden as the scheduled task `Sala de escuta - painel`
(`scripts/start-with-windows.ps1`). After Python changes, restart it:
`Stop-ScheduledTask -TaskName 'Sala de escuta - painel'; Start-ScheduledTask -TaskName 'Sala de escuta - painel'`.
Static files are read from disk on each request (images are cached by browsers for 7 days).

## Map

- `dashboard.py`: HTTP server, routes, per-person state (`Profile`), discoveries, favorites and the scheduler thread.
- `discovery.py`: Sensations, roulette, rabbit hole, new releases; Deezer → Spotify matching by ISRC.
- `artists.py` / `musicbrainz.py`: the Artists search (band members and their Spotify profiles from MusicBrainz).
- `social.py`: Friends (opt-in): recently played history, affinity, matches; who may use it (data/room.json).
  Never expose a non-member's data, and never what a member played alone (only matches show songs).
- `reviews.py`: album reviews (`data/users/<id>/reviews.json`); private ones never reach anyone else.
- `favorites.py`: `data/users/<id>/favorites.json` (curated, discovery with recipe + frequency, or pinned) and `recent.json`.
- `api.py`: Spotify client with a request gate and persisted pauses (`data/spotify-pauses.json`).
- `i18n.py`: server messages; `static/i18n.js`: browser texts (a JSON object after `const STRINGS =`).
- `playlists.py` / `curation.py`: the owner's curated playlists from `playlists.json`.
- `static/app.js`: the whole front end (no build step, no framework).

## Rules

- Python 3.12 standard library only (`miniaudio` is the one optional dependency). Ask before adding packages.
- New text: add the key to **both** languages in `i18n.py` and/or `static/i18n.js` (keep it valid JSON).
  `tests/test_i18n.py` checks parity, placeholders and that used keys exist; keys built at runtime
  (template strings) must be listed in that test.
- Never mention Deezer in the UI. Never add Spotify logos to the app's branding.
- Keep the religious-content filter (`RELIGIOUS_WORDS`) and per-person blocked artists working everywhere.
- Each person's data stays private: friends never see the owner's curation or each other's playlists.
- Spotify rate limits are serious: a burst of searches once paused search for ~20 hours, and one big band
  in Artists (~36 requests in 9 s) paused `/artists` for ~23 hours. Artists still reads everything (every
  old release and feature), but `/artists` calls go 2 s apart and each list is saved page by page in
  `data/artists-cache.json`: a pause resumes where it stopped, and later searches only read what's new.
  Don't run real discoveries in loops while debugging; use the fakes in `tests/` and mocked data in the browser.
- Never commit `.env`, `data/` or `playlists.json` (the repo ships `playlists.example.json`). Before a
  commit, check the staged diff for the Client ID, tokens, the Tailscale address and the owner's Spotify id.
- Commits use the GitHub noreply e-mail already set in the local git config.

## Checking the UI

Headless Chrome through the DevTools Protocol (Node script, not in the repo): emulate desktop and
phone sizes, set the `sala` session cookie and `localStorage` (`lang`, `tour-seen`), take screenshots,
and collect console errors. Create the session with `accounts.Sessions().create(config.owner_id())`
**before** restarting the panel (sessions are loaded at startup) and end it afterwards. Mock discoveries
by setting `state.hunt` with `Runtime.evaluate` and calling `renderHunt()`; never click buttons that
create or change playlists on the real account.

## Environment notes

- Windows; bash heredocs with Python triple-quoted strings break. Write patch scripts to the
  scratchpad with the Write tool and run them with `python -I`.
- Static files are served only from the top level of `static/`, with the suffixes in `CONTENT_TYPES`.
