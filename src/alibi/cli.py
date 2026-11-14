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


def _cmd_generate(args: argparse.Namespace) -> int:
    from alibi.episode import create_episode, load_manifest

    settings = load_settings()
    paths = create_episode(seed=args.seed, variant=args.variant, runs_dir=settings.runs_dir,
                           sealed_dir=settings.sealed_dir, episode_id=args.episode_id)
    manifest = load_manifest(paths)
    print(json.dumps({
        "episode_id": paths.episode_id,
        "bundle_id": manifest.bundle_id,
        "evidence_origin": manifest.evidence_origin,
        "raw_bundle_sha256": manifest.raw_bundle_sha256,
        "derived_db_sha256": manifest.derived_db_sha256,
        "events": manifest.event_count,
        "artifacts": len(manifest.sources),
        "normalization_errors": len(manifest.normalization_errors),
        "evidence_dir": str(paths.evidence),
        "sealed_answer_key": str(paths.answer_key) + "  (sealed: never given to an investigator)",
    }, indent=2))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from alibi.episode import episode_paths, reproduce_raw_hash, verify_raw_integrity

    settings = load_settings()
    paths = episode_paths(args.episode_id, settings.runs_dir, settings.sealed_dir)
    problems = verify_raw_integrity(paths)
    saved, again = reproduce_raw_hash(paths)
    ok = not problems and saved == again
    print(json.dumps({
        "episode_id": args.episode_id,
        "frozen_bundle_intact": not problems,
        "integrity_problems": problems,
        "saved_raw_bundle_sha256": saved,
        "reproduced_raw_bundle_sha256": again,
        "reproducible_from_saved_scenario": saved == again,
    }, indent=2))
    return 0 if ok else 1


def _cmd_steps(args: argparse.Namespace) -> int:
    from alibi.episode import episode_paths, load_answer_key

    settings = load_settings()
    key = load_answer_key(episode_paths(args.episode_id, settings.runs_dir, settings.sealed_dir))
    print("SEALED ANSWER KEY (operator/audience view; never shown to an investigator)")
    for s in key.steps:
        print(f"  {s.step_id} {s.t_start:%H:%M:%S} {s.step_name:<17} {s.execution_status:<9} {s.outcome}")
    print(f"  scorable effects: {[e.effect_type for e in key.effects]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alibi", description="ALIBI forensic proving ground")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("runtime", help="print the runtime mode, caps and live-inference blocker")
    p.set_defaults(func=_cmd_runtime)

    p = sub.add_parser("generate", help="simulate, freeze, normalize and seal one episode")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--variant", default="incident_coverup",
                   help="incident_plain | incident_coverup | benign_rotation | benign_approved_transfer | "
                        "benign_remote_login | benign_collection_gap")
    p.add_argument("--episode-id", default=None)
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser("verify", help="re-hash a frozen bundle and reproduce it from the saved scenario")
    p.add_argument("episode_id")
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("steps", help="print the sealed executed-step record of an episode (operator only)")
    p.add_argument("episode_id")
    p.set_defaults(func=_cmd_steps)

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
    except Exception as exc:  # noqa: BLE001 - CLI boundary: show a short reason, not a traceback
        from alibi.episode import EpisodeError

        if isinstance(exc, (EpisodeError, ValueError, FileNotFoundError)):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
