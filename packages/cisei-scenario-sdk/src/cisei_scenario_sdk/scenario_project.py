"""Representação independente de projetos do Scenario SDK."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScenarioProject:
    path: Path

    def __post_init__(self) -> None:
        path = Path(self.path).expanduser().resolve()
        object.__setattr__(self, "path", path)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def scenario_path(self) -> Path:
        return self.path / "scenario.toml"

    @property
    def features_path(self) -> Path:
        return self.path / "features.json"

    @property
    def result_path(self) -> Path:
        return self.path / "result.json"

    def ensure_directory(self) -> Path:
        """Cria o diretório do projeto sem alterar arquivos existentes."""
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    @classmethod
    def create(
        cls,
        workspace: str | Path,
        project_name: str,
    ) -> ScenarioProject:
        """Cria o workspace e um projeto dentro dele."""
        if not project_name or not project_name.strip():
            raise ValueError("project_name não pode ser vazio.")

        name = project_name.strip()

        if name in {".", ".."} or Path(name).name != name:
            raise ValueError("project_name deve ser um nome simples.")

        root = Path(workspace).expanduser().resolve()
        project = cls(root / "projects" / name)
        project.ensure_directory()
        return project


def normalize_project(project: Any) -> ScenarioProject:
    """Aceita ScenarioProject, Path ou projeto compatível por atributos."""
    if isinstance(project, ScenarioProject):
        return project

    if isinstance(project, (str, Path)):
        return ScenarioProject(Path(project))

    path = getattr(project, "path", None)
    if path is None:
        raise TypeError(
            "project deve ser ScenarioProject, Path ou objeto com atributo path."
        )

    return ScenarioProject(Path(path))
