#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Deploy to remote via rsync + optional Git push + remote bootstrap (venv/migrate).
# Usage:
#   scripts/deploy.sh [--dry-run] [--no-push] [--branch BRANCH]
#     [--remote USER@HOST] [--key PATH] [--remote-dir PATH]
#     [--excludes-file PATH] [--service NAME]
#
# Env overrides:
#   REPO_URL, GIT_REMOTE, REMOTE, SSH_KEY, REMOTE_DIR, EXCLUDES_FILE, REMOTE_PYTHON
#   SERVICE  (same as --service)

REPO_URL_DEFAULT="https://github.com/altmemy/admin-bot.git"
REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
REMOTE="${REMOTE:-ec2-user@13.62.57.59}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/bot-key.pem}"
REMOTE_DIR="${REMOTE_DIR:-/home/ec2-user/admin-bot}"
EXCLUDES_FILE="${EXCLUDES_FILE:-.deployignore}"
SERVICE="${SERVICE:-admin-bot}"
NO_PUSH=false
DRY_RUN=false
BRANCH_OVERRIDE=""

usage() {
  cat <<USAGE
Usage: $0 [options]
  --dry-run               Show actions without making changes
  --no-push               Skip pushing to GitHub (deploy only)
  --branch BRANCH         Branch to push/deploy (default: current)
  --remote USER@HOST      SSH target (default: $REMOTE)
  --key PATH              SSH private key (default: $SSH_KEY)
  --remote-dir PATH       Target dir on remote (default: $REMOTE_DIR)
  --excludes-file PATH    rsync exclude file (default: $EXCLUDES_FILE)
  --service NAME          systemd unit to restart after deploy (default: admin-bot)
  -h, --help              Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --no-push) NO_PUSH=true; shift ;;
    --branch)  BRANCH_OVERRIDE="${2:?}"; shift 2 ;;
    --remote)  REMOTE="${2:?}"; shift 2 ;;
    --key)     SSH_KEY="${2:?}"; shift 2 ;;
    --remote-dir) REMOTE_DIR="${2:?}"; shift 2 ;;
    --excludes-file) EXCLUDES_FILE="${2:?}"; shift 2 ;;
    --service) SERVICE="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

# Rebuild SSH options AFTER parsing CLI overrides
SSH_OPTS=(
  -i "$SSH_KEY"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=60
  -o ServerAliveCountMax=2
)

