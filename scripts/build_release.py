#!/usr/bin/env python3
"""Build a self-contained OpenTalos desktop release for the current platform."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=os.environ.get("OPENTALOS_VERSION", "0.1.0"))
    parser.add_argument("--build-number", default=os.environ.get("GITHUB_RUN_NUMBER", "1"))
    parser.add_argument(
        "--platform",
        choices=("auto", "darwin", "win32", "linux"),
        default="auto",
    )
    parser.add_argument(
        "--arch",
        default="auto",
        help="x86_64, arm64, aarch64, or auto",
    )
    parser.add_argument("--node", type=Path, help="Node.js executable to bundle")
    parser.add_argument("--dist-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=REPO_ROOT / "build" / "release")
    parser.add_argument("--skip-web-build", action="store_true")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--sign-macos", action="store_true")
    parser.add_argument("--notarize-macos", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    platform_name = sys.platform if args.platform == "auto" else args.platform
    arch = normalize_arch(args.arch if args.arch != "auto" else platform.machine())
    dist_dir = args.dist_dir.resolve()
    work_dir = args.work_dir.resolve()
    resources = work_dir / "resources"
    releases = dist_dir / "releases"
    dist_dir.mkdir(parents=True, exist_ok=True)
    releases.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    print(f"Building OpenTalos {args.version} for {platform_name}/{arch}")
    _prepare_web(args, resources)
    _prepare_runtime(resources, args.node)
    _prepare_resources(
        resources,
        version=args.version,
        build_number=args.build_number,
        platform_name=platform_name,
        arch=arch,
    )
    if not args.skip_python:
        _build_pyinstaller(
            args=args,
            resources=resources,
            dist_dir=dist_dir,
            work_dir=work_dir,
        )
    _install_runtime(resources, dist_dir, platform_name)

    artifacts: list[Path] = []
    if platform_name == "darwin":
        app = dist_dir / "OpenTalos.app"
        if not app.is_dir():
            raise SystemExit(f"PyInstaller did not create {app}")
        if args.sign_macos:
            _run([REPO_ROOT / "scripts" / "sign_macos.sh", str(app)])
        else:
            _run(["codesign", "--force", "--deep", "--sign", "-", str(app)])
        if args.notarize_macos:
            _run([REPO_ROOT / "scripts" / "notarize_macos.sh", str(app)])
        dmg = _create_dmg(app, releases, args.version, arch)
        if args.sign_macos:
            _run([REPO_ROOT / "scripts" / "sign_macos.sh", str(dmg)])
        if args.notarize_macos:
            _run([REPO_ROOT / "scripts" / "notarize_macos.sh", str(dmg)])
        artifacts.append(dmg)
    elif platform_name == "win32":
        installer = _create_windows_installer(args, dist_dir, releases, arch)
        artifacts.append(installer)
    elif platform_name == "linux":
        package = _create_deb(dist_dir, releases, args.version, arch)
        artifacts.append(package)
    else:
        raise SystemExit(f"unsupported release platform: {platform_name}")

    for artifact in artifacts:
        _write_checksum(artifact)
        alias = _write_download_alias(artifact, platform_name, arch)
        _write_checksum(alias)
        print(f"artifact: {artifact}")
        print(f"download alias: {alias}")
    return 0


def normalize_arch(value: str) -> str:
    normalized = value.lower()
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(normalized, normalized)


def _prepare_web(args: argparse.Namespace, resources: Path) -> None:
    web_root = REPO_ROOT / "apps" / "web"
    if not args.skip_web_build:
        next_bin = web_root / "node_modules" / ".bin" / (
            "next.cmd" if sys.platform == "win32" else "next"
        )
        if not next_bin.is_file():
            raise SystemExit("Next.js executable is missing; install apps/web dependencies")
        _run([next_bin, "build", "--webpack"], cwd=web_root)
    standalone = web_root / ".next" / "standalone"
    server = standalone / "apps" / "web" / "server.js"
    if not server.is_file():
        raise SystemExit(
            "Next.js standalone output is missing; ensure output='standalone' "
            "and run pnpm -C apps/web build -- --webpack"
        )
    target = resources / "runtime" / "web"
    if sys.platform == "win32":
        _remove(target)
        shutil.copytree(
            standalone,
            target,
            ignore=shutil.ignore_patterns("node_modules"),
        )
        _run(
            [
                "npm",
                "install",
                "--omit=dev",
                "--no-audit",
                "--no-fund",
                "--package-lock=false",
            ],
            cwd=target / "apps" / "web",
        )
    else:
        _replace_tree(standalone, target)
    _copy_tree(web_root / ".next" / "static", target / "apps" / "web" / ".next" / "static")
    public = web_root / "public"
    if public.is_dir():
        _copy_tree(public, target / "apps" / "web" / "public")


def _prepare_runtime(resources: Path, configured_node: Path | None) -> None:
    node = configured_node or Path(shutil.which("node") or "")
    if not node.is_file():
        raise SystemExit("Node.js executable not found; pass --node /path/to/node")
    node_target = resources / "runtime" / "node"
    node_target.mkdir(parents=True, exist_ok=True)
    executable_name = "node.exe" if sys.platform == "win32" else "node"
    target = node_target / executable_name
    shutil.copy2(node, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    for candidate in (
        node.parent.parent / "LICENSE",
        node.parent / "LICENSE",
    ):
        if candidate.is_file():
            shutil.copy2(candidate, node_target / "LICENSE")
            break

    python_license_candidates = (
        Path(sys.base_prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    )
    for python_license in python_license_candidates:
        if python_license.is_file():
            python_target = resources / "runtime" / "python"
            python_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(python_license, python_target / "LICENSE")
            break


def _prepare_resources(
    resources: Path,
    *,
    version: str,
    build_number: str,
    platform_name: str,
    arch: str,
) -> None:
    for relative in ("skills", "specs", "assets"):
        _copy_tree(REPO_ROOT / relative, resources / relative, replace=True)
    for relative in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(REPO_ROOT / relative, resources / relative)
    runtime = resources / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "version.json").write_text(
        json.dumps(
            {
                "version": version,
                "build_number": build_number,
                "platform": platform_name,
                "arch": arch,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    public_key = os.environ.get("OPENTALOS_UPDATE_PUBLIC_KEY_FILE")
    candidates = (
        Path(public_key).expanduser() if public_key else None,
        REPO_ROOT / "release" / "update-public-key.pem",
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            target = resources / "runtime" / "update-public-key.pem"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
            break


def _build_pyinstaller(
    *,
    args: argparse.Namespace,
    resources: Path,
    dist_dir: Path,
    work_dir: Path,
) -> None:
    _remove(dist_dir / "OpenTalos")
    _remove(dist_dir / "OpenTalos.app")
    env = os.environ.copy()
    env.update(
        {
            "OPENTALOS_REPO_ROOT": str(REPO_ROOT),
            "OPENTALOS_RELEASE_RESOURCES": str(resources),
            "OPENTALOS_VERSION": args.version,
            "OPENTALOS_BUILD_NUMBER": args.build_number,
            "PYTHONPATH": os.pathsep.join(
                (str(REPO_ROOT), str(REPO_ROOT / "packages"))
            ),
        }
    )
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir / "pyinstaller"),
            str(REPO_ROOT / "release" / "opentalos.spec"),
        ],
        env=env,
    )


def _install_runtime(resources: Path, dist_dir: Path, platform_name: str) -> None:
    if platform_name == "darwin":
        contents = dist_dir / "OpenTalos.app" / "Contents"
        _remove(contents / "Frameworks" / "runtime")
        target = contents / "Resources" / "runtime"
    else:
        target = dist_dir / "OpenTalos" / "runtime"
    if not target.parent.is_dir():
        raise SystemExit(f"PyInstaller output is missing before runtime copy: {target.parent}")
    _replace_tree(resources / "runtime", target)


def _create_dmg(app: Path, releases: Path, version: str, arch: str) -> Path:
    dmg = releases / f"OpenTalos-{version}-macos-{arch}.dmg"
    with tempfile.TemporaryDirectory(prefix="opentalos-dmg-") as temporary:
        root = Path(temporary)
        _copy_tree(app, root / app.name)
        (root / "Applications").symlink_to("/Applications")
        uninstaller = root / "Uninstall OpenTalos.command"
        uninstaller.write_text(
            """#!/bin/sh
