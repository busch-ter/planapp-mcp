# ============================================================
# PLANAPP — PLANNER ORCHESTRATOR
#
# Camada de aplicação para execução do planejamento.
#
# Arquitetura:
#
#   ScenarioAgentOpenAI
#          |
#          v
#   PlannerOrchestrator
#          |
#          v
#   PlanAppAgentCommon
#          |
#          v
#   PlanApp MCP
#
# O LLM NÃO executa MCP.
#
# O LLM produz somente uma intenção estruturada.
#
# A aplicação executa essa intenção através do
# PlanAppAgentCommon, que já é a camada MCP existente
# utilizada pelo PlanApp AI.
#
# Este módulo NÃO:
#
#   - interpreta linguagem natural;
#   - chama OpenAI;
#   - altera ScenarioBuilder;
#   - gera scenario.toml;
#   - cria parâmetros técnicos do cenário;
#   - implementa uma segunda camada MCP.
#
# Além da execução, este módulo mantém:
#
#   - resultados completos internamente;
#   - respostas compactas para o agente;
#   - dados preparados para futura visualização no mapa.
#
# IMPORTANTE:
#
# A inspeção de planning_result abaixo é temporária.
#
# Ela existe para descobrirmos a estrutura REAL retornada
# pelo Planning Service para:
#
#   - planned_edges
#   - planned_nodes
#
# Não assumimos ainda que "planned_edges": 11 significa
# que existe uma lista contendo 11 objetos.
# ============================================================

from __future__ import annotations

from typing import Any

from agent_common import PlanAppAgentCommon


# ============================================================
# CONFIGURAÇÕES DE EXECUÇÃO DO PLANNER
#
# Estes valores são parâmetros da OPERAÇÃO DE PLANEJAMENTO.
#
# Eles NÃO são defaults técnicos do scenario.toml.
#
# O cenário continua sendo a fonte dos parâmetros técnicos.
# ============================================================

DEFAULT_PLANNER = "cell"
DEFAULT_RANK_THRESHOLD = 10
DEFAULT_PRIMARY_TECH = "lte"
DEFAULT_SOLUTION_KIND = "graph"


# ============================================================
# FERRAMENTAS DO DOMÍNIO DE PLANEJAMENTO
# ============================================================

PLANNING_TOOLS = {
    "planning_open",
    "planning_run",
    "planning_status",
    "planning_result",
    "planning_export",
}


# ============================================================
# EXCEÇÃO
# ============================================================

class PlannerOrchestratorError(RuntimeError):
    """Erro específico da camada de planejamento."""


# ============================================================
# ORQUESTRADOR
# ============================================================

