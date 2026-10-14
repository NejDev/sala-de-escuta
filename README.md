Read in: English | [Português](README.pt-BR.md)

# Sala de escuta

A listening room for Spotify: a web panel that runs on your PC, finds music you've never heard
and plays it straight on your Spotify. You and up to four friends each sign in with your own account,
in Portuguese or English.

- **Sensations**: write what you're feeling (or pick a moment) and get songs at the right tempo.
- **Discover**: a roulette of barely-played records from all over the world, and a rabbit hole that
  hops from an artist you like toward lesser-known ones.
- **New releases**: what just came out in a genre, only from artists of the size you choose.
- **Keep what you like**: turn any selection into a playlist, or add a song to one of yours.
- **Curated shelf** (owner): 5 playlists kept up to date, including a weekly podcast playlist.

Python 3.12. Everything uses only the standard library, except measuring BPM in Sensations,
which needs an MP3 decoder (`pip install -r requirements.txt`).

## Run your own room

Spotify only lets small apps work in **Development Mode**: up to 5 people (counting the owner),
each one added by hand, and the account that owns the app must be Premium. More users require
"extended quota", which Spotify only grants to registered organizations with at least 250k monthly
users ([quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).
So the way to share this project is for each person to run their own room:

1. Create an app at [Spotify for Developers](https://developer.spotify.com/dashboard) (Web API).
   Add `http://127.0.0.1:8888/callback` to its Redirect URIs.
2. Copy `.env.example` to `.env` and fill in `SPOTIFY_CLIENT_ID`. No Client Secret: sign-in uses PKCE.
3. `pip install -r requirements.txt`, then double-click `open-panel.cmd`
   (or run `python -m spotify_assistant ui`).
4. Sign in. The first person to sign in becomes the room's owner.

## The panel

The panel opens at http://127.0.0.1:8888 and stays up while the black window is open.
The first visit shows a short tour with the mascot; **How it works** at the top opens it again.
**PT / EN** switches the language for that person (the server's messages follow it).

- **Shelf**: at the top, in two sections, "Playlists" and "Explore". Each playlist is a colored
  spine, and the selected one becomes the panel's light.
- **Player**: play, pause, skip, shuffle, repeat (off, all, this track), volume and progress.
  Click a track to play from it. Works with Spotify open on your PC or phone (requires Premium).
  The first time, click **Authorize on Spotify** in the bottom bar.
- **Shortcuts**: space plays/pauses, ← → change tracks, 1–9 switch screens.

### Sensations

**Write what you're feeling** ("anger", "missing home", "ódio", "saudade de casa") or pick a
ready-made moment. Free text doesn't use any paid AI:

1. The phrase becomes the first search: lots of people name playlists after feelings.
2. A local dictionary (`FEELINGS`, in `spotify_assistant/discovery.py`, Portuguese and English)
   recognizes the feeling, sets the rhythm (anger: 125–185 BPM and high energy) and widens the search.
3. If the phrase isn't in the dictionary ("Sunday morning"), the room listens to the previews,
   finds the BPM and energy they have in common and keeps the songs that follow that pattern.

For the ready-made moments (heavy workout, running, deep focus, party, rainy day...) the room looks
for playlists people built for that moment, **listens to each track's 30 s preview and measures BPM
and energy**, and keeps only what fits that sensation's range. **Artist fans** (at least / at most)
narrow it to artists of the size you want.

Why measure? Spotify stopped giving BPM to new apps, and the public catalogs' BPM is almost always
zero. The meter (`spotify_assistant/tempo.py`) got 12 of 17 songs with a known BPM right, plus 2 at
double/half tempo; treat the number as approximate.

The moments live in `sensations.json` (name and description in both languages, BPM range, energy
range from 0 to 1, color and the searches used as sources). Measurements are cached in
`data/tempo-cache.json` so the same preview isn't heard twice.

### Discover

- **Roulette**: the mascot digs through a crate of records while drawing barely-played albums from
  a random year and less popular tracks from playlists of genres from all over the world (zamrock,
  enka, huayno, ethio jazz...). The genre list is `WORLD_GENRES`, in `spotify_assistant/discovery.py`.
- **Rabbit hole**: starts from an artist (typed in or drawn from your playlists) and hops 4 times to
  related artists, always among the lesser-known ones. Shows the whole path and the number of fans.

Both take an optional genre (roulette) and the artist's size in fans (minimum and maximum). No free
API says how many times a song was played; the artist's fan count is the measure available.

### New releases

Pick a genre (e.g. K-pop), the artist size and the period (7, 14, 30 or 90 days). The room gathers
artists of that genre from playlists, filters them by fans, looks at each one's releases and shows the
main track of each release, newest first. "Clean" versions of the same release are merged, and on
soundtracks the artist's own track is used.

### Keeping what you like

Above every result:

- **Create playlist**: everything that showed up becomes a playlist with the name you choose
  (it comes filled in, e.g. "Sensation: Deep focus"). If you already have one with that name, the
  room asks before replacing its songs.
- **Add to a playlist**: sends everything to `Finds from the Sala` (created the first time) or to
  any playlist of yours. Songs already there aren't repeated.

Each song has its own **Add**, with the same choices. Playlists the room rebuilds by itself
(the weekly podcasts and the mix) don't show up there, since anything added would be lost.

Each song's ⓘ shows why it showed up (measured BPM and energy, the genre or year drawn, the hops in
the rabbit hole, the release date) and has **Don't show again**: the artist disappears right away and
never comes back in any discovery. The list is per person; to undo, use **Blocked artists** above the results.

**Nothing religious**: discoveries discard tracks, albums and playlists with religious signs of any
denomination (`RELIGIOUS_WORDS` in `spotify_assistant/discovery.py`).

### Curated shelf (owner)

| Playlist | Contents | Updates |
|---|---|---|
| Tech Radar BR | recent episodes of Brazilian tech podcasts | weekly (automatic) |
| Midnight in Monaco | refined jazz | `setup` |
| Deep Focus — Lo-Fi | lo-fi for coding (shuffled) | `setup` |
| The Classical Room | classical, from contemplative to grand | `setup` |
| The Study Collection | jazz + lo-fi + classical, alternating | `setup` |

- **Update now / Redo selection** runs the curation with the log showing live; **See preview**
  shows the result without changing anything.
- **Add track / Follow another show** searches the catalog. The track goes into the playlist right
  away and into `playlists.json`, so it survives the next `setup`. Songs added from a discovery to a
  curated playlist are written to `playlists.json` too.
- Spine colors are the `color` field of each playlist in `playlists.json`.

### Cost

Zero. The Spotify Web API and Deezer's public API are free (they only have request limits, which the
panel respects), BPM is measured on your PC and free text is read locally.

## A room for friends

Each person signs in with their own Spotify and has their own player, discoveries, Finds, blocked
artists and copies of the playlists ("Create in my Spotify"). Friends don't see each other's
playlists or searches. The panel runs on the owner's PC and is made public with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel), at a fixed address `https://<pc>.<network>.ts.net`.

1. Set `SALA_PUBLIC_URL` in `.env` to the Funnel address (`tailscale funnel status` shows it).
2. In the Spotify for Developers app → Settings, add `<SALA_PUBLIC_URL>/callback` to Redirect URIs.
3. Under User Management, add each friend's name and Spotify account e-mail (5 people in total,
   counting the owner).
