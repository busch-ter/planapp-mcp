from __future__ import annotations

from typing import Any

from client.planner_client import PlannerClient


def _get_planner_client() -> PlannerClient:
    """
    Cria o PlannerClient usado pelas ferramentas MCP.

    O PlannerClient é responsável por:
    - autenticação;
    - workspace;
    - sessões;
    - comunicação com o Planning SDK.
    """
    return PlannerClient()


def register_planner_tools(mcp: Any, planner: PlannerClient | None = None) -> None:
    """
    Registra as ferramentas MCP do planejador.

    O contrato MCP permanece orientado a operações de negócio e não
    expõe diretamente os detalhes internos do cisei_planning_sdk.
    """

    client = planner or _get_planner_client()

    # ================================================================
    # planning_open
    # ================================================================

    @mcp.tool()
    def planning_open(
        scenario_id: str,
        planner: str = "cell",
    ) -> dict[str, Any]:
        """
        Abre um cenário de planejamento existente no workspace.

        O cenário deve ter sido previamente produzido pela camada
        de aplicação/ScenarioBuilder.

        Não cria scenario.toml nem inventa parâmetros técnicos.
        """
        return client.open_project(
            scenario_id=scenario_id,
            planner=planner,
        )

    # ================================================================
    # planning_run
    # ================================================================

    @mcp.tool()
    def planning_run(
        scenario_id: str,
        planner: str = "cell",
        rank_threshold: float = 10,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
        include_features: bool = False,
        geo_base_url: str = "http://planning-service:8080",
        geo_user_prefix: str = "planning-sdk",
        geo_pool_size: int = 1,
        geo_timeout: float = 120.0,
    ) -> dict[str, Any]:
        """
        Executa o pipeline de planejamento de um cenário.

        Fluxo:

            open
              ↓
            build candidate edges
              ↓
            compute metrics
              ↓
            solve
              ↓
            evaluate

        O cenário deve existir no workspace.

        Esta ferramenta executa o planejamento, mas não altera o
        ScenarioBuilder nem o scenario.toml.
        """

        opened = client.open_project(
            scenario_id=scenario_id,
            planner=planner,
        )

        candidates = client.build_candidate_edges(
            scenario_id,
            planner=planner,
            preserve_existing=True,
            primary_tech=primary_tech,
        )

        metrics = client.compute_metrics(
            scenario_id,
            geo_base_url=geo_base_url,
            geo_user_prefix=geo_user_prefix,
            geo_pool_size=geo_pool_size,
            geo_timeout=geo_timeout,
            include_features=include_features,
        )

        solution = client.solve(
            scenario_id,
        )

        evaluation = client.evaluate(
            scenario_id,
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

        return {
            "status": "ok",
            "scenario": opened,
            "candidates": {
                "counts": candidates.get("counts"),
                "candidate_edges": len(
                    candidates.get("candidate_edges", [])
                ),
                "sectors": len(
                    candidates.get("sectors", [])
                ),
            },
            "metrics": {
                "counts": metrics.get("counts"),
                "metrics": len(
                    metrics.get("metrics", [])
                ),
            },
            "solution": {
                "counts": solution.get("counts"),
                "planned_nodes": len(
                    solution.get("planned_nodes", [])
                ),
                "planned_edges": len(
                    solution.get("planned_edges", [])
                ),
            },
            "evaluation": evaluation,
        }

    # ================================================================
    # planning_status
    # ================================================================

    @mcp.tool()
    def planning_status(
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Retorna o estado atual da sessão de planejamento.

        Se a sessão não estiver na memória do MCP, o PlannerClient
        tenta reabri-la a partir do projeto persistido.
        """
        return client.session_state(
            scenario_id,
        )

    # ================================================================
    # planning_result
    # ================================================================

    @mcp.tool()
    def planning_result(
        scenario_id: str,
        include_features: bool = False,
        rank_threshold: float | None = None,
        primary_tech: str = "lte",
        solution_kind: str | None = None,
    ) -> dict[str, Any]:
        """
        Obtém o resultado consolidado do planejamento.

        A operação usa export_result() do SDK e retorna:
        - topologia;
        - candidatos;
        - métricas;
        - solução;
        - avaliação.
        """
        result = client.export_result(
            scenario_id,
            include_features=include_features,
            rank_threshold=rank_threshold,
            primary_tech=primary_tech,
            solution_kind=solution_kind,
        )

        return {
            "status": "ok",
            "scenario_id": scenario_id,
            "result": result,
        }

    # ================================================================
    # planning_export
    # ================================================================

    @mcp.tool()
    def planning_export(
        scenario_id: str,
    ) -> dict[str, Any]:
        """
        Exporta a representação do cenário utilizada pelo planner.

        Não altera o ScenarioBuilder nem o scenario.toml original.
        """
        result = client.export_scenario(
            scenario_id,
        )

        return {
            "status": "ok",
            "scenario_id": scenario_id,
            "scenario": result,
        }
