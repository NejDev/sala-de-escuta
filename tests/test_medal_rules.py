import unittest
from datetime import date, datetime

from spotify_assistant import medal_rules, medals
from spotify_assistant.lastfm import Listeners
from spotify_assistant.medal_rules import Context


def at(year=2026, month=10, day=14, hour=12, minute=0, second=0):
    """A time on the room's clock, as plays store it (2026-10-14 is a Wednesday)."""
    return datetime(year, month, day, hour, minute, second).timestamp()


def play(uri="t", title="Song", artists=("Artist",), when=None, ms=200_000, release="2020-01-01",
         album_name="Album", album_id="al", album_type="album", tracks=10, number=None, context=None, disc=None):
    return {"uri": f"spotify:track:{uri}", "title": title,
            "artists": [{"id": name.lower().replace(" ", "-"), "name": name} for name in artists],
            "image": None, "duration_ms": ms, "at": at() if when is None else when,
            "album": {"id": album_id, "name": album_name, "type": album_type, "release": release, "tracks": tracks},
            "track_number": number, "disc_number": disc, "context": context}


def earn(plays, ctx=Context(), phase="play", stats=None):
    """Runs plays through the rules like the engine: the medals earned, each with the play that earned it."""
    stats = stats or medal_rules.new_stats()
    earned = {}
    for item in plays:
        (medal_rules.update if phase == "play" else medal_rules.rich_update)(stats, item, ctx)
        for medal in medals.MEDALS:
            if medal.phase == phase and medal.id not in earned and medal_rules.check(medal, stats, item, ctx):
                earned[medal.id] = item
    return earned


class VolumeTest(unittest.TestCase):
    def test_counts_plays_songs_and_artists(self):
        plays = [play(uri=f"s{n}", artists=(f"A{n % 60}",), when=at() + n * 300) for n in range(100)]
        earned = earn(plays)
        self.assertIs(earned["first-play"], plays[0])
        self.assertIs(earned["plays-100"], plays[99])
        self.assertIs(earned["artists-50"], plays[49])
        self.assertNotIn("songs-500", earned)

    def test_hours_add_durations(self):
        plays = [play(uri=f"s{n}", ms=3_600_000, when=at(day=1) + n * 3600) for n in range(24)]
        self.assertIs(earn(plays)["hours-24"], plays[23])


class DayTest(unittest.TestCase):
    def test_a_day_starts_at_midnight(self):
        late = [play(uri=f"a{n}", when=at(hour=23, minute=10) + n * 60) for n in range(30)]
        early = [play(uri=f"b{n}", when=at(day=15, hour=0, minute=1) + n * 60) for n in range(30)]
        self.assertNotIn("day-plays-50", earn(late + early))
        more = [play(uri=f"c{n}", when=at(hour=23, minute=40) + n) for n in range(20)]
        self.assertIn("day-plays-50", earn(late + more))

    def test_repeats_parts_and_clock_hours(self):
        self.assertIn("day-repeat-10", earn([play(uri="hit", when=at(hour=10) + n * 240) for n in range(10)]))
        parts = [play(uri=f"p{hour}", when=at(hour=hour)) for hour in (2, 8, 14, 20)]
        self.assertIn("day-parts", earn(parts))
        self.assertNotIn("day-clock-12", earn(parts))
        self.assertIn("day-clock-12", earn([play(uri=f"h{hour}", when=at(hour=hour)) for hour in range(12)]))

    def test_decades_in_one_day(self):
        years = (1965, 1975, 1985, 1995, 2005)
        self.assertIn("day-decades-5", earn([play(uri=f"d{y}", release=f"{y}-01-01", when=at() + n)
                                             for n, y in enumerate(years)]))


class StreakTest(unittest.TestCase):
    def test_days_in_a_row_and_breaks(self):
        self.assertIn("streak-7", earn([play(uri=f"w{d}", when=at(day=1 + d)) for d in range(7)]))
        self.assertNotIn("streak-7", earn([play(uri=f"w{d}", when=at(day=1 + d)) for d in (0, 1, 2, 4, 5, 6, 7)]))

    def test_coming_back_after_two_weeks(self):
        self.assertNotIn("comeback", earn([play(when=at(day=1)), play(when=at(day=14))]))
        self.assertIn("comeback", earn([play(when=at(day=1)), play(when=at(day=15, hour=13))]))

    def test_weekends_in_a_row(self):
        weekends = [play(uri=f"{w}{d}", when=at(day=3 + 7 * w + d)) for w in range(4) for d in (0, 1)]  # Oct 3 is a Saturday
        self.assertIn("weekends-4", earn(weekends))
        self.assertNotIn("weekends-4", earn(weekends[:6] + [play(when=at(day=31))]))


