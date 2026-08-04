#!/usr/bin/env python3
"""Test: send today's DecisionPackage as email."""

import json
from pathlib import Path

from qp.monitoring.alerts import Alert, AlertManager, AlertSeverity, EmailAlert
from qp.platform.cli.commands.scheduler import format_decision_email

# Find latest DecisionPackage
decisions_dir = Path("data/decisions")
json_files = sorted(decisions_dir.glob("dp-*.json"), reverse=True)

if not json_files:
    print("No DecisionPackage found. Run: uv run qp run daily --demo")
    exit(1)

dp_path = json_files[0]
print(f"Loading: {dp_path.name}")

dp = json.loads(dp_path.read_text(encoding="utf-8"))
body = format_decision_email(dp, dp_path.stem)

print("=== Email Preview ===")
print(body)
print("=== End Preview ===")

email = EmailAlert()
if not email.is_configured:
    print("\nEmail not configured. Set SMTP_* env vars.")
    exit(1)

mgr = AlertManager()
mgr.add_channel(email)
mgr.send(
    Alert(
        severity=AlertSeverity.INFO,
        title=f"[TEST] QP 每日投资决策 — {dp_path.stem}",
        message=body,
        source="manual_test",
    )
)
print("\n✅ Sent! Check zhangs_shuai777@163.com")