set -eu
APP="/Applications/OpenTalos.app"
if [ ! -d "$APP" ]; then
  echo "OpenTalos is not installed in /Applications."
  exit 1
fi
choice="$(osascript -e 'button returned of (display dialog "Remove OpenTalos user data, plugins, media, and local databases?" buttons {"Keep Data", "Delete Data"} default button "Keep Data")')"
if [ "$choice" = "Delete Data" ]; then
  "$APP/Contents/MacOS/OpenTalos" --uninstall --purge --yes
else
  "$APP/Contents/MacOS/OpenTalos" --uninstall --keep-data --yes
fi
osascript -e 'tell application "Finder" to move application file "OpenTalos.app" of folder "Applications" of startup disk to trash'
""",
            encoding="utf-8",
        )
        uninstaller.chmod(0o755)
        _remove(dmg)
        _run(
            [
                "hdiutil",
                "create",
                "-volname",
                "OpenTalos",
                "-srcfolder",
                str(root),
                "-ov",
                "-format",
                "UDZO",
                str(dmg),
            ]
        )
    return dmg


def _create_windows_installer(
    args: argparse.Namespace,
    dist_dir: Path,
    releases: Path,
    arch: str,
) -> Path:
    if not (dist_dir / "OpenTalos" / "OpenTalos.exe").is_file():
        raise SystemExit("PyInstaller Windows output is missing")
    if os.environ.get("OPENTALOS_WINDOWS_CERT_THUMBPRINT"):
        _sign_windows(dist_dir / "OpenTalos" / "OpenTalos.exe")
    iscc = _find_iscc()
    env = os.environ.copy()
    env["OPENTALOS_VERSION"] = args.version
    _run(
        [
            str(iscc),
            f"/DMyAppVersion={args.version}",
            f"/DMyAppArch={arch}",
            str(REPO_ROOT / "release" / "windows" / "opentalos.iss"),
        ],
        env=env,
    )
    target = releases / f"OpenTalos-{args.version}-windows-{arch}-setup.exe"
    if not target.is_file():
        raise SystemExit(f"Inno Setup did not create {target}")
    if os.environ.get("OPENTALOS_WINDOWS_CERT_THUMBPRINT"):
        _sign_windows(target)
    return target


def _find_iscc() -> Path:
    configured = os.environ.get("ISCC")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        (
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "Inno Setup 6"
            / "ISCC.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Inno Setup 6"
            / "ISCC.exe",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("Inno Setup ISCC.exe not found; set ISCC")


def _sign_windows(path: Path) -> None:
    _run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            REPO_ROOT / "scripts" / "sign_windows.ps1",
            "-Path",
            path,
        ]
    )


def _create_deb(
    dist_dir: Path,
    releases: Path,
    version: str,
    arch: str,
) -> Path:
    source = dist_dir / "OpenTalos"
    if not (source / "OpenTalos").is_file():
        raise SystemExit("PyInstaller Linux output is missing")
    debian_arch = {"x86_64": "amd64", "arm64": "arm64"}.get(arch, arch)
    package = releases / f"OpenTalos-{version}-linux-{arch}.deb"
    with tempfile.TemporaryDirectory(prefix="opentalos-deb-") as temporary:
        root = Path(temporary) / "opentalos"
        _copy_tree(source, root / "opt" / "opentalos")
        launcher_dir = root / "usr" / "bin"
        launcher_dir.mkdir(parents=True)
        launcher = launcher_dir / "opentalos"
        launcher.write_text(
            "#!/bin/sh\nexec /opt/opentalos/OpenTalos \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        uninstaller = launcher_dir / "opentalos-uninstall"
        uninstaller.write_text(
            """#!/bin/sh