class ClockTest(unittest.TestCase):
    def test_moments(self):
        cases = {"midnight": at(hour=0, minute=0, second=30), "three-am": at(hour=3, minute=59),
                 "sunrise": at(hour=5, minute=29), "christmas": at(month=12, day=25), "music-day": at(month=6, day=21),
                 "friday-13": at(month=2, day=13), "carnival": at(month=2, day=17),
                 "leap-day": at(year=2028, month=2, day=29), "new-year": at(month=12, day=31, hour=23, minute=55)}
        for medal_id, when in cases.items():
            with self.subTest(medal=medal_id):
                self.assertIn(medal_id, earn([play(when=when)]))
        self.assertIn("new-year", earn([play(when=at(year=2027, month=1, day=1, hour=0, minute=10))]))
        self.assertNotIn("midnight", earn([play(when=at(hour=0, minute=1))]))
        self.assertNotIn("carnival", earn([play(when=at(month=2, day=18))]))  # Ash Wednesday

    def test_words_on_their_day(self):
        self.assertIn("lovebirds", earn([play(title="Meu Amor", when=at(month=6, day=12))]))
        self.assertNotIn("lovebirds", earn([play(title="Meu Amor", when=at(month=6, day=13))]))
        self.assertIn("halloween", earn([play(title="Ghost Town", when=at(month=10, day=31))]))
        self.assertIn("monday-song", earn([play(title="Manic Monday", when=at(day=12))]))
        self.assertIn("friday-song", earn([play(title="Sextou", when=at(day=16))]))

    def test_a_hundred_nights(self):
        plays = [play(uri=f"n{n}", when=at(day=1 + n // 10, hour=1, minute=n % 10)) for n in range(100)]
        self.assertIn("night-100", earn(plays))

    def test_easter(self):
        self.assertEqual(medal_rules.easter(2026), date(2026, 4, 5))
        self.assertEqual(medal_rules.easter(2027), date(2027, 3, 28))


class ReleaseTest(unittest.TestCase):
    def test_old_records(self):
        self.assertTrue({"before-1970", "before-1950", "before-1930"} <= set(earn([play(release="1929-05-01")])))
        self.assertNotIn("before-1930", earn([play(release="1930")]))
        self.assertNotIn("before-1970", earn([play(release="")]))  # no date: never counts

    def test_release_days(self):
        self.assertIn("same-day", earn([play(release="2026-10-14")]))
        self.assertNotIn("same-day", earn([play(release="2026-10")]))
        self.assertIn("anniversary", earn([play(release="1999-10-14")]))
        self.assertNotIn("anniversary", earn([play(release="2026-10-14")]))
        self.assertIn("fifty-years", earn([play(release="1976")]))

    def test_every_decade(self):
        plays = [play(uri=f"d{y}", release=str(y), when=at() + n) for n, y in enumerate(range(1955, 2035, 10))]
        self.assertIn("decades-all", earn(plays))
        self.assertNotIn("decades-all", earn(plays[1:]))


class RunTest(unittest.TestCase):
    def test_same_artist_different_artists_same_song(self):
        self.assertIn("same-artist-10", earn([play(uri=f"s{n}", artists=("Banda",), when=at() + n * 200)
                                              for n in range(10)]))
        diverse = [play(uri=f"d{n}", artists=(f"A{n}",), when=at() + n * 200) for n in range(20)]
        self.assertIn("diverse-20", earn(diverse))
        broken = diverse[:10] + [play(uri="x", artists=("A3",), when=at() + 2000)] + \
            [play(uri=f"e{n}", artists=(f"B{n}",), when=at() + 2200 + n * 200) for n in range(9)]
        self.assertNotIn("diverse-20", earn(broken))
        self.assertIn("same-song-3", earn([play(uri="loop", when=at() + n * 200) for n in range(3)]))

    def test_nonstop_hours(self):
        plays = [play(uri=f"n{n}", ms=600_000, when=at(hour=8) + n * 600) for n in range(18)]
        self.assertIn("nonstop-3h", earn(plays))
        gap = plays[:9] + [play(uri=f"g{n}", ms=600_000, when=at(hour=11) + n * 600) for n in range(9)]
        self.assertNotIn("nonstop-3h", earn(gap))

    def test_lengths_and_credits(self):
        self.assertIn("long-song-10", earn([play(ms=600_000)]))
        self.assertNotIn("long-song-20", earn([play(ms=600_000)]))
        self.assertIn("short-song", earn([play(ms=45_000)]))
        self.assertIn("crowd", earn([play(artists=("A", "B", "C", "D"))]))
        self.assertIn("short-run-10", earn([play(uri=f"q{n}", ms=90_000, when=at() + n * 100) for n in range(10)]))

    def test_a_whole_album_in_order(self):
        album = [play(uri=f"t{n}", number=n, tracks=6, when=at() + n * 300) for n in range(1, 7)]
        self.assertIn("album-full", earn(album))
        self.assertNotIn("album-full", earn(album[:3] + album[4:]))  # a track skipped
        five = [play(uri=f"t{n}", number=n, tracks=5, when=at() + n * 300) for n in range(1, 6)]
        self.assertNotIn("album-full", earn(five))
        long = [play(uri=f"l{n}", number=n, tracks=15, album_id="dbl", when=at() + n * 300) for n in range(1, 16)]
        self.assertIn("album-full-long", earn(long))
        discs = [play(uri=f"d{d}{n}", number=n, disc=d, tracks=16, album_id="2disc", when=at() + (d * 10 + n) * 300)
                 for d in (1, 2) for n in range(1, 9)]
        self.assertIn("album-full", earn(discs))
        self.assertIn("album-full-long", earn(discs))
        restart = [play(uri=f"r{d}{n}", number=n, disc=d, tracks=16, album_id="2disc", when=at() + (d * 10 + n) * 300)
                   for d in (1, 2) for n in range(1, 9)]
        restart = restart[:8] + restart[9:]  # disc 2 now starts at track 2
        self.assertNotIn("album-full", earn(restart))
        self.assertNotIn("album-full-long", earn(restart))

    def test_the_panels_own_finds_and_playlists(self):
        ctx = Context(finds=frozenset({"spotify:track:found"}), playlists=frozenset({"spotify:playlist:fav"}))
        hooked = [play(uri="found", when=at() + n * 300) for n in range(3)]
        self.assertIn("hooked", earn(hooked, ctx))
        self.assertNotIn("hooked", earn(hooked[:2], ctx))
        from_fav = play(context={"type": "playlist", "uri": "spotify:playlist:fav"})
        self.assertIn("panel-playlist", earn([from_fav], ctx))
        self.assertNotIn("panel-playlist", earn([from_fav]))
        made = medal_rules.new_stats()
        made["made"]["spotify:playlist:fav"] = 1
        self.assertIn("panel-playlist", earn([from_fav], stats=made))


class WordsTest(unittest.TestCase):
    def titles(self, titles):
        return [play(uri=f"w{n}", title=title, when=at() + n) for n, title in enumerate(titles)]

    def test_collections(self):
        rainbow = ["Red", "Laranja Mecânica", "Yellow", "Verde", "Blue Monday", "Indigo", "Purple Rain"]
        self.assertIn("rainbow", earn(self.titles(rainbow)))
        self.assertNotIn("rainbow", earn(self.titles(rainbow[:6])))
        week = ["Manic Monday", "Ruby Tuesday", "Wednesday Morning", "Thursday", "Friday I'm in Love",
                "Saturday Night", "Sunday Bloody Sunday"]
        self.assertIn("weekdays", earn(self.titles(week)))
        self.assertIn("seasons", earn(self.titles(["Spring", "Verão", "Autumn Leaves", "Winter"])))
        numbers = ["One", "Two", "Três", "Four", "Cinco", "Six", "Seven", "Oito", "Nine", "Ten"]
        self.assertIn("numbers", earn(self.titles(numbers)))
        self.assertIn("places-5", earn(self.titles(["Rio", "Paris", "Tokyo Drift", "London Calling", "Bahia"])))
        letters = [play(uri=f"l{n}", artists=(f"{chr(97 + n)}band",), when=at() + n) for n in range(20)]
        self.assertIn("alphabet-20", earn(letters))
        self.assertNotIn("alphabet-26", earn(letters))

    def test_single_songs(self):
        self.assertIn("saudade", earn([play(title="Saudades de Casa")]))
        self.assertIn("long-title", earn([play(title="One Two Three Four Five Six Seven Eight Nine Ten")]))
        self.assertNotIn("long-title", earn([play(title="One Two Three (Live at Some Very Long Venue Name)")]))
        self.assertIn("self-titled", earn([play(title="Bad Company", artists=("Bad Company",))]))
        self.assertIn("title-track", earn([play(title="Kind of Blue", album_name="Kind of Blue (Legacy Edition)")]))
        self.assertNotIn("title-track", earn([play(title="Single", album_name="Single", album_type="single")]))
        self.assertIn("digit-artist", earn([play(artists=("2Pac",))]))
        self.assertIn("namesake", earn([play(artists=("Paulo Ricardo",))], Context(first_name="paulo")))
        self.assertNotIn("namesake", earn([play(artists=("Paulinho",))], Context(first_name="paulo")))
        self.assertNotIn("namesake", earn([play(artists=("Al Green",))], Context(first_name="al")))  # too short

    def test_specific_artists_and_songs(self):
        self.assertIn("linkin-paulo", earn([play(artists=("Steve Aoki", "Linkin Park"))]))
        self.assertIn("apex-predator", earn([play(title="You Are The Jumpmaster", artists=("Stephen Barton",))]))
        self.assertIn("rickroll", earn([play(title="Never Gonna Give You Up - 2022 Remaster", artists=("Rick Astley",))]))
        self.assertNotIn("rickroll", earn([play(title="Never Gonna Give You Up", artists=("Cover Band",))]))
        self.assertIn("ipanema", earn([play(title="Garota de Ipanema", artists=("Tom Jobim",))]))


class GameTest(unittest.TestCase):
    def test_name_with_a_hint_or_the_games_own_artist(self):
        halo = medals.Game("halo", "Halo", ("halo",), context=True, artists=("halo",))
        self.assertTrue(medal_rules.matches_game(halo, play(title="Finish the Fight", artists=("Martin O'Donnell",),
                                                            album_name="Halo 3 (Original Soundtrack)")))
        self.assertFalse(medal_rules.matches_game(halo, play(title="Halo", artists=("Beyoncé",),
                                                             album_name="I Am... Sasha Fierce")))
        self.assertTrue(medal_rules.matches_game(halo, play(title="Heroes", artists=("Halo",), album_name="Infinite")))
        self.assertFalse(medal_rules.matches_game(halo, play(title="Halo (Original Mix)", artists=("DJ X",))))
        apex = medals.Game("apex-legends", "Apex Legends", ("apex legends",))
        self.assertTrue(medal_rules.matches_game(apex, play(title='Main Theme (From "Apex Legends")')))
        self.assertFalse(medal_rules.matches_game(apex, play(title="Apex", album_name="Legends")))

    def test_every_game_medal_works_end_to_end(self):
        for game in medals.GAMES:
            with self.subTest(game=game.slug):
                hint = f"{game.names[0]} original soundtrack" if game.names else "x"
                credit = (game.artists[0],) if game.artists else ("Someone",)
                self.assertIn(f"game-{game.slug}", earn([play(album_name=hint, artists=credit)]))


class RichTest(unittest.TestCase):
    def ctx(self, listeners=None, fans=None):
        return Context(listeners=lambda item: listeners, fans=lambda item: fans)

    def test_rare_songs_need_a_record(self):
        rare = earn([play()], self.ctx(Listeners(40, "u")), phase="rich")
        self.assertTrue({"rare-1000", "rare-100", "rare-50"} <= set(rare))
        self.assertNotIn("rare-10", rare)
        self.assertEqual(earn([play()], self.ctx(Listeners(None, None)), phase="rich"), {})
        self.assertIn("megahit", earn([play()], self.ctx(Listeners(3_000_000, "u")), phase="rich"))

    def test_collecting_different_rare_songs(self):
        ctx = self.ctx(Listeners(99, None))
        self.assertIn("rare-collect-10", earn([play(uri=f"r{n}", when=at() + n) for n in range(10)], ctx, "rich"))
        self.assertNotIn("rare-collect-10", earn([play(uri="same", when=at() + n) for n in range(10)], ctx, "rich"))

    def test_artist_size(self):
        self.assertTrue({"fans-1000", "fans-100"} <= set(earn([play()], self.ctx(fans=50), phase="rich")))
        self.assertIn("giant", earn([play()], self.ctx(fans=20_000_000), phase="rich"))
        self.assertEqual(earn([play()], self.ctx(fans=None), phase="rich"), {})

    def test_basement_to_stadium_in_one_day(self):
        ctx = Context(fans=lambda item: {"spotify:track:small": 500, "spotify:track:big": 20_000_000}[item["uri"]])
        same_day = [play(uri="small", when=at(hour=9)), play(uri="big", when=at(hour=21))]
        self.assertIn("day-extremes", earn(same_day, ctx, "rich"))
        apart = [play(uri="small", when=at(hour=23)), play(uri="big", when=at(day=15, hour=1))]
        self.assertNotIn("day-extremes", earn(apart, ctx, "rich"))


class NumbersTest(unittest.TestCase):
    def test_titles_won(self):
        stats = medal_rules.new_stats()
        stats["titles"] = [{"month": "2026-11", "title": "duo"}, {"month": "2026-12", "title": "duo"},
                           {"month": "2027-01", "title": "duo"}, {"month": "2027-01", "title": "explorer"}]
        values = [medal_rules.stat_value(stats, f"titles:{key}") for key in ("count", "kinds", "double", "streak")]
        self.assertEqual(values, [4, 2, 2, 3])

    def test_every_medal_names_a_rule_and_a_known_number(self):
        for medal in medals.MEDALS:
            with self.subTest(medal=medal.id):
                self.assertIn(medal.rule, medal_rules.RULES)
                if medal.rule == "total":
                    medal_rules.stat_value(medal_rules.new_stats(), medal.params["stat"])
        with self.assertRaises(KeyError):
            medal_rules.stat_value(medal_rules.new_stats(), "nonsense")


if __name__ == "__main__":
    unittest.main()