class PlannerOrchestrator:

    """
    Orquestra a execução do planejamento.

    O MCP continua pertencendo à infraestrutura existente
    do PlanAppAgentCommon.

    Portanto, esta classe não cria:

        - ClientSession
        - streamable_http_client
        - PLANAPP_MCP_URL
        - parsing MCP paralelo

    Ela reutiliza o cliente MCP existente.

    Quando um PlanAppAgentCommon externo é fornecido,
    a sessão pertence ao chamador.

    Quando nenhum é fornecido, o Orchestrator cria uma
    instância própria e passa a ser seu proprietário.
    """

    def __init__(
        self,
        *,
        mcp_agent: PlanAppAgentCommon | None = None,
        progress_callback=None,
        log_callback=None,
    ):

        # ----------------------------------------------------
        # Cliente MCP existente
        # ----------------------------------------------------

        if mcp_agent is not None:

            self.mcp_agent = mcp_agent
            self._owns_mcp_agent = False

        else:

            self.mcp_agent = PlanAppAgentCommon(
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            self._owns_mcp_agent = True

        self.progress_callback = progress_callback
        self.log_callback = log_callback

        # ----------------------------------------------------
        # Últimos resultados completos
        #
        # Estes objetos podem ser grandes.
        # Não devem ser enviados diretamente para o LLM.
        # ----------------------------------------------------

        self.last_open_result: Any = None
        self.last_run_result: Any = None
        self.last_status_result: Any = None
        self.last_result: Any = None
        self.last_export_result: Any = None

        # ----------------------------------------------------
        # Dados preparados para visualização no mapa.
        #
        # Estrutura futura:
        #
        # {
        #     "scenario_id": "...",
        #     "sites": [...],
        #     "planned_nodes": [...],
        #     "planned_edges": [...],
        # }
        #
        # Neste momento ainda estamos descobrindo a estrutura
        # real retornada pelo Planning Service.
        # ----------------------------------------------------

        self.last_map_data: dict[str, Any] = {}

    # ========================================================
    # LOG
    # ========================================================

    def log(
        self,
        message: str,
    ) -> None:

        text = str(message)

        if self.progress_callback:

            try:
                self.progress_callback(text)
            except Exception:
                pass

        if self.log_callback:

            try:
                self.log_callback(text)
            except Exception:
                pass

    # ========================================================
    # CONEXÃO
    # ========================================================

    async def connect(self) -> None:
        """
        Reutiliza a conexão MCP existente do PlanAppAgentCommon.

        Se o PlanAppAgentCommon foi criado externamente,
        esta classe não assume propriedade sobre a sessão.
        """

        if not self.mcp_agent.connected:

            await self.mcp_agent.connect()

    # ========================================================
    # CHAMADA MCP
    # ========================================================

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:

        if tool_name not in PLANNING_TOOLS:

            raise PlannerOrchestratorError(
                "Ferramenta fora do domínio de planejamento: "
                f"{tool_name}"
            )

        await self.connect()

        self.log(
            f"🔧 Planner MCP: {tool_name}"
        )

        try:

            result = await (
                self.mcp_agent.execute_mcp_tool(
                    tool_name,
                    arguments,
                )
            )

        except Exception as exc:

            raise PlannerOrchestratorError(
                f"Erro executando {tool_name}: {exc}"
            ) from exc

        # ----------------------------------------------------
        # execute_mcp_tool() já faz o parsing MCP.
        # ----------------------------------------------------

        return result

    # ========================================================
    # UTILITÁRIOS DE ESTRUTURA
    # ========================================================

    @staticmethod
    def _is_dict(
        value: Any,
    ) -> bool:

        return isinstance(
            value,
            dict,
        )

    @staticmethod
    def _is_list(
        value: Any,
    ) -> bool:

        return isinstance(
            value,
            list,
        )

    @classmethod
    def _walk_dicts(
        cls,
        value: Any,
    ):
        """
        Percorre recursivamente todos os dicionários encontrados
        em uma estrutura JSON-like.

        Não altera os dados originais.
        """

        if isinstance(
            value,
            dict,
        ):

            yield value

            for child in value.values():

                yield from cls._walk_dicts(
                    child
                )

        elif isinstance(
            value,
            list,
        ):

            for child in value:

                yield from cls._walk_dicts(
                    child
                )

    @classmethod
    def _find_first_value(
        cls,
        data: Any,
        keys: tuple[str, ...],
    ) -> Any:
        """
        Procura recursivamente o primeiro valor associado
        a uma das chaves informadas.
        """

        for current in cls._walk_dicts(
            data
        ):

            for key in keys:

                if key in current:

                    return current[key]

        return None

    @classmethod
    def _find_all_values(
        cls,
        data: Any,
        keys: tuple[str, ...],
    ) -> list[Any]:
        """
        Retorna todos os valores encontrados para as chaves
        informadas.

        Atualmente usado apenas como utilitário.
        """

        found = []

        for current in cls._walk_dicts(
            data
        ):

            for key in keys:

                if key in current:

                    found.append(
                        current[key]
                    )

        return found

    # ========================================================
    # RESUMO DO PLANNING OPEN
    # ========================================================

    @classmethod
    def _summarize_open_result(
        cls,
        result: Any,
    ) -> dict[str, Any]:
        """
        Reduz planning_open ao que interessa à conversa.

        O campo 'scenario' completo é deliberadamente removido.
        """

        if not isinstance(
            result,
            dict,
        ):

            return {
                "raw_type":
                    type(result).__name__,
            }

        summary = result.get(
            "summary"
        )

        if not isinstance(
            summary,
            dict,
        ):

            summary = {}

        response = {

            "status":
                result.get(
                    "status"
                ),

            "ok":
                result.get(
                    "ok"
                ),

            "scenario_id":
                result.get(
                    "scenario_id"
                ),

            "name":
                result.get(
                    "name"
                ),

            "planner":
                result.get(
                    "planner"
                ),

            "summary":
                summary,

            "validation_errors":
                result.get(
                    "validation_errors",
                    [],
                ),
        }

        # ----------------------------------------------------
        # Remove valores None para manter o JSON compacto.
        # ----------------------------------------------------

        return {
            key: value
            for key, value in response.items()
            if value is not None
        }

    # ========================================================
    # RESUMO DO PLANNING RUN / RESULT
    # ========================================================

    @classmethod
    def _summarize_planning_result(
        cls,
        result: Any,
    ) -> dict[str, Any]:
        """
        Extrai somente indicadores agregados do planejamento.

        Não devolve listas gigantes de sites, nós ou enlaces.

        Os nomes conhecidos do planner são preservados quando
        encontrados.

        Se uma versão futura do Planning Service alterar o
        nesting, a busca recursiva tenta localizar os mesmos
        campos.
        """

        if not isinstance(
            result,
            dict,
        ):

            return {
                "raw_type":
                    type(result).__name__,
            }

        # ----------------------------------------------------
        # Campos agregados conhecidos.
        # ----------------------------------------------------

        scalar_fields = (
            "sites",
            "rpl_nodes",
            "candidate_edges",
            "metric_edges",
            "planned_nodes",
            "planned_edges",
            "targets",
            "good",
            "poor",
            "unserved",
        )

        response: dict[str, Any] = {}

        for field in scalar_fields:

            value = cls._find_first_value(
                result,
                (field,),
            )

            # ------------------------------------------------
            # Somente valores escalares são incluídos.
            #
            # Isso evita colocar no resultado textual uma lista
            # contendo centenas de objetos.
            # ------------------------------------------------

            if isinstance(
                value,
                (
                    int,
                    float,
                    str,
                    bool,
                ),
            ):

                response[field] = value

        # ----------------------------------------------------
        # Evaluation
        # ----------------------------------------------------

        evaluation = cls._find_first_value(
            result,
            ("evaluation",),
        )

        if isinstance(
            evaluation,
            dict,
        ):

            compact_evaluation = {}

            for field in (
                "targets",
                "good",
                "poor",
                "unserved",
            ):

                value = evaluation.get(
                    field
                )

                if isinstance(
                    value,
                    (
                        int,
                        float,
                        str,
                        bool,
                    ),
                ):

                    compact_evaluation[
                        field
                    ] = value

            if compact_evaluation:

                response[
                    "evaluation"
                ] = compact_evaluation

        # ----------------------------------------------------
        # Status / execução
        # ----------------------------------------------------

        for field in (
            "status",
            "ok",
            "scenario_id",
            "planner",
        ):

            value = result.get(
                field
            )

            if value is not None:

                response[field] = value

        return response

    # ========================================================
    # EXTRAÇÃO DOS DADOS DO MAPA
    # ========================================================

    @classmethod
    def _extract_map_data(
        cls,
        *,
        scenario_id: str,
        open_result: Any = None,
        run_result: Any = None,
        result: Any = None,
    ) -> dict[str, Any]:
        """
        Extrai os dados relevantes para a visualização cartográfica.

        IMPORTANTE:

        Esta função NÃO inventa coordenadas nem enlaces.

        Ela somente reaproveita objetos que realmente vieram
        do Planning Service / MCP.

        A estrutura exata do resultado pode variar conforme
        o endpoint. Por isso são procuradas algumas chaves
        conhecidas.

        O objetivo é manter os dados completos fora da resposta
        textual do agente.
        """

        map_data: dict[str, Any] = {

            "scenario_id":
                scenario_id,

            "sites":
                [],

            "planned_nodes":
                [],

            "planned_edges":
                [],
        }

        # ----------------------------------------------------
        # Coleta todos os resultados disponíveis.
        #
        # A prioridade é:
        #
        #   planning_result
        #   planning_run
        #   planning_open
        # ----------------------------------------------------

        sources = [
            result,
            run_result,
            open_result,
        ]

        # ----------------------------------------------------
        # Sites
        # ----------------------------------------------------

        for source in sources:

            if not isinstance(
                source,
                dict,
            ):
                continue

            sites = cls._find_first_value(
                source,
                ("sites",),
            )

            if isinstance(
                sites,
                list,
            ) and sites:

                map_data[
                    "sites"
                ] = sites

                break

        # ----------------------------------------------------
        # Planned nodes
        # ----------------------------------------------------

        for source in sources:

            if not isinstance(
                source,
                dict,
            ):
                continue

            nodes = cls._find_first_value(
                source,
                (
                    "planned_nodes",
                    "plannedNodes",
                ),
            )

            if isinstance(
                nodes,
                list,
            ) and nodes:

                map_data[
                    "planned_nodes"
                ] = nodes

                break

        # ----------------------------------------------------
        # Planned edges
        # ----------------------------------------------------

        for source in sources:

            if not isinstance(
                source,
                dict,
            ):
                continue

            edges = cls._find_first_value(
                source,
                (
                    "planned_edges",
                    "plannedEdges",
                ),
            )

            if isinstance(
                edges,
                list,
            ) and edges:

                map_data[
                    "planned_edges"
                ] = edges

                break

        # ----------------------------------------------------
        # Metadados úteis para o mapa.
        # ----------------------------------------------------

        map_data[
            "site_count"
        ] = len(
            map_data[
                "sites"
            ]
        )

        map_data[
            "planned_node_count"
        ] = len(
            map_data[
                "planned_nodes"
            ]
        )

        map_data[
            "planned_edge_count"
        ] = len(
            map_data[
                "planned_edges"
            ]
        )

        return map_data

    # ========================================================
    # DEBUG — ESTRUTURA DO PLANNING RESULT
    # ========================================================

    @classmethod
    def _inspect_planning_structure(
        cls,
        result: Any,
    ) -> dict[str, Any]:
        """
        Inspeciona a estrutura REAL devolvida por planning_result.

        Objetivo:
            descobrir onde estão os objetos de:

                - planned_edges
                - planned_nodes

        Não altera o resultado original.

        Não envia o cenário inteiro para o agente.
        """

        inspection: dict[str, Any] = {}

        # ----------------------------------------------------
        # Resultado precisa ser dict.
        # ----------------------------------------------------

        if not isinstance(
            result,
            dict,
        ):

            return {

                "result_type":
                    type(result).__name__,

                "result_is_dict":
                    False,
            }

        inspection[
            "result_type"
        ] = "dict"

        # ----------------------------------------------------
        # Mostra somente as chaves do primeiro nível.
        # ----------------------------------------------------

        inspection[
            "top_level_keys"
        ] = list(
            result.keys()
        )

        # ====================================================
        # PLANNED EDGES
        # ====================================================

        planned_edges = cls._find_first_value(
            result,
            (
                "planned_edges",
                "plannedEdges",
            ),
        )

        if isinstance(
            planned_edges,
            list,
        ):

            inspection[
                "planned_edges"
            ] = {

                "type":
                    "list",

                "count":
                    len(
                        planned_edges
                    ),

                "first_item":
                    (
                        planned_edges[0]
                        if planned_edges
                        else None
                    ),
            }

        elif isinstance(
            planned_edges,
            dict,
        ):

            inspection[
                "planned_edges"
            ] = {

                "type":
                    "dict",

                "keys":
                    list(
                        planned_edges.keys()
                    ),
            }

        elif planned_edges is None:

            inspection[
                "planned_edges"
            ] = {

                "type":
                    "not_found",
            }

        else:

            inspection[
                "planned_edges"
            ] = {

                "type":
                    type(
                        planned_edges
                    ).__name__,

                "value":
                    planned_edges,
            }

        # ====================================================
        # PLANNED NODES
        # ====================================================

        planned_nodes = cls._find_first_value(
            result,
            (
                "planned_nodes",
                "plannedNodes",
            ),
        )

        if isinstance(
            planned_nodes,
            list,
        ):

            inspection[
                "planned_nodes"
            ] = {

                "type":
                    "list",

                "count":
                    len(
                        planned_nodes
                    ),

                "first_item":
                    (
                        planned_nodes[0]
                        if planned_nodes
                        else None
                    ),
            }

        elif isinstance(
            planned_nodes,
            dict,
        ):

            inspection[
                "planned_nodes"
            ] = {

                "type":
                    "dict",

                "keys":
                    list(
                        planned_nodes.keys()
                    ),
            }

        elif planned_nodes is None:

            inspection[
                "planned_nodes"
            ] = {

                "type":
                    "not_found",
            }

        else:

            inspection[
                "planned_nodes"
            ] = {

                "type":
                    type(
                        planned_nodes
                    ).__name__,

                "value":
                    planned_nodes,
            }

        return inspection

    # ========================================================
    # VALIDAÇÃO DA SOLICITAÇÃO
    # ========================================================

    @staticmethod
    def validate_run_request(
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Valida a intenção de execução.

        Não valida o conteúdo técnico do scenario.toml.

        Isso continua pertencendo ao Planner/Planning Service.
        """

        if not isinstance(
            request,
            dict,
        ):

            raise PlannerOrchestratorError(
                "A solicitação de planejamento deve "
                "ser um objeto JSON."
            )

        scenario_id = request.get(
            "scenario_id"
        )

        if not isinstance(
            scenario_id,
            str,
        ) or not scenario_id.strip():

            raise PlannerOrchestratorError(
                "planning_run exige scenario_id."
            )

        planner = request.get(
            "planner"
        )

        if planner is None:

            planner = DEFAULT_PLANNER

        if not isinstance(
            planner,
            str,
        ) or not planner.strip():

            raise PlannerOrchestratorError(
                "planner deve ser uma string não vazia."
            )

        rank_threshold = request.get(
            "rank_threshold"
        )

        if rank_threshold is None:

            rank_threshold = DEFAULT_RANK_THRESHOLD

        try:

            rank_threshold = int(
                rank_threshold
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise PlannerOrchestratorError(
                "rank_threshold deve ser inteiro."
            ) from exc

        primary_tech = request.get(
            "primary_tech"
        )

        if primary_tech is None:

            primary_tech = DEFAULT_PRIMARY_TECH

        if not isinstance(
            primary_tech,
            str,
        ) or not primary_tech.strip():

            raise PlannerOrchestratorError(
                "primary_tech deve ser uma string "
                "não vazia."
            )

        solution_kind = request.get(
            "solution_kind"
        )

        if solution_kind is None:

            solution_kind = DEFAULT_SOLUTION_KIND

        if not isinstance(
            solution_kind,
            str,
        ) or not solution_kind.strip():

            raise PlannerOrchestratorError(
                "solution_kind deve ser uma string "
                "não vazia."
            )

        return {

            "scenario_id":
                scenario_id.strip(),

            "planner":
                planner.strip(),

            "rank_threshold":
                rank_threshold,

            "primary_tech":
                primary_tech.strip(),

            "solution_kind":
                solution_kind.strip(),
        }

    # ========================================================
    # PLANNING OPEN
    # ========================================================

    async def planning_open(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:

        if not isinstance(
            scenario_id,
            str,
        ) or not scenario_id.strip():

            raise PlannerOrchestratorError(
                "scenario_id é obrigatório."
            )

        scenario_id = scenario_id.strip()

        self.log(
            "📂 Abrindo cenário de planejamento: "
            f"{scenario_id}"
        )

        result = await self.call_tool(
            "planning_open",
            {
                "scenario_id":
                    scenario_id,
            },
        )

        # ----------------------------------------------------
        # Guarda resultado COMPLETO.
        # ----------------------------------------------------

        self.last_open_result = result

        # ----------------------------------------------------
        # Retorna somente resumo.
        # ----------------------------------------------------

        return self._summarize_open_result(
            result
        )

    # ========================================================
    # PLANNING RUN
    # ========================================================

    async def planning_run(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:

        validated = self.validate_run_request(
            request
        )

        scenario_id = validated[
            "scenario_id"
        ]

        # ----------------------------------------------------
        # Primeiro abre o cenário.
        # ----------------------------------------------------

        open_summary = await (
            self.planning_open(
                scenario_id
            )
        )

        # ----------------------------------------------------
        # Depois executa o planner.
        # ----------------------------------------------------

        self.log(
            "📐 Executando planejamento "
            f"do cenário '{scenario_id}'..."
        )

        run_result = await (
            self.call_tool(
                "planning_run",
                validated,
            )
        )

        # ----------------------------------------------------
        # Guarda resultado COMPLETO.
        # ----------------------------------------------------

        self.last_run_result = run_result

        # ----------------------------------------------------
        # Prepara dados cartográficos.
        #
        # Neste momento a estrutura ainda é exploratória.
        # O resultado consolidado de planning_result terá
        # prioridade quando execute() buscar esse resultado.
        # ----------------------------------------------------

        self.last_map_data = (
            self._extract_map_data(
                scenario_id=scenario_id,
                open_result=self.last_open_result,
                run_result=run_result,
                result=None,
            )
        )

        # ----------------------------------------------------
        # Retorna somente dados compactos.
        # ----------------------------------------------------

        return {

            "status":
                "OK",

            "scenario_id":
                scenario_id,

            "request":
                validated,

            "planning_open":
                open_summary,

            "planning_run":
                self._summarize_planning_result(
                    run_result
                ),

            "map_summary": {

                "sites":
                    self.last_map_data[
                        "site_count"
                    ],

                "planned_nodes":
                    self.last_map_data[
                        "planned_node_count"
                    ],

                "planned_edges":
                    self.last_map_data[
                        "planned_edge_count"
                    ],
            },
        }

    # ========================================================
    # PLANNING STATUS
    # ========================================================

    async def planning_status(
        self,
        scenario_id: str,
    ) -> Any:

        if not isinstance(
            scenario_id,
            str,
        ) or not scenario_id.strip():

            raise PlannerOrchestratorError(
                "scenario_id é obrigatório."
            )

        result = await (
            self.call_tool(
                "planning_status",
                {
                    "scenario_id":
                        scenario_id.strip(),
                },
            )
        )

        self.last_status_result = result

        return result

    # ========================================================
    # PLANNING RESULT
    # ========================================================

    async def planning_result(
        self,
        scenario_id: str,
    ) -> dict[str, Any]:

        if not isinstance(
            scenario_id,
            str,
        ) or not scenario_id.strip():

            raise PlannerOrchestratorError(
                "scenario_id é obrigatório."
            )

        scenario_id = scenario_id.strip()

        result = await (
            self.call_tool(
                "planning_result",
                {
                    "scenario_id":
                        scenario_id,
                },
            )
        )

        # ----------------------------------------------------
        # Guarda o resultado COMPLETO.
        # ----------------------------------------------------

        self.last_result = result

        # ----------------------------------------------------
        # INSPEÇÃO TEMPORÁRIA
        #
        # Este é o ponto principal deste teste.
        # ----------------------------------------------------

        inspection = (
            self._inspect_planning_structure(
                result
            )
        )

        self.log(
            "🔎 Estrutura do planning_result:"
        )

        self.log(
            str(
                inspection
            )
        )

        # ----------------------------------------------------
        # Atualiza os dados do mapa com o resultado REAL.
        # ----------------------------------------------------

        self.last_map_data = (
            self._extract_map_data(
                scenario_id=scenario_id,
                open_result=self.last_open_result,
                run_result=self.last_run_result,
                result=result,
            )
        )

        # ----------------------------------------------------
        # Retorna resumo.
        #
        # O diagnóstico é temporário e pequeno.
        # ----------------------------------------------------

        summary = (
            self._summarize_planning_result(
                result
            )
        )

        summary[
            "structure_debug"
        ] = inspection

        return summary

    # ========================================================
    # PLANNING EXPORT
    # ========================================================

    async def planning_export(
        self,
        scenario_id: str,
        *,
        result: Any = None,
        rank_threshold: int = DEFAULT_RANK_THRESHOLD,
        primary_tech: str = DEFAULT_PRIMARY_TECH,
        solution_kind: str = DEFAULT_SOLUTION_KIND,
    ) -> Any:

        if not isinstance(
            scenario_id,
            str,
        ) or not scenario_id.strip():

            raise PlannerOrchestratorError(
                "scenario_id é obrigatório."
            )

        arguments = {

            "scenario_id":
                scenario_id.strip(),

            "result":
                result,

            "rank_threshold":
                rank_threshold,

            "primary_tech":
                primary_tech,

            "solution_kind":
                solution_kind,
        }

        exported = await (
            self.call_tool(
                "planning_export",
                arguments,
            )
        )

        self.last_export_result = exported

        return exported

    # ========================================================
    # DADOS PARA O MAPA
    # ========================================================

    def get_map_data(
        self,
    ) -> dict[str, Any]:
        """
        Retorna os dados preparados para visualização.

        Não executa MCP.

        Não recalcula enlaces.

        Não cria coordenadas.

        Apenas devolve os dados extraídos dos resultados
        do planner.
        """

        return self.last_map_data

    # ========================================================
    # EXECUÇÃO COMPLETA
    # ========================================================

    async def execute(
        self,
        request: dict[str, Any],
        *,
        fetch_result: bool = True,
        export: bool = False,
    ) -> dict[str, Any]:
        """
        Executa:

            planning_open
                ↓
            planning_run
                ↓
            planning_result
                ↓
            opcionalmente planning_export
        """

        validated = self.validate_run_request(
            request
        )

        run = await (
            self.planning_run(
                validated
            )
        )

        response = {

            "status":
                "OK",

            "scenario_id":
                validated[
                    "scenario_id"
                ],

            "request":
                validated,

            "planning_open":
                run.get(
                    "planning_open"
                ),

            "planning_run":
                run.get(
                    "planning_run"
                ),

            "map_summary":
                run.get(
                    "map_summary"
                ),
        }

        # ----------------------------------------------------
        # Resultado REAL do planejamento
        # ----------------------------------------------------

        if fetch_result:

            result_summary = await (
                self.planning_result(
                    validated[
                        "scenario_id"
                    ]
                )
            )

            response[
                "planning_result"
            ] = result_summary

            # ------------------------------------------------
            # Atualiza resumo cartográfico depois do resultado
            # consolidado.
            # ------------------------------------------------

            response[
                "map_summary"
            ] = {

                "sites":
                    self.last_map_data.get(
                        "site_count",
                        0,
                    ),

                "planned_nodes":
                    self.last_map_data.get(
                        "planned_node_count",
                        0,
                    ),

                "planned_edges":
                    self.last_map_data.get(
                        "planned_edge_count",
                        0,
                    ),
            }

        # ----------------------------------------------------
        # Exportação
        # ----------------------------------------------------

        if export:

            exported = await (
                self.planning_export(
                    validated[
                        "scenario_id"
                    ],
                    result=self.last_result,
                    rank_threshold=validated[
                        "rank_threshold"
                    ],
                    primary_tech=validated[
                        "primary_tech"
                    ],
                    solution_kind=validated[
                        "solution_kind"
                    ],
                )
            )

            response[
                "planning_export"
            ] = exported

        return response

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(
        self,
    ) -> None:
        """
        Fecha o MCP somente quando este Orchestrator é o
        proprietário do PlanAppAgentCommon.

        Se o mcp_agent foi injetado externamente, o chamador
        continua sendo responsável por fechar a sessão.

        IMPORTANTE:

        O close deve ocorrer no mesmo contexto assíncrono que
        possui a sessão MCP.
        """

        if not self._owns_mcp_agent:

            return None

        await self.mcp_agent.close()

    # ========================================================
    # FACTORY
    # ========================================================


def create_planner_orchestrator(
    *,
    mcp_agent: PlanAppAgentCommon | None = None,
    progress_callback=None,
    log_callback=None,
) -> PlannerOrchestrator:

    return PlannerOrchestrator(
        mcp_agent=mcp_agent,
        progress_callback=progress_callback,
        log_callback=log_callback,
    )