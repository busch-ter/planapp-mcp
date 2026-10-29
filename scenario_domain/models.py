# ============================================================
# PLANAPP / VIBEPLANNER AI
#
# SCENARIO DOMAIN CONTEXT
#
# models.py
#
# Contrato de dados para conhecimento de domínio consumido
# pelos agentes de IA.
#
# IMPORTANTE:
#
# Este módulo NÃO conhece:
#   - OpenAI
#   - Ollama
#   - OpenRouter
#   - ScenarioAgent
#   - ScenarioBuilder
#   - Planning Service
#   - MCP
#
# Ele representa somente conhecimento de domínio normalizado.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# ============================================================
# CLASSIFICAÇÕES DE CONHECIMENTO
# ============================================================

IMPLEMENTED = "Implemented"
DECISION = "Decision"
PROPOSAL = "Proposal"
GAP = "Gap"


KNOWLEDGE_CLASSIFICATIONS = frozenset(
    {
        IMPLEMENTED,
        DECISION,
        PROPOSAL,
        GAP,
    }
)


# ============================================================
# DOMAIN KNOWLEDGE SECTION
# ============================================================

@dataclass(frozen=True)
class DomainKnowledgeSection:
    """
    Uma seção de conhecimento de domínio fornecida por um plugin.

    A seção é deliberadamente neutra em relação ao LLM.

    Parameters
    ----------
    name:
        Identificador estável da seção.

    classification:
        Classificação da informação:
            Implemented
            Decision
            Proposal
            Gap

    content:
        Conteúdo estruturado da seção.

    source:
        Origem da informação, por exemplo:
        "03_SCENARIO_FORMAT.md"

    description:
        Descrição opcional da finalidade da seção.

    metadata:
        Metadados adicionais, sem semântica imposta pelo núcleo.
    """

    name: str
    classification: str
    content: Mapping[str, Any] | list[Any] | str
    source: str | None = None
    description: str | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(
                "DomainKnowledgeSection.name must be a string"
            )

        if not self.name.strip():
            raise ValueError(
                "DomainKnowledgeSection.name cannot be empty"
            )

        if self.classification not in KNOWLEDGE_CLASSIFICATIONS:
            raise ValueError(
                "Unsupported knowledge classification: "
                f"{self.classification!r}. "
                f"Expected one of: "
                f"{sorted(KNOWLEDGE_CLASSIFICATIONS)}"
            )

        if self.source is not None and not isinstance(
            self.source,
            str,
        ):
            raise TypeError(
                "DomainKnowledgeSection.source must be "
                "a string or None"
            )

        if self.description is not None and not isinstance(
            self.description,
            str,
        ):
            raise TypeError(
                "DomainKnowledgeSection.description must be "
                "a string or None"
            )

        if not isinstance(self.metadata, Mapping):
            raise TypeError(
                "DomainKnowledgeSection.metadata must be "
                "a mapping"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Converte a seção para um dicionário serializável.
        """

        return {
            "name": self.name,
            "classification": self.classification,
            "content": self.content,
            "source": self.source,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


# ============================================================
# DOMAIN CONTEXT
# ============================================================

@dataclass(frozen=True)
class DomainContext:
    """
    Contexto de domínio normalizado fornecido ao agente.

    Este objeto representa conhecimento externo ao estado vivo
    da aplicação.

    IMPORTANTE:

    DomainContext NÃO representa:

        - o cenário atual;
        - valores fornecidos pelo usuário;
        - estado de validação;
        - campos missing;
        - confirmação;
        - execução;
        - arquivos.

    Essas responsabilidades permanecem na aplicação.

    Parameters
    ----------
    provider_id:
        Identificador estável do provider/plugin.

    provider_version:
        Versão da implementação do provider/plugin.

    context_version:
        Versão do contrato do DomainContext.

    sections:
        Seções de conhecimento disponíveis.

    metadata:
        Metadados adicionais do provider.
    """

    provider_id: str
    provider_version: str
    context_version: str
    sections: tuple[DomainKnowledgeSection, ...] = field(
        default_factory=tuple
    )
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str):
            raise TypeError(
                "DomainContext.provider_id must be a string"
            )

        if not self.provider_id.strip():
            raise ValueError(
                "DomainContext.provider_id cannot be empty"
            )

        if not isinstance(self.provider_version, str):
            raise TypeError(
                "DomainContext.provider_version must be a string"
            )

        if not self.provider_version.strip():
            raise ValueError(
                "DomainContext.provider_version cannot be empty"
            )

        if not isinstance(self.context_version, str):
            raise TypeError(
                "DomainContext.context_version must be a string"
            )

        if not self.context_version.strip():
            raise ValueError(
                "DomainContext.context_version cannot be empty"
            )

        if not isinstance(self.sections, tuple):
            raise TypeError(
                "DomainContext.sections must be a tuple"
            )

        for section in self.sections:
            if not isinstance(
                section,
                DomainKnowledgeSection,
            ):
                raise TypeError(
                    "All DomainContext.sections entries must "
                    "be DomainKnowledgeSection instances"
                )

        if not isinstance(self.metadata, Mapping):
            raise TypeError(
                "DomainContext.metadata must be a mapping"
            )

    # --------------------------------------------------------
    # SECTION ACCESS
    # --------------------------------------------------------

    def get_section(
        self,
        name: str,
    ) -> DomainKnowledgeSection | None:
        """
        Retorna uma seção pelo nome.

        Retorna None quando a seção não existe.
        """

        for section in self.sections:
            if section.name == name:
                return section

        return None

    def has_section(
        self,
        name: str,
    ) -> bool:
        """
        Verifica se uma seção está presente.
        """

        return self.get_section(name) is not None

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Converte o contexto para um dicionário.

        O resultado é neutro em relação ao LLM.
        """

        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "context_version": self.context_version,
            "sections": [
                section.to_dict()
                for section in self.sections
            ],
            "metadata": dict(self.metadata),
        }

    # --------------------------------------------------------
    # EMPTY CONTEXT
    # --------------------------------------------------------

    @classmethod
    def empty(
        cls,
        *,
        context_version: str = "1",
    ) -> "DomainContext":
        """
        Cria um contexto vazio.

        Útil para manter o agente funcionando sem plugin.
        """

        return cls(
            provider_id="none",
            provider_version="0",
            context_version=context_version,
            sections=(),
        )
