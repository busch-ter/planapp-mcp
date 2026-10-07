# ============================================================
# PLANAPP / VIBEPLANNER AI
#
# SCENARIO AGENT
#
# POC-07a
#
# Camada de orquestração do Scenario Builder.
#
# Arquitetura:
#
#     Conversational Layer / LLM
#                |
#                v
#        ScenarioAgent
#                |
#                v
#        ScenarioConversation
#                |
#                v
#        ScenarioSession
#                |
#                v
#        ScenarioBuilder
#                |
#                v
#        PlanningProject
#                |
#                v
#          scenario.toml
#
# IMPORTANTE:
#
# - NÃO conhece OpenAI.
# - NÃO conhece Ollama.
# - NÃO conhece OpenRouter.
# - NÃO conhece MCP.
# - NÃO executa Planning Service.
# - NÃO define defaults técnicos.
# - NÃO inventa parâmetros.
#
# Neste POC, a entrada é estruturada.
#
# O próximo POC poderá conectar:
#
#     agent_openai.py
#            |
#            v
#     ScenarioAgent
#
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject

from scenario_conversation import (
    ScenarioConfirmationRequiredError,
    ScenarioConversation,
    ScenarioNotReadyError,
)


class ScenarioAgentError(RuntimeError):
    """Erro geral do ScenarioAgent."""


