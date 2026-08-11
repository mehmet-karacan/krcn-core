"""Dependency-free PEP 517 wheel backend for KRCN Core."""

from __future__ import annotations

import base64
import hashlib
import tarfile
import tomllib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]


def _distribution_names() -> tuple[str, str, str]:
    metadata = _project_metadata()
    project_name = metadata["name"]
    version = metadata["version"]
    wheel_name = project_name.replace("-", "_")
    return project_name, version, wheel_name


def _metadata_files() -> dict[str, bytes]:
    metadata = _project_metadata()
    project_name, version, wheel_name = _distribution_names()
    dist_info = f"{wheel_name}-{version}.dist-info"
    author = metadata.get("authors", [{}])[0].get("name", "")
    core_metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {project_name}\n"
        f"Version: {version}\n"
        f"Summary: {metadata['description']}\n"
        f"Author: {author}\n"
        f"Requires-Python: {metadata['requires-python']}\n"
    ).encode("utf-8")
    wheel_metadata = (
        "Wheel-Version: 1.0\n"
        "Generator: krcn-core-build-backend\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    scripts = _project_metadata().get("scripts", {})
    entry_points = "[console_scripts]\n" + "".join(
        f"{name}={target}\n" for name, target in sorted(scripts.items())
    )
    return {
        f"{dist_info}/METADATA": core_metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
        f"{dist_info}/entry_points.txt": entry_points.encode("utf-8"),
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode('ascii')},{len(data)}"


def get_requires_for_build_wheel(config_settings: dict | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict | None = None,
) -> str:
    _, version, wheel_name = _distribution_names()
    dist_info = f"{wheel_name}-{version}.dist-info"
    destination = Path(metadata_directory) / dist_info
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in _metadata_files().items():
        (Path(metadata_directory) / name).write_bytes(content)
    return dist_info


def build_wheel(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    _, version, wheel_name = _distribution_names()
    filename = f"{wheel_name}-{version}-py3-none-any.whl"
    entries: dict[str, bytes] = {}
    source_root = PROJECT_ROOT / "src" / "krcn_core"
    for path in sorted(source_root.rglob("*.py")):
        archive_name = path.relative_to(PROJECT_ROOT / "src").as_posix()
        entries[archive_name] = path.read_bytes()
    entries.update(_metadata_files())
    dist_info = f"{wheel_name}-{version}.dist-info"
    record_name = f"{dist_info}/RECORD"
    record = "\n".join(
        [_record_line(name, data) for name, data in sorted(entries.items())]
        + [f"{record_name},,"]
    ).encode("utf-8")
    entries[record_name] = record

    destination = Path(wheel_directory)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination / filename, "w") as wheel:
        for name, data in sorted(entries.items()):
            wheel.writestr(_zip_info(name), data)
    return filename


def get_requires_for_build_sdist(config_settings: dict | None = None) -> list[str]:
    return []


def build_sdist(
    sdist_directory: str,
    config_settings: dict | None = None,
) -> str:
    project_name, version, _ = _distribution_names()
    filename = f"{project_name}-{version}.tar.gz"
    prefix = f"{project_name}-{version}"
    members = [PROJECT_ROOT / "pyproject.toml", PROJECT_ROOT / "README.md"]
    members.extend(sorted((PROJECT_ROOT / "build_backend").rglob("*.py")))
    members.extend(sorted((PROJECT_ROOT / "src").rglob("*.py")))
    destination = Path(sdist_directory)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination / filename, "w:gz") as archive:
        for path in members:
            archive.add(path, arcname=f"{prefix}/{path.relative_to(PROJECT_ROOT)}")
    return filename
