#!/bin/bash
# install.sh: on a new Mac, installs the studio and opens it.
#   curl -fsSL https://raw.githubusercontent.com/amiel-35/ix-studio/main/install.sh | bash
# Run again: nothing is overwritten, the studio is simply opened (or launched). Nothing here asks for a password.

set -u
DIR="${STUDIO_DIR:-$HOME/ix-studio}"
PORT="${STUDIO_PORT:-8765}"
OPEN="${STUDIO_OPEN:-open}"
URL="http://127.0.0.1:$PORT/"

say() { printf '%s\n' "$*"; }
stop() { say ""; say "$*"; exit 1; }

# install: prerequisites. Python is the only one that blocks.
PY="${STUDIO_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  stop "Il manque Python 3.10 ou plus. Installe-le depuis https://www.python.org/downloads/ (ou : xcode-select --install), puis relance cette commande."
fi
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  stop "Python est trop ancien ($("$PY" -V 2>&1)). Il faut 3.10 ou plus : https://www.python.org/downloads/ , puis relance cette commande."
fi
say "Python : ok"

if [ -d "/Applications/Google Chrome.app" ] || command -v chromium >/dev/null 2>&1; then
  say "Chrome : ok"
else
  say "Chrome : absent (facultatif, il sert à produire piece.png). Installe-le depuis https://www.google.com/chrome/"
fi
if command -v ffmpeg >/dev/null 2>&1; then
  say "ffmpeg : ok"
else
  say "ffmpeg : absent (facultatif). Avec Homebrew : brew install ffmpeg"
fi
if command -v claude >/dev/null 2>&1; then
  say "Claude Code : ok"
else
  say "Claude Code : absent (il écrit les briefs et les variantes). Installe-le : https://claude.com/claude-code"
fi

# install: the studio's files, in your home, without git
if [ -f "$(dirname "$0")/app/server.py" ] 2>/dev/null; then
  DIR="$(cd "$(dirname "$0")" && pwd)"
elif [ -f "$DIR/app/server.py" ]; then
  say "Le studio est déjà dans $DIR, je le garde tel quel."
else
  command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 || stop "Il manque curl ou tar, ce qui ne devrait pas arriver sur un Mac."
  say "Je télécharge le studio dans $DIR"
  tmp="$(mktemp -d)" || stop "Impossible de créer un dossier temporaire."
  curl -fsSL "${STUDIO_TARBALL:-https://github.com/amiel-35/ix-studio/archive/refs/heads/main.tar.gz}" -o "$tmp/studio.tar.gz" \
    || { rm -rf "$tmp"; stop "Le téléchargement a échoué. Vérifie ta connexion et relance cette commande."; }
  mkdir -p "$DIR" && tar -xzf "$tmp/studio.tar.gz" -C "$DIR" --strip-components=1 \
    || { rm -rf "$tmp"; stop "L'archive est illisible. Relance cette commande."; }
  rm -rf "$tmp"
fi

# install: launch and open
if "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('127.0.0.1', $PORT)))"; then
  say "Le studio tourne déjà : $URL"
  "$OPEN" "$URL" >/dev/null 2>&1
  exit 0
fi
say "Je lance le studio : $URL (Ctrl+C pour l'arrêter)"
(
  for _ in $(seq 1 50); do
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('127.0.0.1', $PORT)))" && break
    sleep 0.2
  done
  "$OPEN" "$URL" >/dev/null 2>&1
) &
exec "$PY" "$DIR/app/server.py" --port "$PORT"
