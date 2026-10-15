"""CLI: python -m spotify_assistant {login,check,ui,setup,refresh}"""
from __future__ import annotations

import argparse
import logging
import sys

from . import accounts, config
from .api import Spotify, SpotifyError
from .auth import TokenManager, login
from .config import DATA_DIR, LOG_FILE, load_playlists, load_settings, load_state
from .dashboard import App, serve
from .i18n import t
from .playlists import run

log = logging.getLogger("spotify_assistant")

def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    config.load_env()  # SALA_LANG decides the language of this help and of the messages
    parser = argparse.ArgumentParser(prog="spotify_assistant", description=t("cli.description"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help=t("cli.login"))
    commands.add_parser("check", help=t("cli.check"))
    ui = commands.add_parser("ui", help=t("cli.ui"))
    ui.add_argument("--no-browser", action="store_true", help=t("cli.no_browser"))
    setup = commands.add_parser("setup", help=t("cli.setup"))
    setup.add_argument("--only", action="append", metavar="NAME", help=t("cli.only"))
    setup.add_argument("--dry-run", action="store_true", help=t("cli.dry_run"))
    commands.add_parser("refresh", help=t("cli.refresh"))
    commands.add_parser("weekly", help=t("cli.weekly"))  # the old scheduled task still calls it
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.command == "login":
            person = accounts.register(login(settings))
            log.info(t("cli.logged_in", name=person.name))
            return 0
        accounts.migrate_legacy(settings)
        if args.command == "ui":
            serve(settings, open_browser=not args.no_browser)
            return 0
        if args.command in ("refresh", "weekly"):
            return refresh_everyone(settings)

        owner = config.owner_id()
        if not owner:
            raise SystemExit(t("cli.nobody"))
        paths = config.user_paths(owner)
        playlists_config = load_playlists()
        sp = Spotify(TokenManager(settings, paths.token), market=playlists_config.get("market", "BR"))
        if args.command == "check":
            me = sp.me()
            log.info(t("cli.owner", name=me.get("display_name") or me["id"], id=me["id"]))
            for user_id in config.list_users():
                log.info(t("cli.member", name=accounts.display_name(user_id)))
            return 0
        run(sp, playlists_config, load_state(paths.state), only=args.only, dry_run=args.dry_run)
        return 0
    except SystemExit as exc:
        if isinstance(exc.code, str):  # our own messages; they go to the log too
            log.error(exc.code)
            return 1
        raise
    except SpotifyError as err:
        log.error(t("cli.spotify_error", error=err))
        if err.status == 403:
            log.error(t("cli.forbidden"))
        return 1
    except Exception:
        log.exception("Unexpected error")
        return 1


def refresh_everyone(settings: config.Settings) -> int:
    """Rebuilds every favorite that is due, for everyone (the panel does this by itself while it's open)."""
    app = App(settings)
    count = 0
    while app.run_due():
        count += 1
    log.info(t("cli.refreshed", count=count))
    return 0


def _configure_logging() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handlers: list[logging.Handler] = [file_handler]
    if sys.stdout is not None:  # pythonw (Task Scheduler) has no console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=handlers)


if __name__ == "__main__":
    sys.exit(main())
