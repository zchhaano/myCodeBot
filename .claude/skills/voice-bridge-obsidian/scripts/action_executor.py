"""Safe action executor with allowlist and audit logging.

Only these actions execute automatically:
- Write to Obsidian vault
- Append to daily note
- Generate structured summaries
- Write pending reminders/commands to confirmation queue

Command requests are ALWAYS queued for human confirmation.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from models import Intent, IntentResult, ProcessedRecord, VoiceEvent

logger = logging.getLogger(__name__)

# Audit log path (relative to skill root)
_AUDIT_LOG = "logs/audit.jsonl"


def _audit_log(action: str, details: dict[str, Any], status: str) -> None:
    """Append an entry to the audit log."""
    log_dir = Path(_AUDIT_LOG).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "status": status,
        "details": details,
    }
    with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _sanitize_param(value: str) -> str:
    """Sanitize a parameter value for safe command execution."""
    # Remove shell metacharacters
    sanitized = re.sub(r'[;|&`$]', '', value)
    # Remove newlines
    sanitized = sanitized.replace('\n', ' ').replace('\r', '')
    return sanitized.strip()


def _is_blocked(command: str, blocked_patterns: list[str]) -> bool:
    """Check if a command matches any blocked pattern."""
    for pattern in blocked_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


class ActionExecutor:
    """Executes safe actions and queues unsafe ones for confirmation."""

    def __init__(self, config: Any, store: Any) -> None:
        self.config = config
        self.store = store
        self.safe_mode = config.safe_mode

    def execute(self, record: ProcessedRecord) -> dict[str, Any]:
        """Execute actions based on the classified intent.

        Returns a result dict with actions taken and any pending items.
        """
        results: dict[str, Any] = {
            "actions_taken": [],
            "pending": [],
            "errors": [],
        }

        intent = record.intent.intent

        # Always: write to inbox
        try:
            path = self.store.write_note(record)
            results["actions_taken"].append(f"wrote_inbox:{path}")
            _audit_log("write_inbox", {"path": str(path)}, "success")
        except Exception as e:
            logger.error(f"Failed to write to inbox: {e}")
            results["errors"].append(f"inbox_write_failed: {e}")
            _audit_log("write_inbox", {"error": str(e)}, "failed")

        # Always: append to daily note (if intent confidence sufficient)
        try:
            path = self.store.append_daily(record)
            if path:
                results["actions_taken"].append(f"appended_daily:{path}")
                _audit_log("append_daily", {"path": str(path)}, "success")
        except Exception as e:
            logger.error(f"Failed to append to daily note: {e}")
            results["errors"].append(f"daily_append_failed: {e}")
            _audit_log("append_daily", {"error": str(e)}, "failed")

        # If project identified: route to project folder
        if record.intent.project:
            try:
                path = self.store.write_to_project(record)
                if path:
                    results["actions_taken"].append(f"wrote_project:{path}")
                    _audit_log("write_project", {
                        "path": str(path),
                        "project": record.intent.project,
                    }, "success")
            except Exception as e:
                logger.error(f"Failed to write to project: {e}")
                results["errors"].append(f"project_write_failed: {e}")
                _audit_log("write_project", {"error": str(e)}, "failed")

        # Intent-specific handling
        if intent == Intent.REMINDER_REQUEST:
            self._handle_reminder(record, results)
        elif intent == Intent.COMMAND_REQUEST:
            self._handle_command(record, results)

        # If safe mode, flag all actions as pending
        if self.safe_mode:
            note = "Safe mode enabled — all actions recorded only"
            results["pending"].append({"reason": note})
            _audit_log("safe_mode", {"note": note}, "blocked")

        return results

    def _handle_reminder(
        self, record: ProcessedRecord, results: dict[str, Any]
    ) -> None:
        """Handle reminder_request: always queue for confirmation."""
        try:
            path = self.store.write_pending(
                record, "reminders",
                note=f"Due: {record.intent.due_date or 'unspecified'}"
            )
            results["pending"].append({
                "type": "reminder",
                "path": str(path),
                "due_date": record.intent.due_date,
            })
            _audit_log("queue_reminder", {
                "due_date": record.intent.due_date,
                "path": str(path),
            }, "queued")
        except Exception as e:
            results["errors"].append(f"reminder_queue_failed: {e}")
            _audit_log("queue_reminder", {"error": str(e)}, "failed")

    def _handle_command(
        self, record: ProcessedRecord, results: dict[str, Any]
    ) -> None:
        """Handle command_request: always queue for confirmation.

        Commands are NEVER auto-executed, even if in the allowlist.
        They are validated and queued for human review.
        """
        allowed_commands = self.config.get("actions.allowed_commands", [])
        blocked_patterns = self.config.get("actions.blocked_patterns", [])

        transcript = record.transcript.transcript.lower()
        matched_template = None

        for cmd_spec in allowed_commands:
            template = cmd_spec.get("template", "")
            # Simple check: does the transcript mention this command?
            template_words = template.split()
            if any(w in transcript for w in template_words if len(w) > 2):
                matched_template = cmd_spec
                break

        validation = {
            "matched_template": matched_template,
            "in_allowlist": matched_template is not None,
            "blocked": False,
        }

        if matched_template:
            cmd_str = matched_template["template"]
            if _is_blocked(cmd_str, blocked_patterns):
                validation["blocked"] = True

        try:
            path = self.store.write_pending(
                record, "commands",
                note=f"Validation: {json.dumps(validation)}"
            )
            results["pending"].append({
                "type": "command",
                "path": str(path),
                "validation": validation,
            })
            _audit_log("queue_command", {
                "validation": validation,
                "path": str(path),
            }, "queued")
        except Exception as e:
            results["errors"].append(f"command_queue_failed: {e}")
            _audit_log("queue_command", {"error": str(e)}, "failed")

    def execute_allowlisted_command(
        self,
        template: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """Execute a single allowlisted command after human confirmation.

        This is called ONLY after explicit human approval.
        """
        blocked_patterns = self.config.get("actions.blocked_patterns", [])

        # Validate template is in allowlist
        allowed = self.config.get("actions.allowed_commands", [])
        allowed_templates = [c["template"] for c in allowed]
        if template not in allowed_templates:
            _audit_log("execute_command", {
                "template": template,
                "reason": "not_in_allowlist",
            }, "blocked")
            return {"status": "blocked", "reason": "not_in_allowlist"}

        # Sanitize all parameters
        safe_params = {k: _sanitize_param(v) for k, v in params.items()}

        # Build command
        try:
            command = template.format(**safe_params)
        except KeyError as e:
            return {"status": "error", "reason": f"missing_parameter: {e}"}

        # Final blocked pattern check
        if _is_blocked(command, blocked_patterns):
            _audit_log("execute_command", {
                "command": command,
                "reason": "blocked_pattern",
            }, "blocked")
            return {"status": "blocked", "reason": "matches_blocked_pattern"}

        # Execute
        _audit_log("execute_command", {"command": command}, "executing")
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            _audit_log("execute_command", {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
            }, "completed")
            return {
                "status": "completed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            _audit_log("execute_command", {"command": command}, "timeout")
            return {"status": "timeout"}
        except Exception as e:
            _audit_log("execute_command", {
                "command": command,
                "error": str(e),
            }, "failed")
            return {"status": "error", "reason": str(e)}
