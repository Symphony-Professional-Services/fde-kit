#!/bin/sh
set -eu

# AI-DLC FDE Profile Onboarding Script
# Supports: macOS (Apple Silicon / Intel), Linux (Ubuntu / Debian)
# Windows users: Must run inside WSL2 (Ubuntu)

echo "=== Symphony AI Enablement - FDE Profile Setup ==="

# 1. Platform Check
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        echo "Detected macOS ($ARCH)"
        RAW_MACHINE_ID="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
        ;;
    Linux)
        echo "Detected Linux ($ARCH)"
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            echo "Distribution: ${PRETTY_NAME:-Linux}"
        fi
        RAW_MACHINE_ID="$(hostname -s 2>/dev/null || uname -n)"
        ;;
    CYGWIN*|MINGW*|MSYS*)
        echo "ERROR: Native Windows shell detected ($OS)." >&2
        echo "AI-DLC and the FDE profile require a POSIX environment." >&2
        echo "Please install WSL2 (Ubuntu) on Windows and run this script inside your WSL2 terminal:" >&2
        echo "  wsl --install -d Ubuntu" >&2
        exit 1
        ;;
    *)
        echo "Warning: Untested operating system: $OS" >&2
        RAW_MACHINE_ID="$(hostname -s 2>/dev/null || uname -n)"
        ;;
esac

# 2. Check if ai-dlc is installed
if ! command -v ai-dlc >/dev/null 2>&1; then
    # Check if bootstrap bin directory exists
    BOOTSTRAP_BIN="${XDG_DATA_HOME:-$HOME/.local/share}/ai-dlc/bootstrap/bin"
    if [ -x "$BOOTSTRAP_BIN/ai-dlc" ]; then
        export PATH="$BOOTSTRAP_BIN:$PATH"
    else
        echo "ai-dlc is not installed. Bootstrapping AI-DLC..."
        SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
        if [ -f "$SCRIPT_DIR/bootstrap.sh" ]; then
            sh "$SCRIPT_DIR/bootstrap.sh"
            export PATH="$BOOTSTRAP_BIN:$PATH"
        else
            echo "ERROR: ai-dlc executable not found on PATH and bootstrap script unavailable." >&2
            echo "Please install ai-dlc or add it to PATH." >&2
            exit 1
        fi
    fi
fi

echo "Using ai-dlc: $(command -v ai-dlc)"

# 3. Determine Machine ID (must be stable lowercase ID)
ENROLLMENT_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/ai-dlc/enrollment.toml"
if [ -f "$ENROLLMENT_FILE" ] && grep -q 'machine_id = ' "$ENROLLMENT_FILE"; then
    MACHINE_ID="$(grep 'machine_id = ' "$ENROLLMENT_FILE" | sed -E 's/machine_id = "(.*)"/\1/')"
else
    # Normalize to lowercase and valid identifier
    MACHINE_ID="$(echo "$RAW_MACHINE_ID" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-' | sed -E 's/^-+//;s/-+$//')"
fi

echo "Machine ID: $MACHINE_ID"

# 4. Configure Machine Binding (~/.config/ai-dlc/machines/<machine-id>.toml)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ai-dlc/machines"
MACHINE_CONF="$CONFIG_DIR/$MACHINE_ID.toml"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$MACHINE_CONF" ]; then
    echo "Creating machine configuration: $MACHINE_CONF"
    cat <<EOF > "$MACHINE_CONF"
schema = 4
roles = ["fde", "ai-enablement"]
EOF
else
    # Ensure roles are declared if not present
    if ! grep -q 'roles = ' "$MACHINE_CONF"; then
        echo "Updating machine configuration with FDE roles: $MACHINE_CONF"
        printf 'roles = ["fde", "ai-enablement"]\n%s' "$(cat "$MACHINE_CONF")" > "$MACHINE_CONF"
    fi
fi

# 5. Determine Profile Source Repository
REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -f "$REPO_ROOT/toolkit/ai-dlc/ai-dlc-profile.toml" ]; then
    PROFILE_SOURCE="$REPO_ROOT"
    REF="refs/heads/main"
else
    PROFILE_SOURCE="git@github.com:Symphony-Professional-Services/fde-kit.git"
    REF="refs/heads/main"
fi

echo "Enrolling machine '$MACHINE_ID' into 'fde' profile from $PROFILE_SOURCE..."
ai-dlc machine enroll "$PROFILE_SOURCE" \
    --profile-id fde \
    --subdirectory toolkit/ai-dlc \
    --machine-id "$MACHINE_ID" \
    --ref "$REF" \
    --apply

# 6. Ensure Symphony AI Docs Workspace is cloned
AI_DOCS_DIR="$REPO_ROOT/../ai-docs"
if [ ! -d "$AI_DOCS_DIR" ]; then
    echo "Cloning Symphony AI documentation workspace (ai-docs)..."
    git clone git@github.com:Symphony-Professional-Services/ai-docs.git "$AI_DOCS_DIR" || {
        echo "Warning: Could not clone ai-docs. Ensure you have access to Symphony-Professional-Services/ai-docs." >&2
    }
else
    echo "Symphony AI documentation workspace present at $AI_DOCS_DIR"
fi

# 7. Verify Machine Status
echo ""
echo "Verifying machine status:"
ai-dlc machine status

echo ""
echo "========================================================"
echo "FDE profile successfully enrolled!"
echo ""
echo "Next steps:"
echo "1. Run 'ai-dlc setup apply' to provision tools (Node, Claude Code, OpenSpec, etc.)."
echo "2. Set your Atlassian credentials in your shell (~/.zshrc or ~/.bashrc):"
echo "     export ATLASSIAN_EMAIL=\"your.name@symphony.com\""
echo "     export ATLASSIAN_API_TOKEN=\"<your-api-token>\""
echo "3. Use the cloned ai-docs workspace (../ai-docs) to sync with Confluence spaces (AIINT, AIENG, AIOPS)."
echo "4. In your engagement project repositories, run:"
echo "     ai-dlc agents render --apply"
echo "   to generate configuration for Claude Code and Antigravity."
echo "========================================================"
