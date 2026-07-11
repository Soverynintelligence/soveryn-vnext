"""Runtime trust-stage store for X presence.

Governs whether Aetheria's X posts publish or wait for approval.
Safety principle: fail closed to Stage 0 on any error.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path


def read_trust_stage(path: Path) -> int:
    """Read trust stage from JSON file.

    Returns the current trust stage (0, 1, or 2).
    If the file is missing, unreadable, malformed, or the value isn't
    a valid stage → return 0 (the safe, most-restrictive stage).
    Never returns a higher stage on any error.

    Args:
        path: Path to the x_trust.json file.

    Returns:
        int: The trust stage (0, 1, or 2). Defaults to 0 on any error.
    """
    try:
        text = path.read_text()
        data = json.loads(text)
        stage = data.get("stage")
        # Validate: must be an int in {0, 1, 2}
        if isinstance(stage, int) and stage in {0, 1, 2}:
            return stage
        return 0
    except (FileNotFoundError, json.JSONDecodeError, OSError, PermissionError):
        # Missing, malformed, or unreadable file → safe default
        return 0


def set_trust_stage(path: Path, stage: int) -> None:
    """Set trust stage with atomic write.

    Validates stage in {0, 1, 2}; raises ValueError otherwise.
    Writes atomically (temp file + os.replace) so concurrent
    read_trust_stage never sees a half-written file.
    Creates parent directory if needed.

    Args:
        path: Path to the x_trust.json file.
        stage: The new trust stage (must be 0, 1, or 2).

    Raises:
        ValueError: If stage is not in {0, 1, 2}.
    """
    if stage not in {0, 1, 2}:
        raise ValueError(f"stage must be 0, 1, or 2; got {stage}")

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp file in same dir + replace
    data = {"stage": stage}
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    try:
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def panic_to_zero(path: Path) -> None:
    """Panic: immediately set trust stage to 0.

    Args:
        path: Path to the x_trust.json file.
    """
    set_trust_stage(path, 0)


def _get_default_trust_path() -> Path:
    """Get the default trust file path.

    Default: Path.home()/"soveryn_vnext"/"data"/"x_trust.json"
    Can be overridden by X_TRUST_PATH environment variable.

    Returns:
        Path: The trust file path.
    """
    env_path = os.environ.get("X_TRUST_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / "soveryn_vnext" / "data" / "x_trust.json"


def main() -> None:
    """CLI entry point for trust stage management.

    Commands:
        trust set <0|1|2>  - Set trust stage
        trust panic        - Panic to stage 0
        trust show         - Show current stage
    """
    parser = argparse.ArgumentParser(
        description="X trust-stage store and panic control",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # set command
    set_parser = subparsers.add_parser("set", help="Set trust stage")
    set_parser.add_argument(
        "stage",
        type=int,
        choices=[0, 1, 2],
        help="Trust stage (0=safest, 1=replies, 2=autonomous)",
    )

    # panic command
    subparsers.add_parser("panic", help="Panic to stage 0")

    # show command
    subparsers.add_parser("show", help="Show current stage")

    args = parser.parse_args()

    trust_path = _get_default_trust_path()

    if args.command == "set":
        set_trust_stage(trust_path, args.stage)
        print(f"Trust stage set to {args.stage}")
    elif args.command == "panic":
        panic_to_zero(trust_path)
        print("Panic: trust stage set to 0")
    elif args.command == "show":
        stage = read_trust_stage(trust_path)
        print(f"Current trust stage: {stage}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
