"""Instala e atualiza os notebooks distribuídos com o CISEI Scenario SDK."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path


DEFAULT_DESTINATION = Path(
    "/home/jovyan/work/cisei_workspace/notebooks"
)

NOTEBOOK = "CISEI_Scenario_Builder.ipynb"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instala os notebooks do CISEI Scenario SDK."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Atualiza notebooks existentes, criando backup.",
    )
    args = parser.parse_args()

    destination = args.destination
    destination.mkdir(parents=True, exist_ok=True)

    source = files("cisei_scenario_sdk").joinpath(
        "resources/notebooks", NOTEBOOK
    )
    content = source.read_bytes()
    expected_hash = sha256_bytes(content)

    target = destination / NOTEBOOK

    if target.exists():
        current_hash = sha256_bytes(target.read_bytes())

        if current_hash == expected_hash:
            print(f"Notebook já atualizado: {target}")
            return

        if not args.update:
            raise SystemExit(
                f"Notebook diferente no destino: {target}. "
                "Use --update para atualizar."
            )

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d-%H%M%S-%f"
        )
        backup = destination / f"{NOTEBOOK}.{timestamp}.bak"

        shutil.copy2(target, backup)
        print(f"Backup criado: {backup}")

    temporary = destination / f".{NOTEBOOK}.{os.getpid()}.tmp"

    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        if target.exists():
            shutil.copymode(target, temporary)
        else:
            temporary.chmod(0o664)

        os.replace(temporary, target)

    finally:
        temporary.unlink(missing_ok=True)

    installed_hash = sha256_bytes(target.read_bytes())

    if installed_hash != expected_hash:
        raise RuntimeError(
            "Falha na verificação SHA-256 do notebook instalado."
        )

    print(f"Notebook instalado: {target}")
    print(f"SHA-256: {installed_hash}")


if __name__ == "__main__":
    main()
