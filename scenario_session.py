# ============================================================
# PLANAPP / VIBEPLANNER — SCENARIO SESSION
# ============================================================
from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject
from scenario_builder import ScenarioBuilder, ValidationResult


class ScenarioSession:
    """Mantém o estado de construção, validação, confirmação e persistência."""

    def __init__(self, project: PlanningProject, *, builder: ScenarioBuilder | None = None) -> None:
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")
        self.project = project
        self.builder = builder or ScenarioBuilder()
        self._confirmed = False

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def project_path(self) -> Path:
        return self.project.path

    @property
    def scenario_path(self) -> Path:
        return self.project.scenario_path

    @property
    def features_path(self) -> Path:
        return self.project.features_path

    @property
    def result_path(self) -> Path:
        return self.project.result_path

    def validate(self) -> ValidationResult:
        return self.builder.validate()

    @property
    def valid(self) -> bool:
        return self.validate().valid

    @property
    def complete(self) -> bool:
        return self.validate().complete

    @property
    def missing(self) -> list[str]:
        return list(self.validate().missing)

    @property
    def errors(self) -> list[str]:
        return list(self.validate().errors)

    def status(self) -> dict[str, Any]:
        validation = self.validate()
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
            "confirmed": self.confirmed,
            "project": str(self.project.path),
            "scenario": str(self.project.scenario_path),
        }

    def update(self, values: dict[str, Any]) -> ValidationResult:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        if not values:
            raise ValueError("values must not be empty")
        self.builder.update(values)
        self._confirmed = False
        return self.validate()

    def replace(self, values: dict[str, Any]) -> ValidationResult:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        self.builder.replace(values)
        self._confirmed = False
        return self.validate()

    def to_dict(self) -> dict[str, Any]:
        return self.builder.to_dict()

    def missing_fields(self) -> list[str]:
        return list(self.validate().missing)

    def confirm(self) -> ValidationResult:
        validation = self.validate()
        if not validation.valid:
            raise ValueError("Cannot confirm an invalid scenario. Errors: " + str(validation.errors))
        if not validation.complete:
            raise ValueError("Cannot confirm an incomplete scenario. Missing: " + str(validation.missing))
        self.builder.confirm()
        self._confirmed = True
        return self.validate()

    def generate_toml(self) -> str:
        if not self.confirmed:
            raise RuntimeError("Scenario must be explicitly confirmed before generating TOML.")
        return self.builder.generate_toml()

    def save(self) -> Path:
        if not self.confirmed:
            raise RuntimeError("Scenario must be explicitly confirmed before saving the project.")
        self.builder.save_toml(self.project.scenario_path)
        return self.project.scenario_path

    save_scenario = save

    def finalize(self) -> Path:
        validation = self.validate()
        if not validation.valid:
            raise ValueError("Cannot finalize an invalid scenario. Errors: " + str(validation.errors))
        if not validation.complete:
            raise ValueError("Cannot finalize an incomplete scenario. Missing: " + str(validation.missing))
        if not self.confirmed:
            raise RuntimeError("Scenario must be explicitly confirmed before finalization.")
        return self.save()

    def __repr__(self) -> str:
        validation = self.validate()
        return ("ScenarioSession(" f"project={self.project.name!r}, " f"valid={validation.valid}, " f"complete={validation.complete}, " f"confirmed={self.confirmed}" ")")