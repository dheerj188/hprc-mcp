#!/usr/bin/env bash
# One-time setup on YOUR LAPTOP (macOS, Linux or WSL). Nothing is installed on Grace.
#
#   ./setup.sh <NetID>
#
# 1. installs uv (a Python package manager) and the server's packages, on this laptop
# 2. adds a "grace" entry with login sharing to ~/.ssh/config (backup kept), unless one exists;
#    the shared login closes itself after 1 hour without use (ControlPersist 1h)
# 3. registers the "hprc" server with Claude Desktop (macOS) and Claude Code (.mcp.json here)
# 4. runs the tests on a simulated cluster
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"
NETID="${1:-}"

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "==> Installing uv on this laptop (~/.local/bin)"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

echo "==> Installing the server's Python packages into $REPO/.venv"
"$UV" sync --quiet

echo "==> SSH: one login (password + Duo), shared until you close it or 1 hour without use"
if ssh -G grace 2>/dev/null | grep -qi '^hostname grace.hprc.tamu.edu'; then
  if ssh -G grace 2>/dev/null | grep -qi '^controlmaster auto'; then
    echo "    ~/.ssh/config already has 'Host grace' with login sharing."
  else
    echo "    You already have 'Host grace' in ~/.ssh/config. Add these three lines under it:"
    printf '      ControlMaster auto\n      ControlPath ~/.ssh/cm-%%C\n      ControlPersist 1h\n'
  fi
else
  [ -n "$NETID" ] || read -rp "    Your TAMU NetID: " NETID
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  [ -f "$HOME/.ssh/config" ] && cp "$HOME/.ssh/config" "$HOME/.ssh/config.bak-hprc-mcp"
  printf '\nHost grace\n  HostName grace.hprc.tamu.edu\n  User %s\n  ControlMaster auto\n  ControlPath ~/.ssh/cm-%%C\n  ControlPersist 1h\n' \
    "$NETID" >> "$HOME/.ssh/config"
  chmod 600 "$HOME/.ssh/config"
  echo "    Added 'Host grace' to ~/.ssh/config (backup: ~/.ssh/config.bak-hprc-mcp if it existed)."
fi

echo "==> Registering the server with Claude"
cat > .mcp.json <<EOF
{ "mcpServers": { "hprc": { "type": "stdio", "command": "$UV", "args": ["run", "--quiet", "--directory", "$REPO", "hprc-mcp"] } } }
EOF
echo "    Claude Code: .mcp.json written (run 'claude' in this folder)."
DESKTOP="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
if [ -d "$(dirname "$DESKTOP")" ]; then
  "$UV" run --quiet python - "$DESKTOP" "$UV" "$REPO" <<'PY'
import json, os, shutil, sys
path, uv, repo = sys.argv[1:]
config = {}
if os.path.exists(path):
    shutil.copy(path, path + ".bak-hprc-mcp")
    config = json.load(open(path))
config.setdefault("mcpServers", {})["hprc"] = {"command": uv, "args": ["run", "--quiet", "--directory", repo, "hprc-mcp"]}
json.dump(config, open(path, "w"), indent=2)
PY
  echo "    Claude Desktop: 'hprc' added (backup kept). Quit and reopen Claude Desktop."
fi

echo "==> Testing the server on a simulated cluster"
"$UV" run --quiet pytest -q

cat <<'EOF'

Done. Next:
  1. ssh grace      (password + Duo once, then type exit; the login stays shared in the background)
  2. Claude Desktop: open a normal chat and switch on "hprc"   - or -   run: claude   (in this folder)
  3. Ask: "Run examples/monte_carlo_pi.py with 4 cores for 10 minutes and tell me the result."
  4. Done? Tell Claude "I'm done, end the session", or run: ssh -O exit grace
     (it also closes itself after 1 hour without use)
EOF