log()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[err]\033[0m  %s\n" "$*"; }

trap 'err "Failed at line $LINENO"; exit 1' ERR

# DRY-RUN aware command runner (array-safe)
run_cmd() {
  if $DRY_RUN; then printf "DRY-RUN: "; printf "%q " "$@"; printf "\n"; else "$@"; fi
}

ssh_run() {
  local cmd="$1"
  if $DRY_RUN; then
    echo "DRY-RUN: ssh ${SSH_OPTS[*]} $REMOTE \"$cmd\""
  else
    ssh "${SSH_OPTS[@]}" "$REMOTE" "$cmd"
  fi
}

require_cmd() { command -v "$1" >/dev/null 2>&1 || { err "'$1' not installed"; exit 1; }; }

ensure_repo_root() {
  # Prefer Git root if available; else, use script dir/..
  local to_root=""
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    to_root="$(git rev-parse --show-toplevel)"
  else
    to_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  cd "$to_root"
}

git_current_branch() {
  if [[ -n "$BRANCH_OVERRIDE" ]]; then
    echo "$BRANCH_OVERRIDE"; return
  fi
  local b
  b="$(git symbolic-ref --short -q HEAD || true)"
  if [[ -z "$b" ]]; then
    # detached HEAD
    echo "HEAD"
  else
    echo "$b"
  fi
}

ensure_git_remote() {
  if git remote get-url "$GIT_REMOTE" >/dev/null 2>&1; then
    local existing_url; existing_url=$(git remote get-url "$GIT_REMOTE")
    if [[ "$existing_url" != "$REPO_URL" ]]; then
      warn "Remote '$GIT_REMOTE' already set to $existing_url (leaving as-is)"
    fi
  else
    log "Adding git remote '$GIT_REMOTE' -> $REPO_URL"
    run_cmd git remote add "$GIT_REMOTE" "$REPO_URL"
  fi
}

push_to_github() {
  ensure_git_remote
  local branch; branch=$(git_current_branch)

  if [[ "$branch" == "HEAD" && -z "$BRANCH_OVERRIDE" ]]; then
    warn "Detached HEAD; skipping Git push. Use --branch to force."
    return 0
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    warn "Local changes detected; skipping GitHub push and deploying working tree."
    return 0
  fi

  log "Pushing branch '$branch' to '$GIT_REMOTE'"
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    run_cmd git push "$GIT_REMOTE" "$branch"
  else
    run_cmd git push -u "$GIT_REMOTE" "$branch"
  fi
}

rsync_sync() {
  require_cmd rsync
  require_cmd ssh

  # Key permissions (avoid SSH warnings)
  if [[ -f "$SSH_KEY" ]]; then
    chmod 600 "$SSH_KEY" >/dev/null 2>&1 || true
  else
    err "SSH key not found: $SSH_KEY"; exit 1
  fi

  log "Ensuring remote directory exists: $REMOTE_DIR"
  ssh_run "mkdir -p '$REMOTE_DIR'"

  local excludes=(
    "--exclude=.git/"
    "--exclude=.github/"
    "--exclude=.venv/"
    "--exclude=__pycache__/"
    "--exclude=*.pyc"
    "--exclude=*.pyo"
    "--exclude=.mypy_cache/"
    "--exclude=.pytest_cache/"
    "--exclude=.ruff_cache/"
    "--exclude=data/"
    "--exclude=*.db"
    "--exclude=*.sqlite*"
    "--exclude=*.log"
    "--exclude=*.pid"
    "--exclude=.DS_Store"
  )

  local rsync_cmd=( rsync -az --delete )
  rsync_cmd+=( "${excludes[@]}" )
  [[ -f "$EXCLUDES_FILE" ]] && rsync_cmd+=( "--exclude-from=$EXCLUDES_FILE" )

  # Use current SSH key/options for rsync
  local ssh_e="ssh -i '$SSH_KEY' -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 -o ServerAliveCountMax=2"
  rsync_cmd+=( -e "$ssh_e" ./ "$REMOTE:$REMOTE_DIR/" )

  if $DRY_RUN; then
    printf "DRY-RUN: "; printf "%q " "${rsync_cmd[@]}"; printf "\n"
  else
    "${rsync_cmd[@]}"
  fi
}

remote_verify() {
  log "Verifying essential files on remote"
  cmd=$(cat <<EOF
set -Eeuo pipefail
cd '$REMOTE_DIR' 2>/dev/null || cd /home/ec2-user/admin-bot || exit 1

ok=true
check() { if [ -e "\$1" ]; then echo "[ok] \$1"; else echo "[missing] \$1"; ok=false; fi; }

check pyproject.toml
check bot/main.py
check bot/infra/migrate.py
check bot/locales/en.json
check bot/locales/ar.json

for d in bot/core bot/infra bot/features; do
  if [ -d "\$d" ]; then echo "[ok] \$d/"; else echo "[missing] \$d/"; ok=false; fi
done

if [ "\$ok" = true ]; then
  echo "verify: OK"
  exit 0
else
  echo "verify: FAILED" >&2
  exit 2
fi
EOF
)
  ssh_run "$cmd" || true
}

remote_bootstrap() {
  log "Bootstrapping/updating Python environment on remote"
  local script
  script=$(cat <<'EOS'
set -Eeuo pipefail
cd "$REMOTE_DIR" || exit 1

PYTHON_CAND="${REMOTE_PYTHON:-}"
pick_python() {
  if [ -n "$PYTHON_CAND" ] && command -v "$PYTHON_CAND" >/dev/null 2>&1; then echo "$PYTHON_CAND"; return 0; fi
  if command -v python3.11 >/dev/null 2>&1; then echo python3.11; return 0; fi
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)'; then
    echo python3; return 0
  fi
  return 1
}

PY_BIN=$(pick_python || true)
if [ -z "$PY_BIN" ]; then
  echo "Python >= 3.11 not found. Attempting to install..."
  if command -v dnf >/dev/null 2>&1; then
    sudo -n dnf install -y python3.11 python3.11-devel || true
  elif command -v yum >/dev/null 2>&1; then
    if command -v amazon-linux-extras >/dev/null 2>&1; then
      sudo -n amazon-linux-extras enable python3.11 || true
    fi
    sudo -n yum install -y python3.11 python3.11-devel || true
  elif command -v apt-get >/dev/null 2>&1; then
    sudo -n apt-get update || true
    sudo -n apt-get install -y python3.11 python3.11-venv python3.11-distutils || true
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    PY_BIN=python3.11
  else
    echo "Could not install Python 3.11 automatically. Please install it and rerun." >&2
    exit 1
  fi
fi

if [ -d .venv ]; then
  if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)'; then
    echo "Existing .venv uses older Python; recreating with $PY_BIN"
    rm -rf .venv
  fi
fi

[ -d .venv ] || "$PY_BIN" -m venv .venv
set +u; . .venv/bin/activate; set -u
python -m pip install -U pip setuptools wheel
pip install -e .

if [ -f .env ]; then
  echo "Running DB migrations..."
  python -m bot.infra.migrate || { echo "Migration failed; check .env/logs" >&2; exit 1; }
else
  echo "No .env on remote; skipping migrations."
fi
EOS
)
  local env_prefix="REMOTE_DIR=$(printf "%q" "$REMOTE_DIR")"
  if [[ -n "${REMOTE_PYTHON:-}" ]]; then env_prefix+=" REMOTE_PYTHON=$(printf "%q" "$REMOTE_PYTHON")"; fi
  ssh_run "$env_prefix bash -lc $(printf "%q" "$script")"
}

remote_restart_service() {
  if [[ -z "${SERVICE:-}" ]]; then return 0; fi
  log "Restarting systemd service: $SERVICE"
  ssh_run "sudo -n systemctl daemon-reload || true; sudo -n systemctl restart '$SERVICE'; sudo -n systemctl status --no-pager --lines=10 '$SERVICE' || true"
}

with_remote_lock() {
  # prevent concurrent deploys
  local body="$1"
  local lock_cmd=$(cat <<EOF
flock -n /tmp/admin-bot.deploy.lock bash -lc $(printf "%q" "$body") || {
  echo "Another deploy is in progress (lock busy)"; exit 1;
}
EOF
)
  ssh_run "$lock_cmd"
}

main() {
  require_cmd ssh
  require_cmd rsync
  ensure_repo_root

  if ! $NO_PUSH; then
    require_cmd git
    push_to_github
  else
    warn "Skipping git push as requested (--no-push)"
  fi

  rsync_sync
  # Lock only around bootstrap/restart (rsync already done)
  with_remote_lock "$(cat <<EOF
cd $(printf "%q" "$REMOTE_DIR") || exit 1
EOF
)"
  remote_verify
  remote_bootstrap
  remote_restart_service

  log "Deployment complete. Remote: $REMOTE:$REMOTE_DIR"
}

main "$@"
