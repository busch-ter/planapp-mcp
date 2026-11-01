"""Instala os notebooks distribuídos com o CISEI Scenario SDK."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from importlib.resources import files
from pathlib import Path


DEFAULT_DESTINATION = Path(
    "/home/jovyan/work/cisei_workspace/notebooks"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "resources/notebooks/CISEI_Scenario_Builder.ipynb"
    )

    target = destination / "CISEI_Scenario_Builder.ipynb"

    with source.open("rb") as stream:
        content = stream.read()

    if target.exists():
        current = target.read_bytes()

        if hashlib.sha256(current).digest() == hashlib.sha256(content).digest():
            print(f"Notebook atualizado: {target}")
            return

        if not args.update:
            print(f"Notebook existente preservado: {target}")
            print("Use --update para atualizar com backup.")
            return

        backup = target.with_suffix(target.suffix + ".bak")
        if backup.exists():
            raise SystemExit(
                f"Backup já existe; atualização cancelada: {backup}"
            )
        shutil.copy2(target, backup)
        print(f"Backup criado: {backup}")

    temporary = target.with_suffix(target.suffix + ".tmp")

    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    print(f"Notebook instalado: {target}")


if __name__ == "__main__":
    main()
