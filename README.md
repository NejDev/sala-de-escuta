Read in: English | [Português](README.pt-BR.md)

# Sala de escuta

A listening room for Spotify: a web panel that runs on your PC, finds music you've never heard
and plays it straight on your Spotify. You and up to four friends each sign in with your own account,
in Portuguese or English.

- **Sensations**: write what you're feeling (or pick a moment) and get songs at the right tempo.
- **Discover**: a roulette of barely-played records from all over the world (any genre or subgenre), and
  a rabbit hole that hops from an artist or a song you like toward lesser-known ones.
- **New releases**: what just came out in a genre, only from artists of the size you choose.
- **Artists**: everything a band or artist released, with each member's solo work and their features.
- **Lyrics**: synced lyrics of the song playing, line by line, plus who wrote it and what Last.fm knows about it.
- **Friends** (opt-in): musical affinity between friends, and matches when you play the same song.
- **Favorites that update themselves**: turn a selection into a playlist that gets new songs every
  day, week or month. Only these special playlists go on the top bar.
- **Home**: a suggestion for this time of day, what's playing, your favorites, shortcuts and recent finds.
- **Curated shelf** (owner): 5 playlists from `playlists.json`, including a weekly podcast playlist.

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

Your curated shelf lives in `playlists.json`, created from `playlists.example.json` on the first run.
It's yours: it stays out of git, and the panel writes to it when you add tracks.

## The panel

The panel opens at http://127.0.0.1:8888 and stays up while the black window is open.
The first visit shows a short tour with the mascot; **How it works** at the top opens it again.
**PT / EN** switches the language for that person (the server's messages follow it).

- **Bar**: at the top, "Favorites" (playlists that update themselves, plus any you pin) and "Room" (Home,
  Sensations, Discover, New releases). Each favorite is a colored spine, and the selected one becomes
  the panel's light. The mascot next to the name also goes back Home.
- **Home**: "For right now" suggests a sensation for this time of day (morning, afternoon, evening;
  a party on Friday and Saturday nights) and plays it at once if it's already a favorite; "Now playing";
  your favorites with their next update; shortcuts to the roulette, the rabbit hole and the latest
  releases of your last genre; and the songs you saved most recently.
- **Player**: play, pause, skip, shuffle, repeat (off, all, this track), volume and progress.
  Click a track to play from it. Works with Spotify open on your PC or phone (requires Premium).
  The first time, click **Authorize on Spotify** in the bottom bar. The microphone opens the lyrics
  (see [Lyrics](#lyrics)).
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

The moments are listed from the slowest to the fastest. They live in `sensations.json` (name and description in both languages, BPM range, energy
range from 0 to 1, color and the searches used as sources). Measurements are cached in
`data/tempo-cache.json` so the same preview isn't heard twice.

### Discover

- **Roulette**: the mascot digs through a crate of records while drawing barely-played albums from
  a random year and less popular tracks from playlists of genres from all over the world (zamrock,
  enka, huayno, ethio jazz...). The genre list is `WORLD_GENRES`, in `spotify_assistant/discovery.py`.
  Pick **Little-known genre** to draw only from that list, a different genre on each card.
  The main genres sit in a row under the genre field; picking one opens a row with its subgenres
  (Emo: midwest emo, screamo, post-hardcore...), each checked against the catalog's playlists (`SUBGENRES`, in
  `static/app.js`). Any other genre can still be typed. Playlists whose title names the genre come first;
  the others count only when none does (the catalog also knows genres by tag: "rap nacional" brings
  "Essenciais do Rap Brasileiro").
- **Rabbit hole**: starts from an artist (typed in or drawn from your playlists) and hops 4 times to
  related artists, always among the lesser-known ones. Shows the whole path and the number of fans.
  Switch it to **Song** (or use **Rabbit hole from here** on any find, on Home's "Now playing" or in the
  lyrics panel) and it hops from song to similar song instead: Last.fm's similar tracks, toward the less
  played, never back to an artist already on the way; four trails of up to five songs. Without a Last.fm
  key, or for a song Last.fm has nothing like, it goes through the song's artist (Spotify no longer gives
  similar songs to apps like this one).

Both take an optional genre (roulette) and the artist's size in fans (minimum and maximum; the
smallest cap is 200). No free API says how many times a song was played; the artist's fan count is the measure
available. With a cap of 1,000 fans or less, the roulette skips the barely-played albums: each one
costs a Spotify search and almost none fits.

With a Last.fm key, every discovery also takes **song listeners: at most**, counted on Last.fm (people who scrobbled
the song). A song Last.fm has no record of passes and says so. Each song is checked once a month (new releases once a day) and
remembered in `data/lastfm-cache.json`; songs over the cap are dropped before anything is searched on Spotify.

