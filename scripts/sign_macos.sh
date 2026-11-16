#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/OpenTalos.app|artifact.dmg" >&2
  exit 2
fi

target="$1"
identity="${OPENTALOS_MACOS_SIGNING_IDENTITY:--}"
if [[ "$identity" == "-" ]]; then
  timestamp_args=()
else
  timestamp_args=(--timestamp)
fi

sign_path() {
  local path="$1"
  if [[ "$path" == *.app ]]; then
    codesign --force --options runtime --entitlements \
      "$(dirname "$0")/../release/entitlements.plist" \
      "${timestamp_args[@]}" --sign "$identity" "$path"
  else
    codesign --force "${timestamp_args[@]}" --sign "$identity" "$path"
  fi
}

if [[ -d "$target" && "$target" == *.app ]]; then
  while IFS= read -r -d '' candidate; do
    if file "$candidate" | grep -q "Mach-O"; then
      sign_path "$candidate"
    fi
  done < <(find "$target" -type f \
    \( -perm -111 -o -name '*.dylib' -o -name '*.so' \) -print0)
  sign_path "$target"
  codesign --verify --deep --strict --verbose=2 "$target"
elif [[ -f "$target" ]]; then
  sign_path "$target"
else
  echo "signing target does not exist: $target" >&2
  exit 1
fi
