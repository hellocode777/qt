#!/usr/bin/env bash
# =============================================================================
# deploy/git-post-commit.sh — post-commit hook: auto-deploy scheduler
#
# Runs after every successful `git commit`. If the commit touched anything
# that affects the running scheduler process, it re-runs
# deploy/install-systemd.sh so the live service always matches the code.
#
# Guards (so the hook never breaks your day):
#   1. Path filter — only scheduler-affecting paths trigger a redeploy
#      (qp/monitoring/**, scheduler.py, deploy/systemd/**, install script).
#      Pure doc / web / data commits skip deployment entirely.
#   2. Job window guard — never restart during scheduler job windows
#      (09:05-09:10, 09:15-09:20, 16:50-16:56, 17:58-18:08, 18:28-18:33),
#      otherwise the restart would interrupt a running job (daily pipeline
#      at 18:00 etc.). In-window commits are skipped with a reminder to run
#      the install script manually.
#   3. sudo guard — install-systemd.sh only needs sudo when a system-level
#      copy exists (rare). If sudo is required but not passwordless, skip
#      and tell the user to run it manually instead of hanging the hook.
#
# Install (idempotent):
#   ln -sf "$(pwd)/deploy/git-post-commit.sh" .git/hooks/post-commit
# =============================================================================
set -uo pipefail

REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -n "$REPO_DIR" ] || exit 0
cd "$REPO_DIR" || exit 0

HOOK_NAME="[post-commit]"

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
FILES="$(git show --name-only --format= HEAD 2>/dev/null || true)"

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
# 2. Job window guard (minute-of-day comparisons)
# ---------------------------------------------------------------------------
NOW_MIN=$((10#$(date +%H) * 60 + 10#$(date +%M)))

in_window() { [ "$NOW_MIN" -ge "$1" ] && [ "$NOW_MIN" -le "$2" ]; }

if in_window 545 550 || in_window 555 560 || in_window 1010 1016 \
   || in_window 1078 1088 || in_window 1108 1113; then
    echo "$HOOK_NAME in scheduler job window — skipped auto-restart"
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
echo "$HOOK_NAME running deploy/install-systemd.sh ..."
bash deploy/install-systemd.sh
exit $?
