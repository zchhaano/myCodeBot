from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


SERVICE_NAME = "telegram-claude-bridge"
REPO_DIR = Path(__file__).resolve().parent
PYTHON_BIN = Path(sys.executable).resolve()
CLAUDE_SETTINGS_TEMPLATE = REPO_DIR / "systemd" / "telegram-claude-bridge.claude-settings.json"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def detect_platform() -> str:
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    raise RuntimeError(f"Unsupported platform: {system}")


def config_dir_for(target: str) -> Path:
    home = Path.home()
    if target == "linux":
        return home / ".config" / SERVICE_NAME
    if target == "macos":
        return home / "Library" / "Application Support" / SERVICE_NAME
    return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / SERVICE_NAME


def default_path_prefix(target: str) -> str:
    home = Path.home()
    if target == "linux":
        return ":".join(
            [
                str(home / ".local" / "bin"),
                "/home/linuxbrew/.linuxbrew/bin",
                "/home/linuxbrew/.linuxbrew/sbin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
            ]
        )
    if target == "macos":
        return ":".join(
            [
                str(home / ".local" / "bin"),
                "/opt/homebrew/bin",
                "/opt/homebrew/sbin",
                "/usr/local/bin",
                "/usr/local/sbin",
                "/usr/bin",
                "/bin",
            ]
        )
    local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return ";".join(
        [
            str(local_appdata / "Programs" / "Python" / "Python313"),
            str(local_appdata / "Programs" / "Python" / "Python312"),
            str(local_appdata / "Microsoft" / "WindowsApps"),
        ]
    )


def ensure_env_file(target: str, config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    env_path = config_dir / "env"
    settings_path = config_dir / "claude-settings.json"

    if not settings_path.exists():
        shutil.copyfile(CLAUDE_SETTINGS_TEMPLATE, settings_path)

    if env_path.exists():
        return env_path

    env_content = textwrap.dedent(
        f"""\
        TELEGRAM_BOT_TOKEN=
        CLAUDE_BIN=claude
        CLAUDE_WORKDIR={REPO_DIR}
        CLAUDE_SETTINGS_FILE={settings_path}
        CLAUDE_PERMISSION_MODE=default
        CLAUDE_ALLOWED_TOOLS=
        CLAUDE_DISALLOWED_TOOLS=
        CLAUDE_TIMEOUT_SECONDS=300
        CLAUDE_STREAMING=true
        TELEGRAM_POLL_TIMEOUT=30
        TELEGRAM_EDIT_INTERVAL_SECONDS=1.0
        SESSION_STORE_PATH={REPO_DIR / "sessions.json"}
        BRIDGE_PATH_PREFIX={default_path_prefix(target)}
        """
    )
    env_path.write_text(env_content, encoding="utf-8")
    return env_path


def install_linux(env_path: Path, *, start: bool) -> None:
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / f"{SERVICE_NAME}.service"
    service_content = textwrap.dedent(
        f"""\
        [Unit]
        Description=Telegram Claude CLI Bridge
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REPO_DIR}
        Environment=PYTHONUNBUFFERED=1
        ExecStart={PYTHON_BIN} {REPO_DIR / "service_entry.py"} --env {env_path}
        Restart=on-failure
        RestartSec=3
        TimeoutStopSec=20

        [Install]
        WantedBy=default.target
        """
    )
    service_path.write_text(service_content, encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"])
    if start:
        run(["systemctl", "--user", "enable", f"{SERVICE_NAME}.service"])
        run(["systemctl", "--user", "restart", f"{SERVICE_NAME}.service"])


def install_macos(env_path: Path, *, start: bool) -> None:
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / f"com.{SERVICE_NAME}.plist"
    logs_dir = config_dir_for("macos") / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plist_content = textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>com.{SERVICE_NAME}</string>
          <key>ProgramArguments</key>
          <array>
            <string>{PYTHON_BIN}</string>
            <string>{REPO_DIR / "service_entry.py"}</string>
            <string>--env</string>
            <string>{env_path}</string>
          </array>
          <key>WorkingDirectory</key>
          <string>{REPO_DIR}</string>
          <key>RunAtLoad</key>
          <true/>
          <key>KeepAlive</key>
          <true/>
          <key>StandardOutPath</key>
          <string>{logs_dir / "stdout.log"}</string>
          <key>StandardErrorPath</key>
          <string>{logs_dir / "stderr.log"}</string>
        </dict>
        </plist>
        """
    )
    plist_path.write_text(plist_content, encoding="utf-8")
    if start:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)], check=False)
        run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)])
        run(["launchctl", "enable", f"gui/{os.getuid()}/com.{SERVICE_NAME}"])
        run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.{SERVICE_NAME}"])


def install_windows(env_path: Path, *, start: bool) -> None:
    task_name = SERVICE_NAME
    python_bin = str(PYTHON_BIN)
    service_entry = str(REPO_DIR / "service_entry.py")
    task_command = f'"{python_bin}" "{service_entry}" --env "{env_path}"'
    run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "ONLOGON",
            "/TR",
            task_command,
            "/F",
        ]
    )
    if start:
        run(["schtasks", "/Run", "/TN", task_name])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the Telegram Claude bridge as a background service.")
    parser.add_argument("--platform", choices=["linux", "macos", "windows"], help="Override platform detection.")
    parser.add_argument("--no-start", action="store_true", help="Install the service but do not start it.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = args.platform or detect_platform()
    config_dir = config_dir_for(target)
    env_path = ensure_env_file(target, config_dir)

    if target == "linux":
        install_linux(env_path, start=not args.no_start)
    elif target == "macos":
        install_macos(env_path, start=not args.no_start)
    else:
        install_windows(env_path, start=not args.no_start)

    print(f"Installed {SERVICE_NAME} for {target}.")
    print(f"Env file: {env_path}")
    print("Fill TELEGRAM_BOT_TOKEN if it is still empty.")


if __name__ == "__main__":
    main()
