#!/bin/bash
# =============================================================
# Selwyn Football Watcher — One-shot GitHub setup script
# Run this from your Mac Terminal once. It will:
#   1. Install GitHub CLI (gh) if needed
#   2. Authenticate with GitHub
#   3. Create the selwyn-football-watcher repo
#   4. Push all the code
#   5. Add the Gmail secrets
#   6. Enable GitHub Pages
# =============================================================

set -e

REPO_NAME="selwyn-football-watcher"
GMAIL_USER="nickmackesonsmith@gmail.com"
GMAIL_APP_PASSWORD="vaqu jaoh afzs jyni"   # ← rotate this after setup!
TEAMREACH_UID="3594459"
TEAMREACH_TOKEN="TnlCE29K9xcRHlAMHsCVbt1EDXYQ4T4xnMhx2d0fnePjiaOhUrMH4COqN9Uc8yJCFSkc"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Selwyn Football Watcher — GitHub Setup             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Install gh CLI if missing ────────────────────────
if ! command -v gh &>/dev/null; then
  echo "→ Installing GitHub CLI via Homebrew..."
  if ! command -v brew &>/dev/null; then
    echo "ERROR: Homebrew not found. Install it from https://brew.sh first."
    exit 1
  fi
  brew install gh
else
  echo "✓ GitHub CLI already installed ($(gh --version | head -1))"
fi

# ── Step 2: Authenticate if needed ───────────────────────────
if ! gh auth status &>/dev/null; then
  echo ""
  echo "→ You need to log in to GitHub."
  echo "  A browser window will open — just click 'Authorize'."
  echo ""
  gh auth login --web --hostname github.com
else
  echo "✓ Already authenticated with GitHub"
fi

# ── Step 3: Make sure we're in the right directory ───────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
echo ""
echo "→ Working directory: $SCRIPT_DIR"

# ── Step 4: Create the GitHub repo ───────────────────────────
echo ""
echo "→ Creating GitHub repo '$REPO_NAME'..."
if gh repo view "$REPO_NAME" &>/dev/null; then
  echo "  Repo already exists — skipping creation."
else
  gh repo create "$REPO_NAME" \
    --public \
    --description "Automated fixture watcher for Selwyn College 2nd XI and 13A Boys football teams" \
    --confirm 2>/dev/null || \
  gh repo create "$REPO_NAME" \
    --public \
    --description "Automated fixture watcher for Selwyn College 2nd XI and 13A Boys football teams"
  echo "  ✓ Repo created"
fi

GITHUB_USERNAME=$(gh api user --jq '.login')
REMOTE_URL="https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"

# ── Step 5: Push the code ────────────────────────────────────
echo ""
echo "→ Pushing code to GitHub..."

if [ ! -d ".git" ]; then
  git init
  git branch -M main
fi

git config user.name "Nick Mackeson-Smith"
git config user.email "nickmackesonsmith@gmail.com"

# Set remote (remove existing if present)
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"

git add .
git commit -m "feat: initial commit — Selwyn Football Watcher" 2>/dev/null || \
  echo "  (nothing new to commit — already up to date)"

git push -u origin main --force
echo "  ✓ Code pushed"

# ── Step 6: Set GitHub Secrets ───────────────────────────────
echo ""
echo "→ Adding Gmail secrets..."

gh secret set GMAIL_USER \
  --repo "$GITHUB_USERNAME/$REPO_NAME" \
  --body "$GMAIL_USER"

gh secret set GMAIL_APP_PASSWORD \
  --repo "$GITHUB_USERNAME/$REPO_NAME" \
  --body "$GMAIL_APP_PASSWORD"

gh secret set TEAMREACH_UID \
  --repo "$GITHUB_USERNAME/$REPO_NAME" \
  --body "$TEAMREACH_UID"

gh secret set TEAMREACH_TOKEN \
  --repo "$GITHUB_USERNAME/$REPO_NAME" \
  --body "$TEAMREACH_TOKEN"

echo "  ✓ Secrets set (Gmail + TeamReach)"

# ── Step 7: Enable GitHub Pages ──────────────────────────────
echo ""
echo "→ Enabling GitHub Pages (from docs/ folder)..."

# Pages are now deployed via the pages.yml workflow (uses GitHub Actions pages)
# We just need to trigger the workflow once. The pages.yml in .github/workflows
# handles deployment automatically.

# Trigger the morning workflow manually as a test
echo ""
echo "→ Triggering a test run (morning workflow, test mode)..."
sleep 3  # let GitHub catch up after push
gh workflow run morning.yml \
  --repo "$GITHUB_USERNAME/$REPO_NAME" \
  --field test_mode=true 2>/dev/null || echo "  (workflow trigger will work once Actions are enabled on the repo)"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   ✅  Setup complete!                                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Repo URL:  https://github.com/$GITHUB_USERNAME/$REPO_NAME"
echo "Actions:   https://github.com/$GITHUB_USERNAME/$REPO_NAME/actions"
echo ""
echo "⚠️  IMPORTANT: The Gmail app password is in this script file."
echo "   Please do these two things now:"
echo "   1. Delete the password line from setup.sh (or delete the file)"
echo "   2. Revoke the app password at myaccount.google.com/apppasswords"
echo "      and generate a fresh one — then set it as the secret again:"
echo ""
echo "   gh secret set GMAIL_APP_PASSWORD --repo $GITHUB_USERNAME/$REPO_NAME"
echo ""
echo "Morning emails arrive at 7am NZ. Check nickmackesonsmith@gmail.com"
echo "for a [TEST] email to confirm everything worked."
echo ""
