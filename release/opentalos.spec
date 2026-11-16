# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

repo_root = Path(os.environ.get("OPENTALOS_REPO_ROOT", ".")).resolve()
resources = Path(os.environ["OPENTALOS_RELEASE_RESOURCES"]).resolve()
icon_dir = repo_root / "assets" / "icon"
sys.path.insert(0, str(repo_root / "packages"))
sys.path.insert(0, str(repo_root))

hiddenimports = []
for package in (
    "apps",
    "agent_platform",
    "gateway",
    "gateway_access",
    "media_platform",
    "plugin_platform",
    "privacy",
    "release_platform",
    "subscriptions",
    "websearch",
    "ai",
    "agents",
    "skill",
    "tool",
    "memory",
    "core",
    "mcp",
    "a2apeer",
    "observability",
    "sandbox",
    "context",
):
    hiddenimports += collect_submodules(package)
hiddenimports += [
    "apps.api.main",
    "apps.api.release_routes",
    "apps.gateway.main",
    "db",
    "release_routes",
    "runtime",
    "agentgen",
    "evaluation",
    "suggest",
    "model_control",
    "agent_platform_routes",
    "m7_routes",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

datas = [
    (str(resources / "skills"), "skills"),
    (str(resources / "specs"), "specs"),
    (str(resources / "assets"), "assets"),
    (str(resources / "LICENSE"), "."),
    (str(resources / "THIRD_PARTY_NOTICES.md"), "."),
]

a = Analysis(
    [str(repo_root / "apps" / "desktop" / "main.py")],
    pathex=[
        str(repo_root),
        str(repo_root / "packages"),
        str(repo_root / "apps" / "api"),
        str(repo_root / "apps" / "gateway"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenTalos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=(
        str(icon_dir / "opentalos.ico")
        if os.name == "nt"
        else str(icon_dir / "opentalos.icns")
        if sys.platform == "darwin"
        else None
    ),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpenTalos",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OpenTalos.app",
        icon=str(icon_dir / "opentalos.icns"),
        bundle_identifier="ai.opentalos.desktop",
        info_plist={
            "CFBundleName": "OpenTalos",
            "CFBundleDisplayName": "OpenTalos",
            "CFBundleShortVersionString": os.environ.get("OPENTALOS_VERSION", "0.1.0"),
            "CFBundleVersion": os.environ.get("OPENTALOS_BUILD_NUMBER", "1"),
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSNetworkClientUsageDescription": "OpenTalos connects to providers and local agents.",
        },
    )
