#!/usr/bin/env python3
"""Voice Bridge Obsidian — Main pipeline entry point.

Orchestrates: validate event → transcribe → classify intent → execute actions → store.

Usage:
    python scripts/ingest_voice.py --event path/to/event.json
    python scripts/ingest_voice.py --stdin < event.json
    python scripts/ingest_voice.py --event event.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add scripts dir to path for local imports
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from action_executor import ActionExecutor
from config_loader import Config
from intent_router import classify
from models import ProcessedRecord, TranscriptResult, VoiceEvent
from obsidian_store import ObsidianStore
from transcribe_audio import transcribe


def setup_logging(config: Config) -> None:
    """Configure logging based on settings."""
    log_dir = Path(config.get("logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    level_name = config.get("logging.level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # File handler
    from datetime import date
    today = date.today()
    log_file = log_dir / config.get("logging.file_pattern", "voice-bridge.log").format(
        year=today.year, month=f"{today.month:02d}", day=f"{today.day:02d}",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)


def process_event(event_data: dict[str, Any], config: Config, dry_run: bool = False) -> dict[str, Any]:
    """Process a single voice event through the full pipeline.

    Args:
        event_data: Raw event dictionary from bridge service
        config: Application configuration
        dry_run: If True, skip all write operations

    Returns:
        Processing result with transcript, intent, and action outcomes
    """
    logger = logging.getLogger(__name__)

    # Step 1: Validate event
    try:
        event = VoiceEvent.from_dict(event_data)
    except ValueError as e:
        logger.error(f"Event validation failed: {e}")
        return {"status": "error", "stage": "validation", "message": str(e)}

    logger.info(f"Processing event: {event.platform.value}/{event.message_id} from {event.user_id}")

    # Step 2: Validate config
    issues = config.validate()
    if issues and not dry_run:
        for issue in issues:
            logger.warning(f"Config issue: {issue}")

    # Step 3: Transcribe
    try:
        transcript = transcribe(
            audio_path=event.audio_path,
            config=config,
            language_hint=event.language_hint,
        )
        logger.info(
            f"Transcription complete: lang={transcript.detected_language}, "
            f"status={transcript.status.value}, "
            f"length={len(transcript.transcript)}"
        )
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        transcript = TranscriptResult.failed(str(e))

    # Step 4: Classify intent
    try:
        intent = classify(transcript=transcript, config=config)
        logger.info(
            f"Intent classified: {intent.intent.value} "
            f"(confidence={intent.confidence:.2f})"
        )
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        from models import Intent as IntentEnum
        intent = IntentResult(intent=IntentEnum.UNKNOWN, confidence=0.0)

    # Build processed record
    record = ProcessedRecord(event=event, transcript=transcript, intent=intent)

    # Step 5: Execute actions (or skip in dry-run)
    if dry_run:
        logger.info("Dry run — skipping all write operations")
        return {
            "status": "dry_run",
            "event": event.to_dict(),
            "transcript": transcript.to_dict(),
            "intent": intent.to_dict(),
        }

    store = ObsidianStore(config)
    executor = ActionExecutor(config, store)
    action_results = executor.execute(record)

    return {
        "status": "success",
        "event": event.to_dict(),
        "transcript": transcript.to_dict(),
        "intent": intent.to_dict(),
        "actions": action_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice Bridge Obsidian — Process a voice message event")
    parser.add_argument("--event", type=str, help="Path to event JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read event JSON from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Validate and process without writing")
    parser.add_argument("--config", type=str, default=None, help="Path to settings.yaml")
    args = parser.parse_args()

    # Load config
    config_path = args.config
    if config_path is None:
        # Look in standard locations
        for candidate in [
            Path(__file__).parent.parent / "config" / "settings.yaml",
            Path.cwd() / "config" / "settings.yaml",
        ]:
            if candidate.exists():
                config_path = str(candidate)
                break

    config = Config.load(config_path)
    setup_logging(config)

    logger = logging.getLogger(__name__)

    # Load event
    if args.stdin:
        event_data = json.load(sys.stdin)
    elif args.event:
        event_path = Path(args.event)
        if not event_path.exists():
            print(f"Error: Event file not found: {args.event}", file=sys.stderr)
            sys.exit(1)
        with open(event_path, "r", encoding="utf-8") as f:
            event_data = json.load(f)
    else:
        parser.print_help()
        sys.exit(1)

    # Process
    result = process_event(event_data, config, dry_run=args.dry_run)

    # Output
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
