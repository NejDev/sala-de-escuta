import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import achievements, config, i18n, medals, monthly, reviews, social
from spotify_assistant.deezer import DeezerError
from spotify_assistant.lastfm import LastFmError, Listeners
from spotify_assistant.medal_rules import Context
from tests.test_medal_rules import at, play


def no_fans(name):
    return None


class Room(unittest.TestCase):
    """Three people in a temporary room: paulo (the owner), ana and bia."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        patcher = mock.patch.object(config, "DATA_DIR", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.data / "owner.txt").write_text("paulo", encoding="utf-8")
        for user_id in ("paulo", "ana", "bia"):
            folder = self.data / "users" / user_id
            folder.mkdir(parents=True)
            (folder / "token.json").write_text("{}", encoding="utf-8")
            (folder / "profile.json").write_text(json.dumps({"name": user_id.title()}), encoding="utf-8")

    def join(self, *people):
        for user_id in people:
            social.set_share(user_id, True)
            achievements.set_on(user_id, True, now=at(day=1))

    def save_plays(self, user_id, plays):
        (self.data / "users" / user_id / "plays.json").write_text(json.dumps(plays), encoding="utf-8")


class ParticipationTest(Room):
    def test_joining_counts_the_history_already_collected(self):
        social.set_share("paulo", True)
        history = [play(uri=f"s{n}", when=at(day=1) + n * 300) for n in range(100)]
        achievements.set_on("paulo", True, now=at(day=14))
        self.assertIn("plays-100", achievements.process("paulo", history, Context(), lastfm=False))
        self.assertEqual(achievements.load("paulo")["earned"]["plays-100"]["song"]["uri"], history[99]["uri"])
        self.assertEqual(achievements.load("paulo")["through"], history[-1]["at"])
        self.assertEqual(achievements.process("paulo", history, Context(), lastfm=False), [])  # nothing twice
        self.assertEqual(achievements.load("paulo")["stats"]["plays"], 100)

    def test_back_after_leaving_skips_what_was_played_meanwhile(self):
        self.join("paulo")
        achievements.process("paulo", [play(when=at(day=1, hour=13))], Context(), False)
        achievements.set_on("paulo", False)
        self.assertEqual(achievements.process("paulo", [play(uri="x", when=at(day=2))], Context(), False), [])
        achievements.set_on("paulo", True, now=at(day=3))
        achievements.process("paulo", [play(uri="x", when=at(day=2)), play(uri="y", when=at(day=4))], Context(), False)
        self.assertEqual(achievements.load("paulo")["stats"]["plays"], 2)  # day 1 and day 4

    def test_only_people_in_friends_take_part(self):
        achievements.set_on("ana", True)
        self.assertFalse(achievements.taking_part("ana"))  # not sharing in Friends
        social.set_share("ana", True)
        self.assertTrue(achievements.taking_part("ana"))
        self.assertEqual(achievements.participants(), ["ana"])

    def test_erase_removes_the_file_and_past_titles(self):
        self.join("paulo", "ana")
        room = {"since": "2026-09", "months": {"2026-09": {"duo": {"users": ["ana", "paulo"], "value": 3},
                                                           "explorer": {"users": ["ana"], "value": 9}}}}
        (self.data / "achievements.json").write_text(json.dumps(room), encoding="utf-8")
        achievements.forget("ana")
        self.assertFalse((self.data / "users" / "ana" / "achievements.json").exists())
        months = json.loads((self.data / "achievements.json").read_text(encoding="utf-8"))["months"]
        self.assertEqual(months["2026-09"], {"duo": {"users": ["paulo"], "value": 3}})

    def test_an_unreadable_file_is_left_alone(self):
        self.join("paulo")
        path = self.data / "users" / "paulo" / "achievements.json"
        path.write_text("{oops", encoding="utf-8")
        with self.assertRaises(achievements.Unreadable):
            achievements.process("paulo", [play()], Context(), False)
        self.assertEqual(achievements.note("paulo", "block"), [])
        self.assertFalse(achievements.taking_part("paulo"))
        self.assertEqual(path.read_text(encoding="utf-8"), "{oops")


class EventsTest(Room):
    def test_panel_events_count_for_participants_only(self):
        self.assertEqual(achievements.note("ana", "hunt", kind="roulette"), [])
        self.assertFalse((self.data / "users" / "ana" / "achievements.json").exists())  # nothing kept for outsiders
        self.join("ana")
        self.assertEqual(achievements.note("ana", "hunt", kind="roulette", rare=True), ["roulette-1", "roulette-rare"])
        for kind in ("sense", "rabbit"):
            achievements.note("ana", "hunt", kind=kind)
        self.assertIn("all-discoveries", achievements.note("ana", "hunt", kind="news"))
        self.assertIsNone(achievements.load("ana")["earned"]["roulette-1"]["song"])

    def test_the_listener_cap_medal_needs_the_key(self):
        self.join("ana")
        self.assertNotIn("listeners-tight", achievements.note("ana", "hunt", kind="roulette", listeners=50))
        self.assertIn("listeners-tight", achievements.note("ana", "hunt", kind="roulette", listeners=50, lastfm=True))

    def test_review_medals_follow_the_reviews(self):
        self.join("ana")
        reviews.save("ana", {"id": "a" * 22, "name": "Kind of Blue"}, 5, "x" * 500, True)
        self.assertEqual(achievements.note("ana", "review"), ["review-1", "review-five", "review-long"])

    def test_playlists_made_in_the_panel_count_for_later_plays(self):
        self.join("ana")
        achievements.note("ana", "playlist", uri="spotify:playlist:p1")
        from_it = play(context={"type": "playlist", "uri": "spotify:playlist:p1"})
        self.assertIn("panel-playlist", achievements.process("ana", [from_it], Context(), False))


class ViewTest(Room):
    def setUp(self):
        super().setUp()
        self.join("paulo", "ana")
        achievements.process("paulo", [play(title="Saudade")], Context(), False)

    def view(self, user_id):
        return achievements.view(user_id, False, no_fans, now=at())

    def test_outsiders_see_nothing(self):
        self.assertEqual(self.view("bia"), {"sharing": False, "on": False})
        social.set_share("bia", True)
        self.assertEqual(self.view("bia"), {"sharing": True, "on": False})

    def test_how_only_for_whoever_earned_it(self):
        saudade = next(medal for medal in self.view("paulo")["me"]["medals"] if medal["id"] == "saudade")
        self.assertEqual(saudade["how"], i18n.t("medal.saudade.how"))
        self.assertEqual(saudade["song"]["title"], "Saudade")
        paulo = next(person for person in self.view("ana")["people"] if person["id"] == "paulo")
        shown = next(medal for medal in paulo["medals"] if medal["id"] == "saudade")
        self.assertNotIn("how", shown)
        self.assertEqual(shown["holders"], 1)

    def test_a_medal_nobody_earned_never_shows(self):
        seen = self.view("ana")
        earned = set(achievements.load("paulo")["earned"]) | set(achievements.load("ana")["earned"])
        ids = set(re.findall(r'"id": "([a-z0-9-]+)"', json.dumps(seen))) - {"paulo", "ana"} - set(medals.TITLES)
        self.assertLessEqual(ids, earned)
        self.assertEqual(seen["total"], len([medal for medal in medals.MEDALS if medal.requires != "lastfm"]))

    def test_new_until_seen_and_highlights(self):
        self.assertIn("saudade", self.view("paulo")["new"])
        achievements.mark_seen("paulo", list(achievements.load("paulo")["earned"]) + ["rare-10"])
        self.assertEqual(self.view("paulo")["new"], [])
        self.assertNotIn("rare-10", achievements.load("paulo")["seen"])
        achievements.set_highlights("paulo", ["saudade", "rare-10", "saudade"])
        self.assertEqual(achievements.load("paulo")["highlights"], ["saudade"])
        self.assertEqual([medal["id"] for medal in self.view("ana")["people"][0]["highlights"]], ["saudade"])
        self.assertEqual(achievements.highlights_of("paulo", False), [{"id": "saudade", "name": i18n.t("medal.saudade")}])
        self.assertEqual(achievements.summary("paulo", False), {"on": True, "new": 0})

    def test_revoked_friends_access_drops_the_person(self):
        (self.data / "room.json").write_text(json.dumps({"friends_new": True, "friends_people": {"ana": False}}),
                                             encoding="utf-8")
        self.assertEqual(self.view("ana"), {"sharing": True, "on": False})
        self.assertNotIn("ana", [person["id"] for person in self.view("paulo")["people"]])

    def test_people_who_leave_disappear(self):
        achievements.set_on("paulo", False)
        self.assertEqual(self.view("ana")["people"], [])
        self.assertEqual(achievements.highlights_of("paulo", False), [])
        self.assertEqual(achievements.summary("paulo", False), {"on": False, "new": 0})


class FakeCounts:
    """Last.fm with a cache: titles it knows have listeners, others no record."""

    def __init__(self, listeners=None, error=None):
        self.listeners, self.error, self.asked, self.known = listeners or {}, error, [], {}

    def cached(self, artist, title):
        return self.known.get((artist, title))

    def get(self, artist, title, fresh_s=None):
        self.asked.append((artist, title))
        if self.error:
            raise LastFmError(self.error)
        self.known[(artist, title)] = Listeners(self.listeners.get(title), None)
        return self.known[(artist, title)]


class FakeDeezer:
    def __init__(self, fans=None, error=False):
        self.fans, self.error, self.asked = fans or {}, error, []

    def search_artist(self, name):
        self.asked.append(name)
        if self.error:
            raise DeezerError("down")
        return {"nb_fan": self.fans[name]} if name in self.fans else None


class LookupTest(Room):
    def fans(self):
        return achievements.ArtistFans(path=self.data / "fans.json")

    def plays(self, count):
        return [play(uri=f"s{n}", title=f"Song {n}", artists=(f"A{n}",), when=at() + n) for n in range(count)]

    def test_artist_fans_are_asked_once_and_kept(self):
        dz, fans = FakeDeezer({"Banda": 500}), self.fans()
        self.assertFalse(fans.known("Banda"))
        self.assertEqual((fans.get(dz, "Banda"), fans.get(dz, "BANDA "), fans.get(dz, "Ninguém")), (500, 500, None))
        fans.save()
        again = self.fans()
        self.assertTrue(again.known("Ninguém"))
        self.assertEqual((again.cached("Ninguém"), again.cached("banda")), (None, 500))
        self.assertEqual(dz.asked, ["Banda", "Ninguém"])

    def test_lookups_are_capped_per_loop(self):
        counts, dz, fans = FakeCounts(), FakeDeezer(), self.fans()
        achievements.enrich(self.plays(5), 0, counts, fans, dz, budget=3)
        self.assertEqual((len(counts.asked), len(dz.asked)), (3, 3))
        achievements.enrich(self.plays(5), 0, counts, fans, dz, budget=3)
        self.assertEqual((len(counts.asked), len(dz.asked)), (5, 5))  # the next loop goes on from there

    def test_a_failure_stops_only_that_kind_of_lookup(self):
        counts, dz = FakeCounts(error="down"), FakeDeezer()
        achievements.enrich(self.plays(5), 0, counts, self.fans(), dz)
        self.assertEqual((len(counts.asked), len(dz.asked)), (1, 5))
        counts, dz = FakeCounts(), FakeDeezer(error=True)
        achievements.enrich(self.plays(5), 0, counts, self.fans(), dz)
        self.assertEqual((len(counts.asked), len(dz.asked)), (5, 1))

    def test_rich_medals_wait_for_their_numbers(self):
        self.join("paulo")
        plays = [play(uri="a", title="Rara", artists=("Pequena",), when=at()),
                 play(uri="b", title="Outra", artists=("Grande",), when=at() + 300)]
        counts, dz, fans = FakeCounts({"Rara": 30, "Outra": 5000}), FakeDeezer({"Pequena": 50, "Grande": 20_000_000}), self.fans()
        ctx = achievements.context("paulo", counts, fans)
        achievements.enrich(plays, 0, counts, fans, dz, budget=1)  # only the first play's numbers
        new = achievements.rich_pass("paulo", plays, ctx, True, counts, fans)
        self.assertIn("rare-50", new)
        self.assertNotIn("giant", new)
        data = achievements.load("paulo")
        self.assertEqual(data["rich_through"], plays[0]["at"])
        self.assertEqual(data["earned"]["rare-50"]["lastfm"], {"listeners": 30, "url": None})
        self.assertEqual(data["earned"]["rare-50"]["song"]["title"], "Rara")
        achievements.enrich(plays, data["rich_through"], counts, fans, dz)
        self.assertIn("giant", achievements.rich_pass("paulo", plays, ctx, True, counts, fans))

    def test_without_a_key_there_are_no_rare_medals(self):
        self.join("paulo")
        dz, fans = FakeDeezer({"Pequena": 50}), self.fans()
        plays = [play(artists=("Pequena",))]
        achievements.enrich(plays, 0, None, fans, dz)
        new = achievements.rich_pass("paulo", plays, achievements.context("paulo", None, fans), False, None, fans)
        self.assertIn("fans-100", new)
        self.assertFalse(any(medal_id.startswith("rare") for medal_id in new))

    def test_a_blank_credit_is_not_looked_up(self):
        counts, dz = FakeCounts(), FakeDeezer()
        achievements.enrich([play(artists=("\xa0, \xa0",))], 0, counts, self.fans(), dz)
        self.assertEqual((counts.asked, dz.asked), ([], []))


class RoomTest(Room):
    def test_matches_between_participants(self):
        self.join("paulo", "ana", "bia")
        plays = {"paulo": [play(uri="x", when=at(hour=10)), play(uri="y", when=at(hour=11))],
                 "ana": [play(uri="x", when=at(hour=10, minute=3))],
                 "bia": [play(uri="y", when=at(hour=15))]}
        new = achievements.room_pass(plays, False, now=at(hour=20))
        self.assertTrue({"match-1", "match-sync", "match-everyone"} <= set(new["paulo"]))
        self.assertTrue({"match-1", "match-sync"} <= set(new["ana"]))
        self.assertNotIn("match-everyone", new["ana"])  # Ana and Bia never matched
        self.assertEqual(set(new["bia"]) & {"match-sync", "match-everyone"}, set())
        self.assertIn(achievements.load("paulo")["earned"]["match-1"]["song"]["uri"],
                      {"spotify:track:x", "spotify:track:y"})
        self.assertEqual(achievements.room_pass(plays, False, now=at(hour=20)), {"paulo": [], "ana": [], "bia": []})

    def test_three_people_on_one_song(self):
        self.join("paulo", "ana", "bia")
        plays = {who: [play(uri="z", when=at(hour=hour))] for who, hour in (("paulo", 9), ("ana", 12), ("bia", 14))}
        new = achievements.room_pass(plays, False, now=at(hour=20))
        self.assertTrue(all("trio" in new[who] for who in plays))
        self.assertEqual(achievements.load("bia")["earned"]["trio"]["song"]["uri"], "spotify:track:z")

    def test_picking_up_artists_after_someone(self):
        self.join("paulo", "ana")
        paulo = [play(uri=f"p{n}", artists=(f"Novo {n}",), when=at(day=1) + n) for n in range(5)]
        ana = [play(uri=f"a{n}", artists=(f"Novo {n}",), when=at(day=10) + n) for n in range(5)]
        achievements.process("paulo", paulo, Context(), False)
        achievements.process("ana", ana, Context(), False)
        new = achievements.room_pass({"paulo": paulo, "ana": ana}, False, now=at(day=10, hour=20))
        self.assertIn("trendsetter", new["paulo"])
        self.assertIn("follower", new["ana"])
        self.assertIsNone(achievements.load("paulo")["earned"]["trendsetter"]["song"])


def month_of_plays(prefix, count, hour=12, release="2020-01-01", artists=25):
    return [play(uri=f"{prefix}{n}", artists=(f"{prefix}-artist-{n % artists}",), release=release,
                 when=at(day=1 + n % 28, hour=hour, minute=n % 60)) for n in range(count)]


class StandingsTest(unittest.TestCase):
    def test_fewer_than_fifty_plays_dont_compete_and_ties_share(self):
        result = monthly.standings("2026-10", {"paulo": month_of_plays("p", 60), "ana": month_of_plays("a", 40)}, {}, no_fans)
        self.assertEqual(result["marathoner"], {"users": ["paulo"], "value": 60})
        tie = monthly.standings("2026-10", {"paulo": month_of_plays("p", 60), "ana": month_of_plays("a", 60)}, {}, no_fans)
        self.assertEqual(tie["marathoner"], {"users": ["ana", "paulo"], "value": 60})
        self.assertNotIn("night-owl", tie)  # nobody played at night: nobody holds it

    def test_hours_decades_and_fans(self):
        plays = {"paulo": month_of_plays("p", 60, hour=2, release="1975"), "ana": month_of_plays("a", 60, hour=6)}
        fans = lambda name: 100 if name.startswith("p-") else 5000
        result = monthly.standings("2026-10", plays, {}, fans)
        self.assertEqual(result["night-owl"]["users"], ["paulo"])
        self.assertEqual(result["early-bird"]["users"], ["ana"])
        self.assertEqual(result["alternative"], {"users": ["paulo"], "value": 100})
        plays["ana"] += [play(uri="old", release="1965", when=at(day=2))]
        self.assertEqual(monthly.standings("2026-10", plays, {}, fans)["time-traveler"]["users"], ["ana"])

    def test_the_duo_and_first_heard_artists(self):
        shared = [play(uri=f"s{n}", when=at(day=5, hour=10) + n * 60) for n in range(5)]
        plays = {"paulo": month_of_plays("p", 55) + shared, "ana": month_of_plays("a", 55) + shared,
                 "bia": month_of_plays("b", 60)}
        firsts = {"paulo": {"x": at(day=2), "y": at(day=3)}, "ana": {"x": at(day=9), "y": at(day=12)}, "bia": {}}
        result = monthly.standings("2026-10", plays, firsts, no_fans)
        self.assertEqual(result["duo"], {"users": ["ana", "paulo"], "value": 5})
        self.assertEqual(result["explorer"], {"users": ["ana", "paulo"], "value": 2})  # two new artists each
        self.assertEqual(result["trendsetter"], {"users": ["paulo"], "value": 2})  # Ana picked up both after Paulo did


class CloseMonthTest(Room):
    def test_closes_last_month_once_from_the_first_month_on(self):
        self.join("paulo", "ana")
        plays = {"paulo": [play(uri=f"p{n}", when=at(day=1 + n % 28, hour=1)) for n in range(60)], "ana": []}
        self.assertIsNone(achievements.close_month(plays, no_fans, False, now=at(day=20)))  # September predates it
        self.assertEqual(achievements.close_month(plays, no_fans, False, now=at(month=11, day=1, hour=0, minute=5)),
                         "2026-10")
        room = json.loads((self.data / "achievements.json").read_text(encoding="utf-8"))
        self.assertEqual(room["months"]["2026-10"]["marathoner"], {"users": ["paulo"], "value": 60})
        self.assertIn("title-1", achievements.load("paulo")["earned"])
        self.assertIsNone(achievements.close_month(plays, no_fans, False, now=at(month=11, day=2)))  # only once

    def test_the_tab_shows_the_race_and_past_months(self):
        self.join("paulo", "ana")
        plays = [play(uri=f"p{n}", when=at(day=1 + n % 28, hour=1)) for n in range(60)]
        self.save_plays("paulo", plays)
        achievements.close_month({"paulo": plays, "ana": []}, no_fans, False, now=at(day=20))
        seen = achievements.view("ana", False, no_fans, now=at(day=20))
        race = {title["id"]: title for title in seen["race"]}
        self.assertEqual(race["marathoner"]["holders"], ["Paulo"])
        self.assertEqual(race["marathoner"]["value"], i18n.t("title.marathoner.value", count=60, value="60"))
        achievements.close_month({"paulo": plays, "ana": []}, no_fans, False, now=at(month=11, day=1))
        months = achievements.view("ana", False, no_fans, now=at(month=11, day=1))["months"]
        self.assertEqual([month["month"] for month in months], ["2026-10"])

    def test_only_participants_compete(self):
        self.join("paulo", "ana")
        achievements.close_month({"paulo": [], "ana": []}, no_fans, False, now=at(day=20))  # sets the first month
        plays = {"paulo": [play(uri=f"p{n}", when=at(day=1 + n % 28, hour=1)) for n in range(60)], "ana": [],
                 "bia": [play(uri=f"b{n}", when=at(day=1 + n % 28, hour=1)) for n in range(80)]}  # bia is not in
        achievements.close_month(plays, no_fans, False, now=at(month=11, day=1))
        room = json.loads((self.data / "achievements.json").read_text(encoding="utf-8"))
        self.assertEqual(room["months"]["2026-10"]["marathoner"], {"users": ["paulo"], "value": 60})
        self.assertFalse((self.data / "users" / "bia" / "achievements.json").exists())


if __name__ == "__main__":
    unittest.main()