if [ "${1:-}" = "--purge" ]; then
  exec /opt/opentalos/OpenTalos --uninstall --purge --yes
fi
exec /opt/opentalos/OpenTalos --uninstall --keep-data --yes
""",
            encoding="utf-8",
        )
        uninstaller.chmod(0o755)
        applications = root / "usr" / "share" / "applications"
        applications.mkdir(parents=True)
        shutil.copy2(
            REPO_ROOT / "release" / "linux" / "opentalos.desktop",
            applications / "opentalos.desktop",
        )
        icons = root / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
        icons.mkdir(parents=True)
        shutil.copy2(
            REPO_ROOT / "assets" / "icon" / "opentalos.png",
            icons / "opentalos.png",
        )
        control_dir = root / "DEBIAN"
        control_dir.mkdir(parents=True)
        control = (
            REPO_ROOT / "release" / "linux" / "control"
        ).read_text(encoding="utf-8")
        control = control.replace("__VERSION__", version).replace(
            "Architecture: amd64",
            f"Architecture: {debian_arch}",
        )
        (control_dir / "control").write_text(control, encoding="utf-8")
        (control_dir / "prerm").write_text(
            """#!/bin/sh
set -e
if [ -x /opt/opentalos/OpenTalos ]; then
  /opt/opentalos/OpenTalos --uninstall --keep-data --yes || true