class ScenarioAgent:
    """
    Orquestrador do fluxo conversacional de construção de cenário.

    O ScenarioAgent não conhece o provedor de LLM.

    Ele recebe dados estruturados e controla o ciclo:

        collect
          ↓
        validate
          ↓
        complete
          ↓
        confirm
          ↓
        finalize
    """

    def __init__(
        self,
        project: PlanningProject,
        *,
        conversation: ScenarioConversation | None = None,
    ):
        if not isinstance(project, PlanningProject):
            raise TypeError(
                "project must be an instance of PlanningProject"
            )

        self.project = project

        self.conversation = (
            conversation
            if conversation is not None
            else ScenarioConversation(project)
        )

    # --------------------------------------------------------
    # PROPRIEDADES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ESTADO
    # --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """
        Retorna o estado completo da conversa.
        """

        return self.conversation.status()

    def conversation_state(self) -> dict[str, Any]:
        """
        Retorna o estado orientado para a próxima ação
        conversacional.
        """

        return self.conversation.conversation_state()

    def missing_fields(self) -> list[str]:
        """
        Retorna os campos ainda não preenchidos.
        """

        return self.conversation.missing_fields()

    def snapshot(self) -> dict[str, Any]:
        """
        Retorna o cenário estruturado atual.
        """

        return self.conversation.to_dict()

    # --------------------------------------------------------
    # COLETA DE DADOS
    # --------------------------------------------------------

    def update(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Atualiza incrementalmente o cenário.

        values deve conter somente dados explicitamente
        fornecidos pela camada conversacional.
        """

        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        return self.conversation.update(values)

    def replace(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Substitui o cenário atual.

        A confirmação anterior será invalidada pela
        ScenarioSession.
        """

        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        return self.conversation.replace(values)

    # --------------------------------------------------------
    # FLUXO CONVERSACIONAL
    # --------------------------------------------------------

    def next_action(self) -> str:
        """
        Determina a próxima ação do fluxo.

        Possíveis valores:

            collect_missing_fields
            resolve_validation_errors
            confirm
        """

        state = self.conversation_state()

        return state["next_action"]

    def needs_input(self) -> bool:
        """
        Indica se ainda existem campos a coletar.
        """

        return self.next_action() == (
            "collect_missing_fields"
        )

    def needs_confirmation(self) -> bool:
        """
        Indica se o cenário está pronto para confirmação.
        """

        return self.next_action() == "confirm"

    def has_validation_errors(self) -> bool:
        """
        Indica se o cenário possui erros de validação.
        """

        return self.next_action() == (
            "resolve_validation_errors"
        )

    # --------------------------------------------------------
    # CONFIRMAÇÃO
    # --------------------------------------------------------

    def confirm(self) -> dict[str, Any]:
        """
        Confirma explicitamente o cenário.

        A confirmação somente é aceita quando o cenário
        estiver válido e completo.
        """

        return self.conversation.confirm()

    # --------------------------------------------------------
    # GERAÇÃO
    # --------------------------------------------------------

    def generate_toml(self) -> str:
        """
        Gera o TOML somente após confirmação explícita.
        """

        return self.conversation.generate_toml()

    # --------------------------------------------------------
    # PERSISTÊNCIA
    # --------------------------------------------------------

    def save(self) -> Path:
        """
        Persiste o scenario.toml somente após confirmação.
        """

        return self.conversation.save()

    def finalize(self) -> Path:
        """
        Finaliza o cenário.

        Regras:

        1. cenário válido;
        2. cenário completo;
        3. confirmação explícita;
        4. persistência.
        """

        return self.conversation.finalize()

    # --------------------------------------------------------
    # RESUMO PARA A CAMADA CONVERSACIONAL
    # --------------------------------------------------------

    def build_summary(self) -> dict[str, Any]:
        """
        Produz um resumo estruturado para o agente
        conversacional.

        O método não interpreta os parâmetros técnicos.
        Apenas expõe os dados já fornecidos e validados.
        """

        state = self.conversation_state()
        snapshot = self.snapshot()

        return {
            "valid": state["valid"],
            "complete": state["complete"],
            "confirmed": state["confirmed"],
            "missing": list(state["missing"]),
            "errors": list(state["errors"]),
            "scenario": snapshot,
            "project_path": str(self.project_path),
            "scenario_path": str(self.scenario_path),
            "next_action": state["next_action"],
        }

    # --------------------------------------------------------
    # FLUXO DE ALTO NÍVEL
    # --------------------------------------------------------

    def process_update(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Processa uma atualização e retorna o estado
        conversacional resultante.

        Este método é o principal ponto de entrada que
        futuramente poderá ser chamado pelo agente LLM.
        """

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
            result["request"] = {
                "type": "missing_fields",
                "fields": list(state["missing"]),
            }

        elif state["next_action"] == "resolve_validation_errors":
            result["request"] = {
                "type": "validation_errors",
                "errors": list(state["errors"]),
            }

        elif state["next_action"] == "confirm":
            result["request"] = {
                "type": "confirmation",
                "scenario": self.snapshot(),
            }

        return result

    def process_confirmation(
        self,
        confirmed: bool,
    ) -> dict[str, Any]:
        """
        Processa a decisão explícita de confirmação.

        confirmed=True:
            confirma o cenário.

        confirmed=False:
            mantém o cenário não confirmado.
        """

        if not isinstance(confirmed, bool):
            raise TypeError(
                "confirmed must be a boolean"
            )

        if not confirmed:
            return {
                "action": "collect_missing_fields",
                "confirmed": False,
                "complete": self.complete,
                "valid": self.valid,
                "missing": self.missing_fields(),
                "message": (
                    "Scenario remains unconfirmed."
                ),
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
        """
        Finaliza e persiste o cenário.

        Retorna o caminho do scenario.toml.
        """

        path = self.finalize()

        return {
            "action": "completed",
            "valid": True,
            "complete": True,
            "confirmed": True,
            "scenario_path": str(path),
            "project_path": str(self.project_path),
        }

    # --------------------------------------------------------
    # REPRESENTAÇÃO
    # --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "ScenarioAgent("
            f"project={self.project.path!s}, "
            f"valid={self.valid}, "
            f"complete={self.complete}, "
            f"confirmed={self.confirmed}"
            ")"
        )


def create_scenario_agent(
    project_path: str | Path,
) -> ScenarioAgent:
    """
    Cria um ScenarioAgent para um projeto.
    """

    project = PlanningProject(project_path)

    return ScenarioAgent(project)