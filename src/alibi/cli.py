"""ALIBI command line. `uv run alibi --help`."""

from __future__ import annotations

import argparse
import json
import sys

from alibi.config import ConfigError, load_settings


def _cmd_runtime(args: argparse.Namespace) -> int:
    settings = load_settings()
    print(json.dumps(settings.public_dict(), indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import socket

    import uvicorn

    from alibi.api.app import create_app

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) == 0:
            print(
                f"error: {host}:{port} is already in use. Stop the other process or run "
                f"`uv run alibi serve --port <free port>`.",
                file=sys.stderr,
            )
            return 2
    print(f"ALIBI case board: http://{host}:{port}  (runtime mode: {settings.runtime_mode})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alibi", description="ALIBI forensic proving ground")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("runtime", help="print the runtime mode, caps and live-inference blocker")
    p.set_defaults(func=_cmd_runtime)

    p = sub.add_parser("serve", help="serve the API and the built case board on localhost")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
