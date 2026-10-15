"""Interface language: Brazilian Portuguese or English.

The browser keeps the person's choice in the "lang" cookie (falling back to
Accept-Language). Each request, and each discovery running in the background,
sets the language for its own thread with use(); t() then reads messages from
MESSAGES. The command line uses SALA_LANG from .env; a favorite's automatic
updates use the language of whoever created it.
"""
from __future__ import annotations

import threading
from datetime import date, datetime

LANGUAGES = ("pt", "en")
DEFAULT = "en"
COOKIE = "lang"

_local = threading.local()


def use(lang: str | None) -> str:
    """Sets the language for the current thread and returns the one actually used."""
    _local.lang = lang if lang in LANGUAGES else DEFAULT
    return _local.lang


def current() -> str:
    return getattr(_local, "lang", DEFAULT)


def pick(cookie: str | None, accept_language: str | None = None) -> str:
    """The cookie wins; otherwise the first supported language the browser asks for."""
    if cookie in LANGUAGES:
        return cookie
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return DEFAULT


def t(key: str, **params: object) -> str:
    """Message in the current language. Tuples are (singular, plural), chosen by `count`."""
    text = MESSAGES[current()].get(key)
    if text is None:
        text = MESSAGES[DEFAULT][key]
    if isinstance(text, tuple):
        text = text[0] if params.get("count") == 1 else text[1]
    return text.format(**params)


def number(value: int) -> str:
    """1.234 in Portuguese, 1,234 in English."""
    text = f"{value:,}"
    return text.replace(",", ".") if current() == "pt" else text


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def long_date(day: date) -> str:
    return f"{day:%d/%m/%Y}" if current() == "pt" else f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


def short_date(day: date) -> str:
    return f"{day:%d/%m}" if current() == "pt" else f"{MONTHS[day.month - 1]} {day.day}"


def clock(moment: datetime) -> str:
    if current() == "pt":
        return f"{moment:%H:%M}"
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment:%M} {'AM' if moment.hour < 12 else 'PM'}"