### New releases

Pick a genre (e.g. K-pop), the artist size and the period (today, or the last 3, 7, 14, 30 or 90 days). The room gathers
artists of that genre from playlists, filters them by fans, looks at each one's releases and shows the
main track of each release, newest first. "Clean" versions of the same release are merged, and on
soundtracks the artist's own track is used.

### Artists

Type a band or an artist, of any genre (e.g. Racionais MC's, TWICE, Coldplay), and see everything
they released: albums, singles and EPs, features on other artists' songs, compilations and soundtracks,
plus the solo work and features of each member and subunit (former members included). Filter by
person and by type (one checkbox per type, so "only compilations" or "everything but features" works), and
sort newest or oldest first. A feature plays from the track where they appear.

When several artists share the name ("Andy"), the room asks which one, showing each one's photo,
genres and latest release.

Who is in a band comes from [MusicBrainz](https://musicbrainz.org) (open data, no key; one request per
second, kept for a month in `data/musicbrainz-cache.json`), which also links each person to their
Spotify profile. Members without that link are looked up by name, and left out when the name is
ambiguous. This search barely uses Spotify search, so it keeps working while search is paused.

### Lyrics

The microphone in the player opens a panel beside the page (over it on phones) with the song playing:

- **Lyrics**: synced lyrics light up line by line and follow the song; click a line to jump there; scroll
  by hand and they stop following until **Back to the current line**. Lyrics without timing show as text.
  **Translate** appears where the browser has a built-in translator (recent Chrome): it translates line by
  line on the device. Lyrics come from [LRCLIB](https://lrclib.net) (open, free, no key); each song is asked
  once and kept in `data/lyrics/` (a song it doesn't have, again after a week). LRCLIB limits requests: after
  a "too many requests" the room waits as long as it asks.
- **About**: Last.fm's listeners, plays, tags (a tag fills the roulette's genre) and summary (with a Last.fm
  key); who composed, wrote, produced and mixed it, from MusicBrainz (by the song's ISRC, kept a month);
  shortcuts to the rabbit hole and the album review.

### Reviews

Letterboxd for albums: half-star ratings and a few words. Each review is either **just for you** or
**open to the room** (everyone sees the rating, the text and your name). Review from the star in the
player, from any release in Artists, or by pasting an album's Spotify link. Opening an album shows
the room's open reviews and their average.

### Friends

Only for people who join, and only among them: whoever doesn't join sees nothing and doesn't show up.
The room reads each member's recently played songs on Spotify every 15 minutes (kept for 90 days) and shows:

- **Affinity** with each friend: it compares the artists each one likes, from Spotify's most played
  (4 weeks, 6 months, a year), the playlists they made, their liked songs and the last 30 days of plays
  (rebuilt every 3 days, in the background). Only the artists you have in common are named; nobody sees
  anyone's playlists.
- **Matches**: the same song played by both of you within 6 hours, over the last week; each one plays
  with a click. What a friend plays alone is never shown.

**Leave and delete my history** removes everything. Joining needs one more Spotify permission, so
each person authorizes Spotify again once.

The owner decides who can use Friends (**Who can use Friends**, at the bottom of the owner's Friends
page): a switch per person, and whether people who join the room later start with it. Someone without
Friends doesn't see the tab, and their history is deleted.

### Achievements

Inside Friends, each person can also take part in achievements: more than 100 hidden medals (plus one per game with a
memorable soundtrack) that turn up as you listen, and eight monthly titles the participants compete for. Nobody knows
what unlocks a medal until they earn it; only whoever earned it sees how. Participants see each other's medals and
the song behind each one. Everything is worked out in the background from what Friends already collects (no extra
Spotify requests); medals about rare songs need the Last.fm key.

### Keeping what you like

Above every result:

- **Create playlist**: everything that showed up becomes a playlist with the name you choose
  (it comes filled in, e.g. "Sensation: Deep focus"). If you already have one with that name, the
  room asks before replacing its songs. **Update by itself** (every day, week or month) turns it into
  a favorite: it goes on the bar and, on each update, the same discovery runs again and its songs are
  replaced with a fresh selection.
- **Add to a playlist**: sends everything to `Finds from the Sala` (created the first time) or to
  any playlist of yours. Songs already there aren't repeated.

Each song has its own **Add**, with the same choices. Playlists the room rebuilds by itself
(the weekly podcasts and the mix) don't show up there, since anything added would be lost.

On a favorite's page: **Update now**, the frequency, and **Remove from the bar** (the playlist stays on
Spotify; it just stops updating). The **+** at the end of the favorites (or **Put a playlist on the bar**
on Home) pins any playlist of yours as a shortcut, without automatic updates, and brings back curated
playlists that left the bar. Up to 8 favorites per person. Updates run inside the panel, one at a
time and at most one every 10 minutes, to spare Spotify's request limits; while Spotify has search paused,
they wait. If the PC was off at the time, the update runs once the panel is back.

Each song's ⓘ shows why it showed up (measured BPM and energy, the genre or year drawn, the hops in
the rabbit hole, the release date) and has **Don't show again**: the artist disappears right away and
never comes back in any discovery. The list is per person; to undo, use **Blocked artists** above the results.

**Nothing religious**: discoveries discard tracks, albums and playlists with religious signs of any
denomination (`RELIGIOUS_WORDS` in `spotify_assistant/discovery.py`).

### Curated shelf (owner)

| Playlist | Contents | Updates (default) |
|---|---|---|
| Tech Radar BR | recent episodes of Brazilian tech podcasts | every week |
| Midnight in Monaco | refined jazz | every month |
| Deep Focus — Lo-Fi | lo-fi for coding (shuffled) | every month |
| The Classical Room | classical, from contemplative to grand | every month |
| The Study Collection | jazz + lo-fi + classical, alternating | every month |

The curated playlists are the owner's favorites; the frequency can be changed on each page, and
**Remove from the bar** hides one (it stops updating until it comes back through the **+**).

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

Each person signs in with their own Spotify and has their own player, discoveries, favorites, Finds
and blocked artists. Friends don't see each other's playlists or searches. The panel runs on the owner's PC and is made public with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel), at a fixed address `https://<pc>.<network>.ts.net`.

1. Set `SALA_PUBLIC_URL` in `.env` to the Funnel address (`tailscale funnel status` shows it).
2. In the Spotify for Developers app → Settings, add `<SALA_PUBLIC_URL>/callback` to Redirect URIs.
3. Under User Management, add each friend's name and Spotify account e-mail (5 people in total,
   counting the owner).
