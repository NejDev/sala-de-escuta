# Achievements: design

Date: 2026-10-15. Part 2 of 2 (part 1: `2026-10-15-lastfm-listeners-design.md`). The decisions below were made with
the owner in conversation; this file is the written record.

## Why

The room wants a game on top of listening: monthly titles the participants compete for, and personal medals that
are earned once and kept. The owner asked for at least 100 medals and for them to be a surprise, for the owner too.

## Secrecy (the owner's request)

- **The catalog is a spoiler.** Medal names and rules live in `2026-10-15-achievements-catalog.md` (next to this file)
  and, in code, in `spotify_assistant/medals.py`. The owner doesn't read either one. This spec, the plan, commit
  messages and conversations with the owner name no medal and describe rules only by family.
- **Only whoever earned a medal learns how.** Their own medal shows its name, the day, the song that unlocked it (when
  a song did) and a line saying what they did. On someone else's profile the same medal shows only the name, the day
  and the song.
- **The browser never receives a medal nobody in the room has earned, nor the "how" of a medal the viewer hasn't
  earned.** The API sends the person's own medals (with "how"), the other participants' medals (without it) and two
  numbers: how many the person has and how many exist. A locked medal can't be found in the page, the network log or
  the browser's memory.
- The eight monthly titles are not secret (the owner chose them); the race for them is shown openly.

## Decisions

- **Privacy:** participants see each other's medals *and the song that unlocked each one*. This changes the room's
  rule that a friend's solo listening is never shown, so joining comes with a notice, and only participants see it.
- **Joining:** a separate switch, "Take part in achievements", inside Friends. It needs Friends on (sharing plays),
  because medals come from the plays Friends collects. People already in Friends stay out until they turn it on.
- **Reciprocity:** someone who doesn't take part sees no one's achievements (like Friends).
- **Place:** a new tab, "Conquistas" / "Achievements", shown to whoever may use Friends.
- **Profile highlights:** each participant may highlight up to 10 of their medals; they show on that person's profile
  card in the tab and next to their name in Friends (there, only to viewers who also take part).
- **Where the work happens:** in the background, in the loop that already collects plays every 15 minutes (approach
  A). Opening the tab never makes an outside request.
- **Leaving:** turning the switch off hides the person's achievements and stops new ones (kept for a return). "Leave
  and erase" deletes them and removes the person from past monthly titles. Leaving Friends, or the owner turning
  Friends off for someone, does the same as "erase" (their plays are deleted then too).

## What is measured

Everything comes from the plays Friends already collects (Spotify's recently played list: songs heard for more than
30 seconds, no podcasts), plus two lookups done in the background and cached:

- **Last.fm listeners** per song (only with `LASTFM_API_KEY`; the cache from part 1). Medals that need them don't exist
  in an installation without a key: they're left out of the total too.
- **Artist fans** per artist (Deezer, by name; a new cache `data/fans-cache.json`, 30 days, like the Last.fm one).
  Deezer is never mentioned on screen.

`plays.json` gains, from now on, what the recently played list already returns and isn't kept today:
`album` (`id`, `name`, `type`, `release` as Spotify gives it, `tracks` total), `track_number` and `context` (album,
playlist, artist, collection or null, plus its URI). Older plays lack them; rules that need them skip those plays.
No new Spotify request is made for achievements, ever.

Times use the room's clock (the server's local time zone).

## The catalog, by family (counts only)

At least 100 medals, plus one per game. The catalog file has the exact list; these are the families:

