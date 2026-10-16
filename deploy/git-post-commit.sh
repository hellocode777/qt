#!/usr/bin/env bash
# =============================================================================
# deploy/git-post-commit.sh — post-commit hook: auto-deploy scheduler
#
# Runs after every successful `git commit`. If the commit touched anything
# that affects the running scheduler process, it re-runs
# deploy/install-systemd.sh so the live service always matches the code.
#
# Guards (so the hook never breaks your day):
#   0. Pause guard — if the unit is not `enabled` the scheduler has been
#      intentionally paused (systemctl --user disable qp-scheduler): the hook
#      does NOT deploy, otherwise a code commit would silently resurrect a
#      service the operator just stopped. (install-systemd.sh enables+starts
#      unconditionally, so this guard is the only thing that makes a pause
#      survive a commit.)
#   1. Path filter — only scheduler-affecting paths trigger a redeploy
#      (qp/** except qp/web/**, deploy/systemd/**, install script).
#      Pure doc / web / data commits skip deployment entirely.
#   2. Job window guard — never restart while a scheduled job may be running,
#      otherwise the restart (SIGTERM → QPScheduler.stop() →
#      shutdown(wait=False), qp/platform/scheduler/scheduler.py) kills the
#      in-flight job without waiting for it.  The windows are DERIVED from the
#      job registry in qp/platform/cli/commands/scheduler.py (single source of
#      truth) instead of hand-copied times: [start - LEAD, start + guard(job)].
#      A parse failure falls back to the legacy static windows and says so.
#   3. sudo guard — install-systemd.sh only needs sudo when a system-level
#      copy exists (rare). If sudo is required but not passwordless, skip
#      and tell the user to run it manually instead of hanging the hook.
#
# Install (idempotent):
#   ln -sf "$(pwd)/deploy/git-post-commit.sh" .git/hooks/post-commit
#
# Testing (no git commit needed, never touches the service):
#   QP_HOOK_DRY_RUN=1 QP_HOOK_FILES="qp/pipeline/daily_pipeline.py" \
#   QP_HOOK_NOW_MIN=1090 bash deploy/git-post-commit.sh
#     QP_HOOK_DRY_RUN=1   report instead of deploy
#     QP_HOOK_FILES=...   override the committed-file list (newline separated)
#     QP_HOOK_NOW_MIN=... override minute-of-day (0-1439) for the window guard
#     QP_HOOK_VERBOSE=1   print the derived window table as well
#     QP_HOOK_REGISTRY=.. override the registry file (to exercise the fallback)
# =============================================================================
set -uo pipefail

REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -n "$REPO_DIR" ] || exit 0
cd "$REPO_DIR" || exit 0

SERVICE_NAME="qp-scheduler"
HOOK_NAME="[post-commit]"
DRY_RUN="${QP_HOOK_DRY_RUN:-0}"

# ---------------------------------------------------------------------------
# 0. Pause guard — a disabled unit means "operator paused this on purpose"
# ---------------------------------------------------------------------------
ENABLED_STATE="$(systemctl --user is-enabled "$SERVICE_NAME" 2>/dev/null || true)"
if [ "$ENABLED_STATE" != "enabled" ]; then
    echo "$HOOK_NAME $SERVICE_NAME is '$ENABLED_STATE' (paused) — skip auto-deploy"
    echo "$HOOK_NAME resume with: systemctl --user enable --now $SERVICE_NAME"
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Path filter — which commits trigger a redeploy
#
# The scheduler is a single in-process APScheduler (BackgroundScheduler,
# qp/platform/scheduler/scheduler.py). Its jobs import qp.pipeline,
# qp.monitoring, qp.data, qp.decision etc. directly, so ANY change under
# qp/** (except qp/web/**, which runs as a separate --reload process) can
# affect the running scheduler and requires a restart.
#
# Exclusion-based (safer than a whitelist): trigger on any qp/** change
# outside qp/web/**, plus deploy scripts. Skip docs/tests/data-only files.
# ---------------------------------------------------------------------------
if [ -n "${QP_HOOK_FILES:-}" ]; then
    FILES="$QP_HOOK_FILES"
else
    FILES="$(git show --name-only --format= HEAD 2>/dev/null || true)"
fi

