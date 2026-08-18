#!/usr/bin/env bash
# =============================================================================
# deploy/install-systemd.sh — idempotent QP systemd service installer
#
# Background: qp-scheduler.service historically existed in BOTH
#   /etc/systemd/system/          (system level, first deployed 2026-07-25)
#   ~/.config/systemd/user/       (user level, added 2026-08-13)
# After a reboot both got started → two scheduler processes → every
# 18:30 email_report fired twice (2026-08-13 double-run, 2026-08-18 again).
#
# This installer enforces ONE canonical instance: the USER-level service.
# - If a system-level copy exists, it is stopped/disabled/removed.
# - The user-level copy is (re)installed from the deploy template.
# - Safe to run repeatedly (idempotent): no-op when already correct.
#
# Usage:
#   bash deploy/install-systemd.sh            # install/repair user-level service
#   bash deploy/install-systemd.sh --check    # dry-run: report state, change nothing
# =============================================================================
set -euo pipefail

SERVICE_NAME="qp-scheduler.service"
SYSTEM_UNIT="/etc/systemd/system/${SERVICE_NAME}"
USER_UNIT="${HOME}/.config/systemd/user/${SERVICE_NAME}"
TEMPLATE="$(cd "$(dirname "$0")" && pwd)/systemd/${SERVICE_NAME}"
CHECK_ONLY="${1:-}"

log()  { printf '[install-systemd] %s\n' "$*"; }
die()  { printf '[install-systemd] ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

# ---------------------------------------------------------------------------
# 1. Report current state
# ---------------------------------------------------------------------------
sys_exists=no;  sys_enabled=no;  sys_active=no
usr_exists=no;  usr_enabled=no;  usr_active=no

if [ -f "$SYSTEM_UNIT" ]; then sys_exists=yes; fi
if [ "$sys_exists" = yes ] && systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then sys_enabled=yes; fi
if [ "$sys_exists" = yes ] && systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then sys_active=yes; fi

if [ -f "$USER_UNIT" ]; then usr_exists=yes; fi
if [ "$usr_exists" = yes ] && systemctl --user is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then usr_enabled=yes; fi
if [ "$usr_exists" = yes ] && systemctl --user is-active "$SERVICE_NAME" >/dev/null 2>&1; then usr_active=yes; fi

log "state: system=${sys_exists}/enabled=${sys_enabled}/active=${sys_active}  user=${usr_exists}/enabled=${usr_enabled}/active=${usr_active}"

if [ "$CHECK_ONLY" = "--check" ]; then
    log "dry-run (--check): would remove system-level copy if present, install user-level from template"
    exit 0
fi

# ---------------------------------------------------------------------------
# 2. Remove system-level copy (the duplicate source)
# ---------------------------------------------------------------------------
if [ "$sys_exists" = yes ]; then
    log "removing system-level ${SERVICE_NAME} (duplicate)"
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "$SYSTEM_UNIT"
    sudo systemctl daemon-reload
    log "system-level copy removed"
else
    log "no system-level copy (good)"
fi

# ---------------------------------------------------------------------------
# 3. Install / refresh user-level copy (canonical)
# ---------------------------------------------------------------------------
mkdir -p "${HOME}/.config/systemd/user"

if [ -f "$USER_UNIT" ]; then
    if ! diff -q "$TEMPLATE" "$USER_UNIT" >/dev/null 2>&1; then
        log "user-level unit differs from template — refreshing"
        cp "$TEMPLATE" "$USER_UNIT"
        systemctl --user daemon-reload
    else
        log "user-level unit already matches template (no-op)"
    fi
else
    log "installing user-level ${SERVICE_NAME}"
    cp "$TEMPLATE" "$USER_UNIT"
    systemctl --user daemon-reload
fi

if [ "$usr_enabled" != yes ]; then
    systemctl --user enable "$SERVICE_NAME"
    log "user-level service enabled"
else
    log "user-level service already enabled (no-op)"
fi

if [ "$usr_active" = yes ]; then
    log "user-level service already running — restarting to pick up unit changes"
    systemctl --user restart "$SERVICE_NAME"
else
    systemctl --user start "$SERVICE_NAME"
    log "user-level service started"
fi

# ---------------------------------------------------------------------------
# 4. Verify: exactly ONE scheduler process
# ---------------------------------------------------------------------------
sleep 2
count=$(pgrep -fc "qp.platform.cli.main scheduler start" || true)
log "verification: ${count} scheduler process(es) running"

if [ "$count" -gt 1 ]; then
    die "expected 1 scheduler process, found ${count} — manual cleanup required"
fi
if [ "$count" -lt 1 ]; then
    die "scheduler not running after install — check journalctl --user -u ${SERVICE_NAME}"
fi

log "OK — exactly one scheduler instance. System-level duplicate removed."