fi
""",
            encoding="utf-8",
        )
        (control_dir / "prerm").chmod(0o755)
        _remove(package)
        _run(["dpkg-deb", "--build", "--root-owner-group", str(root), str(package)])
    return package


def _run(
    command: list[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"+ {printable}")
    subprocess.run(
        [str(part) for part in command],
        cwd=cwd or REPO_ROOT,
        env=env,
        check=True,
    )


def _write_checksum(artifact: Path) -> Path:
    hasher = hashlib.sha256()
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    target = artifact.with_suffix(f"{artifact.suffix}.sha256")
    target.write_text(f"{hasher.hexdigest()}  {artifact.name}\n", encoding="utf-8")
    return target


def _write_download_alias(artifact: Path, platform_name: str, arch: str) -> Path:
    if platform_name == "darwin":
        filename = f"OpenTalos-macos-{arch}.dmg"
    elif platform_name == "win32":
        filename = f"OpenTalos-windows-{arch}-setup.exe"
    elif platform_name == "linux":
        filename = f"OpenTalos-linux-{arch}.deb"
    else:
        raise SystemExit(f"unsupported release platform: {platform_name}")
    target = artifact.parent / filename
    shutil.copy2(artifact, target)
    return target


def _copy_tree(source: Path, target: Path, *, replace: bool = False) -> None:
    if replace:
        _remove(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        _copy_tree_windows(source, target)
        return
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        symlinks=True,
    )


def _copy_tree_windows(
    source: Path,
    target: Path,
    seen: set[Path] | None = None,
) -> None:
    resolved_source = source.resolve()
    visited = set() if seen is None else set(seen)
    if resolved_source in visited:
        raise RuntimeError(f"junction cycle detected while copying {source}")
    visited.add(resolved_source)
    target.mkdir(parents=True, exist_ok=True)
    with os.scandir(source) as entries:
        for entry in entries:
            item = Path(entry.path)
            destination = target / entry.name
            if entry.is_symlink() or item.is_junction():
                try:
                    link_target = Path(os.readlink(item))
                    linked = (
                        link_target
                        if link_target.is_absolute()
                        else item.parent / link_target
                    )
                    if linked.is_dir():
                        _copy_tree_windows(linked, destination, visited)
                    elif linked.is_file():
                        shutil.copy2(linked, destination)
                except OSError as error:
                    print(f"warning: skipping inaccessible link {item}: {error}")
            elif entry.is_dir(follow_symlinks=False):
                _copy_tree_windows(item, destination, visited)
            else:
                shutil.copy2(item, destination)


def _replace_tree(source: Path, target: Path) -> None:
    _remove(target)
    _copy_tree(source, target)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


if __name__ == "__main__":
    raise SystemExit(main())
