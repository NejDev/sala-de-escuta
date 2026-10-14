"""CLI: python -m spotify_assistant {login,check,ui,setup,weekly}"""
from __future__ import annotations

import argparse
import logging
import sys

from . import accounts, config
from .api import Spotify, SpotifyError
from .auth import TokenManager, login
from .config import DATA_DIR, LOG_FILE, load_playlists, load_settings, load_state
from .dashboard import serve
from .playlists import run

log = logging.getLogger("spotify_assistant")

FORBIDDEN_HINT = (
    "O Spotify recusou o acesso. Confira: (1) a conta dona do app é Premium; "
    "(2) o e-mail da conta está em User Management no app do Spotify for Developers; "
    "(3) entre de novo se mudou as permissões."
)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="spotify_assistant", description="Sala de escuta: playlists do Spotify.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="entra com a conta do dono (abre o navegador)")
    commands.add_parser("check", help="testa a conexão e mostra quem está na sala")
    ui = commands.add_parser("ui", help="abre o painel no navegador")
    ui.add_argument("--no-browser", action="store_true", help="só sobe o servidor, sem abrir o navegador")
    setup = commands.add_parser("setup", help="cria/recria as playlists do playlists.json na conta do dono")
    setup.add_argument("--only", action="append", metavar="NOME", help="só esta playlist (pode repetir)")
    weekly = commands.add_parser("weekly", help="atualiza as playlists semanais de todos da sala")
    for command in (setup, weekly):
        command.add_argument("--dry-run", action="store_true", help="mostra o que seria feito, sem alterar nada")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.command == "login":
            person = accounts.register(login(settings))
            log.info("Login feito como %s. Agora rode: python -m spotify_assistant check", person.name)
            return 0
        accounts.migrate_legacy(settings)
        if args.command == "ui":
            serve(settings, open_browser=not args.no_browser)
            return 0
        if args.command == "weekly":
            return weekly_for_everyone(settings, dry_run=args.dry_run)

        owner = config.owner_id()
        if not owner:
            raise SystemExit("Ninguém entrou na sala ainda. Rode: python -m spotify_assistant login")
        paths = config.user_paths(owner)
        playlists_config = load_playlists()
        sp = Spotify(TokenManager(settings, paths.token), market=playlists_config.get("market", "BR"))
        if args.command == "check":
            me = sp.me()
            log.info("Dono: %s (%s).", me.get("display_name") or me["id"], me["id"])
            for user_id in config.list_users():
                log.info("  na sala: %s", accounts.display_name(user_id))
            return 0
        run(sp, playlists_config, load_state(paths.state), only=args.only, dry_run=args.dry_run)
        return 0
    except SystemExit as exc:
        if isinstance(exc.code, str):  # mensagens nossas; vão para o log também
            log.error(exc.code)
            return 1
        raise
    except SpotifyError as err:
        log.error("Erro do Spotify: %s", err)
        if err.status == 403:
            log.error(FORBIDDEN_HINT)
        return 1
    except Exception:
        log.exception("Erro inesperado")
        return 1


def weekly_for_everyone(settings: config.Settings, dry_run: bool = False) -> int:
    """Atualiza as playlists semanais de cada pessoa que já criou alguma delas."""
    playlists_config = load_playlists()
    weekly_names = {spec["name"] for spec in playlists_config["playlists"] if spec.get("refresh") == "weekly"}
    failures = 0
    for user_id in config.list_users():
        paths = config.user_paths(user_id)
        state = load_state(paths.state)
        if not weekly_names & set(state.get("playlists", {})):
            continue  # nunca criou a Tech Radar: não criamos nada sem a pessoa pedir
        log.info("== %s", accounts.display_name(user_id))
        try:
            sp = Spotify(TokenManager(settings, paths.token), market=playlists_config.get("market", "BR"))
            run(sp, playlists_config, state, weekly=True, dry_run=dry_run)
        except (SystemExit, SpotifyError) as err:
            failures += 1
            log.error("Não deu para atualizar %s: %s", accounts.display_name(user_id), getattr(err, "code", err))
    return 1 if failures else 0


def _configure_logging() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handlers: list[logging.Handler] = [file_handler]
    if sys.stdout is not None:  # pythonw (Agendador de Tarefas) não tem console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=handlers)


if __name__ == "__main__":
    sys.exit(main())
