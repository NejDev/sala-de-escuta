import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import achievements, config, i18n, medals, reviews, social
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


if __name__ == "__main__":
    unittest.main()