4. Send them the address. The player only works for people with Premium; discovering and saving work for everyone.

To keep the room up without your PC, host it on a free server: [Oracle Cloud guide](docs/oracle-cloud.md).

On the PC, the site is only up while the PC is on and the panel is open. To have the panel start on its own,
hidden, every time you sign in to Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1           # turn on
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1 -Remove   # undo
```

With it on, `open-panel.cmd` just opens the room in the browser, and favorites update themselves.

## Command line

```powershell
python -m spotify_assistant login            # signs in the owner (only once)
python -m spotify_assistant check            # shows the owner and who's in the room
python -m spotify_assistant setup --dry-run  # shows what would be created, without changing anything
python -m spotify_assistant setup            # creates/recreates the 5 playlists
python -m spotify_assistant setup --only "Midnight in Monaco"
python -m spotify_assistant refresh          # updates now every favorite that is due, for everyone
```

`refresh` is only needed if you don't keep the panel open (the panel does it by itself).
`SALA_LANG` in `.env` (`en` or `pt`) sets the language of the command line and of automatic updates.

### Last.fm (optional)

The listener filter needs a free Last.fm API key: create an API account at
https://www.last.fm/api/account/create (any application name; no callback needed), copy the "API key" into
`LASTFM_API_KEY` in `.env` and restart the panel. Without it, the filter doesn't show, the rabbit hole from a song
goes through the song's artist and the lyrics panel has no Last.fm numbers. Last.fm's terms ask for credit, so the
panel names Last.fm and links each song to its Last.fm page.

## Customize

Everything is in `playlists.json` (your copy of `playlists.example.json`):

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
- `users/<id>/favorites.json`, `recent.json`: favorites (recipe, frequency, last update) and recent finds.
- `users/<id>/social.json`, `plays.json`: whether the person joined Friends, and their plays (90 days).
- `owner.txt`, `sessions.json`: who owns the room and the browser sessions.
- `tempo-cache.json`, `spotify-matches.json`, `spotify-pauses.json`: measured BPMs, tracks already
  located on Spotify and Spotify's request pauses.
- `lyrics/<track id>.json`: each song's lyrics (or that LRCLIB didn't have them).
- `assistant.log`: run history (including scheduled runs).

## Common problems

- **403 / "Your account isn't allowed in yet"**: in Development Mode the account that owns the app
  must be Premium and each person's e-mail must be under *User Management*.
- **"Your Spotify session expired"**: sign in again (or `python -m spotify_assistant login` for the owner).
- **"Spotify paused this app's searches"**: the app made too many requests and Spotify suspended
  search for a few hours (the player and playlists keep working). The panel respects the pause, shows
  when it comes back and keeps the songs it already found so it doesn't search them again. Avoid
  leaving several panel tabs open: each one polls the player.

## License

[MIT](LICENSE). Not affiliated with Spotify; it uses the Spotify Web API under Spotify's developer terms.
