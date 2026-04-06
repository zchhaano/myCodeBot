# Scheduling Examples

## Method A: System Cron (Linux/macOS)

### Daily Digest — Every day at 22:00

```cron
0 22 * * * cd /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian && /usr/bin/python3 scripts/daily_digest.py >> logs/digest.log 2>&1
```

### Weekly Digest — Every Sunday at 21:30

```cron
30 21 * * 0 cd /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian && /usr/bin/python3 scripts/weekly_digest.py >> logs/digest.log 2>&1
```

### Install crontab

```bash
# Edit crontab
crontab -e

# Or install from a file
crontab scheduling/crontab.example
```

### systemd Timer (Linux only)

**scheduling/voice-digest-daily.timer:**
```ini
[Unit]
Description=Voice Bridge Daily Digest

[Timer]
OnCalendar=*-*-* 22:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**scheduling/voice-digest-daily.service:**
```ini
[Unit]
Description=Run daily voice digest

[Service]
Type=oneshot
WorkingDirectory=/home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian
ExecStart=/usr/bin/python3 scripts/daily_digest.py
```

## Method B: Claude Code Scheduled Tasks

Use Claude Code's built-in cron system to schedule digests.

### Daily Digest

In Claude Code, run:
```
/schedule "0 22 * * *" "Generate the daily voice digest by running: python /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian/scripts/daily_digest.py — then report the result briefly."
```

Or using CronCreate with durable:true for persistence across sessions.

### Weekly Digest

```
/schedule "30 21 * * 0" "Generate the weekly voice digest by running: python /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian/scripts/weekly_digest.py — then report the result briefly."
```

### Using the CronCreate tool directly

```
CronCreate({
  cron: "0 22 * * *",
  prompt: "Run the daily voice digest: cd /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian && python3 scripts/daily_digest.py. Report any errors.",
  recurring: true,
  durable: true
})
```

```
CronCreate({
  cron: "30 21 * * 0",
  prompt: "Run the weekly voice digest: cd /home/chao/projects/ObsidianVaults/openclaw/.claude/skills/voice-bridge-obsidian && python3 scripts/weekly_digest.py. Report any errors.",
  recurring: true,
  durable: true
})
```
