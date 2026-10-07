# ============================================================
# PLANAPP / VIBEPLANNER AI
#
# SCENARIO CONVERSATION
#
# Camada de conversação entre o agente/Notebook e a
# ScenarioSession.
#
# Arquitetura:
#
#     LLM / Notebook
#          |
#          v
#     ScenarioConversation
#          |
#          v
#     ScenarioSession
#          |
#          +--> ScenarioBuilder
#          |
#          +--> PlanningProject
#          |
#          v
#     scenario.toml
#
# IMPORTANTE:
#
# - Este módulo NÃO conhece OpenAI.
# - Este módulo NÃO conhece MCP.
# - Este módulo NÃO executa Planning Service.
# - Este módulo NÃO define defaults técnicos.
# - Este módulo NÃO inventa parâmetros.
#
# O LLM deve fornecer dados estruturados.
# A ScenarioSession continua sendo responsável pela
# validação, confirmação e persistência.
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject

from scenario_session import ScenarioSession


# ============================================================
# EXCEÇÕES
# ============================================================


class ScenarioConversationError(RuntimeError):
    """Erro relacionado ao fluxo conversacional do cenário."""


class ScenarioNotReadyError(ScenarioConversationError):
    """Tentativa de finalizar um cenário ainda incompleto."""


class ScenarioConfirmationRequiredError(ScenarioConversationError):
    """Tentativa de persistir um cenário sem confirmação."""


# ============================================================
# SCENARIO CONVERSATION
# ============================================================


