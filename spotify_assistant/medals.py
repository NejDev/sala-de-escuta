"""The achievements catalog. SPOILERS: the owner chose not to read this file (the medals are a surprise).

A medal names a rule in medal_rules.RULES with its parameters, and a phase: "play" (checked on each new play),
"rich" (on each play once its Last.fm listeners and artist fans are known), "event" (something done in the panel),
"room" (matches between participants) or "titles" (closed months). Medals with requires="lastfm" exist only in
rooms with a Last.fm key. Names and "how" lines are in medal_names.py (generated from the catalog file).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Medal:
    id: str
    family: str
    rule: str
    params: dict = field(default_factory=dict)
    phase: str = "play"
    requires: str = ""
    song: bool = True  # keeps the song that earned it


@dataclass(frozen=True)
class Game:
    slug: str
    name: str
    names: tuple[str, ...]  # normalized names, searched as whole words in the album name or the title
    context: bool = False  # a common word: the same text also needs a soundtrack hint
    artists: tuple[str, ...] = ()  # normalized names of artists tied to this game only


# The monthly titles (not secret: the owner chose them).
TITLES = ("marathoner", "alternative", "explorer", "night-owl", "early-bird", "duo", "trendsetter", "time-traveler")

LOVE = ("love", "amor", "amore", "amour", "liebe", "amar", "amo")
SPOOKY = ("ghost", "fantasma", "witch", "bruxa", "bruja", "monster", "monstro", "zombie", "zumbi", "vampire",
          "vampiro", "halloween", "devil", "diabo", "diablo", "skeleton", "esqueleto", "haunted", "assombrada")
MOON = ("moon", "lua", "luna", "lune", "luar")
SUN = ("sun", "sol", "soleil", "sunshine", "sunny", "ensolarado")
MONDAY = ("monday", "segunda", "lunes")
FRIDAY = ("friday", "sexta", "sextou", "viernes")
WEEKDAYS = (("monday", "segunda", "lunes"), ("tuesday", "terca", "martes"), ("wednesday", "quarta", "miercoles"),
            ("thursday", "quinta", "jueves"), ("friday", "sexta", "viernes"), ("saturday", "sabado"),
            ("sunday", "domingo"))
SEASONS = (("spring", "primavera"), ("summer", "verao", "verano"), ("autumn", "fall", "outono", "otono"),
           ("winter", "inverno", "invierno"))
RAINBOW = (("red", "vermelho", "vermelha", "rojo", "roja"), ("orange", "laranja", "naranja"),
           ("yellow", "amarelo", "amarela", "amarillo", "amarilla"), ("green", "verde"), ("blue", "azul"),
           ("indigo", "anil"), ("violet", "purple", "roxo", "roxa", "violeta", "morado", "lilas"))
NUMBERS = (("1", "one", "um", "uma", "uno"), ("2", "two", "dois", "duas", "dos"), ("3", "three", "tres"),
           ("4", "four", "quatro", "cuatro"), ("5", "five", "cinco"), ("6", "six", "seis"),
           ("7", "seven", "sete", "siete"), ("8", "eight", "oito", "ocho"), ("9", "nine", "nove", "nueve"),
           ("10", "ten", "dez", "diez"))
PLACES = (("rio", "rio de janeiro"), ("sao paulo",), ("bahia",), ("recife",), ("salvador",), ("brasilia",), ("belem",),
          ("manaus",), ("minas", "minas gerais"), ("ipanema",), ("copacabana",), ("brasil", "brazil"), ("paris",),
          ("london", "londres"), ("tokyo", "toquio"), ("berlin", "berlim"), ("roma", "rome"), ("madrid",),
          ("lisboa", "lisbon"), ("new york", "nova york", "nova iorque"), ("chicago",), ("california",), ("texas",),
          ("memphis",), ("nashville",), ("detroit",), ("havana",), ("cuba",), ("mexico",), ("buenos aires",),
          ("argentina",), ("lima",), ("bogota",), ("jamaica",), ("africa",), ("lagos",), ("cairo",), ("istanbul",),
          ("moscow", "moscou"), ("india",), ("bombay", "mumbai"), ("bangkok",), ("seoul", "seul"), ("hong kong",),
          ("sydney",), ("amsterdam",), ("dublin",), ("vienna", "viena"), ("venice", "veneza"),
          ("napoli", "napoles", "naples"), ("barcelona",), ("sevilla", "seville"), ("hollywood",), ("las vegas",),
          ("miami",))
WORDS = {"love": LOVE, "spooky": SPOOKY, "monday": MONDAY, "friday": FRIDAY}
COLLECTIONS = {"rainbow": RAINBOW, "weekdays": WEEKDAYS, "seasons": SEASONS, "numbers": NUMBERS, "places": PLACES}

GAMES: tuple[Game, ...] = (
    Game("league-of-legends", "League of Legends", ("league of legends",), False, ("league of legends", "k da", "pentakill", "true damage", "heartsteel", "league of legends brasil")),
    Game("grand-theft-auto", "Grand Theft Auto", ("grand theft auto", "gtavi", "gta vi", "gta v", "gta iv", "gta san andreas", "gta vice city"), True, ("grand theft auto vi",)),
    Game("clair-obscur-expedition-33", "Clair Obscur: Expedition 33", ("expedition 33",), False, ("lorien testard",)),
    Game("cyberpunk-2077", "Cyberpunk 2077", ("cyberpunk 2077", "cyberpunk edgerunners"), False, ()),
    Game("minecraft", "Minecraft", ("minecraft",), True, ("c418", "minecraft")),
    Game("valorant", "Valorant", ("valorant",), False, ("valorant",)),
    Game("undertale", "Undertale", ("undertale", "megalovania"), False, ()),
    Game("persona", "Persona", ("persona 3", "persona 4", "persona 5", "persona3", "persona4", "persona5"), False, ("lyn inaizumi",)),
    Game("outer-wilds", "Outer Wilds", ("outer wilds",), False, ()),
    Game("the-elder-scrolls", "The Elder Scrolls", ("skyrim", "elder scrolls"), True, ()),
    Game("genshin-impact", "Genshin Impact", ("genshin impact",), False, ()),
    Game("deltarune", "Deltarune", ("deltarune",), False, ()),
    Game("the-legend-of-zelda", "The Legend of Zelda", ("legend of zelda", "breath of the wild", "tears of the kingdom", "ocarina of time", "majora s mask", "twilight princess", "wind waker", "skyward sword", "link s awakening", "zelda s lullaby", "gerudo valley"), False, ()),
    Game("the-last-of-us", "The Last of Us", ("the last of us",), False, ()),
    Game("assassins-creed", "Assassin's Creed", ("assassin s creed", "ezio s family"), False, ("assassin s creed",)),
    Game("hollow-knight", "Hollow Knight", ("hollow knight", "silksong"), False, ("christopher larkin",)),
    Game("pokemon", "Pokémon", ("pokemon",), True, ("pokemon",)),
    Game("death-stranding", "Death Stranding", ("death stranding",), False, ()),
    Game("red-dead-redemption", "Red Dead Redemption", ("red dead redemption",), False, ()),
    Game("the-witcher", "The Witcher", ("witcher 3", "witcher 2"), False, ()),
    Game("doki-doki-literature-club", "Doki Doki Literature Club!", ("doki doki literature club",), False, ("dan salvato",)),
    Game("doom", "Doom", ("doom eternal", "doom the dark ages", "doom original game soundtrack", "doom 1993", "doom 64", "bfg division", "e1m1"), False, ()),
    Game("super-mario", "Super Mario", ("super mario", "mario kart", "mario bros"), True, ()),
    Game("sonic", "Sonic the Hedgehog", ("sonic the hedgehog", "sonic adventure", "sonic heroes", "sonic unleashed", "sonic colors", "sonic generations", "sonic forces", "sonic frontiers", "sonic mania", "shadow the hedgehog"), False, ("crush 40", "tomoya ohtani")),
    Game("baldurs-gate", "Baldur's Gate", ("baldur s gate",), False, ()),
    Game("celeste", "Celeste", ("celeste",), True, ()),
    Game("ultrakill", "Ultrakill", ("ultrakill",), False, ()),
    Game("hades", "Hades", ("hades original soundtrack", "hades ii"), False, ()),
    Game("dark-souls", "Dark Souls", ("dark souls",), True, ()),
    Game("god-of-war", "God of War", ("god of war",), True, ()),
    Game("omori", "Omori", ("omori",), True, ()),
    Game("world-of-warcraft", "World of Warcraft", ("world of warcraft", "warcraft iii", "warcraft ii"), False, ("world of warcraft",)),
    Game("brawl-stars", "Brawl Stars", ("brawl stars",), True, ("brawl stars",)),
    Game("final-fantasy", "Final Fantasy", ("final fantasy",), True, ()),
    Game("mass-effect", "Mass Effect", ("mass effect",), True, ()),
    Game("resident-evil", "Resident Evil", ("resident evil",), True, ()),
    Game("silent-hill", "Silent Hill", ("silent hill", "silent hill2", "silent hill3", "silent hill4"), True, ()),
    Game("nier", "NieR", ("nier automata", "nier replicant", "nier gestalt", "nier re in carnation"), False, ()),
    Game("free-fire", "Free Fire", ("free fire",), True, ("garena free fire",)),
    Game("apex-legends", "Apex Legends", ("apex legends",), False, ()),
)


def total(medal_id: str, family: str, stat: str, at_least: float, phase: str = "play", requires: str = "",
          song: bool = True, **params) -> Medal:
    """A medal earned when one of the running numbers (medal_rules.stat_value) reaches `at_least`."""
    return Medal(medal_id, family, "total", {"stat": stat, "at_least": at_least, **params}, phase, requires, song)


def event(medal_id: str, stat: str, at_least: float = 1, requires: str = "") -> Medal:
    """A medal for something done in the panel (no song)."""
    return total(medal_id, "panel", stat, at_least, phase="event", requires=requires, song=False)


MEDALS: tuple[Medal, ...] = (
    # Volume
    total("first-play", "volume", "plays", 1),
    total("plays-100", "volume", "plays", 100),
    total("plays-1000", "volume", "plays", 1000),
    total("plays-5000", "volume", "plays", 5000),
    total("plays-10000", "volume", "plays", 10000),
    total("hours-24", "volume", "hours", 24),
    total("hours-100", "volume", "hours", 100),
    total("hours-500", "volume", "hours", 500),
    total("artists-50", "volume", "artists", 50),
    total("artists-250", "volume", "artists", 250),
    total("artists-1000", "volume", "artists", 1000),
    total("songs-500", "volume", "songs", 500),
    total("songs-2000", "volume", "songs", 2000),
    # A single day
    total("day-plays-50", "day", "day:plays", 50),
    total("day-plays-100", "day", "day:plays", 100),
    total("day-hours-5", "day", "day:hours", 5),
    total("day-hours-10", "day", "day:hours", 10),
    total("day-artists-30", "day", "day:artists", 30),
    total("day-repeat-10", "day", "day:repeat", 10),
    total("day-repeat-25", "day", "day:repeat", 25),
    total("day-parts", "day", "day:parts", 4),
    total("day-clock-12", "day", "day:clock", 12),
    total("day-decades-5", "day", "day:decades", 5),
    total("day-extremes", "day", "rich_day:extremes", 1, phase="rich"),
    # Streaks and returns
    total("streak-7", "streaks", "streak", 7),
    total("streak-30", "streaks", "streak", 30),
    total("streak-100", "streaks", "streak", 100),
    total("streak-365", "streaks", "streak", 365),
    Medal("comeback", "streaks", "comeback", {"days": 14}),
    total("weekends-4", "streaks", "weekends", 4),
    # Clock and calendar
    Medal("midnight", "clock", "clock", {"from": "00:00", "to": "00:00"}),
    Medal("three-am", "clock", "clock", {"from": "03:00", "to": "03:59"}),
    Medal("sunrise", "clock", "clock", {"from": "05:00", "to": "05:29"}),
    Medal("new-year", "clock", "new_year"),
    Medal("christmas", "clock", "date", {"month": 12, "day": 25}),
    Medal("music-day", "clock", "date", {"month": 6, "day": 21}),
    Medal("friday-13", "clock", "friday_13"),
    Medal("carnival", "clock", "carnival"),
    Medal("lovebirds", "clock", "date_words", {"month": 6, "day": 12, "words": "love"}),
    Medal("halloween", "clock", "date_words", {"month": 10, "day": 31, "words": "spooky"}),
    Medal("monday-song", "clock", "weekday_words", {"weekday": 0, "words": "monday"}),
    Medal("friday-song", "clock", "weekday_words", {"weekday": 4, "words": "friday"}),
    Medal("leap-day", "clock", "date", {"month": 2, "day": 29}),
    total("lunch-100", "clock", "count:lunch", 100),
    total("night-100", "clock", "count:night", 100),
    total("dawn-100", "clock", "count:dawn", 100),
    total("weekend-500", "clock", "count:weekend", 500),
    # Release dates
    Medal("before-1970", "release", "released_before", {"year": 1970}),
    Medal("before-1950", "release", "released_before", {"year": 1950}),
    Medal("before-1930", "release", "released_before", {"year": 1930}),
    Medal("same-day", "release", "same_day"),
    Medal("anniversary", "release", "anniversary"),
    Medal("fifty-years", "release", "years_ago", {"years": 50}),
    total("decades-all", "release", "collection:decades", 8),
    total("old-200", "release", "count:old", 200),
    total("new-200", "release", "count:new", 200),
    # Rare songs (Last.fm)
    Medal("rare-1000", "rare", "listeners_below", {"n": 1000}, phase="rich", requires="lastfm"),
    Medal("rare-100", "rare", "listeners_below", {"n": 100}, phase="rich", requires="lastfm"),
    Medal("rare-50", "rare", "listeners_below", {"n": 50}, phase="rich", requires="lastfm"),
    Medal("rare-10", "rare", "listeners_below", {"n": 10}, phase="rich", requires="lastfm"),
    total("rare-collect-10", "rare", "distinct:rare100", 10, phase="rich", requires="lastfm"),
    total("rare-collect-50", "rare", "distinct:rare1000", 50, phase="rich", requires="lastfm"),
    Medal("megahit", "rare", "listeners_above", {"n": 2_000_000}, phase="rich", requires="lastfm"),
    # Artist size (fans)
    Medal("fans-1000", "size", "fans_below", {"n": 1000}, phase="rich"),
    Medal("fans-100", "size", "fans_below", {"n": 100}, phase="rich"),
    total("small-artists-50", "size", "distinct:small_artists", 50, phase="rich"),
    Medal("giant", "size", "fans_above", {"n": 10_000_000}, phase="rich"),
    # Runs, albums and lengths
    total("album-full", "runs", "albums", 1),
    total("album-full-5", "runs", "albums", 5),
    total("album-full-long", "runs", "albums_long", 1),
    total("same-artist-10", "runs", "run:artist", 10),
    total("same-artist-25", "runs", "run:artist", 25),
    total("diverse-20", "runs", "run:diverse", 20),
    total("same-song-3", "runs", "run:song", 3),
    total("nonstop-3h", "runs", "run:nonstop_hours", 3),
    total("nonstop-8h", "runs", "run:nonstop_hours", 8),
    total("short-run-10", "runs", "run:short", 10),
    Medal("long-song-10", "runs", "min_ms", {"ms": 600_000}),
    Medal("long-song-20", "runs", "min_ms", {"ms": 1_200_000}),
    Medal("short-song", "runs", "max_ms", {"ms": 60_000}),
    Medal("crowd", "runs", "min_artists", {"n": 4}),
    total("feats-100", "runs", "count:feats", 100),
    Medal("panel-playlist", "runs", "panel_playlist"),
    total("hooked", "runs", "hooked", 3),
    # Words in titles and names
    total("alphabet-20", "words", "collection:letters", 20),
    total("alphabet-26", "words", "collection:letters", 26),
    Medal("digit-artist", "words", "digit_artist"),
    total("rainbow", "words", "collection:rainbow", 7),
    total("weekdays", "words", "collection:weekdays", 7),
    total("seasons", "words", "collection:seasons", 4),
    total("numbers", "words", "collection:numbers", 10),
    total("love-100", "words", "count:love", 100),
    Medal("saudade", "words", "title_has", {"words": ("saudade", "saudades")}),
    total("moon-10", "words", "distinct:moon", 10),
    total("sun-10", "words", "distinct:sun", 10),
    total("places-5", "words", "collection:places", 5),
    total("places-15", "words", "collection:places", 15),
    Medal("long-title", "words", "title_words", {"n": 10}),
    Medal("self-titled", "words", "self_titled"),
    Medal("title-track", "words", "title_track"),
    Medal("namesake", "words", "namesake"),
    # Specific artists and songs
    Medal("linkin-paulo", "specific", "artist", {"names": ("linkin park",)}),
    Medal("apex-predator", "specific", "song", {"titles": ("you are the jumpmaster",)}),
    Medal("rickroll", "specific", "song", {"titles": ("never gonna give you up",), "artist": "rick astley"}),
    Medal("galileo", "specific", "song", {"titles": ("bohemian rhapsody",), "artist": "queen"}),
    Medal("ipanema", "specific", "song", {"titles": ("garota de ipanema", "the girl from ipanema")}),
    Medal("sandstorm", "specific", "song", {"titles": ("sandstorm",), "artist": "darude"}),
    Medal("karaoke", "specific", "song", {"titles": ("evidencias",)}),
    # Friends
    total("match-1", "friends", "distinct:matched", 1, phase="room"),
    total("match-10", "friends", "distinct:matched", 10, phase="room"),
    total("match-50", "friends", "distinct:matched", 50, phase="room"),
    total("match-sync", "friends", "room:sync", 1, phase="room"),
    total("match-everyone", "friends", "room:everyone", 1, phase="room"),
    total("trio", "friends", "room:trio", 1, phase="room", song_from="trio"),
    total("trendsetter", "friends", "room:trend", 5, phase="room", song=False),
    total("follower", "friends", "room:follow", 5, phase="room", song=False),
    # The panel
    event("roulette-1", "events:roulette"),
    event("roulette-50", "events:roulette", 50),
    event("roulette-rare", "events:roulette_rare"),
    event("sense-1", "events:sense"),
    event("sense-text", "events:sense_text"),
    event("rabbit-1", "events:rabbit"),
    event("news-1", "events:news"),
    event("listeners-tight", "events:listeners_tight", requires="lastfm"),
    event("all-discoveries", "kinds", 4),
    event("playlist-1", "events:playlist"),
    event("favorite-1", "events:favorite"),
    event("review-1", "events:reviews"),
    event("review-10", "events:reviews", 10),
    event("review-five", "events:review_five"),
    event("review-long", "events:review_long"),
    event("block-1", "events:block"),
    event("artists-search-10", "events:artist", 10),
    # Monthly titles won
    total("title-1", "titles", "titles:count", 1, phase="titles", song=False),
    total("title-kinds-3", "titles", "titles:kinds", 3, phase="titles", song=False),
    total("title-same-3", "titles", "titles:streak", 3, phase="titles", song=False),
    total("title-double", "titles", "titles:double", 2, phase="titles", song=False),
    total("title-all", "titles", "titles:kinds", 8, phase="titles", song=False),
) + tuple(Medal(f"game-{game.slug}", "games", "game", {"game": game.slug}) for game in GAMES)

BY_ID = {medal.id: medal for medal in MEDALS}
GAMES_BY_SLUG = {game.slug: game for game in GAMES}