NEEDS_DEPLOY=0
while IFS= read -r f; do
    case "$f" in
        qp/*)
            # qp/web runs under its own uvicorn --reload process → no restart.
            case "$f" in
                qp/web/*) ;;
                *) NEEDS_DEPLOY=1 ;;
            esac
            ;;
        deploy/systemd/*|deploy/install-systemd.sh|deploy/git-post-commit.sh)
            NEEDS_DEPLOY=1
            ;;
    esac
done <<< "$FILES"

if [ "$NEEDS_DEPLOY" -eq 0 ]; then
    echo "$HOOK_NAME no scheduler-affecting changes — skip auto-deploy"
    exit 0
fi

echo "$HOOK_NAME scheduler-affecting changes detected"

# ---------------------------------------------------------------------------
# 2. Job window guard — windows derived from the job registry
#
# Guard length AFTER the scheduled start, in minutes: how long the job may
# still be running, so a restart inside the window would kill it mid-run.
#   daily_pipeline: 25 — measured 22 min on 2026-10-16
#     (logs/2026-10-16/daily_pipeline.log: 18:00:00 → 18:21:54)
#   others: 5 — measured well under a minute (monitor/pre_close logs finish
#     ~30s after their start; paper_trading was a no-op)
# ---------------------------------------------------------------------------
GUARD_LEAD=2  # minutes BEFORE the scheduled start

guard_minutes() {
    case "$1" in
        daily_pipeline) echo 25 ;;
        *) echo 5 ;;
    esac
}

registry_schedule() {
    local py="$REPO_DIR/.venv/bin/python"
    [ -x "$py" ] || py="$(command -v python3 || true)"
    [ -n "$py" ] || return 1
    "$py" - "${QP_HOOK_REGISTRY:-$REPO_DIR/qp/platform/cli/commands/scheduler.py}" 2>/dev/null <<'PY'
"""Print '<job_name> <minute_of_day>' for every CronTrigger job.

Reads the job registry (single source of truth) so the post-commit window
guard can never drift from the real schedule.
"""
import pathlib
import re
import sys

src = pathlib.Path(sys.argv[1]).read_text()
blocks = src.split("scheduler.add_job(")[1:]  # one chunk per registered job
name_re = re.compile(r'name="([a-z_]+)"')
cron_re = re.compile(
    r'CronTrigger\([^)]*?hour="(\d+)",\s*minute="(\d+)"',
    re.S,
)

found = 0
for block in blocks:
    m_name = name_re.search(block)
    m_cron = cron_re.search(block)
    if not (m_name and m_cron):
        continue
    print(f"{m_name.group(1)} {int(m_cron.group(1)) * 60 + int(m_cron.group(2))}")
    found += 1
sys.exit(0 if found else 1)
PY
}

NOW_MIN="${QP_HOOK_NOW_MIN:-$((10#$(date +%H) * 60 + 10#$(date +%M)))}"

SCHEDULE="$(registry_schedule)" || SCHEDULE=""
JOBS=$(printf '%s\n' "$SCHEDULE" | grep -c '[^[:space:]]' || true)

if [ "${JOBS:-0}" -ge 1 ]; then
    if [ "$DRY_RUN" != "0" ] || [ -n "${QP_HOOK_VERBOSE:-}" ]; then
        echo "$HOOK_NAME job windows derived from scheduler.py ($JOBS jobs):"
        while read -r name start; do
            [ -n "$name" ] || continue
            g=$(guard_minutes "$name")
            printf '%s   %s  window %02d:%02d-%02d:%02d\n' \
                "$HOOK_NAME" "$name" \
                $(( (start - GUARD_LEAD) / 60 )) $(( (start - GUARD_LEAD) % 60 )) \
                $(( (start + g) / 60 )) $(( (start + g) % 60 ))
        done <<< "$SCHEDULE"
    fi

    BLOCKED=""
    while read -r name start; do
        [ -n "$name" ] || continue
        g=$(guard_minutes "$name")
        if [ "$NOW_MIN" -ge $((start - GUARD_LEAD)) ] && [ "$NOW_MIN" -le $((start + g)) ]; then
            BLOCKED="$name"
        fi
    done <<< "$SCHEDULE"
else
    # Fallback: legacy hand-copied windows (kept only for the parse-failure
    # case — if this branch fires, fix registry_schedule(), not this list).
    echo "$HOOK_NAME WARNING: could not derive job windows from scheduler.py — using fallback"
    BLOCKED=""
    for w in "545 550" "555 560" "1010 1016" "1078 1105" "1108 1113"; do
        set -- $w
        if [ "$NOW_MIN" -ge "$1" ] && [ "$NOW_MIN" -le "$2" ]; then
            BLOCKED="(fallback window $1-$2)"
        fi
    done
fi

if [ -n "$BLOCKED" ]; then
    echo "$HOOK_NAME in job window ($BLOCKED) at $(printf '%02d:%02d' $((NOW_MIN / 60)) $((NOW_MIN % 60))) — skipped auto-restart"
    echo "$HOOK_NAME run manually after the window: bash deploy/install-systemd.sh"
    exit 0
fi

# ---------------------------------------------------------------------------
# 3. sudo guard — system-level copy requires sudo; don't hang on password
# ---------------------------------------------------------------------------
if [ -f /etc/systemd/system/qp-scheduler.service ]; then
    if ! sudo -n true 2>/dev/null; then
        echo "$HOOK_NAME system-level copy found and sudo needs a password —"
        echo "$HOOK_NAME run manually: sudo bash deploy/install-systemd.sh"
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# 4. Deploy
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" != "0" ]; then
    echo "$HOOK_NAME DRY RUN — would execute: bash deploy/install-systemd.sh"
    exit 0
fi

echo "$HOOK_NAME running deploy/install-systemd.sh ..."
bash deploy/install-systemd.sh
status=$?
if [ "$status" -eq 0 ]; then
    echo "$HOOK_NAME deployed — $(systemctl --user show "$SERVICE_NAME" -p MainPID --value) active since $(systemctl --user show "$SERVICE_NAME" -p ActiveEnterTimestamp --value)"
fi
exit "$status"
