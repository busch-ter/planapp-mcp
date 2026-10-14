# ============================================================
# PLANAPP / VIBEPLANNER AI
# SCENARIO AGENT — POC-07a
# ============================================================
from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject
from scenario_conversation import ScenarioConversation


class ScenarioAgentError(RuntimeError):
    """Erro geral do ScenarioAgent."""


class ScenarioAgent:
    """Orquestra o fluxo collect -> validate -> confirm -> finalize."""

    def __init__(self, project: PlanningProject, *, conversation: ScenarioConversation | None = None):
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")
        self.project = project
        self.conversation = conversation if conversation is not None else ScenarioConversation(project)

    @property
    def project_path(self) -> Path:
        return self.project.path

    @property
    def scenario_path(self) -> Path:
        return self.project.scenario_path

    @property
    def confirmed(self) -> bool:
        return self.conversation.confirmed

    @property
    def valid(self) -> bool:
        return self.conversation.valid

    @property
    def complete(self) -> bool:
        return self.conversation.complete

    def status(self) -> dict[str, Any]:
        return self.conversation.status()

    def conversation_state(self) -> dict[str, Any]:
        return self.conversation.conversation_state()

    def missing_fields(self) -> list[str]:
        return self.conversation.missing_fields()

    def snapshot(self) -> dict[str, Any]:
        return self.conversation.to_dict()

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        return self.conversation.update(values)

    def replace(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        return self.conversation.replace(values)

    def next_action(self) -> str:
        return self.conversation_state()["next_action"]

    def needs_input(self) -> bool:
        return self.next_action() == "collect_missing_fields"

    def needs_confirmation(self) -> bool:
        return self.next_action() == "confirm"

    def has_validation_errors(self) -> bool:
        return self.next_action() == "resolve_validation_errors"

    def confirm(self) -> dict[str, Any]:
        return self.conversation.confirm()

    def generate_toml(self) -> str:
        return self.conversation.generate_toml()

    def save(self) -> Path:
        return self.conversation.save()

    def finalize(self) -> Path:
        return self.conversation.finalize()

    def build_summary(self) -> dict[str, Any]:
        state = self.conversation_state()
        return {
            "valid": state["valid"],
            "complete": state["complete"],
            "confirmed": state["confirmed"],
            "missing": list(state["missing"]),
            "errors": list(state["errors"]),
            "scenario": self.snapshot(),
            "project_path": str(self.project_path),
            "scenario_path": str(self.scenario_path),
            "next_action": state["next_action"],
        }

    def process_update(self, values: dict[str, Any]) -> dict[str, Any]:
        self.update(values)
        state = self.conversation_state()
        result = {
            "action": state["next_action"],
            "valid": state["valid"],
            "complete": state["complete"],
            "confirmed": state["confirmed"],
            "missing": list(state["missing"]),
            "errors": list(state["errors"]),
        }
        if state["next_action"] == "collect_missing_fields":
            result["request"] = {"type": "missing_fields", "fields": list(state["missing"])}
        elif state["next_action"] == "resolve_validation_errors":
            result["request"] = {"type": "validation_errors", "errors": list(state["errors"])}
        elif state["next_action"] == "confirm":
            result["request"] = {"type": "confirmation", "scenario": self.snapshot()}
        elif state["next_action"] == "finalize":
            result["request"] = {"type": "finalization_ready", "scenario": self.snapshot()}
        return result

    def process_confirmation(self, confirmed: bool) -> dict[str, Any]:
        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a boolean")
        if not confirmed:
            # Rejeitar a confirmação não significa que faltam campos.
            # O cenário permanece intacto e volta para revisão/edição.
            return {
                "action": "review_scenario",
                "confirmed": False,
                "complete": self.complete,
                "valid": self.valid,
                "missing": self.missing_fields(),
                "errors": list(self.conversation_state()["errors"]),
                "message": "Scenario remains unconfirmed. Ask what the user wants to change.",
            }
        result = self.confirm()
        return {
            "action": "finalize",
            "valid": result["valid"],
            "complete": result["complete"],
            "confirmed": result["confirmed"],
            "missing": list(result["missing"]),
            "errors": list(result["errors"]),
        }

    def process_finalize(self) -> dict[str, Any]:
        path = self.finalize()
        return {
            "action": "completed",
            "valid": True,
            "complete": True,
            "confirmed": True,
            "scenario_path": str(path),
            "project_path": str(self.project_path),
        }

    def __repr__(self) -> str:
        return ("ScenarioAgent(" f"project={self.project.path!s}, " f"valid={self.valid}, " f"complete={self.complete}, " f"confirmed={self.confirmed}" ")")


def create_scenario_agent(project_path: str | Path) -> ScenarioAgent:
    return ScenarioAgent(PlanningProject(project_path))