from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path

from bot import main as bot_main


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Env file does not exist: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _default_path_entries() -> list[str]:
    system = platform.system()
    entries: list[str] = []
    home = Path.home()

    if system in {"Linux", "Darwin"}:
        entries.append(str(home / ".local" / "bin"))
        for candidate in (
            "/home/linuxbrew/.linuxbrew/bin",
            "/home/linuxbrew/.linuxbrew/sbin",
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/bin",
        ):
            if Path(candidate).exists():
                entries.append(candidate)
    else:
        entries.extend(
            [
                str(home / "AppData" / "Local" / "Programs" / "Python" / "Python313"),
                str(home / "AppData" / "Local" / "Programs" / "Python" / "Python312"),
                str(home / "AppData" / "Local" / "Microsoft" / "WindowsApps"),
            ]
        )

    return entries


def _merge_path(extra_entries: list[str]) -> None:
    current_entries = os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
    merged: list[str] = []
    seen: set[str] = set()
    for entry in [*extra_entries, *current_entries]:
        if not entry:
            continue
        normalized = os.path.normcase(entry)
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(entry)
    os.environ["PATH"] = os.pathsep.join(merged)


def _load_runtime_env(path: Path) -> None:
    values = _parse_env_file(path)
    for key, value in values.items():
        os.environ[key] = value

    extra_path = values.get("BRIDGE_PATH_PREFIX", "")
    extra_entries = [item for item in extra_path.split(os.pathsep) if item]
    _merge_path([*extra_entries, *_default_path_entries()])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Telegram Claude bridge from an env file.")
    parser.add_argument("--env", required=True, help="Path to the bridge env file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env_path = Path(args.env).expanduser().resolve()
    _load_runtime_env(env_path)
    bot_main()


if __name__ == "__main__":
    main()
