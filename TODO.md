# To do

What's left to call Sala de escuta finished. Check items off as they're done.

## Verify with real Spotify (once search is no longer paused)

These were built with tests and mocked screens only, because Spotify search was paused.

- [ ] Sensations with an artist-fans range (minimum and maximum), from a preset and from free text.
- [ ] New releases for a real genre (e.g. K-pop) with a fans range and each period.
- [ ] **Create playlist** with **Update by itself**: it shows up on the bar, its page shows the next
      update, and **Update now** replaces the songs.
- [ ] **Add to a playlist**: `Finds from the Sala` is created only once, repeated songs are skipped,
      and songs added to a curated playlist land in `playlists.json`.
- [ ] Repeat button on a real device: off → all → this track.
- [ ] The **+** on the bar: pin one of your playlists, add a track to it, take it off; take a curated
      playlist off the bar and bring it back.
- [ ] The heart in the player: each person authorizes Spotify once more (new library permission, the
      heart shows the link), then likes and unlikes a song and a podcast episode; check Liked Songs.
- [ ] Artists: a K-pop group (members without a MusicBrainz link need Spotify search), a solo artist,
      a rock band with former members; play a feature from its track.
- [ ] Artists: a generic name (e.g. "Andy") shows the "which one?" cards and picking one works.
- [ ] Friends: two people join (each authorizes Spotify again), plays appear after 15 minutes,
      affinity and a match show up; leaving deletes the history.
- [ ] Friends: someone new signs in and doesn't see the Friends tab (newcomers start without it).
- [ ] Home: **For right now** builds the sensation, or plays it when it's already a favorite;
      **Now playing** follows the player; recent finds play.

## Watch in normal use

- [ ] The first automatic update of a favorite (see `data/assistant.log` and the favorite's page).
- [ ] Spotify request pauses when several people have daily favorites. If they happen, raise
      `SCHEDULER_TICK_S` or lower `MAX_FAVORITES` in the code.
- [ ] Tech Radar now updates 7 days after its last run instead of Mondays at 09:00. If a fixed
      weekday/hour matters, add a preferred time to favorites.

## Friends

- [ ] Add each friend's Spotify e-mail under User Management in Spotify for Developers (5 people
      in total, counting the owner). Accounts that sign in with Facebook show their e-mail at
      spotify.com/account/overview.
- [ ] A friend signs in through the public address on a phone, builds a sensation and makes a favorite.

## Before calling it 1.0

- [ ] Use each person's own country (from `/me`) instead of the single `market` in `playlists.json`.
- [ ] Remove the old library-shelf code (`LIBRARY_KEY` in `dashboard.playlist` and `dashboard.add_item`,
      and the tests that use it): pinned favorites (`fav:<id>` keys) replaced it.
- [ ] Drop the `weekly` command alias (kept only for old scheduled tasks).
- [ ] README: screenshots (home, sensations, a favorite) and a social preview image with the mascot.
- [ ] GitHub Actions running `python -m unittest discover -s tests` on every push.
- [ ] Notes for Linux/macOS: run `python -m spotify_assistant ui`; the autostart scripts are Windows-only.
- [ ] Split `static/app.js` (about 1,900 lines) into a few files if it keeps growing.
