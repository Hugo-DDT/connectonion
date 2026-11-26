#!/bin/sh
# Install ConnectOnion and set it up, in one line:
#
#   curl -fsSL https://raw.githubusercontent.com/openonion/connectonion/main/install.sh | sh
#
# 1. installs co in its own environment with uv (installing uv first if needed),
#    never into your system Python; uv fetches a Python if you have none
# 2. co init: your agent identity, an OpenOnion key with starter credit, and the
#    co skills and command index for Codex and Claude Code
# A preview instead of the stable release:  ... | CO_VERSION=1.9.2b10 sh
#
# An upgrade installs into a new tool environment and points ~/.local/bin/co at
# it only after the new `co --version` runs. `uv tool install --force` removes
# the old environment first; a failure then leaves no `co` (#3363).
set -eu

spec="connectonion${CO_VERSION:+==$CO_VERSION}"
your_path="$PATH"   # before this script adds to it

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (https://docs.astral.sh/uv), which keeps co out of your system Python..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
fi

json_escape() {
  printf '%s' "$1" | tr '\r\n' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

record() {
  # $1 outcome (ok, failed, partial), $2 reason. The previous co is still the one on PATH.
  mkdir -p "$HOME/.co"
  at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"outcome":"%s","reason":"%s","spec":"%s","kept":"%s","at":"%s"}\n' \
    "$1" "$(json_escape "$2")" "$(json_escape "$spec")" "$(json_escape "$kept")" "$at" \
    > "$HOME/.co/upgrade.json"
}

echo "Installing $spec..."
# A version released minutes ago can be missing from PyPI's index, which uv reads, for a few
# minutes: wait for it rather than fail the handoff that pinned it (#2457).
live_bin="$(uv tool dir --bin)"
tools_dir="$(uv tool dir)"
mkdir -p "$live_bin" "$tools_dir"
kept=""
if [ -x "$live_bin/co" ]; then
  kept=$("$live_bin/co" --version 2>/dev/null || true)
fi
stage=$(mktemp -d "${TMPDIR:-/tmp}/co-upgrade.XXXXXX")
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT

install_staged() {
  # $1 is "" or "--refresh". Unquoted so an empty flag is not passed to uv.
  # shellcheck disable=SC2086
  UV_TOOL_DIR="$stage/tools" UV_TOOL_BIN_DIR="$stage/bin" \
    uv tool install --python ">=3.11" --quiet $1 "$spec" >"$stage/uv.out" 2>"$stage/uv.err"
}

tries=0 refresh=""
until install_staged "$refresh"; do
  tries=$((tries + 1)) refresh="--refresh"
  cat "$stage/uv.err" >&2 || true
  if [ -z "${CO_VERSION:-}" ] || [ "$tries" -ge 10 ]; then
    reason=$(tail -n 1 "$stage/uv.err" 2>/dev/null || echo "uv tool install failed")
    record failed "$reason"
    exit 1
  fi
  echo "$CO_VERSION may have been released minutes ago and not be on PyPI's index yet; trying again in ${CO_INSTALL_WAIT:-30}s ($tries/9)..."
  sleep "${CO_INSTALL_WAIT:-30}"
done

if [ ! -x "$stage/bin/co" ] || ! "$stage/bin/co" --version >/dev/null 2>"$stage/uv.err"; then
  reason=$(tail -n 1 "$stage/uv.err" 2>/dev/null || echo "new install did not run")
  record failed "$reason"
  exit 1
fi
py=$(sed -n '1s/^#![[:space:]]*//p' "$stage/bin/co" | awk '{print $1}')
case "$py" in
  *python*)
    if ! "$py" -c "import connectonion" >/dev/null 2>"$stage/uv.err"; then
      reason=$(tail -n 1 "$stage/uv.err" 2>/dev/null || echo "cannot import connectonion")
      record failed "new install cannot import connectonion: $reason"
      exit 1
    fi
    ;;
esac

# A real uv env's shebang points into the stage. Move it before the stage is removed,
# and leave the previous tool directory untouched until the live shim has been checked.
src="$stage/tools/connectonion"
if [ -d "$src" ]; then
  version=$("$stage/bin/co" --version 2>/dev/null | awk '{print $NF}')
  dest="$tools_dir/connectonion-${version:-new}"
  rm -rf "$dest"
  mv "$src" "$dest"
  for shim in "$stage/bin/"*; do
    [ -f "$shim" ] || continue
    if head -1 "$shim" | grep -q "$src"; then
      sed "1s|$src|$dest|" "$shim" > "$shim.rewritten"
      mv "$shim.rewritten" "$shim"
      chmod 755 "$shim"
    fi
  done
  if ! "$stage/bin/co" --version >/dev/null 2>"$stage/uv.err"; then
    record failed "new install did not run after it was moved"
    exit 1
  fi
fi

if [ -e "$live_bin/co" ]; then
  cp -a "$live_bin/co" "$stage/previous-co"
fi
for shim in "$stage/bin/"*; do
  [ -f "$shim" ] || continue
  name=$(basename "$shim")
  cp -a "$shim" "$live_bin/.$name.new"
  chmod 755 "$live_bin/.$name.new"
  mv -f "$live_bin/.$name.new" "$live_bin/$name"
done
if ! "$live_bin/co" --version >/dev/null 2>"$stage/live.err"; then
  if [ -e "$stage/previous-co" ]; then
    mv -f "$stage/previous-co" "$live_bin/co"
  fi
  reason=$(tail -n 1 "$stage/live.err" 2>/dev/null || echo "live co did not run after swap")
  record partial "$reason"
  exit 1
fi
record ok ""

bin="$live_bin"
uv tool update-shell >/dev/null 2>&1 || true

"$bin/co" init --yes

echo
echo "✓ $("$bin/co" --version) is installed in $bin"
case ":$your_path:" in
  *":$bin:"*) ;;
  *) echo "  Open a new terminal, or run: export PATH=\"$bin:\$PATH\"" ;;
esac
echo
echo "Try:"
echo "  co status           what is set up"
echo "  co auth google      connect Gmail and Google Calendar"
echo "  co auth microsoft   connect Outlook"
echo "  co commands         everything else; add --help to any command"
if grep -qs "co:begin" "$HOME/.codex/AGENTS.md" "$HOME/.claude/CLAUDE.md"; then
  echo
  echo "Codex and Claude Code know about co now: ask them to use it."
fi
