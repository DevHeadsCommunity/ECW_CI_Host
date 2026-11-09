"""Thin CLI adapter. The library never reads GitHub output/environment files."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys

from .config import RunConfig
from .runner import run_test, validate_run


def parser():
    root = argparse.ArgumentParser(
        description="Run ECW hardware workflows from any CI runner, terminal, or Python application.",
        epilog="Example: ecw-ci run --config examples/arduino/run.toml. Authentication: ECW_API_KEY.")
    root.add_argument("--version", action="version", version="ecw-ci-host 0.1.0")
    subcommands = root.add_subparsers(dest="command", required=True)
    for name in ("run", "validate"):
        command = subcommands.add_parser(
            name, help="Run on hardware" if name == "run" else "Validate inputs without network or hardware",
            description=("Book → wait → optional HIL → upload → explicit flash → jobs → collect → release."
                         if name == "run" else "Validate project inputs locally, without API requests or a key."),
            epilog="Configuration and examples: README.md. Set ECW_API_KEY through your credential store.")
        command.add_argument("--config", type=Path, help="TOML or JSON run configuration")
        command.add_argument("--board", help="Exact ECW board type name")
        command.add_argument("--firmware", type=Path)
        command.add_argument("--jobs-dir", type=Path)
        command.add_argument("--output-dir", type=Path)
        command.add_argument("--backend-url")
        command.add_argument("--booking-id", type=int, help="Reuse and preserve an owned booking")
        command.add_argument("--new-booking", dest="reuse_existing", action="store_false", default=None,
                             help="Request a new slot instead of reusing the nearest existing booking")
        command.add_argument("--booking-timeout", type=float)
        command.add_argument("--job-timeout", type=float)
        command.add_argument("--poll-interval", type=float)
        command.add_argument("--hil-sensor")
        command.add_argument("--hil-csv", type=Path)
        command.add_argument("--metadata-file", type=Path, help="Additional non-secret JSON provenance")
        if name == "validate":
            command.add_argument("--check-firmware", action="store_true", help="Also require an existing built firmware file")
    return root


def _config(args):
    overrides = {key: getattr(args, key) for key in (
        "board", "firmware", "jobs_dir", "output_dir", "backend_url", "booking_id",
        "booking_timeout", "job_timeout", "poll_interval", "hil_sensor", "hil_csv", "reuse_existing",
    ) if getattr(args, key) is not None}
    if "backend_url" not in overrides and os.environ.get("ECW_BACKEND_URL"):
        overrides["backend_url"] = os.environ["ECW_BACKEND_URL"]
    for key in ("firmware", "jobs_dir", "output_dir", "hil_csv"):
        if key in overrides:
            overrides[key] = overrides[key].resolve()
    if not args.config:
        missing = [name for name in ("board", "firmware", "jobs_dir") if name not in overrides]
        if missing:
            raise ValueError("Provide --config or the required options: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    config = RunConfig.from_file(args.config, **overrides) if args.config else RunConfig(**overrides)
    if args.metadata_file:
        from dataclasses import replace
        metadata = json.loads(args.metadata_file.read_text())
        if not isinstance(metadata, dict):
            raise ValueError("metadata-file must contain a JSON object")
        config = replace(config, metadata={**config.metadata, **metadata})
    return config


def main(argv=None):
    args = parser().parse_args(argv)
    previous = None
    try:
        config = _config(args)
        if args.command == "validate":
            specs, values = validate_run(config, require_firmware=args.check_firmware)
            print(json.dumps({"valid": True, "jobs": [s.label for s in specs], "hil_samples": values[1] if values else 0}))
            return 0
        if hasattr(signal, "SIGTERM"):
            def interrupted(_signum, _frame):
                raise KeyboardInterrupt("Termination requested")
            previous = signal.signal(signal.SIGTERM, interrupted)
        result = run_test(config)
        print(json.dumps(result.to_dict(), indent=2))
        return result.exit_code
    except Exception as error:
        message = str(error)
        if os.environ.get("ECW_API_KEY"):
            message = message.replace(os.environ["ECW_API_KEY"], "[redacted]")
        print(json.dumps({"success": False, "error": message}), file=sys.stderr)
        return 2
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
