# ============================================================
# PLANAPP MCP — PLANNER CLIENT
#
# Adapter entre os MCP tools e o cisei_planning_sdk.
#
# Arquitetura:
#
#   MCP tool
#      |
#      v
#   PlannerClient
#      |
#      v
#   PlanningClient (SDK 0.1.18)
#      |
#      v
#   ScenarioSession
#      |
#      v
#   network-service
#
# Este módulo NÃO implementa:
#   - HTTP manual
#   - autenticação/X-Token manual
#   - lógica de planejamento
#   - validação própria do cenário
#   - execução direta dos endpoints
#
# Toda comunicação com o Planning Service é delegada ao SDK.
# ============================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cisei_planning_sdk import PlanningClient, PlanningProject
from cisei_planning_sdk.session import ScenarioSession


class PlannerClient:
    """
    Thin adapter sobre o cisei_planning_sdk.

    Responsabilidades:
      - criar/configurar PlanningClient;
      - manter sessões de cenário;
      - traduzir operações de alto nível para o SDK;
      - devolver somente dados serializáveis aos MCP tools.

    Não implementa a lógica de planejamento.
    """

    DEFAULT_BASE_URL = "http://network-service:8080"
    DEFAULT_TIMEOUT = 900.0
    DEFAULT_PLANNER = "graph"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        user_id: str | None = None,
        workspace: str | Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        auto_register: bool = True,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("PLANAPP_PLANNER_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")

        self.user_id = (
            user_id
            or os.environ.get("PLANAPP_USER_ID")
            or "planapp-mcp"
        )

        self.workspace = self._resolve_workspace(workspace)

        self.timeout = float(timeout)

        self.client = PlanningClient(
            self.base_url,
            workspace=self.workspace,
            user_id=self.user_id,
            auto_register=auto_register,
            timeout=self.timeout,
        )

        # scenario_id -> ScenarioSession
        self._sessions: dict[str, ScenarioSession] = {}

    # ========================================================
    # CONNECTION
    # ========================================================

    def connect(self) -> dict[str, Any]:
        """
        Register/re-register this MCP user with the planning hub.

        Authentication is entirely delegated to PlanningClient.
        """
        self.client.connect()

        return {
            "status": "ok",
            "user_id": self.client.user_id,
            "base_url": self.base_url,
        }

    @property
    def connected(self) -> bool:
        """Return whether the SDK currently has an authentication token."""
        return self.client.token is not None

    # ========================================================
    # SCENARIO
    # ========================================================

    def define_scenario(
        self,
        *,
        scenario_id: str,
        scenario: dict[str, Any],
        planner: str = DEFAULT_PLANNER,
    ) -> dict[str, Any]:
        """
        Define a scenario on the planning service.

        The scenario is supplied as a Python dictionary.

        The SDK requires an active PlanningProject before calling
        PlanningClient.define_scenario(). For MCP usage we create a
        lightweight project directory associated with the scenario.

        The actual scenario data remains the authority supplied by
        the caller; this adapter does not generate or modify it.
        """
        if not isinstance(scenario, dict):
            raise TypeError("scenario must be a dictionary")

        project = self._ensure_project(scenario_id)

        self.client.project = project

        session = self.client.define_scenario(
            name=scenario_id,
            scenario=scenario,
            planner=planner,
        )

        self._sessions[session.scenario_id] = session

        return self._scenario_state(session)

    def get_scenario(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Reload the Stage 1 scenario from the planning service.
        """
        session = self._get_session(scenario_id)

        session.refresh()

        return self._scenario_state(session)

    # ========================================================
    # CANDIDATE EDGES
    # ========================================================

    def build_candidate_edges(
        self,
        *,
        scenario_id: str,
        planner: str | None = None,
        preserve_existing: bool = True,
        primary_tech: str = "lte",
        sector_aware: bool = True,
        limit_m: float | None = None,
        degree: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute Stage 2: candidate graph construction.
        """
        session = self._get_session(scenario_id)

        result = session.build_candidate_edges(
            planner=planner,
            preserve_existing=preserve_existing,
            primary_tech=primary_tech,
            sector_aware=sector_aware,
            limit_m=limit_m,
            degree=degree,
        )

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "candidate_edges": result,
        }

    def get_candidate_edges(
        self,
        *,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Read the currently stored candidate graph.
        """
        session = self._get_session(scenario_id)

        result = session.get_candidate_edges()

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "candidate_edges": result,
        }

    # ========================================================
    # METRICS
    # ========================================================

    def compute_metrics(
        self,
        *,
        scenario_id: str,
        geo_base_url: str = "http://planning-service:8080",
        geo_user_prefix: str = "planning-sdk",
        geo_pool_size: int = 1,
        geo_timeout: float = 120.0,
        include_features: bool = False,
    ) -> dict[str, Any]:
        """
        Execute Stage 3/metric computation through the SDK.
        """
        session = self._get_session(scenario_id)

        result = session.compute_metrics(
            geo_base_url=geo_base_url,
            geo_user_prefix=geo_user_prefix,
            geo_pool_size=geo_pool_size,
            geo_timeout=geo_timeout,
            include_features=include_features,
        )

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "metrics": result,
        }

    def get_metrics(
        self,
        *,
        scenario_id: str,
        include_features: bool = False,
    ) -> dict[str, Any]:
        """
        Read already-computed metrics.
        """
        session = self._get_session(scenario_id)

        result = session.get_metrics(
            include_features=include_features,
        )

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "metrics": result,
        }

    # ========================================================
    # SOLUTION
    # ========================================================

    def solve(
        self,
        *,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Execute the solver stage.
        """
        session = self._get_session(scenario_id)

        result = session.solve()

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "solution": result,
        }

    def get_solution(
        self,
        *,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Read an already-saved solution.
        """
        session = self._get_session(scenario_id)

        result = session.get_solution()

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "solution": result,
        }

    # ========================================================
    # EVALUATION
    # ========================================================

    def evaluate(
        self,
        *,
        scenario_id: str,
        rank_threshold: float,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate an already-solved scenario.
        """
        session = self._get_session(scenario_id)

        result = session.evaluate(
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "evaluation": result,
        }

    # ========================================================
    # EXPORT
    # ========================================================

    def export_result(
        self,
        *,
        scenario_id: str,
        include_features: bool = False,
        rank_threshold: float | None = None,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
    ) -> dict[str, Any]:
        """
        Export the current server-side planning result.
        """
        session = self._get_session(scenario_id)

        result = session.export_result(
            include_features=include_features,
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "result": result,
        }

    def export_scenario(
        self,
        *,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Export the complete Stage 1 scenario stored by the server.
        """
        session = self._get_session(scenario_id)

        result = session.export_scenario()

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "scenario": result,
        }

    # ========================================================
    # SESSION INFORMATION
    # ========================================================

    def session_state(
        self,
        *,
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Return local SDK session state without executing a planning stage.
        """
        session = self._get_session(scenario_id)

        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "name": session.name,
            "planner": session.planner,
            "ok": session.ok,
            "summary": session.summary,
            "validation_errors": session.validation_errors,
            "has_scenario": session.scenario is not None,
            "has_candidate_edges": session.candidate_edges is not None,
            "has_metrics": session.metrics is not None,
            "has_solution": session.solution is not None,
            "has_evaluation": session.evaluation is not None,
            "has_result": session.result is not None,
        }

    # ========================================================
    # INTERNAL
    # ========================================================

    def _get_session(self, scenario_id: str) -> ScenarioSession:
        """
        Return an existing local ScenarioSession.

        We deliberately do not silently create a new session because a
        missing local session usually means the MCP caller has lost the
        scenario handle.
        """
        if not scenario_id:
            raise ValueError("scenario_id is required")

        session = self._sessions.get(scenario_id)

        if session is None:
            raise KeyError(
                f"Unknown planning scenario session: {scenario_id}"
            )

        return session

    def _ensure_project(self, scenario_id: str) -> PlanningProject:
        """
        Create a lightweight local project for SDK compatibility.

        The SDK's PlanningClient.define_scenario() requires client.project,
        although the define operation itself can consume a dictionary and
        does not need a scenario.toml file.

        This directory is therefore only an SDK bookkeeping/workspace
        requirement. The MCP adapter does not generate scenario.toml here.
        """
        workspace = self.workspace

        projects_root = workspace / "projects"
        project_path = projects_root / scenario_id

        project = PlanningProject(project_path)

        return project

    @staticmethod
    def _resolve_workspace(
        workspace: str | Path | None,
    ) -> Path:
        """
        Resolve the MCP planning workspace.

        Preference:
          1. explicit workspace argument;
          2. PLANAPP_PLANNING_WORKSPACE;
          3. /workspace;
          4. /workspace/planapp-user.
        """
        if workspace is not None:
            path = Path(workspace).expanduser().resolve()
        else:
            env_workspace = os.environ.get("PLANAPP_PLANNING_WORKSPACE")

            if env_workspace:
                path = Path(env_workspace).expanduser().resolve()
            elif Path("/workspace").is_dir():
                path = Path("/workspace").resolve()
            elif Path("/workspace/planapp-user").is_dir():
                path = Path("/workspace/planapp-user").resolve()
            else:
                path = Path("/tmp/planapp-planning-workspace").resolve()

        (path / "projects").mkdir(parents=True, exist_ok=True)

        return path

    @staticmethod
    def _scenario_state(
        session: ScenarioSession,
    ) -> dict[str, Any]:
        """
        Convert ScenarioSession state into an MCP-safe dictionary.
        """
        return {
            "status": "ok",
            "scenario_id": session.scenario_id,
            "name": session.name,
            "planner": session.planner,
            "ok": session.ok,
            "summary": session.summary,
            "validation_errors": session.validation_errors,
            "scenario": session.scenario,
        }