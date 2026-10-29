from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cisei_planning_sdk import PlanningClient, PlanningProject
from cisei_planning_sdk.session import ScenarioSession


class PlannerClient:
    """
    Adapter de produção para o cisei_planning_sdk.

    Responsabilidades:
    - conexão com o network-service;
    - gerenciamento do workspace do planejador;
    - abertura/reabertura de projetos;
    - manutenção das sessões ScenarioSession em memória;
    - exposição de operações de alto nível para a futura camada MCP.

    O PlannerClient NÃO:
    - interpreta linguagem natural;
    - cria ou altera ScenarioBuilder;
    - inventa parâmetros técnicos;
    - executa lógica de planejamento própria;
    - substitui o cisei_planning_sdk.
    """

    DEFAULT_BASE_URL = "http://network-service:8080"
    DEFAULT_TIMEOUT = 900.0
    DEFAULT_PLANNER = "cell"
    DEFAULT_WORKSPACE = "/workspace/cisei_workspace"

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

        self._sessions: dict[str, ScenarioSession] = {}

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """
        Garante que o PlanningClient esteja autenticado.

        Evita registro duplicado quando o SDK já realizou auto_register
        durante o __init__.
        """
        if not self.connected:
            self.client.connect()

        return {
            "status": "ok",
            "user_id": self.client.user_id,
            "base_url": self.base_url,
            "workspace": str(self.workspace),
        }

    @property
    def connected(self) -> bool:
        return self.client.token is not None

    # ------------------------------------------------------------------
    # Scenario lifecycle
    # ------------------------------------------------------------------

    def define_scenario(
        self,
        *,
        scenario_id: str,
        scenario: dict[str, Any],
        planner: str = DEFAULT_PLANNER,
    ) -> dict[str, Any]:
        """
        Define um cenário novo a partir de um scenario dict.

        Usado principalmente quando a aplicação ainda não abriu um
        PlanningProject existente.
        """
        if not scenario_id:
            raise ValueError("scenario_id is required")

        if not isinstance(scenario, dict):
            raise TypeError("scenario must be a dictionary")

        self.connect()

        project = self._ensure_project(scenario_id)
        self.client.project = project

        session = self.client.define_scenario(
            name=scenario_id,
            scenario=scenario,
            planner=planner,
        )

        self._sessions[session.scenario_id] = session

        return self._scenario_state(session)

    def open_project(
        self,
        *,
        scenario_id: str,
        planner: str = DEFAULT_PLANNER,
    ) -> dict[str, Any]:
        """
        Abre/reabre um projeto existente no workspace.

        Esta é a operação preferencial quando o ScenarioBuilder já
        produziu scenario.toml + nodes.csv.
        """
        if not scenario_id:
            raise ValueError("scenario_id is required")

        self.connect()

        project = self._get_project(scenario_id)

        session = self.client.open_project(
            project,
            planner=planner,
        )

        self._sessions[session.scenario_id] = session

        return self._scenario_state(session)

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        """
        Obtém o estado de um cenário.

        Se a sessão não estiver em memória, tenta reidratá-la a partir
        do projeto persistido no workspace.
        """
        session = self._get_or_rehydrate_session(scenario_id)

        session.refresh()

        return self._scenario_state(session)

    # ------------------------------------------------------------------
    # Candidate edges
    # ------------------------------------------------------------------

    def build_candidate_edges(
        self,
        scenario_id: str,
        *,
        planner: str | None = None,
        preserve_existing: bool = True,
        primary_tech: str = "lte",
        sector_aware: bool = True,
        limit_m: float | None = None,
        degree: int | None = None,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)

        return session.build_candidate_edges(
            planner=planner,
            preserve_existing=preserve_existing,
            primary_tech=primary_tech,
            sector_aware=sector_aware,
            limit_m=limit_m,
            degree=degree,
        )

    def get_candidate_edges(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)
        return session.get_candidate_edges()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        scenario_id: str,
        *,
        geo_base_url: str = "http://planning-service:8080",
        geo_user_prefix: str = "planning-sdk",
        geo_pool_size: int = 1,
        geo_timeout: float = 120.0,
        include_features: bool = False,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)

        return session.compute_metrics(
            geo_base_url=geo_base_url,
            geo_user_prefix=geo_user_prefix,
            geo_pool_size=geo_pool_size,
            geo_timeout=geo_timeout,
            include_features=include_features,
        )

    def get_metrics(
        self,
        scenario_id: str,
        *,
        include_features: bool = False,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)

        return session.get_metrics(
            include_features=include_features,
        )

    # ------------------------------------------------------------------
    # Solution
    # ------------------------------------------------------------------

    def solve(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)
        return session.solve()

    def get_solution(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)
        return session.get_solution()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        scenario_id: str,
        *,
        rank_threshold: float,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)

        return session.evaluate(
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_result(
        self,
        scenario_id: str,
        *,
        include_features: bool = False,
        rank_threshold: float | None = None,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)

        return session.export_result(
            include_features=include_features,
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

    def export_scenario(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)
        return session.export_scenario()

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def session_state(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:
        session = self._get_or_rehydrate_session(scenario_id)
        return self._scenario_state(session)

    # ------------------------------------------------------------------
    # Internal session management
    # ------------------------------------------------------------------

    def _get_session(
        self,
        scenario_id: str,
    ) -> ScenarioSession:
        if not scenario_id:
            raise ValueError("scenario_id is required")

        session = self._sessions.get(scenario_id)

        if session is None:
            raise KeyError(
                f"Unknown planning scenario session: {scenario_id}"
            )

        return session

    def _get_or_rehydrate_session(
        self,
        scenario_id: str,
        *,
        planner: str | None = None,
    ) -> ScenarioSession:
        """
        Retorna a sessão em memória ou reabre o projeto persistido.

        Isso permite que o MCP continue trabalhando com um cenário
        depois de um restart do processo.
        """
        try:
            return self._get_session(scenario_id)
        except KeyError:
            pass

        project = self._get_project(scenario_id)

        session = self.client.open_project(
            project,
            planner=planner or self.DEFAULT_PLANNER,
        )

        self._sessions[session.scenario_id] = session

        return session

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    def _ensure_project(
        self,
        scenario_id: str,
    ) -> PlanningProject:
        projects_root = self.workspace / "projects"
        project_path = projects_root / scenario_id

        project_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return PlanningProject(project_path)

    def _get_project(
        self,
        scenario_id: str,
    ) -> PlanningProject:
        if not scenario_id:
            raise ValueError("scenario_id is required")

        project_path = (
            self.workspace
            / "projects"
            / scenario_id
        )

        if not project_path.is_dir():
            raise FileNotFoundError(
                f"Planning project not found: {project_path}"
            )

        scenario_path = project_path / "scenario.toml"

        if not scenario_path.is_file():
            raise FileNotFoundError(
                f"scenario.toml not found: {scenario_path}"
            )

        return PlanningProject(project_path)

    # ------------------------------------------------------------------
    # Workspace resolution
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_workspace(
        cls,
        workspace: str | Path | None,
    ) -> Path:
        if workspace is not None:
            path = Path(workspace).expanduser().resolve()

        else:
            env_workspace = os.environ.get(
                "PLANAPP_PLANNING_WORKSPACE"
            )

            if env_workspace:
                path = Path(
                    env_workspace
                ).expanduser().resolve()

            else:
                path = Path(
                    cls.DEFAULT_WORKSPACE
                ).resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"Planning workspace not found: {path}"
            )

        if not path.is_dir():
            raise NotADirectoryError(
                f"Planning workspace is not a directory: {path}"
            )

        projects_root = path / "projects"

        if not projects_root.exists():
            projects_root.mkdir(
                parents=True,
                exist_ok=True,
            )

        return path

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _scenario_state(
        session: ScenarioSession,
    ) -> dict[str, Any]:
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