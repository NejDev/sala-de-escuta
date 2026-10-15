import json
import re
import string
import unittest
from datetime import date, datetime
from pathlib import Path

from spotify_assistant import i18n

PACKAGE = Path(__file__).resolve().parent.parent / "spotify_assistant"
STATIC = PACKAGE / "static"


def placeholders(text) -> set[str]:
    texts = text if isinstance(text, (list, tuple)) else [text]
    return {name for value in texts for _, name, _, _ in string.Formatter().parse(value) if name}


def browser_strings() -> dict:
    source = (STATIC / "i18n.js").read_text(encoding="utf-8")
    return json.loads(source.split("const STRINGS = ", 1)[1].rstrip().rstrip(";"))


class CatalogTest(unittest.TestCase):
    """Both languages say the same things: same keys, same {placeholders}, same plural forms."""

    def check_parity(self, catalogs: dict) -> None:
        pt, en = catalogs["pt"], catalogs["en"]
        self.assertEqual(set(pt) ^ set(en), set())
        for key in pt:
            with self.subTest(key=key):
                self.assertEqual(placeholders(pt[key]), placeholders(en[key]))
                self.assertEqual(isinstance(pt[key], (list, tuple)), isinstance(en[key], (list, tuple)))

    def test_server_messages(self):
        self.check_parity(i18n.MESSAGES)

    def test_browser_texts(self):
        self.check_parity(browser_strings())

    def test_every_server_key_exists(self):
        used = set()
        for path in PACKAGE.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            used |= set(re.findall(r'\bt\(\s*"([\w.]+)"', source))
            used |= set(re.findall(r'\bt\([^)\n]*?\belse "([\w.]+)"', source))
            for pattern in re.findall(r'\bt\(\s*f"([\w.{}]+)"', source):  # t(f"pause.{what}.soon")
                regex = re.sub(r"\\\{\w+\\\}", r"\\w+", re.escape(pattern))
                self.assertTrue(any(re.fullmatch(regex, key) for key in i18n.MESSAGES["en"]), pattern)
        self.assertEqual(used - set(i18n.MESSAGES["en"]), set())

    def test_every_browser_key_exists(self):
        keys = set(browser_strings()["en"])
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        used = set(re.findall(r'"([a-z]+(?:\.[a-z0-9_]+)+)"', app))
        # Keys built from a variable.
        used |= {f"hunt.again.{kind}" for kind in ("sense", "roulette", "rabbit", "news")}
        used |= {f"period.{days}" for days in (0, 3, 7, 14, 30, 90)}
        used |= {f"player.repeat_{mode}" for mode in ("off", "context", "track")}
        used |= {f"every.{every}" for every in ("daily", "weekly", "monthly")}
        tour = re.search(r"const TOUR = \[(.*?)\];", app, re.S).group(1)
        used |= {f"tour.{key}.{part}" for key in re.findall(r'key: "(\w+)"', tour) for part in ("title", "text")}
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n="([\w.]+)"', page))
        for attrs in re.findall(r'data-i18n-attr="([^"]+)"', page):
            used |= {pair.split(":")[1] for pair in attrs.split(";")}
        self.assertEqual(used - keys, set())


class LanguageTest(unittest.TestCase):
    def tearDown(self):
        i18n.use(i18n.DEFAULT)

    def test_cookie_then_browser_then_english(self):
        self.assertEqual(i18n.pick("pt", "en-US"), "pt")
        self.assertEqual(i18n.pick(None, "pt-BR,pt;q=0.9"), "pt")
        self.assertEqual(i18n.pick("fr", "de-DE, en;q=0.5"), "en")
        self.assertEqual(i18n.pick(None, None), "en")

    def test_plural_and_formats(self):
        i18n.use("pt")
        self.assertEqual(i18n.t("save.created", name="X", count=1), "Playlist X criada com 1 música.")
        self.assertEqual(i18n.number(1234567), "1.234.567")
        self.assertEqual(i18n.long_date(date(2026, 10, 3)), "03/10/2026")
        self.assertEqual(i18n.clock(datetime(2026, 1, 1, 21, 5)), "21:05")
        i18n.use("en")
        self.assertEqual(i18n.t("save.created", name="X", count=3), "Playlist X created with 3 songs.")
        self.assertEqual(i18n.number(1234567), "1,234,567")
        self.assertEqual(i18n.long_date(date(2026, 10, 3)), "Oct 3, 2026")
        self.assertEqual(i18n.clock(datetime(2026, 1, 1, 21, 5)), "9:05 PM")
        self.assertEqual(i18n.clock(datetime(2026, 1, 1, 0, 30)), "12:30 AM")
        self.assertEqual(i18n.use("es"), "en")


if __name__ == "__main__":
    unittest.main()
