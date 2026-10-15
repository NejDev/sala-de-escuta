# Achievements catalog (SPOILERS)

> **Owner: don't read this file.** You asked for the medals to be a surprise. Everything below is what earns them.

Companion of `2026-10-15-achievements-design.md`. The code transcribes this file into `spotify_assistant/medals.py`
(rules) and `spotify_assistant/medal_names.py` (names and "how" lines, keys `medal.<id>` and `medal.<id>.how`).
Names and "how" lines show as written; the "how" line only ever reaches the person who earned the medal.

## Conventions

- "A play" is one entry of `plays.json`. "Local" times use the room's clock. A day runs from 00:00 to 23:59 local.
- `base` title: `curation.base_title()` then `curation.normalize()` (no version, no accents, lower case, words split by
  spaces). Word tests match whole words (or whole phrases, for multi-word entries) of the normalized title.
- "Release year/date" comes from `album.release` (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`); rules needing a day skip plays
  whose release has no day.
- "Listeners" = Last.fm listeners of a song **with a record** (a song Last.fm doesn't know never counts). Medals marked
  **[key]** exist only with `LASTFM_API_KEY`.
- "Fans" = fans of the play's first credited artist (cache by name). Marked **[fans]**.
- "Since joining" counts include the 90 days of history processed at joining.
- The song saved with a medal: for a single play, that play; for a total, the play that crossed the line; for a day or
  a run, the last play of it; for friends, the matched song; panel and titles medals have no song.

## Word lists (normalized; pt, en, es)

`|` joins words of one group; a collection counts groups, not words.

- Love: `love|amor|amore|amour|liebe|amar|amo`.
- Spooky: `ghost|fantasma|witch|bruxa|bruja|monster|monstro|zombie|zumbi|vampire|vampiro|halloween|devil|diabo|diablo|skeleton|esqueleto|haunted|assombrada`.
- Moon: `moon|lua|luna|lune|luar`. Sun: `sun|sol|soleil|sunshine|sunny|ensolarado`.
- Monday: `monday|segunda|lunes`. Friday: `friday|sexta|sextou|viernes`.
- Weekdays (7 groups): `monday|segunda|lunes`, `tuesday|terca|martes`, `wednesday|quarta|miercoles`,
  `thursday|quinta|jueves`, `friday|sexta|viernes`, `saturday|sabado`, `sunday|domingo`.
- Seasons (4 groups): `spring|primavera`, `summer|verao|verano`, `autumn|fall|outono|otono`, `winter|inverno|invierno`.
- Rainbow (7 groups): `red|vermelho|vermelha|rojo|roja`, `orange|laranja|naranja`,
  `yellow|amarelo|amarela|amarillo|amarilla`, `green|verde`, `blue|azul`, `indigo|anil`,
  `violet|purple|roxo|roxa|violeta|morado|lilas`.
- Numbers (10 groups, digits or words): `1|one|um|uma|uno`, `2|two|dois|duas|dos`, `3|three|tres`,
  `4|four|quatro|cuatro`, `5|five|cinco`, `6|six|seis`, `7|seven|sete|siete`, `8|eight|oito|ocho`, `9|nine|nove|nueve`,
  `10|ten|dez|diez`.
- Places (one group each): `rio|rio de janeiro`, `sao paulo`, `bahia`, `recife`, `salvador`, `brasilia`, `belem`,
  `manaus`, `minas|minas gerais`, `ipanema`, `copacabana`, `brasil|brazil`, `paris`, `london|londres`, `tokyo|toquio`,
  `berlin|berlim`, `roma|rome`, `madrid`, `lisboa|lisbon`, `new york|nova york|nova iorque`, `chicago`, `california`,
  `texas`, `memphis`, `nashville`, `detroit`, `havana`, `cuba`, `mexico`, `buenos aires`, `argentina`, `lima`,
  `bogota`, `jamaica`, `africa`, `lagos`, `cairo`, `istanbul`, `moscow|moscou`, `india`, `bombay|mumbai`, `bangkok`,
  `seoul|seul`, `hong kong`, `sydney`, `amsterdam`, `dublin`, `vienna|viena`, `venice|veneza`, `napoli|napoles|naples`,
  `barcelona`, `sevilla|seville`, `hollywood`, `las vegas`, `miami`.

## Medals

`id | rule | name pt | name en | how pt | how en`

### Volume (13)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| first-play | 1 play since joining | Agulha no disco | Needle Drop | Ouviu a primeira música nas conquistas. | Played your first song in achievements. |
| plays-100 | 100 plays | Cem faixas | Hundred Tracks | Ouviu 100 músicas. | Played 100 songs. |
| plays-1000 | 1,000 plays | Mil e uma | A Thousand and One | Ouviu 1.000 músicas. | Played 1,000 songs. |
| plays-5000 | 5,000 plays | Jukebox ambulante | Walking Jukebox | Ouviu 5.000 músicas. | Played 5,000 songs. |
| plays-10000 | 10,000 plays | Lenda do toca-discos | Turntable Legend | Ouviu 10.000 músicas. | Played 10,000 songs. |
| hours-24 | 24 hours of listening (sum of durations) | Um dia inteiro | One Whole Day | Somou 24 horas de música. | Added up 24 hours of music. |
| hours-100 | 100 hours | Cem horas de voo | Hundred Flight Hours | Somou 100 horas de música. | Added up 100 hours of music. |
| hours-500 | 500 hours | Tímpano de aço | Steel Eardrums | Somou 500 horas de música. | Added up 500 hours of music. |
| artists-50 | 50 different artists (any credited) | Agenda cheia | Full Address Book | Ouviu 50 artistas diferentes. | Played 50 different artists. |
| artists-250 | 250 different artists | Festival particular | Private Festival | Ouviu 250 artistas diferentes. | Played 250 different artists. |
| artists-1000 | 1,000 different artists | Enciclopédia | Encyclopedia | Ouviu 1.000 artistas diferentes. | Played 1,000 different artists. |
| songs-500 | 500 different songs | Repertório | Repertoire | Ouviu 500 músicas diferentes. | Played 500 different songs. |
| songs-2000 | 2,000 different songs | Acervo | The Archive | Ouviu 2.000 músicas diferentes. | Played 2,000 different songs. |

### A single day (11)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| day-plays-50 | 50 plays in one day | Dia de faxina | Cleaning Day | Ouviu 50 músicas num só dia. | Played 50 songs in a single day. |
| day-plays-100 | 100 plays in one day | Trilha do dia inteiro | All-Day Soundtrack | Ouviu 100 músicas num só dia. | Played 100 songs in a single day. |
| day-hours-5 | 5 hours of listening in one day | Maratona | Marathon | Ouviu 5 horas de música num dia. | Listened to 5 hours of music in a day. |
| day-hours-10 | 10 hours in one day | Ultramaratona | Ultramarathon | Ouviu 10 horas de música num dia. | Listened to 10 hours of music in a day. |
| day-artists-30 | 30 different artists in one day | Zapeando | Channel Surfer | Ouviu 30 artistas diferentes num dia. | Played 30 different artists in a day. |
| day-repeat-10 | the same song 10 times in one day | Repeteco | On Repeat | Ouviu a mesma música 10 vezes num dia. | Played the same song 10 times in a day. |
| day-repeat-25 | the same song 25 times in one day | Disco arranhado | Broken Record | Ouviu a mesma música 25 vezes num dia. | Played the same song 25 times in a day. |
| day-parts | plays in all four quarters of one day (0–6, 6–12, 12–18, 18–24 h) | Dia redondo | Round the Clock | Ouviu música de madrugada, de manhã, de tarde e de noite no mesmo dia. | Played music at dawn, morning, afternoon and night on the same day. |
| day-clock-12 | plays in 12 different clock hours of one day | Relógio cheio | Full Clock | Ouviu música em 12 horas diferentes do mesmo dia. | Played music in 12 different hours of the same day. |
| day-decades-5 | songs released in 5 different decades in one day | Máquina do tempo | Time Machine | Ouviu músicas de 5 décadas diferentes num dia. | Played songs from 5 different decades in a day. |
| day-extremes | **[fans]** in one day, an artist under 1,000 fans and one over 10,000,000 | Do porão ao estádio | Basement to Stadium | No mesmo dia, ouviu um artista com menos de mil fãs e outro com mais de 10 milhões. | On the same day, played an artist with under a thousand fans and one with over 10 million. |

### Streaks and returns (6)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| streak-7 | plays on 7 days in a row | Sequência | Streak | Ouviu música 7 dias seguidos. | Played music 7 days in a row. |
| streak-30 | 30 days in a row | Mês sem silêncio | A Month Without Silence | Ouviu música 30 dias seguidos. | Played music 30 days in a row. |
| streak-100 | 100 days in a row | Cem dias de som | Hundred Days of Sound | Ouviu música 100 dias seguidos. | Played music 100 days in a row. |
| streak-365 | 365 days in a row | Volta ao sol | Around the Sun | Ouviu música todos os dias por um ano. | Played music every day for a year. |
| comeback | a play after 14 or more days without any (since joining) | De volta ao palco | Back on Stage | Voltou a ouvir música depois de duas semanas em silêncio. | Came back to music after two silent weeks. |
| weekends-4 | plays on both Saturday and Sunday, 4 weekends in a row | Fim de semana sagrado | Sacred Weekends | Ouviu música no sábado e no domingo por 4 fins de semana seguidos. | Played music on Saturday and Sunday for 4 weekends in a row. |

### Clock and calendar (17)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| midnight | a play at 00:00 (that minute) | Badalada | Midnight Chime | Ouviu uma música à meia-noite em ponto. | Played a song at midnight sharp. |
| three-am | a play from 3:00 to 3:59 | Hora morta | Witching Hour | Ouviu música às 3 da manhã. | Played music at 3 a.m. |
| sunrise | a play from 5:00 to 5:29 | Primeiro raio | First Light | Ouviu música antes das 5h30 da manhã. | Played music before 5:30 a.m. |
| new-year | a play from 23:50 on Dec 31 to 00:10 on Jan 1 | Virada | Happy New Year | Ouviu música na virada do ano. | Played music as the new year began. |
| christmas | a play on Dec 25 | Noite feliz | Silent Night | Ouviu música no Natal. | Played music on Christmas Day. |
| music-day | a play on Jun 21 | Festa da música | Fête de la Musique | Ouviu música no Dia da Música, 21 de junho. | Played music on Music Day, June 21. |
| friday-13 | a play on a Friday the 13th | Sexta-feira 13 | Friday the 13th | Ouviu música numa sexta-feira 13. | Played music on a Friday the 13th. |
| carnival | a play on Carnival Monday or Tuesday (Easter − 48 / − 47 days) | Folião | Reveler | Ouviu música no Carnaval. | Played music during Carnival. |
| lovebirds | on Jun 12, a song with a love word | Dia dos namorados | Lovebirds | Ouviu uma música de amor no Dia dos Namorados. | Played a love song on Brazil's Valentine's Day, June 12. |
| halloween | on Oct 31, a song with a spooky word | Gostosuras | Trick or Treat | Ouviu uma música assustadora no Halloween. | Played a spooky song on Halloween. |
| monday-song | on a Monday, a song with a Monday word | Segunda de novo | Monday Again | Ouviu uma música sobre segunda-feira numa segunda. | Played a song about Monday on a Monday. |
| friday-song | on a Friday, a song with a Friday word | Sextou | TGIF | Ouviu uma música sobre sexta-feira numa sexta. | Played a song about Friday on a Friday. |
| leap-day | a play on Feb 29 | Bissexto | Leap Day | Ouviu música num 29 de fevereiro. | Played music on February 29. |
| lunch-100 | 100 plays from 12:00 to 13:59 | Almoço com trilha | Lunch Soundtrack | Ouviu 100 músicas na hora do almoço. | Played 100 songs at lunchtime. |
| night-100 | 100 plays from 0:00 to 4:59 | Vampiro | Vampire | Ouviu 100 músicas de madrugada. | Played 100 songs in the small hours. |
| dawn-100 | 100 plays from 5:00 to 7:59 | Galo cantor | Singing Rooster | Ouviu 100 músicas bem cedo, entre 5h e 8h. | Played 100 songs early, between 5 and 8 a.m. |
| weekend-500 | 500 plays on Saturdays and Sundays | Sabadou | Weekend Warrior | Ouviu 500 músicas em fins de semana. | Played 500 songs on weekends. |

### Release dates (9)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| before-1970 | a song released before 1970 | Arqueólogo | Archaeologist | Ouviu uma música lançada antes de 1970. | Played a song released before 1970. |
| before-1950 | released before 1950 | Fóssil | Fossil | Ouviu uma música lançada antes de 1950. | Played a song released before 1950. |
| before-1930 | released before 1930 | Gramofone | Gramophone | Ouviu uma música lançada antes de 1930. | Played a song released before 1930. |
| same-day | a song played on its release day | Saiu do forno | Fresh Out of the Oven | Ouviu uma música no dia em que ela saiu. | Played a song on the day it came out. |
| anniversary | a song played on its release's day and month, a year or more later | Parabéns, disco | Happy Birthday, Record | Ouviu uma música no aniversário do lançamento dela. | Played a song on its release anniversary. |
| fifty-years | a song released in the year 50 years before the play | Bodas de ouro | Golden Anniversary | Ouviu uma música lançada exatamente 50 anos antes. | Played a song released exactly 50 years earlier. |
| decades-all | songs from every decade 1950s–2020s (collection of 8) | Todas as décadas | Every Decade | Ouviu músicas de todas as décadas, dos anos 50 aos 2020. | Played songs from every decade, the 1950s to the 2020s. |
| old-200 | 200 plays of songs released 25 or more years before the play | Saudosista | Nostalgic | Ouviu 200 músicas com mais de 25 anos. | Played 200 songs over 25 years old. |
| new-200 | 200 plays of songs released within 30 days before the play | Antenado | Ahead of the Curve | Ouviu 200 músicas no primeiro mês depois do lançamento. | Played 200 songs within a month of their release. |

### Rare songs (7, all [key])

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| rare-1000 | a song under 1,000 listeners | Garimpeiro | Prospector | Ouviu uma música com menos de mil ouvintes no Last.fm. | Played a song with under a thousand listeners on Last.fm. |
| rare-100 | under 100 listeners | Joia rara | Rare Gem | Ouviu uma música com menos de 100 ouvintes no Last.fm. | Played a song with under 100 listeners on Last.fm. |
| rare-50 | under 50 listeners | Quase segredo | Almost a Secret | Ouviu uma música com menos de 50 ouvintes no Last.fm. | Played a song with under 50 listeners on Last.fm. |
| rare-10 | under 10 listeners | Ouvido único | One of a Kind | Ouviu uma música com menos de 10 ouvintes no Last.fm. | Played a song with under 10 listeners on Last.fm. |
| rare-collect-10 | 10 different songs under 100 listeners | Colecionador de raridades | Rarity Collector | Ouviu 10 músicas diferentes com menos de 100 ouvintes no Last.fm. | Played 10 different songs with under 100 listeners on Last.fm. |
| rare-collect-50 | 50 different songs under 1,000 listeners | Veio farto | Rich Vein | Ouviu 50 músicas diferentes com menos de mil ouvintes no Last.fm. | Played 50 different songs with under a thousand listeners on Last.fm. |
| megahit | a song over 2,000,000 listeners | Hino mundial | World Anthem | Ouviu uma música com mais de 2 milhões de ouvintes no Last.fm. | Played a song with over 2 million listeners on Last.fm. |

### Artist size (4, all [fans])

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| fans-1000 | an artist under 1,000 fans | Palco pequeno | Small Stage | Ouviu um artista com menos de mil fãs. | Played an artist with under a thousand fans. |
| fans-100 | an artist under 100 fans | Show no quintal | Backyard Show | Ouviu um artista com menos de 100 fãs. | Played an artist with under 100 fans. |
| small-artists-50 | 50 different artists under 1,000 fans | Olheiro | Talent Scout | Ouviu 50 artistas diferentes com menos de mil fãs. | Played 50 different artists with under a thousand fans. |
| giant | an artist over 10,000,000 fans | Estádio lotado | Sold-Out Stadium | Ouviu um artista com mais de 10 milhões de fãs. | Played an artist with over 10 million fans. |

### Runs, albums and lengths (17)

A run is consecutive plays in time order. "Nonstop" means each play starts within 5 minutes after the previous one
ends (gap between `at`s ≤ the later play's duration + 5 min).

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| album-full | a whole album in order: plays of tracks 1..N of one album, consecutive, N = the album's total and N ≥ 6 | Lado A, lado B | Side A, Side B | Ouviu um álbum inteiro, do começo ao fim, na ordem. | Played a whole album, start to finish, in order. |
| album-full-5 | 5 different whole albums | Ouvinte de álbum | Album Listener | Ouviu 5 álbuns inteiros, na ordem. | Played 5 whole albums in order. |
| album-full-long | a whole album with 15 or more tracks | Álbum duplo | Double Album | Ouviu inteiro, na ordem, um álbum com 15 faixas ou mais. | Played an album of 15 or more tracks whole, in order. |
| same-artist-10 | 10 plays in a row with the same first artist | Fã de carteirinha | Card-Carrying Fan | Ouviu 10 músicas seguidas do mesmo artista. | Played 10 songs in a row by the same artist. |
| same-artist-25 | 25 in a row | Discografia | Deep Dive | Ouviu 25 músicas seguidas do mesmo artista. | Played 25 songs in a row by the same artist. |
| diverse-20 | 20 plays in a row, all with different first artists | Rádio pirata | Pirate Radio | Ouviu 20 músicas seguidas, cada uma de um artista diferente. | Played 20 songs in a row, each by a different artist. |
| same-song-3 | the same song 3 times in a row | Mais uma vez | One More Time | Ouviu a mesma música 3 vezes seguidas. | Played the same song 3 times in a row. |
| nonstop-3h | 3 hours nonstop | Sem intervalo | No Intermission | Ouviu 3 horas de música sem pausa. | Listened to 3 hours of music without a break. |
| nonstop-8h | 8 hours nonstop | Plantão | Night Shift | Ouviu 8 horas de música sem pausa. | Listened to 8 hours of music without a break. |
| short-run-10 | 10 plays in a row, each under 2 minutes | Pressa | In a Hurry | Ouviu 10 músicas seguidas com menos de 2 minutos cada. | Played 10 songs in a row, each under 2 minutes. |
| long-song-10 | a song of 10 minutes or more | Épico | Epic | Ouviu uma música de 10 minutos ou mais. | Played a song of 10 minutes or more. |
| long-song-20 | 20 minutes or more | Viagem longa | Long Haul | Ouviu uma música de 20 minutos ou mais. | Played a song of 20 minutes or more. |
| short-song | a song under 1 minute | Vinheta | Jingle | Ouviu uma música com menos de 1 minuto. | Played a song under a minute long. |
| crowd | a song with 4 or more credited artists | Coletivo | Collective | Ouviu uma música com 4 artistas ou mais nos créditos. | Played a song crediting 4 or more artists. |
| feats-100 | 100 plays with 2 or more credited artists | Participação especial | Special Guest | Ouviu 100 músicas com participação de outro artista. | Played 100 songs featuring another artist. |
| panel-playlist | a play whose context is a playlist the panel made for this person (a favorite's playlist or one made from a discovery) | Prova do pudim | Proof of the Pudding | Ouviu uma playlist que a sala montou para você. | Played a playlist the room made for you. |
| hooked | a song the panel found for this person (in their recent finds) played 3 times | Fisgado | Hooked | Ouviu 3 vezes uma música que a sala descobriu para você. | Played a song the room found for you 3 times. |

### Words in titles and names (17)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| alphabet-20 | artists whose names start with 20 different letters A–Z | Soletrando | Spelling Bee | Ouviu artistas com 20 iniciais diferentes. | Played artists with 20 different initials. |
| alphabet-26 | all 26 letters | De A a Z | A to Z | Ouviu artistas com todas as letras do alfabeto. | Played artists for every letter of the alphabet. |
| digit-artist | an artist whose name starts with a digit | Numerologia | Numerology | Ouviu um artista cujo nome começa com um número. | Played an artist whose name starts with a number. |
| rainbow | titles with all 7 rainbow color groups | Arco-íris | Rainbow | Ouviu músicas com as 7 cores do arco-íris no título. | Played songs with all 7 rainbow colors in their titles. |
| weekdays | titles with all 7 weekday groups | Semana completa | Full Week | Ouviu músicas com os 7 dias da semana no título. | Played songs with all 7 days of the week in their titles. |
| seasons | titles with all 4 season groups | Quatro estações | Four Seasons | Ouviu músicas com as 4 estações do ano no título. | Played songs with all 4 seasons in their titles. |
| numbers | titles with all 10 number groups | Contagem regressiva | Countdown | Ouviu músicas com os números de 1 a 10 no título. | Played songs with the numbers 1 to 10 in their titles. |
| love-100 | 100 plays of songs with a love word | Romântico incurável | Hopeless Romantic | Ouviu 100 músicas com "amor" no título. | Played 100 songs with "love" in the title. |
| saudade | a song with "saudade" or "saudades" in the title | Saudade | Saudade | Ouviu uma música com "saudade" no título. | Played a song with "saudade" in the title. |
| moon-10 | 10 different songs with a moon word | Lunático | Lunatic | Ouviu 10 músicas diferentes com a lua no título. | Played 10 different songs with the moon in the title. |
| sun-10 | 10 different songs with a sun word | Banho de sol | Sunbather | Ouviu 10 músicas diferentes com o sol no título. | Played 10 different songs with the sun in the title. |
| places-5 | titles naming 5 different places from the list | Turista | Tourist | Ouviu músicas com 5 lugares diferentes no título. | Played songs naming 5 different places. |
| places-15 | 15 different places | Passaporte carimbado | Stamped Passport | Ouviu músicas com 15 lugares diferentes no título. | Played songs naming 15 different places. |
| long-title | a base title with 10 or more words | Fôlego | Out of Breath | Ouviu uma música com 10 palavras ou mais no título. | Played a song with 10 or more words in its title. |
| self-titled | a song whose base title equals its first artist's normalized name | Autorretrato | Self-Portrait | Ouviu uma música com o mesmo nome do artista. | Played a song named after its own artist. |
| title-track | a song whose base title equals its album's base name, on an album (type `album`) | Faixa-título | Title Track | Ouviu a faixa que dá nome ao álbum. | Played the track an album is named after. |
| namesake | an artist whose normalized name contains the person's normalized first name as a word (first names of 3+ letters) | Xará | Namesake | Ouviu um artista com o seu nome. | Played an artist who shares your name. |

### Specific artists and songs (7)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| linkin-paulo | any song with Linkin Park among its artists | Linkin Paulo | Linkin Paulo | Ouviu Linkin Park. | Played Linkin Park. |
| apex-predator | a song whose base title is "you are the jumpmaster" (Apex Legends' jump music; any artist) | Predador Apex | Apex Predator | Ouviu a música do salto do Apex Legends. | Played the Apex Legends jump music. |
| rickroll | "never gonna give you up" by Rick Astley | Rickrollado | Rickrolled | Ouviu "Never Gonna Give You Up". | Played "Never Gonna Give You Up". |
| galileo | "bohemian rhapsody" by Queen | Galileo | Galileo | Ouviu "Bohemian Rhapsody". | Played "Bohemian Rhapsody". |
| ipanema | base title "garota de ipanema" or "the girl from ipanema" (any artist) | Coisa mais linda | Tall and Tan | Ouviu "Garota de Ipanema". | Played "The Girl from Ipanema". |
| sandstorm | "sandstorm" by Darude | Du du du du duuu | Du Du Du Du Duuu | Ouviu "Sandstorm". | Played "Sandstorm". |
| karaoke | base title "evidencias" (any artist) | Hino do karaokê | Karaoke Anthem | Ouviu "Evidências". | Played "Evidências". |

### Friends (8)

A match is the same song played by two participants within 6 hours of each other (as in Friends). Counted from the
plays of participants only.

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| match-1 | a first match | Sintonia | In Tune | Ouviu a mesma música que alguém da sala, com poucas horas de diferença. | Played the same song as someone in the room, a few hours apart. |
| match-10 | matches on 10 different songs | Mesma frequência | Same Wavelength | Coincidiu com a sala em 10 músicas diferentes. | Matched the room on 10 different songs. |
| match-50 | 50 different songs | Alma gêmea musical | Musical Soulmate | Coincidiu com a sala em 50 músicas diferentes. | Matched the room on 50 different songs. |
| match-sync | a match within 5 minutes | Sincronizados | In Sync | Ouviu a mesma música que alguém da sala com até 5 minutos de diferença. | Played the same song as someone in the room within 5 minutes. |
| match-everyone | matches with every other participant (2 or more others) | Turma toda | The Whole Gang | Coincidiu com cada pessoa que participa das conquistas. | Matched every other person taking part. |
| trio | the same song by 3 participants within 6 hours | Trio elétrico | Trio Elétrico | Três pessoas da sala ouviram a mesma música em poucas horas. | Three people in the room played the same song within hours. |
| trendsetter | 5 artists another participant heard for the first time within 30 days after you did | Influenciador | Influencer | Alguém da sala começou a ouvir 5 artistas depois de você. | Someone in the room picked up 5 artists after you did. |
| follower | 5 artists you heard for the first time within 30 days after another participant did | Bom ouvinte | Good Listener | Começou a ouvir 5 artistas depois de alguém da sala. | Picked up 5 artists after someone in the room did. |

### The panel (17)

Events counted from joining on.

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| roulette-1 | a first roulette spin | Primeiro giro | First Spin | Girou a roleta pela primeira vez. | Spun the roulette for the first time. |
| roulette-50 | 50 roulette spins | Cassino | Casino | Girou a roleta 50 vezes. | Spun the roulette 50 times. |
| roulette-rare | a spin with "little-known genre" | Terra incógnita | Terra Incognita | Girou a roleta num gênero pouco conhecido. | Spun the roulette on a little-known genre. |
| sense-1 | a first Sensation | À flor da pele | Gut Feeling | Buscou uma sensação pela primeira vez. | Looked for a sensation for the first time. |
| sense-text | a Sensation from typed words | Poeta | Poet | Escreveu o que estava sentindo para buscar músicas. | Wrote down a feeling to find songs. |
| rabbit-1 | a first rabbit hole | Alice | Alice | Entrou na toca do coelho. | Went down the rabbit hole. |
| news-1 | a first New releases search | Primeira fila | Front Row | Buscou lançamentos pela primeira vez. | Looked for new releases for the first time. |
| listeners-tight | **[key]** a discovery with a listener cap of 50 | Agulha no palheiro | Needle in a Haystack | Buscou músicas com no máximo 50 ouvintes. | Searched for songs with 50 listeners at most. |
| all-discoveries | used roulette, Sensations, rabbit hole and New releases | Volta completa | Grand Tour | Usou as quatro descobertas da sala. | Used all four of the room's discoveries. |
| playlist-1 | a first playlist made from a discovery | DJ | DJ | Criou uma playlist a partir de uma descoberta. | Made a playlist from a discovery. |
| favorite-1 | a first self-updating favorite | Piloto automático | Autopilot | Criou uma favorita que se atualiza sozinha. | Created a favorite that updates itself. |
| review-1 | a first album review | Primeira crítica | First Review | Escreveu a primeira resenha de álbum. | Wrote your first album review. |
| review-10 | 10 album reviews | Crítico | Critic | Escreveu 10 resenhas de álbum. | Wrote 10 album reviews. |
| review-five | a review with 5 stars | Obra-prima | Masterpiece | Deu 5 estrelas a um álbum. | Gave an album 5 stars. |
| review-long | a public review with 500 or more characters | Ensaísta | Essayist | Publicou uma resenha com mais de 500 caracteres. | Published a review over 500 characters long. |
| block-1 | an artist blocked | Não, obrigado | No, Thanks | Bloqueou um artista. | Blocked an artist. |
| artists-search-10 | 10 searches in Artists | Detetive | Detective | Pesquisou 10 artistas. | Looked up 10 artists. |

### Monthly titles won (5)

| id | rule | pt | en | how pt | how en |
|---|---|---|---|---|---|
| title-1 | a first monthly title | Coroado | Crowned | Ganhou um título do mês. | Won a monthly title. |
| title-kinds-3 | 3 different titles | Multicampeão | Multi-Champion | Ganhou 3 títulos do mês diferentes. | Won 3 different monthly titles. |
| title-same-3 | the same title 3 months in a row | Tricampeão | Three-Peat | Ganhou o mesmo título 3 meses seguidos. | Won the same title 3 months in a row. |
| title-double | 2 titles in the same month | Dobradinha | Double | Ganhou 2 títulos no mesmo mês. | Won 2 titles in the same month. |
| title-all | all 8 titles (over time) | Lenda da sala | Room Legend | Ganhou todos os 8 títulos do mês. | Won all 8 monthly titles. |

**Total besides games: 138** (130 without a Last.fm key).

### Games

One medal per game, named after the game (same name in both languages), id `game-<slug>`. "How" line for all of them
(one shared key, `medal.game.how`): pt "Ouviu música de {game}." / en "Played music from {game}.".

A play matches when a game name appears as whole words in the play's normalized album name or title (plus a soundtrack
hint in the same text when the game's `context` is true: `soundtrack, ost, original, from, game, video game, theme,
music from`; "original mix" doesn't count), or when a credited artist is one of the game's own artists.

40 games, chosen by the audience of their music on the catalog: the mean rank of the three most popular
tracks each rule matches (covers count), keeping a score of 400k or more, plus Apex Legends (asked by the owner) and
Free Fire (the Brazilian mobile pick). Checked against known non-game songs with the same words (Beyonce's "Halo",
Drake's "Final Fantasy", the Netflix Witcher...): none match. Composers who scored several franchises are left out
of `artists`; a few names use specific phrases ("doom eternal", "witcher 3", "hades ii") because the plain word
hit other music. "Original Mix" (dance tracks) never counts as a soundtrack hint. Research notes and rejected
candidates: the session's scratchpad `games/games.md` (not kept in the repo).

```python
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
```

## Code: `spotify_assistant/medals.py`

The rows above, as the module the engine reads (Task 2 of the plan copies this block; `GAMES` comes from the games
section once the research is in).

```python
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

GAMES: tuple[Game, ...] = ()  # filled from the games section


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
```
