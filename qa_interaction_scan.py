from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_AGENTS = ("restaurant", "hotel", "hausverwaltung", "private", "main")
OPENCLAW_HOME = Path("/home/openclaw/.openclaw")
LOCAL_TZ = ZoneInfo("Europe/Berlin")

COMPLAINT_TERMS = (
    "enttäuscht",
    "enttaeuscht",
    "enttauscht",
    "nicht überprüft",
    "nicht geprueft",
    "nicht gefunden",
    "nicht vollständig",
    "unvollständig",
    "fehlt",
    "falsch",
    "warum",
    "wieso",
    "wo ist",
    "immer noch",
    "noch nicht",
    "hast du nicht",
    "hat nicht",
    "funktioniert nicht",
    "beschwer",
    "problem",
    "failed",
    "failure",
    "error",
    "not found",
    "not created",
    "抱怨",
    "不满",
    "失望",
    "为什么",
    "没有",
    "没找到",
)

STRONG_TERMS = (
    "enttäuscht",
    "enttaeuscht",
    "enttauscht",
    "nicht überprüft",
    "nicht geprueft",
    "nicht vollständig",
    "unvollständig",
    "hast du nicht",
    "failed",
    "failure",
    "error",
    "失望",
    "抱怨",
)


@dataclass(frozen=True)
class Finding:
    timestamp: datetime
    agent: str
    role: str
    file: Path
    line_no: int
    severity: str
    terms: tuple[str, ...]
    text: str


def parse_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_ms_timestamp(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def message_timestamp(record: dict) -> datetime | None:
    nested = record.get("message")
    if isinstance(nested, dict):
        parsed = parse_ms_timestamp(nested.get("timestamp"))
        if parsed is not None:
            return parsed
    return parse_iso_timestamp(record.get("timestamp"))


def extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def compact(text: str, limit: int = 260) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def is_automated_prompt(text: str) -> bool:
    return text.lstrip().casefold().startswith("[cron:")


def matched_terms(text: str) -> tuple[str, ...]:
    lower = text.casefold()
    return tuple(term for term in COMPLAINT_TERMS if term.casefold() in lower)


def severity_for(terms: tuple[str, ...]) -> str:
    lower_terms = {term.casefold() for term in terms}
    if any(term.casefold() in lower_terms for term in STRONG_TERMS):
        return "high"
    return "medium"


def iter_session_files(agent: str) -> list[Path]:
    sessions_dir = OPENCLAW_HOME / "agents" / agent / "sessions"
    if not sessions_dir.is_dir():
        return []
    return sorted(
        path
        for path in sessions_dir.glob("*.jsonl")
        if not path.name.endswith(".trajectory.jsonl")
    )


def scan_file(agent: str, path: Path, start: datetime, end: datetime) -> list[Finding]:
    findings: list[Finding] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return findings
    with handle:
        for line_no, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "message":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role != "user":
                continue
            ts = message_timestamp(record)
            if ts is None or ts < start or ts > end:
                continue
            text = extract_text(message.get("content"))
            if not text:
                continue
            if is_automated_prompt(text):
                continue
            terms = matched_terms(text)
            if not terms:
                continue
            findings.append(
                Finding(
                    timestamp=ts,
                    agent=agent,
                    role=str(role),
                    file=path,
                    line_no=line_no,
                    severity=severity_for(terms),
                    terms=terms,
                    text=compact(text),
                )
            )
    return findings


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan OpenClaw agent session transcripts for recent customer complaints."
    )
    parser.add_argument("--minutes", type=int, default=75)
    parser.add_argument("--agents", default=",".join(DEFAULT_AGENTS))
    parser.add_argument("--since", help="ISO datetime; overrides --minutes start")
    parser.add_argument("--until", help="ISO datetime; defaults to now")
    args = parser.parse_args()

    end = parse_dt(args.until) if args.until else datetime.now(timezone.utc)
    start = parse_dt(args.since) if args.since else end - timedelta(minutes=args.minutes)
    agents = tuple(agent.strip() for agent in args.agents.split(",") if agent.strip())

    findings: list[Finding] = []
    for agent in agents:
        for path in iter_session_files(agent):
            findings.extend(scan_file(agent, path, start, end))

    findings.sort(key=lambda item: (item.timestamp, item.agent, str(item.file), item.line_no))

    start_local = start.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    end_local = end.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    print(f"QA_SCAN_WINDOW {start_local} - {end_local} Europe/Berlin")

    if not findings:
        print("NO_FINDINGS")
        return 0

    print(f"FINDINGS {len(findings)}")
    for finding in findings:
        local_ts = finding.timestamp.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        terms = ", ".join(finding.terms[:5])
        print(
            f"- {local_ts} | {finding.severity} | {finding.agent} | "
            f"{finding.file.name}:{finding.line_no} | terms={terms}"
        )
        print(f"  text: {finding.text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
