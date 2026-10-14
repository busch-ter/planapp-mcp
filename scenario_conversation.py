# ============================================================
# PLANAPP / VIBEPLANNER AI — SCENARIO CONVERSATION
# ============================================================
from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject
from scenario_session import ScenarioSession


class ScenarioConversationError(RuntimeError):
    """Erro relacionado ao fluxo conversacional do cenário."""


class ScenarioNotReadyError(ScenarioConversationError):
    """Tentativa de finalizar um cenário ainda incompleto."""


class ScenarioConfirmationRequiredError(ScenarioConversationError):
    """Tentativa de persistir um cenário sem confirmação."""


class ScenarioConversation:
    """Camada de conversação que encaminha dados estruturados à sessão."""

    def __init__(self, project: PlanningProject, *, session: ScenarioSession | None = None):
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")
        self.project = project
        self.session = session if session is not None else ScenarioSession(project)

    @property
    def project_path(self) -> Path:
        return self.project.path

    @property
    def scenario_path(self) -> Path:
        return self.project.scenario_path

    @property
    def confirmed(self) -> bool:
        return self.session.confirmed

    @property
    def valid(self) -> bool:
        return self.session.valid

    @property
    def complete(self) -> bool:
        return self.session.complete

    def status(self) -> dict[str, Any]:
        validation = self.session.validate()
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
            "project_path": str(self.project.path),
            "scenario_path": str(self.project.scenario_path),
        }

    def missing_fields(self) -> list[str]:
        return list(self.session.missing_fields())

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        validation = self.session.update(values)
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    def replace(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        validation = self.session.replace(values)
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.session.to_dict()

    def validate(self):
        return self.session.validate()

    def is_complete(self) -> bool:
        return self.session.complete

    def confirm(self) -> dict[str, Any]:
        validation = self.session.confirm()
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    def generate_toml(self) -> str:
        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError("Scenario must be explicitly confirmed before generating TOML.")
        return self.session.generate_toml()

    def save(self) -> Path:
        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError("Scenario must be explicitly confirmed before saving the project.")
        return self.session.save()

    def finalize(self) -> Path:
        validation = self.session.validate()
        if not validation.valid:
            raise ScenarioNotReadyError("Scenario is not valid: " + "; ".join(validation.errors))
        if not validation.complete:
            raise ScenarioNotReadyError("Scenario is incomplete. Missing fields: " + ", ".join(validation.missing))
        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError("Scenario must be explicitly confirmed before finalization.")
        return self.session.save()

    def conversation_state(self) -> dict[str, Any]:
        status = self.status()
        state = {
            "valid": status["valid"],
            "complete": status["complete"],
            "confirmed": status["confirmed"],
            "missing": status["missing"],
            "errors": status["errors"],
        }
        if status["complete"] and status["valid"] and status["confirmed"]:
            state["next_action"] = "finalize"
        elif status["complete"] and status["valid"]:
            state["next_action"] = "confirm"
        elif status["missing"]:
            state["next_action"] = "collect_missing_fields"
        else:
            state["next_action"] = "resolve_validation_errors"
        return state

    def __repr__(self) -> str:
        return ("ScenarioConversation(" f"project={self.project.path!s}, " f"valid={self.valid}, " f"complete={self.complete}, " f"confirmed={self.confirmed}" ")")


def create_scenario_conversation(project_path: str | Path) -> ScenarioConversation:
    return ScenarioConversation(PlanningProject(project_path))