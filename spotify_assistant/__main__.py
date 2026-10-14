"""CLI: python -m spotify_assistant {login,check,setup,weekly}"""
from __future__ import annotations

import argparse
import logging
import sys

from .api import Spotify, SpotifyError
from .auth import TokenManager, login
from .config import DATA_DIR, LOG_FILE, load_playlists, load_settings, load_state
from .dashboard import serve
from .playlists import run

log = logging.getLogger("spotify_assistant")

FORBIDDEN_HINT = (
    "O Spotify recusou o acesso. Confira: (1) a conta dona do app é Premium; "
    "(2) seu e-mail está em User Management no app do Spotify for Developers; "
    "(3) rode o login de novo se mudou as permissões."
)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="spotify_assistant", description="Assistente pessoal de playlists do Spotify.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="autoriza o acesso à sua conta (abre o navegador)")
    commands.add_parser("check", help="testa a conexão e mostra a conta conectada")
    ui = commands.add_parser("ui", help="abre o painel visual no navegador")
    ui.add_argument("--no-browser", action="store_true", help="só sobe o servidor, sem abrir o navegador")
    setup = commands.add_parser("setup", help="cria/recria as playlists do playlists.json")
    setup.add_argument("--only", action="append", metavar="NOME", help="só esta playlist (pode repetir)")
    weekly = commands.add_parser("weekly", help="atualiza as playlists semanais (podcasts)")
    for command in (setup, weekly):
        command.add_argument("--dry-run", action="store_true", help="mostra o que seria feito, sem alterar nada")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.command == "login":
            login(settings)
            log.info("Login feito! Agora rode: python -m spotify_assistant check")
            return 0
        if args.command == "ui":
            serve(settings, open_browser=not args.no_browser)
            return 0

        config = load_playlists()
        sp = Spotify(TokenManager(settings), market=config.get("market", "BR"))
        if args.command == "check":
            me = sp.me()
            log.info("Conectado como %s (%s).", me.get("display_name") or me["id"], me["id"])
            return 0
        run(
            sp,
            config,
            load_state(),
            weekly=args.command == "weekly",
            only=getattr(args, "only", None),
            dry_run=args.dry_run,
        )
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
