"""Build and install the KRCN Core wheel without network access."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "build_backend"))

import krcn_build_backend  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        wheel_directory = root / "wheel"
        installed = root / "installed"
        filename = krcn_build_backend.build_wheel(str(wheel_directory))
        environment = os.environ.copy()
        environment["PIP_NO_INDEX"] = "1"
        install = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--disable-pip-version-check",
                "--target",
                str(installed),
                str(wheel_directory / filename),
            ],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        if install.returncode != 0:
            print(install.stderr, file=sys.stderr)
            return install.returncode
        smoke = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(installed)!r}); "
                    "from krcn_core.application import OPERATIONS, create_application_service; "
                    "from krcn_core.portable_backup import prepare_portable_backup; "
                    "from krcn_core.portable_restore import prepare_portable_restore; "
                    "from krcn_core.repo_local_migration import prepare_repo_local_migration; "
                    "from krcn_core.project_home_merge import prepare_project_home_merge; "
                    "from krcn_core.project_context import resolve_current_project; "
                    "from krcn_core.client_bootstrap import prepare_client_bootstrap; "
                    "required={'project.learn','project.rebind','portability.backup',"
                    "'portability.restore','portability.migrate-repo-local',"
                    "'portability.merge-project-home','project.resolve-current',"
                    "'project.resume','client.bootstrap'}; "
                    "assert required <= OPERATIONS; "
                    "from krcn_core.project_learning import prepare_project_learning; "
                    "from krcn_core.intent_routing import project_learning_route; "
                    "print('offline wheel portability verification passed; "
                    "project-learning verification passed')"
                ),
            ],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
        if smoke.returncode != 0:
            print(smoke.stderr, file=sys.stderr)
            return smoke.returncode
        print(smoke.stdout.strip())
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
