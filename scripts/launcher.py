from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


def main() -> int:
    root = project_root()
    launcher = root / "Start Fiverr Lead CRM.bat"
    if not launcher.exists():
        subprocess.Popen(
            [
                "cmd.exe",
                "/c",
                "start",
                "Fiverr Lead Extractor CRM",
                "cmd.exe",
                "/k",
                f'echo Missing launcher: "{launcher}"',
            ],
            cwd=str(root),
        )
        return 1

    subprocess.Popen(
        ["cmd.exe", "/c", "start", "Fiverr Lead Extractor CRM", str(launcher)],
        cwd=str(root),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
