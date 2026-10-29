"""Validação remota de cenários CISEI, sem execução de planejamento RF."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

import requests


def validate_with_planning_sdk(
    *,
    project_path: str | Path,
    scenario_path: str | Path,
    base_url: str,
    workspace: str | Path,
    planner: str = "cell",
    timeout: float = 120.0,
) -> dict:
    """Valida um cenário no motor e remove seu registro temporário."""

    from cisei_planning_sdk.client import PlanningClient
    from cisei_planning_sdk.project import PlanningProject

    project_path = Path(project_path).resolve(strict=True)
    scenario_path = Path(scenario_path).resolve(strict=True)

    if not project_path.is_dir():
        raise NotADirectoryError(project_path)

    if not scenario_path.is_file():
        raise FileNotFoundError(scenario_path)

    if scenario_path.parent != project_path:
        raise ValueError(
            "O TOML de validação deve estar diretamente no projeto."
        )

    validation_id = (
        f"validation_{project_path.name}_{uuid.uuid4().hex}"
    )

    client = PlanningClient(
        base_url=base_url,
        workspace=str(workspace),
        auto_register=True,
        timeout=timeout,
    )

    client.project = PlanningProject(path=project_path)

    report = {
        "validator": "cisei_planning_sdk / PlanningScenario.validate()",
        "scenario_id": validation_id,
        "sdk_ok": False,
        "validation_errors": [],
        "summary": None,
        "cleanup_ok": False,
        "cleanup_error": None,
    }

    definition_attempted = False

    try:
        definition_attempted = True

        result = client.define_scenario(
            name=validation_id,
            scenario=scenario_path,
            planner=planner,
        )

        errors = list(result.validation_errors or [])

        report["sdk_ok"] = bool(result.ok) and not errors
        report["validation_errors"] = errors
        report["summary"] = result.summary

    finally:
        if definition_attempted:
            url = (
                base_url.rstrip("/")
                + "/planning/scenarios/"
                + quote(validation_id, safe="")
            )

            try:
                response = requests.delete(
                    url,
                    timeout=timeout,
                )
                response.raise_for_status()

                payload = response.json()
                report["cleanup_ok"] = True
                report["cleanup_result"] = payload

            except Exception as exc:
                report["cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    return report