class ScenarioConversation:
    """
    Controlador de uma conversa de construção de cenário.

    A classe recebe dados estruturados provenientes da camada
    conversacional e os encaminha para ScenarioSession.

    Exemplo:

        conversation = ScenarioConversation(project)

        conversation.update({
            "scenario": {
                "working_crs": "EPSG:31982"
            }
        })

        conversation.update({
            "antennas": {
                ...
            }
        })

        if conversation.is_complete():
            conversation.confirm()
            conversation.save()

    O agente conversacional não precisa conhecer os detalhes
    internos de ScenarioBuilder.
    """

    # ========================================================
    # CONSTRUTOR
    # ========================================================

    def __init__(
        self,
        project: PlanningProject,
        *,
        session: ScenarioSession | None = None,
    ):
        """
        Cria uma nova conversa de construção de cenário.

        Parameters
        ----------
        project:
            PlanningProject associado ao cenário.

        session:
            ScenarioSession opcional já existente.

            Se não for fornecida, uma nova sessão será criada.
        """

        if not isinstance(project, PlanningProject):
            raise TypeError(
                "project must be an instance of PlanningProject"
            )

        self.project = project

        self.session = (
            session
            if session is not None
            else ScenarioSession(project)
        )

    # ========================================================
    # PROPRIEDADES
    # ========================================================

    @property
    def project_path(self) -> Path:
        """Retorna o diretório do projeto."""

        return self.project.path

    @property
    def scenario_path(self) -> Path:
        """Retorna o caminho do scenario.toml."""

        return self.project.scenario_path

    @property
    def confirmed(self) -> bool:
        """Indica se o cenário foi explicitamente confirmado."""

        return self.session.confirmed

    @property
    def valid(self) -> bool:
        """Indica se o cenário atual é válido."""

        return self.session.valid

    @property
    def complete(self) -> bool:
        """Indica se todos os campos obrigatórios foram preenchidos."""

        return self.session.complete

    # ========================================================
    # ESTADO
    # ========================================================

    def status(self) -> dict[str, Any]:
        """
        Retorna o estado atual da conversa.

        O resultado é adequado para ser consumido pelo agente
        conversacional ou pelo notebook.
        """

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

    # ========================================================
    # CAMPOS FALTANTES
    # ========================================================

    def missing_fields(self) -> list[str]:
        """
        Retorna os campos obrigatórios ainda ausentes.
        """

        return list(
            self.session.missing_fields()
        )

    # ========================================================
    # ATUALIZAÇÃO
    # ========================================================

    def update(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Atualiza o cenário com informações fornecidas pela
        camada conversacional.

        Parameters
        ----------
        values:
            Dicionário declarativo contendo as informações
            fornecidas pelo usuário.

        Returns
        -------
        dict
            Estado atualizado da conversa.

        Exemplo:

            conversation.update({
                "scenario": {
                    "working_crs": "EPSG:31982"
                }
            })
        """

        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        validation = self.session.update(values)

        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    # ========================================================
    # REPLACE
    # ========================================================

    def replace(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Substitui o conteúdo do cenário.

        Diferentemente de update(), replace() representa uma
        nova especificação completa do cenário.

        A confirmação anterior é invalidada pela
        ScenarioSession.
        """

        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        validation = self.session.replace(values)

        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        """
        Retorna a especificação atual do cenário.
        """

        return self.session.to_dict()

    # ========================================================
    # VALIDAÇÃO
    # ========================================================

    def validate(self):
        """
        Executa a validação atual da ScenarioSession.
        """

        return self.session.validate()

    # ========================================================
    # COMPLETUDE
    # ========================================================

    def is_complete(self) -> bool:
        """
        Indica se o cenário está completo e válido.
        """

        return self.session.complete

    # ========================================================
    # CONFIRMAÇÃO
    # ========================================================

    def confirm(self) -> dict[str, Any]:
        """
        Confirma explicitamente o cenário.

        A confirmação somente será aceita quando o cenário
        estiver completo e válido.
        """

        validation = self.session.confirm()

        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "confirmed": self.session.confirmed,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
        }

    # ========================================================
    # GERAÇÃO
    # ========================================================

    def generate_toml(self) -> str:
        """
        Gera o TOML do cenário.

        A ScenarioSession exige confirmação explícita antes
        da geração.
        """

        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError(
                "Scenario must be explicitly confirmed "
                "before generating TOML."
            )

        return self.session.generate_toml()

    # ========================================================
    # SAVE
    # ========================================================

    def save(self) -> Path:
        """
        Persiste o scenario.toml no PlanningProject.

        A ScenarioSession exige confirmação explícita.
        """

        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError(
                "Scenario must be explicitly confirmed "
                "before saving the project."
            )

        return self.session.save()

    # ========================================================
    # FINALIZAÇÃO
    # ========================================================

    def finalize(self) -> Path:
        """
        Finaliza a conversa e salva o cenário.

        Requisitos:

        1. cenário válido;
        2. cenário completo;
        3. confirmação explícita.

        Returns
        -------
        Path
            Caminho do scenario.toml salvo.
        """

        validation = self.session.validate()

        if not validation.valid:
            raise ScenarioNotReadyError(
                "Scenario is not valid: "
                + "; ".join(validation.errors)
            )

        if not validation.complete:
            raise ScenarioNotReadyError(
                "Scenario is incomplete. Missing fields: "
                + ", ".join(validation.missing)
            )

        if not self.session.confirmed:
            raise ScenarioConfirmationRequiredError(
                "Scenario must be explicitly confirmed "
                "before finalization."
            )

        return self.session.save()

    # ========================================================
    # RESPOSTA PARA O AGENTE
    # ========================================================

    def conversation_state(self) -> dict[str, Any]:
        """
        Retorna um estado compacto destinado ao agente
        conversacional.

        Esse método evita que o agente precise conhecer
        diretamente a implementação de ScenarioSession.

        Máquina de estados:

            incomplete + missing
                -> collect_missing_fields

            invalid + sem missing
                -> resolve_validation_errors

            complete + valid + not confirmed
                -> confirm

            complete + valid + confirmed
                -> finalize
        """

        status = self.status()

        state = {
            "valid": status["valid"],
            "complete": status["complete"],
            "confirmed": status["confirmed"],
            "missing": status["missing"],
            "errors": status["errors"],
        }

        # ----------------------------------------------------
        # CENÁRIO COMPLETO, VÁLIDO E JÁ CONFIRMADO
        # ----------------------------------------------------
        #
        # Este teste precisa vir ANTES de:
        #
        #     complete + valid -> confirm
        #
        # caso contrário um cenário confirmado continuará
        # incorretamente apresentando next_action="confirm".
        #
        if (
            status["complete"]
            and status["valid"]
            and status["confirmed"]
        ):
            state["next_action"] = "finalize"

        # ----------------------------------------------------
        # CENÁRIO COMPLETO E VÁLIDO, MAS AINDA NÃO CONFIRMADO
        # ----------------------------------------------------
        elif status["complete"] and status["valid"]:
            state["next_action"] = "confirm"

        # ----------------------------------------------------
        # CAMPOS OBRIGATÓRIOS AUSENTES
        # ----------------------------------------------------
        elif status["missing"]:
            state["next_action"] = "collect_missing_fields"

        # ----------------------------------------------------
        # ERROS DE VALIDAÇÃO
        # ----------------------------------------------------
        else:
            state["next_action"] = "resolve_validation_errors"

        return state

    # ========================================================
    # REPRESENTAÇÃO
    # ========================================================

    def __repr__(self) -> str:
        return (
            "ScenarioConversation("
            f"project={self.project.path!s}, "
            f"valid={self.valid}, "
            f"complete={self.complete}, "
            f"confirmed={self.confirmed}"
            ")"
        )


# ============================================================
# FACTORY
# ============================================================


def create_scenario_conversation(
    project_path: str | Path,
) -> ScenarioConversation:
    """
    Cria uma ScenarioConversation a partir do caminho de um
    projeto.

    Essa função é útil para o Notebook e, posteriormente,
    para o agente.
    """

    project = PlanningProject(project_path)

    return ScenarioConversation(project)