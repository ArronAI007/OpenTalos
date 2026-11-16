# OpenTalos Release Builds

The M8 release pipeline builds one self-contained desktop application per
platform. PyInstaller runs the Python API, Gateway, and desktop shell from one
executable. Next.js runs from its standalone output with the bundled Node.js
executable.

## Build Locally

macOS:

```bash
uv sync --group dev
pnpm -C apps/web install --frozen-lockfile
uv run python scripts/build_release.py
```

The default output is `dist/releases/OpenTalos-0.1.0-macos-<arch>.dmg`.

Linux and Windows use the same command on their native build hosts. Packaging
requires `dpkg-deb` on Linux and Inno Setup 6 on Windows.

Useful options:

```text
--skip-web-build       reuse apps/web/.next/standalone
--skip-python          only refresh the platform package from dist/OpenTalos
--sign-macos           code-sign the app and DMG
--notarize-macos       submit the signed artifacts to Apple
```

## Update Signing

Generate an update signing key once, then keep the private key outside the
repository:

```bash
uv run python scripts/sign_release_manifest.py \
  --generate-key-dir /secure/path/opentalos-update-keys
```

The release workflow derives `release/update-public-key.pem` from the private
key stored in the release secret `OPENTALOS_UPDATE_PRIVATE_KEY`, then embeds
that public key in the app. Do not commit the private key.

Create a signed manifest:

```bash
uv run python scripts/sign_release_manifest.py \
  --artifact dist/releases/OpenTalos-0.1.0-macos-x86_64.dmg \
  --version 0.1.0 \
  --platform darwin \
  --arch x86_64 \
  --url https://example.com/OpenTalos-0.1.0-macos-x86_64.dmg \
  --private-key /secure/path/update-private-key.pem \
  --output dist/releases/OpenTalos-update-darwin-x86_64.json
```

The installed app checks
`https://github.com/ArronAI007/OpenTalos/releases/latest/download/OpenTalos-update-<platform>-<arch>.json`
using the public key embedded at `runtime/update-public-key.pem`.
`OPENTALOS_UPDATE_MANIFEST_URL` can override that URL for staging.

## Signing Secrets

macOS:

- `OPENTALOS_MACOS_SIGNING_IDENTITY`
- `APPLE_CERTIFICATE_P12_BASE64`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_ID`
- `APPLE_APP_PASSWORD`
- `APPLE_TEAM_ID`

Windows:

- `OPENTALOS_WINDOWS_CERT_PFX_BASE64`
- `OPENTALOS_WINDOWS_CERT_PASSWORD`

The workflow imports the Windows certificate and supplies its thumbprint to
the signing script automatically.

## User Data and Uninstall

Installed builds store writable data in:

- macOS: `~/Library/Application Support/OpenTalos`
- Windows: `%LOCALAPPDATA%/OpenTalos`
- Linux: `$XDG_DATA_HOME/OpenTalos`

Uninstall while preserving data:

```bash
OpenTalos --uninstall --keep-data --yes
```

Uninstall and remove application data:

```bash
OpenTalos --uninstall --purge --yes
```

Uninstall always attempts to restore Agent-managed configuration snapshots
before application data is deleted.