| Family | Medals | Measured from |
|---|---|---|
| Volume (all-time totals since joining) | 13 | plays |
| A single day | 11 | plays |
| Streaks and returns | 6 | plays |
| Clock and calendar | 17 | plays (time, date, words in titles) |
| Release dates | 9 | plays (album release) |
| Rare songs | 7 | Last.fm listeners (needs the key) |
| Artist size | 4 | fans |
| Runs, albums and lengths | 17 | plays (order, album, duration, credits, the panel's own finds) |
| Words in titles and names | 17 | plays |
| Specific artists and songs (two asked by the owner) | 7 | plays |
| Friends | 8 | matches between participants |
| The panel | 17 | discoveries, playlists, favorites, reviews, blocks, Artists searches |
| Monthly titles won | 5 | closed months |
| Games: one medal named after each game with a memorable soundtrack | 40 | plays (album, title, artists) |

Games are chosen by the size of their soundtrack's audience (fans and catalog rank), and matched by the game's name in
the album or title (with a soundtrack hint when the name is a common word) or by artists tied to that one game.

## Monthly titles (not secret)

Eight titles, one holder per month among the participants (ties share it). Someone with fewer than 50 plays in the
month doesn't compete.

1. **Maratonista / Marathoner:** most plays.
2. **Mais alternativo / Most alternative:** smallest median fans among the month's artists (needs fans for at least 20).
3. **Explorador / Explorer:** most artists heard for the first time.
4. **Coruja / Night owl:** most plays from midnight to 5 a.m.
5. **Madrugador / Early bird:** most plays from 5 to 8 a.m.
6. **Dupla do mês / Duo of the month:** the pair with the most matches.
7. **Lançador de tendência / Trendsetter:** most artists a participant heard for the first time after you did, within
   30 days.
8. **Viajante do tempo / Time traveler:** most different decades of release.

The month in progress is computed when the tab opens, from plays (cheap, no outside requests). On the first loop of a
new month, the previous month is closed and saved in `data/achievements.json`.

## Engine: `spotify_assistant/achievements.py`

- **Per person:** `data/users/<id>/achievements.json`: `on`, `joined`, `earned` (medal id → `at`, optional song and
  Last.fm numbers), `seen` (ids already revealed), `highlights` (up to 10 ids), `stats` (running counters and sets the
  rules need) and two cursors: `through` (last play processed) and `rich_through` (last play processed by rules that
  need Last.fm or fans).
- **Rule kinds:** a single play; an all-time total; a single day; a streak; a run of consecutive plays; a collection
  (gathering every member of a set, such as letters or decades); friends; panel events; monthly titles. Each kind is
  a small function; the catalog is data (`medals.py`) that names a kind and its parameters.
- **Each loop,** for each participant: collect plays (as today), process new plays into `stats`, award what's due, then
  look up Last.fm and fans for new songs and artists (at most 300 lookups per person per loop; the rest wait for the
  next loop) and run the rules that need them up to `rich_through`. A Last.fm or Deezer failure stops only the
  lookups; it's logged and retried next loop.
- **On joining,** the 90 days of history already collected are processed at once, so the first visit can reveal
  several medals.
- **Panel events** (a discovery started, a playlist made, a favorite created, a review saved, an artist blocked, an
  Artists search) call `achievements.note(user_id, event, ...)`, which counts them only for participants and awards
  right away.
- A medal is earned once and kept for good (until "erase").
- A file that can't be read is never overwritten: the person is skipped that loop and the log says why.

## Panel

New tab `#conquistas` (`#achievements`), visible to whoever may use Friends:

- **Not sharing in Friends:** a line explaining that achievements come from Friends, with a link there.
- **Not taking part:** the invitation with the notice (others will see your medals and the songs behind them) and the
  switch. The same switch sits inside Friends.
- **Taking part:**
  1. **Reveal:** new medals open one at a time (a card that turns over, showing the name and how it was earned), then
     count as seen.
  2. **Your profile:** name, "N of M medals", the highlights (up to 10) and a way to pick them from the earned medals.
  3. **The month's race:** the eight titles with who leads and their number.
  4. **Your medals:** newest first; name, how you earned it, date, the song (cover, title, artist) when there is one,
     "N listeners on Last.fm" with a link when the medal came from Last.fm, and how many participants have it ("only
     you", "2 of 4").
  5. **The room:** each participant's profile card (name, highlights, count); opening it shows their medals, without
     the "how".
  6. **Past months:** the titles of closed months.
  7. **Leave** and **Leave and erase**.
- **New medal signal:** `/api/overview` carries `achievements: {"on": bool, "new": int}`; the tab shows a dot with the
  number and a toast says there's a new achievement, without naming it.
- Medals look like badges (a shape and colors from the medal's id); there's no icon that hints at the rule.
- Every text through `t()` in both languages. Medal names and "how" lines are keys `medal.<id>` and `medal.<id>.how`
  kept in their own module (`spotify_assistant/medal_names.py`) and merged into `i18n.MESSAGES`, so the parity test
  covers them. Game medals use the game's name, which is the same in both languages, and one shared "how" line with
  the game's name in it.

## API

- `GET /api/achievements`: the state for the person (as above); never anything for non-participants.
- `POST /api/achievements`: `{"on": bool, "forget": bool}`.
- `POST /api/achievements/seen`: `{"ids": [...]}` (only the person's own earned ids are accepted).
- `POST /api/achievements/highlights`: `{"ids": [...]}` (up to 10, only earned ones).

## Privacy rule (CLAUDE.md)

Add: "Achievements (opt-in inside Friends): participants see each other's medals and the song behind each one;
nothing for non-participants; a medal nobody has earned never reaches the browser, and only whoever earned a medal
sees how."

## Testing

Fakes only (no Spotify, Last.fm or Deezer for real), with a fixed clock:

- Each rule kind on hand-made plays, including the edges (midnight, month change, streak breaks, ties).
- The catalog: at least 100 medals besides games, unique ids, every id has a name in both languages, every rule names a
  known kind with valid parameters, and Last.fm medals drop out without a key.
- Privacy: a non-participant gets nothing; the API never sends a medal nobody earned, nor the "how" of a medal the
  viewer hasn't earned; erase removes the person from files and past titles; leaving Friends erases.
- The loop: lookups capped per loop, failures don't block other medals, an unreadable file is left alone.
- Monthly titles: the race, the minimum plays, ties and closing a month once.
- Screens: the fake panel in headless Chrome at phone and desktop sizes (invitation, reveal, profile, race, room),
  console clean.

## Rollout

Push and update the server. The owner turns achievements on in Friends and opens the tab: the first reveal comes from
the last 90 days.

## Out of scope

YouTube views; notifications outside the panel; anything that needs extra Spotify requests; medals for people outside
the room.