4. Send them the address. The player only works for people with Premium; discovering and saving work for everyone.

The site is only up while the PC is on and the panel is open. To have the panel start on its own,
hidden, every time you sign in to Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1           # turn on
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1 -Remove   # undo
```

With it on, `open-panel.cmd` just opens the room in the browser. `weekly` updates the Tech Radar of
everyone who created it.

## Command line

```powershell
python -m spotify_assistant login            # signs in the owner (only once)
python -m spotify_assistant check            # shows the owner and who's in the room
python -m spotify_assistant setup --dry-run  # shows what would be created, without changing anything
python -m spotify_assistant setup            # creates/recreates the 5 playlists
python -m spotify_assistant setup --only "Midnight in Monaco"
python -m spotify_assistant weekly           # updates only Tech Radar BR
```

`SALA_LANG` in `.env` (`en` or `pt`) sets the language of the command line and of the weekly task.

Schedule the weekly update (Monday at 09:00; if the PC is off, it runs once it's turned on):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1 -Day Friday -Time 18:30
```

## Customize

Everything is in `playlists.json`:

- `tracks`: `"Artist - Title"`. The search skips karaoke, lo-fi, lullaby versions, etc.
- `artists`: takes the `per_artist` most relevant tracks from each artist.
- `podcasts.shows`: show names; `max_age_days` defines what counts as "recent".
- `mix`: draws `per_source` tracks from each listed playlist and alternates between them.

Anything that isn't found shows up as `not found:` in the output. Just adjust the name in the JSON.

Interface texts are in `spotify_assistant/static/i18n.js` (browser) and `spotify_assistant/i18n.py`
(server); `tests/test_i18n.py` checks that both languages have the same keys.

## Local files (in `data/`, never committed)

- `users/<id>/token.json`: each person's access token. Don't share it.
- `users/<id>/state.json`, `blocked.json`, `profile.json`: playlist IDs, blocked artists and display name.
- `owner.txt`, `sessions.json`: who owns the room and the browser sessions.
- `tempo-cache.json`, `spotify-matches.json`, `spotify-pauses.json`: measured BPMs, tracks already
  located on Spotify and Spotify's request pauses.
- `assistant.log`: run history (including scheduled runs).

## Common problems

- **403 / "Your account isn't allowed in yet"**: in Development Mode the account that owns the app
  must be Premium and each person's e-mail must be under *User Management*.
- **"Your Spotify session expired"**: sign in again (or `python -m spotify_assistant login` for the owner).
- **"Spotify paused this app's searches"**: the app made too many requests and Spotify suspended
  search for a few hours (the player and playlists keep working). The panel respects the pause, shows
  when it comes back and keeps the songs it already found so it doesn't search them again. Avoid
  leaving several panel tabs open: each one polls the player.
