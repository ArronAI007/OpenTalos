#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/OpenTalos.app|artifact.dmg" >&2
  exit 2
fi

target="$1"
if [[ -n "${OPENTALOS_NOTARY_PROFILE:-}" ]]; then
  auth=(--keychain-profile "$OPENTALOS_NOTARY_PROFILE")
else
  : "${APPLE_ID:?APPLE_ID is required}"
  : "${APPLE_APP_PASSWORD:?APPLE_APP_PASSWORD is required}"
  : "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
  auth=(--apple-id "$APPLE_ID" --password "$APPLE_APP_PASSWORD" --team-id "$APPLE_TEAM_ID")
fi

if [[ -d "$target" && "$target" == *.app ]]; then
  temporary="$(mktemp -d)"
  archive="$temporary/OpenTalos.zip"
  trap 'rm -rf "$temporary"' EXIT
  /usr/bin/ditto -c -k --keepParent "$target" "$archive"
  submission="$archive"
else
  submission="$target"
fi

xcrun notarytool submit "$submission" "${auth[@]}" --wait
xcrun stapler staple "$target"
xcrun stapler validate "$target"
spctl --assess --type execute --verbose=2 "$target" 2>/dev/null || true