# Placeholders must match across languages (tests/test_i18n.py checks it).
MESSAGES: dict[str, dict[str, str | tuple[str, str]]] = {
    "pt": {
        # Reviews
        "reviews.invalid_album": "Não achei esse álbum no Spotify.",
        "reviews.bad_rating": "A nota vai de meia estrela a 5 estrelas.",
        "reviews.too_long": "A resenha pode ter até {max} caracteres.",
        "reviews.empty": "Dê uma nota ou escreva alguma coisa.",
        "reviews.saved": "Resenha salva. Só você vê.",
        "reviews.saved_public": "Resenha salva e aberta para a sala.",
        "reviews.deleted": "Resenha apagada.",
        "reviews.not_found": "Você não tem resenha deste álbum.",
        # Friends: who may use it
        "friends.off": "O Amigos não está disponível para você.",
        "err.which_person": "Escolha uma pessoa da sala.",
        "friends.access_on": "{name} pode usar o Amigos.",
        "friends.access_off": "{name} não usa mais o Amigos; o histórico dessa pessoa foi apagado.",
        "friends.access_new_on": "Quem entrar na sala daqui para frente já pode usar o Amigos.",
        "friends.access_new_off": "Quem entrar na sala daqui para frente começa sem o Amigos, até você liberar.",
        # Friends
        "friends.need_auth": "Para participar, autorize o Spotify de novo (só uma vez).",
        "friends.joined": "Pronto! Agora a sala lê o que você ouve a cada 15 minutos.",
        "friends.left": "Você saiu. Ninguém vê mais o que você ouve.",
        "friends.forgot": "Você saiu e o seu histórico foi apagado.",
        "artists.choose": "Tem mais de um artista chamado “{name}”. Qual é o seu?",
        # Artists search
        "err.artist_name": "Digite o nome de um artista ou banda.",
        "artists.looking": "Procurando {name} e quem faz parte…",
        "artists.reading": "Lendo tudo de {name} ({progress} de {total}), devagar para o Spotify não pausar… {count} até agora.",
        "artists.not_found": "Não achei “{name}”. Confira o nome do artista ou da banda.",
        "artists.none": "Nenhum lançamento de {name} no Spotify.",
        "artists.done": ("1 lançamento de {name}.", "{count} lançamentos de {name}."),
        "artists.done_group": ("1 lançamento de {name} e de quem faz parte.",
                               "{count} lançamentos de {name} e de quem faz parte."),
        "artists.no_track": "Não achei essa participação no álbum.",
        # New releases from today
        "news.none_today": "Nenhum lançamento de {genre} nesse tamanho hoje. Aumente o período ou o tamanho.",
        "news.done_today": ("1 lançamento de {genre} de hoje.", "{count} lançamentos de {genre} de hoje."),
        # Pinned playlists and the bar
        "fav.hidden": "{name} saiu da barra e não se atualiza mais. Para trazer de volta, use o + da barra.",
        "fav.shown": "{name} voltou para a barra.",
        "fav.pinned": "{name} está na barra.",
        "fav.unpinned": "{name} saiu da barra. A playlist continua no seu Spotify.",
        "fav.already": "Essa playlist já está na barra.",
        "fav.too_many_pinned": "Dá para fixar até {max} playlists. Tire uma da barra para pôr outra.",
        "fav.pinned_no_update": "Playlists fixadas não se atualizam sozinhas.",
        "fav.pinned_only_add": "Essa playlist ganha músicas novas a cada atualização; adicionar à mão não adianta.",
        # The heart (Spotify library)
        "err.like_what": "Nada para curtir aqui.",
        "liked.need_auth": "Para curtir por aqui, autorize o Spotify de novo (só uma vez).",
        "liked.track_on": "Salva nas suas Músicas Curtidas.",
        "liked.track_off": "Removida das Músicas Curtidas.",
        "liked.episode_on": "Salvo nos seus episódios.",
        "liked.episode_off": "Removido dos seus episódios.",
        # Favorites (the bar)
        "every.daily": "todo dia",
        "every.weekly": "toda semana",
        "every.monthly": "todo mês",
        "fav.bad_every": "Frequência inválida.",
        "fav.needs_discovery": "Só dá para atualizar sozinha uma playlist feita de uma descoberta inteira.",
        "fav.too_many": "Você já tem {max} favoritas que se atualizam. Tire uma da barra para pôr outra.",
        "fav.added": "Ela fica na barra e se atualiza {every}.",
        "fav.not_found": "Favorita não encontrada.",
        "fav.every_set": "Agora ela se atualiza {every}.",
        "fav.already_running": "Essa playlist já está se atualizando.",
        "fav.queued": "Na fila para atualizar…",
        "fav.updated_curated": "Atualizada.",
        "fav.updated": ("Atualizada com 1 música.", "Atualizada com {count} músicas."),
        "fav.missing": "A playlist foi apagada no Spotify.",
        "cli.refresh": "atualiza agora as favoritas no prazo, de todos da sala",
        "cli.weekly": "o mesmo que refresh (nome antigo)",
        "cli.refreshed": ("1 favorita atualizada.", "{count} favoritas atualizadas."),
        # Sign-in and tokens
        "auth.bad_state": "Resposta de login inválida (state não confere). Tente de novo.",
        "auth.refused": "Login recusado pelo Spotify: {error}",
        "auth.timeout": "Tempo esgotado esperando a autorização no navegador.",
        "auth.opening": "Abrindo o navegador para autorizar. Se não abrir, acesse:\n{url}",
        "auth.done_page": "Pronto! Pode fechar esta aba e voltar ao terminal.",
        "auth.expired": "A sessão do Spotify expirou. Entre de novo com o Spotify.",
        "auth.not_signed_in": "Você ainda não entrou. Entre com o Spotify.",
        "config.no_client_id": "Defina SPOTIFY_CLIENT_ID no arquivo .env (veja .env.example).",
        # Spotify and catalog connections
        "api.rate_limited": "limite de pedidos; tente de novo em {seconds}s",
        "api.offline": "sem conexão: {reason}",
        "catalog.offline": "sem conexão com o catálogo de músicas",
        "catalog.no_answer": "o catálogo de músicas não respondeu",
        "catalog.error": "erro no catálogo de músicas",
        # Curated playlists (update console and CLI)
        "playlists.unknown": "Não existe no playlists.json: {names}",
        "playlists.bad_mix": "“{name}” mistura “{source}”, que não existe (ou também é uma mistura).",
        "playlists.bad_entry": "Faixa fora do formato “Artista - Título” no playlists.json: {entry}",
        "playlists.building": "Montando {name}...",
        "playlists.summary": "\n{name}: {count} itens",
        "playlists.missing": "   não encontrado: {item}",
        "playlists.dry_run": "\nSimulação: nada foi alterado no Spotify.",
        "playlists.empty": "{name} ficou vazia nesta rodada; o conteúdo atual foi mantido.",
        "playlists.saved": "{name} gravada no Spotify ({count} itens).",
        "playlists.created": "Playlist criada: {name}",
        # Command line
        "cli.description": "Sala de escuta: playlists do Spotify.",
        "cli.login": "entra com a conta do dono (abre o navegador)",
        "cli.check": "testa a conexão e mostra quem está na sala",
        "cli.ui": "abre o painel no navegador",
        "cli.no_browser": "só sobe o servidor, sem abrir o navegador",
        "cli.setup": "cria/recria as playlists do playlists.json na conta do dono",
        "cli.only": "só esta playlist (pode repetir)",
        "cli.dry_run": "mostra o que seria feito, sem alterar nada",
        "cli.logged_in": "Login feito como {name}. Agora rode: python -m spotify_assistant check",
        "cli.nobody": "Ninguém entrou na sala ainda. Rode: python -m spotify_assistant login",
        "cli.owner": "Dono: {name} ({id}).",
        "cli.member": "  na sala: {name}",
        "cli.spotify_error": "Erro do Spotify: {error}",
        "cli.forbidden": (
            "O Spotify recusou o acesso. Confira: (1) a conta dona do app é Premium; "
            "(2) o e-mail da conta está em User Management no app do Spotify for Developers; "
            "(3) entre de novo se mudou as permissões."
        ),
        # Configuration and requests
        "err.not_in_config": "{name} não está no playlists.json.",
        "err.mix_add": "{name} é montada com faixas das outras playlists. Adicione em uma delas.",
        "err.already_in": "{entry} já está em {name}.",
        "err.fans_invalid": "Número de fãs inválido.",
        "err.fans_order": "O máximo de fãs precisa ser maior que o mínimo.",
        "err.genre_required": "Escolha um gênero para ver as novidades.",
        "err.genre_religious": "Gêneros religiosos ficam fora da sala.",
        "err.login_expired": "O pedido de login expirou. Tente de novo.",
        "err.login_required": "Entre com o seu Spotify para continuar.",
        "err.playlist_not_found": "Playlist não encontrada.",
        "err.search_kind": "Tipo de busca inválido.",
        "err.player_scope": "Autorize o controle do player primeiro.",
        "err.unknown_action": "Ação desconhecida: {action}",
        "err.no_device_open": "Nenhum Spotify aberto. Abra o app no PC ou no celular e tente de novo.",
        "err.feeling_too_long": "Escreva algo mais curto, até {max} letras.",
        "err.sensation_not_found": "Sensação não encontrada.",
        "err.tempo_missing": "Para medir o BPM, instale o decodificador: pip install miniaudio",
        "err.period": "Período inválido.",
        "err.hunt_kind": "Tipo de descoberta inválido.",
        "err.discovery_failed": "A busca de músicas novas falhou ({error}). Tente de novo.",
        "err.unexpected": "Erro inesperado. Detalhes em data/assistant.log.",
        "err.rabbit_seed": "Digite um artista para começar a descer a toca.",
        "err.which_artist": "Diga qual artista.",
        "err.pick_result": "Escolha um item da busca.",
        "err.job_running": "Já tem uma atualização sua em andamento.",
        "err.host": "Host não permitido.",
        "err.json_required": "Envie JSON.",
        "err.json_invalid": "JSON inválido.",
        "err.body_too_big": "Pedido grande demais.",
        "err.route": "Endereço não encontrado.",
        "err.not_found": "Não encontrado.",
        # Spotify pauses and refusals
        "pause.search.soon": "A Spotify pausou as buscas deste app por excesso de pedidos. Tente de novo daqui a pouco.",
        "pause.other.soon": "A Spotify pausou esse tipo de pedido deste app por excesso de pedidos. Tente de novo daqui a pouco.",
        "pause.search.until": "A Spotify pausou as buscas deste app por excesso de pedidos. Voltam por volta de {time} {day}.",
        "pause.other.until": "A Spotify pausou esse tipo de pedido deste app por excesso de pedidos. Volta por volta de {time} {day}.",
        "day.today": "hoje",
        "day.tomorrow": "amanhã",
        "day.on": "em {date}",
        "spotify.no_device": "Nenhum Spotify ativo. Toque uma playlist daqui ou abra o app no PC ou no celular.",
        "spotify.premium": "O controle do player exige Spotify Premium.",
        "spotify.refused": "O Spotify recusou o pedido ({text}).",
        # Blocked artists
        "blocked.on": "{artist} não aparece mais nas suas descobertas.",
        "blocked.off": "{artist} pode aparecer de novo.",
        # Saving what the person liked
        "save.none": "Nenhuma música para guardar.",
        "save.too_many": "Dá para guardar até {max} músicas de uma vez.",
        "save.name_required": "Dê um nome para a playlist.",
        "save.name_long": "Nome muito longo: até {max} letras.",
        "save.curated_name": "{name} é da sua curadoria. Escolha outro nome ou adicione as músicas nela.",
        "save.exists": "Você já tem uma playlist chamada {name}.",
        "save.replaced": ("{name} agora tem só esta música.", "{name} agora tem estas {count} músicas."),
        "save.created": ("Playlist {name} criada com 1 música.", "Playlist {name} criada com {count} músicas."),
        "save.not_yours": "Você só pode adicionar em playlists que são suas.",
        "save.rebuilt": "{name} é remontada pela Sala; o que entrar nela some na próxima vez.",
        "added.already_one": "Já estava em {name}.",
        "added.already_all": "Todas já estavam em {name}.",
        "added.one": "Adicionada a {name}.",
        "added.many": ("1 música adicionada a {name}.", "{count} músicas adicionadas a {name}."),
        "added.some_there": ("1 já estava lá.", "{count} já estavam lá."),
        "added.plain": "Adicionada.",
        "added.show_next": "{entry} entra na {name} a partir da próxima atualização.",
        "finds.name": "Achados da Sala",
        "finds.description": "Músicas descobertas na Sala de escuta: sensações, roleta, toca do coelho e novidades.",
        "desc.sense_bpm": "Entre {low} e {high} BPM, medidos pela Sala de escuta.",
        "desc.sense_learned": "Ritmo aprendido pela Sala de escuta com playlists sobre isso.",
        "desc.roulette": "Sorteadas na roleta da Sala de escuta.",
        "desc.rabbit": "Do conhecido ao desconhecido, pela toca do coelho da Sala de escuta.",
        "desc.news": "{label}, reunidas na Sala de escuta.",
        "desc.default": "Montada na Sala de escuta.",
        # Curated playlist updates
        "job.preview": "Prévia de {name}",
        "job.update": "Atualizando {name}",
        # Sign-in pages
        "page.not_invited.title": "Sua conta ainda não foi liberada",
        "page.not_invited.text": (
            "A Spotify só deixa entrar quem foi convidado. Peça para {who} adicionar o e-mail da sua conta "
            "do Spotify em User Management, no Spotify for Developers. Depois é só entrar de novo."
        ),
        "page.owner": "o dono da sala",
        "page.login_failed": "Não deu para entrar",
        "page.back": "Voltar para a sala",
        # Discoveries: labels
        "label.roulette": "Roleta",
        "label.roulette_genre": "Roleta: {genre}",
        "label.roulette_rare": "Roleta: gênero pouco conhecido",
        "label.rabbit": "Toca do coelho",
        "label.news": "Novidades: {genre}",
        # Sensations
        "sense.free_description": "Músicas para {feeling}.",
        "sense.free_learned": "Músicas para {feeling}, no ritmo que as playlists sobre isso têm em comum.",
        "sense.query_songs": "músicas {feeling}",
        "sense.looking": "Procurando playlists feitas para esse momento…",
        "sense.no_playlists": "Não achei playlists sobre “{name}”. Tente outra palavra.",
        "sense.no_size": "Nenhum artista desse tamanho nas playlists sobre “{name}”. Mude os fãs mínimos ou máximos.",
        "sense.checking_size": "Conferindo o tamanho dos artistas: {count} no tamanho certo até agora.",
        "sense.checking_listeners": "Conferindo ouvintes no Last.fm: {count} dentro do limite até agora.",
        "sense.no_listeners": "Nenhuma música das playlists sobre “{name}” dentro do limite de ouvintes. Aumente o limite.",
        "sense.listening": "Ouvindo prévias: {progress} de {total}. {found} no ritmo certo.",
        "sense.done": ("1 música no ritmo de “{name}”, de {heard} prévias ouvidas.",
                       "{count} músicas no ritmo de “{name}”, de {heard} prévias ouvidas."),
        "sense.none": "Nenhuma prévia ficou no ritmo desta vez. Gere de novo para ouvir outras.",
        "consensus.listening": "Ouvindo para entender o ritmo de “{name}”: {progress} de {total}.",
        "consensus.few": "Poucas músicas para entender “{name}”. Tente outra palavra.",
        "consensus.center": "O ritmo de “{name}” fica perto de {bpm} BPM. Separando as músicas…",
        "consensus.done": ("1 música no ritmo de “{name}”, perto de {bpm} BPM.",
                           "{count} músicas no ritmo de “{name}”, perto de {bpm} BPM."),
        "consensus.none": "As músicas sobre “{name}” não têm um ritmo em comum. Tente outra palavra.",
        # Roulette
        "roulette.spinning": "Girando a roleta…",
        "roulette.progress": "Sorteadas {progress} de {total}.",
        "roulette.done": ("1 música sorteada.", "{count} músicas sorteadas."),
        "roulette.none": "A roleta não achou nada desta vez. Gire de novo.",
        "reason.obscure_album": "Sorteada de um álbum de {year} que quase ninguém ouve.",
        "reason.genre_playlist": "Sorteada de uma playlist de {genre}.",
        # New releases
        "news.looking": "Procurando artistas de {genre}…",
        "news.no_artists": "Não achei artistas de “{genre}”. Tente escrever o gênero de outro jeito.",
        "news.progress": "Olhando {progress} de {total} artistas. {releases} lançamentos até agora.",
        "news.none": "Nenhum lançamento de {genre} nesse tamanho nos últimos {days} dias. Aumente o período ou o tamanho.",
        "news.picking": "Separando a faixa principal de cada lançamento…",
        "news.done": ("1 lançamento de {genre} dos últimos {days} dias.",
                      "{count} lançamentos de {genre} dos últimos {days} dias."),
        "news.not_on_spotify": "Os lançamentos encontrados não estão no Spotify do seu país. Tente outro gênero ou período.",
        "record.single": "Single",
        "record.ep": "EP",
        "record.album": "Álbum",
        "record.compile": "Coletânea",
        "record.other": "Lançamento",
        "reason.release": "{kind} de {who}, saiu em {date}.",
        "reason.who_fans": "{name} ({fans} fãs)",
        # Rabbit hole
        "rabbit.going": "Descendo a toca a partir de {seed}…",
        "reason.rabbit_end": "Fim da toca: {hops} pulos a partir de {seed}.",
        "reason.rabbit_hop": "Pulo {hop} de {hops} a partir de {seed}.",
        "rabbit.done": "{chains} caminhos, {count} músicas do conhecido ao desconhecido.",
        "rabbit.none": "A toca não levou a lugar nenhum desta vez. Tente de novo, outro artista ou outro tamanho.",
    },
    "en": {
        # Reviews
        "reviews.invalid_album": "Couldn't find that album on Spotify.",
        "reviews.bad_rating": "Ratings go from half a star to 5 stars.",
        "reviews.too_long": "A review can be up to {max} characters.",
        "reviews.empty": "Give a rating or write something.",
        "reviews.saved": "Review saved. Only you see it.",
        "reviews.saved_public": "Review saved and open to the room.",
        "reviews.deleted": "Review deleted.",
        "reviews.not_found": "You don't have a review of this album.",
        # Friends: who may use it
        "friends.off": "Friends isn't available to you.",
        "err.which_person": "Pick a person in the room.",
        "friends.access_on": "{name} can use Friends.",
        "friends.access_off": "{name} no longer uses Friends; their history was deleted.",
        "friends.access_new_on": "People who join the room from now on can use Friends right away.",
        "friends.access_new_off": "People who join the room from now on start without Friends until you allow them.",
        # Friends
        "friends.need_auth": "To join, authorize Spotify again (just once).",
        "friends.joined": "Done! The room now reads what you listen to every 15 minutes.",
        "friends.left": "You left. Nobody sees what you listen to anymore.",
        "friends.forgot": "You left and your history was deleted.",
        "artists.choose": "There's more than one artist called “{name}”. Which one?",
        # Artists search
        "err.artist_name": "Type the name of an artist or band.",
        "artists.looking": "Looking up {name} and who's part of it…",
        "artists.reading": "Reading everything by {name} ({progress} of {total}), slowly so Spotify doesn't pause… {count} so far.",
        "artists.not_found": "Couldn't find “{name}”. Check the artist or band name.",
        "artists.none": "No releases by {name} on Spotify.",
        "artists.done": ("1 release by {name}.", "{count} releases by {name}."),
        "artists.done_group": ("1 release by {name} and its members.", "{count} releases by {name} and its members."),
        "artists.no_track": "Couldn't find that feature on the album.",
        # New releases from today
        "news.none_today": "No {genre} releases of that size today. Widen the period or the size.",
        "news.done_today": ("1 {genre} release from today.", "{count} {genre} releases from today."),
        # Pinned playlists and the bar
        "fav.hidden": "{name} left the bar and won't update anymore. To bring it back, use the + on the bar.",
        "fav.shown": "{name} is back on the bar.",
        "fav.pinned": "{name} is on the bar.",
        "fav.unpinned": "{name} left the bar. The playlist stays on your Spotify.",
        "fav.already": "That playlist is already on the bar.",
        "fav.too_many_pinned": "You can pin up to {max} playlists. Take one off the bar to add another.",
        "fav.pinned_no_update": "Pinned playlists don't update themselves.",
        "fav.pinned_only_add": "This playlist gets new songs on every update; adding by hand won't stick.",
        # The heart (Spotify library)
        "err.like_what": "Nothing to like here.",
        "liked.need_auth": "To like songs from here, authorize Spotify again (just once).",
        "liked.track_on": "Saved to your Liked Songs.",
        "liked.track_off": "Removed from your Liked Songs.",
        "liked.episode_on": "Saved to your episodes.",
        "liked.episode_off": "Removed from your episodes.",
        # Favorites (the bar)
        "every.daily": "every day",
        "every.weekly": "every week",
        "every.monthly": "every month",
        "fav.bad_every": "Invalid frequency.",
        "fav.needs_discovery": "Only a playlist made from a whole discovery can update itself.",
        "fav.too_many": "You already have {max} self-updating favorites. Take one off the bar to add another.",
        "fav.added": "It's on the bar and updates itself {every}.",
        "fav.not_found": "Favorite not found.",
        "fav.every_set": "It now updates itself {every}.",
        "fav.already_running": "This playlist is already updating.",
        "fav.queued": "Waiting to update…",
        "fav.updated_curated": "Updated.",
        "fav.updated": ("Updated with 1 song.", "Updated with {count} songs."),
        "fav.missing": "The playlist was deleted on Spotify.",
        "cli.refresh": "updates the favorites that are due now, for everyone in the room",
        "cli.weekly": "same as refresh (old name)",
        "cli.refreshed": ("1 favorite updated.", "{count} favorites updated."),
        # Sign-in and tokens
        "auth.bad_state": "Invalid sign-in response (state doesn't match). Try again.",
        "auth.refused": "Spotify refused the sign-in: {error}",
        "auth.timeout": "Timed out waiting for authorization in the browser.",
        "auth.opening": "Opening the browser to authorize. If it doesn't open, go to:\n{url}",
        "auth.done_page": "Done! You can close this tab and go back to the terminal.",
        "auth.expired": "Your Spotify session expired. Sign in with Spotify again.",
        "auth.not_signed_in": "You haven't signed in yet. Sign in with Spotify.",
        "config.no_client_id": "Set SPOTIFY_CLIENT_ID in the .env file (see .env.example).",
        # Spotify and catalog connections
        "api.rate_limited": "rate limited; try again in {seconds}s",
        "api.offline": "no connection: {reason}",
        "catalog.offline": "no connection to the music catalog",
        "catalog.no_answer": "the music catalog didn't answer",
        "catalog.error": "music catalog error",
        # Curated playlists (update console and CLI)
        "playlists.unknown": "Not in playlists.json: {names}",
        "playlists.bad_mix": "“{name}” mixes “{source}”, which doesn't exist (or is also a mix).",
        "playlists.bad_entry": "Track not in the “Artist - Title” format in playlists.json: {entry}",
        "playlists.building": "Building {name}...",
        "playlists.summary": "\n{name}: {count} items",
        "playlists.missing": "   not found: {item}",
        "playlists.dry_run": "\nDry run: nothing was changed on Spotify.",
        "playlists.empty": "{name} came out empty this time; the current content was kept.",
        "playlists.saved": "{name} saved to Spotify ({count} items).",
        "playlists.created": "Playlist created: {name}",
        # Command line
        "cli.description": "Sala de escuta: Spotify playlists.",
        "cli.login": "signs in with the owner's account (opens the browser)",
        "cli.check": "tests the connection and shows who's in the room",
        "cli.ui": "opens the panel in the browser",
        "cli.no_browser": "only starts the server, without opening the browser",
        "cli.setup": "creates/recreates the playlists from playlists.json on the owner's account",
        "cli.only": "only this playlist (can be repeated)",
        "cli.dry_run": "shows what would be done, without changing anything",
        "cli.logged_in": "Signed in as {name}. Now run: python -m spotify_assistant check",
        "cli.nobody": "Nobody has signed in yet. Run: python -m spotify_assistant login",
        "cli.owner": "Owner: {name} ({id}).",
        "cli.member": "  in the room: {name}",
        "cli.spotify_error": "Spotify error: {error}",
        "cli.forbidden": (
            "Spotify refused access. Check that: (1) the app owner's account is Premium; "
            "(2) the account's e-mail is under User Management in the Spotify for Developers app; "
            "(3) you signed in again if you changed permissions."
        ),
        # Configuration and requests
        "err.not_in_config": "{name} isn't in playlists.json.",
        "err.mix_add": "{name} is built from the other playlists' tracks. Add it to one of them.",
        "err.already_in": "{entry} is already in {name}.",
        "err.fans_invalid": "Invalid number of fans.",
        "err.fans_order": "The maximum number of fans has to be higher than the minimum.",
        "err.genre_required": "Pick a genre to see new releases.",
        "err.genre_religious": "Religious genres stay out of the room.",
        "err.login_expired": "The sign-in request expired. Try again.",
        "err.login_required": "Sign in with your Spotify to continue.",
        "err.playlist_not_found": "Playlist not found.",
        "err.search_kind": "Invalid search type.",
        "err.player_scope": "Authorize player control first.",
        "err.unknown_action": "Unknown action: {action}",
        "err.no_device_open": "No Spotify open. Open the app on your computer or phone and try again.",
        "err.feeling_too_long": "Write something shorter, up to {max} characters.",
        "err.sensation_not_found": "Sensation not found.",
        "err.tempo_missing": "To measure BPM, install the decoder: pip install miniaudio",
        "err.period": "Invalid period.",
        "err.hunt_kind": "Invalid discovery type.",
        "err.discovery_failed": "The search for new music failed ({error}). Try again.",
        "err.unexpected": "Unexpected error. Details in data/assistant.log.",
        "err.rabbit_seed": "Type an artist to start down the rabbit hole.",
        "err.which_artist": "Say which artist.",
        "err.pick_result": "Pick an item from the search.",
        "err.job_running": "One of your updates is already running.",
        "err.host": "Host not allowed.",
        "err.json_required": "Send JSON.",
        "err.json_invalid": "Invalid JSON.",
        "err.body_too_big": "Request too large.",
        "err.route": "Address not found.",
        "err.not_found": "Not found.",
        # Spotify pauses and refusals
        "pause.search.soon": "Spotify paused this app's searches for too many requests. Try again in a little while.",
        "pause.other.soon": "Spotify paused this kind of request from this app for too many requests. Try again in a little while.",
        "pause.search.until": "Spotify paused this app's searches for too many requests. They're back around {time} {day}.",
        "pause.other.until": "Spotify paused this kind of request from this app for too many requests. It's back around {time} {day}.",
        "day.today": "today",
        "day.tomorrow": "tomorrow",
        "day.on": "on {date}",
        "spotify.no_device": "No active Spotify. Play a playlist from here or open the app on your computer or phone.",
        "spotify.premium": "Player control requires Spotify Premium.",
        "spotify.refused": "Spotify refused the request ({text}).",
        # Blocked artists
        "blocked.on": "{artist} won't show up in your discoveries anymore.",
        "blocked.off": "{artist} can show up again.",
        # Saving what the person liked
        "save.none": "No songs to save.",
        "save.too_many": "You can save up to {max} songs at once.",
        "save.name_required": "Give the playlist a name.",
        "save.name_long": "Name too long: up to {max} characters.",
        "save.curated_name": "{name} is one of your curated playlists. Pick another name or add the songs to it.",
        "save.exists": "You already have a playlist called {name}.",
        "save.replaced": ("{name} now has just this song.", "{name} now has these {count} songs."),
        "save.created": ("Playlist {name} created with 1 song.", "Playlist {name} created with {count} songs."),
        "save.not_yours": "You can only add to playlists you own.",
        "save.rebuilt": "{name} is rebuilt by the Sala; anything added to it disappears next time.",
        "added.already_one": "It was already in {name}.",
        "added.already_all": "They were all already in {name}.",
        "added.one": "Added to {name}.",
        "added.many": ("1 song added to {name}.", "{count} songs added to {name}."),
        "added.some_there": ("1 was already there.", "{count} were already there."),
        "added.plain": "Added.",
        "added.show_next": "{entry} joins {name} from the next update on.",
        "finds.name": "Finds from the Sala",
        "finds.description": "Songs discovered in Sala de escuta: sensations, roulette, rabbit hole and new releases.",
        "desc.sense_bpm": "Between {low} and {high} BPM, measured by Sala de escuta.",
        "desc.sense_learned": "Rhythm learned by Sala de escuta from playlists about it.",
        "desc.roulette": "Drawn by the Sala de escuta roulette.",
        "desc.rabbit": "From the known to the unknown, down the Sala de escuta rabbit hole.",
        "desc.news": "{label}, gathered in Sala de escuta.",
        "desc.default": "Made in Sala de escuta.",
        # Curated playlist updates
        "job.preview": "Preview of {name}",
        "job.update": "Updating {name}",
        # Sign-in pages
        "page.not_invited.title": "Your account isn't allowed in yet",
        "page.not_invited.text": (
            "Spotify only lets invited people in. Ask {who} to add your Spotify account's e-mail under "
            "User Management in Spotify for Developers. Then just sign in again."
        ),
        "page.owner": "the room's owner",
        "page.login_failed": "Couldn't sign in",
        "page.back": "Back to the room",
        # Discoveries: labels
        "label.roulette": "Roulette",
        "label.roulette_genre": "Roulette: {genre}",
        "label.roulette_rare": "Roulette: little-known genre",
        "label.rabbit": "Rabbit hole",
        "label.news": "New releases: {genre}",
        # Sensations
        "sense.free_description": "Songs for {feeling}.",
        "sense.free_learned": "Songs for {feeling}, at the rhythm that playlists about it share.",
        "sense.query_songs": "{feeling} songs",
        "sense.looking": "Looking for playlists made for this moment…",
        "sense.no_playlists": "Couldn't find playlists about “{name}”. Try another word.",
        "sense.no_size": "No artists of that size in the playlists about “{name}”. Change the minimum or maximum fans.",
        "sense.checking_size": "Checking artist sizes: {count} the right size so far.",
        "sense.checking_listeners": "Checking listeners on Last.fm: {count} within the limit so far.",
        "sense.no_listeners": "No songs from the playlists about “{name}” within the listener limit. Raise the limit.",
        "sense.listening": "Listening to previews: {progress} of {total}. {found} at the right tempo.",
        "sense.done": ("1 song at the tempo of “{name}”, from {heard} previews heard.",
                       "{count} songs at the tempo of “{name}”, from {heard} previews heard."),
        "sense.none": "No preview hit the tempo this time. Run it again to hear others.",
        "consensus.listening": "Listening to learn the rhythm of “{name}”: {progress} of {total}.",
        "consensus.few": "Too few songs to understand “{name}”. Try another word.",
        "consensus.center": "“{name}” sits around {bpm} BPM. Picking the songs…",
        "consensus.done": ("1 song at the rhythm of “{name}”, around {bpm} BPM.",
                           "{count} songs at the rhythm of “{name}”, around {bpm} BPM."),
        "consensus.none": "Songs about “{name}” don't share a rhythm. Try another word.",
        # Roulette
        "roulette.spinning": "Spinning the roulette…",
        "roulette.progress": "Drawn {progress} of {total}.",
        "roulette.done": ("1 song drawn.", "{count} songs drawn."),
        "roulette.none": "The roulette found nothing this time. Spin again.",
        "reason.obscure_album": "Drawn from a {year} album almost nobody listens to.",
        "reason.genre_playlist": "Drawn from a {genre} playlist.",
        # New releases
        "news.looking": "Looking for {genre} artists…",
        "news.no_artists": "Couldn't find “{genre}” artists. Try writing the genre another way.",
        "news.progress": "Checking {progress} of {total} artists. {releases} releases so far.",
        "news.none": "No {genre} releases of that size in the last {days} days. Widen the period or the size.",
        "news.picking": "Picking the main track of each release…",
        "news.done": ("1 {genre} release from the last {days} days.",
                      "{count} {genre} releases from the last {days} days."),
        "news.not_on_spotify": "The releases found aren't on Spotify in your country. Try another genre or period.",
        "record.single": "Single",
        "record.ep": "EP",
        "record.album": "Album",
        "record.compile": "Compilation",
        "record.other": "Release",
        "reason.release": "{kind} by {who}, out {date}.",
        "reason.who_fans": "{name} ({fans} fans)",
        # Rabbit hole
        "rabbit.going": "Going down the hole from {seed}…",
        "reason.rabbit_end": "End of the hole: {hops} hops from {seed}.",
        "reason.rabbit_hop": "Hop {hop} of {hops} from {seed}.",
        "rabbit.done": "{chains} paths, {count} songs from the known to the unknown.",
        "rabbit.none": "The hole led nowhere this time. Try again, with another artist or another size.",
    },
}
