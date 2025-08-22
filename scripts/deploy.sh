#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Push current branch to GitHub and deploy to remote host via rsync over SSH.
# - Adds origin if missing (defaults to https://github.com/altmemy/admin-bot.git)
# - Syncs files to remote, excluding DB and env/caches via .deployignore
# - Bootstraps/updates a Python venv on remote and runs DB migrations if .env exists
#
# Usage:
#   scripts/deploy.sh [--dry-run] [--no-push] [--branch BRANCH]
#                     [--remote USER@HOST] [--key PATH] [--remote-dir PATH]
# Env overrides:
#   REPO_URL, GIT_REMOTE, REMOTE, SSH_KEY, REMOTE_DIR, EXCLUDES_FILE, REMOTE_PYTHON

REPO_URL_DEFAULT="https://github.com/altmemy/admin-bot.git"
REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
REMOTE="${REMOTE:-ec2-user@13.62.57.59}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/bot-key.pem}"
REMOTE_DIR="${REMOTE_DIR:-/home/ec2-user/admin-bot}"
EXCLUDES_FILE="${EXCLUDES_FILE:-.deployignore}"
NO_PUSH=false
DRY_RUN=false
BRANCH_OVERRIDE=""

SSH_OPTS=(
  -i "$SSH_KEY"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=60
  -o ServerAliveCountMax=2
)

usage() {
  cat <<USAGE
Usage: $0 [options]
  --dry-run               Show actions without making changes
  --no-push               Skip pushing to GitHub (deploy only)
  --branch BRANCH         Branch to push/deploy (default: current)
  --remote USER@HOST      SSH target (default: $REMOTE)
  --key PATH              SSH private key (default: $SSH_KEY)
  --remote-dir PATH       Target dir on remote (default: $REMOTE_DIR)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --no-push) NO_PUSH=true; shift ;;
    --branch)  BRANCH_OVERRIDE="$2"; shift 2 ;;
    --remote)  REMOTE="$2"; shift 2 ;;
    --key)     SSH_KEY="$2"; shift 2 ;;
    --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Error: '$1' not installed" >&2; exit 1; }; }

log() { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[err]\033[0m  %s\n" "$*"; }

run() {
  if $DRY_RUN; then
    echo "DRY-RUN: $*"
  else
    eval "$@"
  fi
}

ssh_run() {
  local cmd="$1"
  if $DRY_RUN; then
    echo "DRY-RUN: ssh ${SSH_OPTS[*]} $REMOTE \"$cmd\""
  else
    ssh "${SSH_OPTS[@]}" "$REMOTE" "$cmd"
  fi
}

git_current_branch() {
  if [[ -n "$BRANCH_OVERRIDE" ]]; then
    echo "$BRANCH_OVERRIDE"
  else
    git rev-parse --abbrev-ref HEAD
  fi
}

ensure_git_remote() {
  if git remote get-url "$GIT_REMOTE" >/dev/null 2>&1; then
    local existing_url
    existing_url=$(git remote get-url "$GIT_REMOTE")
    if [[ "$existing_url" != "$REPO_URL" ]]; then
      warn "Remote '$GIT_REMOTE' already set to $existing_url (leaving as-is)"
    fi
  else
    log "Adding git remote '$GIT_REMOTE' -> $REPO_URL"
    run "git remote add '$GIT_REMOTE' '$REPO_URL'"
  fi
}

push_to_github() {
  require_cmd git
  ensure_git_remote
  local branch
  branch=$(git_current_branch)
  if [[ -n "$(git status --porcelain)" ]]; then
    err "Uncommitted changes present. Commit or stash before pushing."
    exit 1
  fi
  log "Pushing branch '$branch' to '$GIT_REMOTE'"
  # Use -u if no upstream is set
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    run "git push '$GIT_REMOTE' '$branch'"
  else
    run "git push -u '$GIT_REMOTE' '$branch'"
  fi
}

rsync_sync() {
  require_cmd rsync
  require_cmd ssh

  # Ensure remote dir exists
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
    "--exclude=.env"
    "--exclude=.env.*"
    "--exclude=data/"
    "--exclude=*.db"
    "--exclude=*.sqlite*"
    "--exclude=*.log"
    "--exclude=*.pid"
    "--exclude=.DS_Store"
  )

  local exclude_arg=""
  if [[ -f "$EXCLUDES_FILE" ]]; then
    exclude_arg="--exclude-from=$EXCLUDES_FILE"
  fi

  log "Syncing project to $REMOTE:$REMOTE_DIR (excluding DB/env/caches)"
  local rsync_cmd=(
    rsync -az --delete
    "${excludes[@]}"
  )
  if [[ -n "$exclude_arg" ]]; then
    rsync_cmd+=("$exclude_arg")
  fi
  # Compose a single remote shell string for rsync (-e). Avoid newlines or array
  # expansions here to prevent ssh from mis-parsing -i and -o flags.
  local ssh_e="ssh -i '$SSH_KEY' -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 -o ServerAliveCountMax=2"
  rsync_cmd+=( -e "$ssh_e" ./ "$REMOTE:$REMOTE_DIR/" )

  if $DRY_RUN; then
    echo "DRY-RUN: ${rsync_cmd[*]}"
  else
    "${rsync_cmd[@]}"
  fi
}

remote_bootstrap() {
  # Create venv if missing, install deps, run migrations if .env present
  log "Bootstrapping/updating Python environment on remote"
  local cmd
  read -r -d '' cmd <<EOF || true
set -Eeuo pipefail
cd '$REMOTE_DIR'
PYTHON_CAND="${REMOTE_PYTHON:-}"

pick_python() {
  if [ -n "$PYTHON_CAND" ] && command -v "$PYTHON_CAND" >/dev/null 2>&1; then
    echo "$PYTHON_CAND"; return 0
  fi
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
    echo "Could not install Python 3.11 automatically. Please install it (e.g., 'sudo dnf install -y python3.11') and rerun."
    exit 1
  fi
fi

# Recreate venv if present but uses <3.11
if [ -d .venv ]; then
  if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)'; then
    echo "Existing .venv uses older Python; recreating with $PY_BIN"
    rm -rf .venv
  fi
fi

if [ ! -d .venv ]; then
  "$PY_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -e .

if [ -f .env ]; then
  echo "Running DB migrations..."
  python -m bot.infra.migrate || {
    echo "Migration failed; please check .env and logs" >&2
    exit 1
  }
else
  echo "No .env on remote; skipping migrations. Create $REMOTE_DIR/.env"
fi
EOF
  ssh_run "$cmd"
}

main() {
  # Validate tools
  require_cmd git
  require_cmd ssh
  require_cmd rsync

  if [[ ! -f "$SSH_KEY" ]]; then
    err "SSH key not found: $SSH_KEY"
    exit 1
  fi

  if ! $NO_PUSH; then
    push_to_github
  else
    warn "Skipping git push as requested (--no-push)"
  fi

  rsync_sync
  remote_bootstrap
  log "Deployment complete. Remote: $REMOTE:$REMOTE_DIR"
}

main "$@"
