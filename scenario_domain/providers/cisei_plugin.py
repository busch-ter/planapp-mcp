# scenario_domain/providers/cisei_plugin.py

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..models import (
    DECISION,
    GAP,
    IMPLEMENTED,
    PROPOSAL,
    DomainContext,
    DomainKnowledgeSection,
)

from ..provider import DomainContextProvider


class CISEIPluginDomainContextProvider(DomainContextProvider):
    """
    Provider do knowledge package CISEI Planning Engineering.

    O plugin é tratado como um snapshot de conhecimento.

    Este provider:
      - lê os documentos de references/;
      - preserva a proveniência;
      - preserva o conteúdo original;
      - expõe o conhecimento através de DomainContext;
      - permite carregar somente determinadas seções.

    Este provider NÃO:
      - cria valores de cenário;
      - fornece defaults;
      - altera ScenarioBuilder;
      - valida cenários;
      - executa Planning Service;
      - executa MCP;
      - chama qualquer LLM.
    """

    PROVIDER_ID = "cisei_plugin"
    PROVIDER_VERSION = "0.4.0"
    CONTEXT_VERSION = "1"

    PLUGIN_NAME = "cisei-planning-engineering"
    PLUGIN_SNAPSHOT = "2026-09-24"
    PLUGIN_GUIDANCE_REVIEW = "2026-09-29"

    DOCUMENTS: dict[str, str] = {
        "agent_instructions": "00_AGENT_INSTRUCTIONS.md",
        "current_architecture": "01_CURRENT_ARCHITECTURE.md",
        "workspace_and_sdk": "02_WORKSPACE_AND_SDK.md",
        "scenario_format": "03_SCENARIO_FORMAT.md",
        "service_api_and_results": "04_SERVICE_API_AND_RESULTS.md",
        "assistant_workflow": "05_ASSISTANT_WORKFLOW.md",
        "design_gaps_and_decisions": (
            "06_DESIGN_GAPS_AND_DECISIONS.md"
        ),
        "canonical_cases": "07_CANONICAL_CASES.md",
        "usage_guide": "08_USAGE_GUIDE.md",
        "mcp_interface_requirements": (
            "09_MCP_INTERFACE_REQUIREMENTS.md"
        ),
        "exploration_workflow": (
            "10_EXPLORATION_WORKFLOW.md"
        ),
    }

    DOCUMENT_DESCRIPTIONS: dict[str, str] = {
        "agent_instructions": (
            "Behavior, evidence, authority and explanation rules."
        ),
        "current_architecture": (
            "Implemented architecture, services, ownership and limits."
        ),
        "workspace_and_sdk": (
            "Workspace, projects, SDK lifecycle, cache and revisions."
        ),
        "scenario_format": (
            "Scenario dictionary, TOML, CSV, routing, connectivity "
            "and validation semantics."
        ),
        "service_api_and_results": (
            "Planning API, candidate/metric pipeline, solving, "
            "results and deterministic evaluation."
        ),
        "assistant_workflow": (
            "Target assistant workflow and revision loop."
        ),
        "design_gaps_and_decisions": (
            "Confirmed decisions and unresolved implementation gaps."
        ),
        "canonical_cases": (
            "LTE, Wi-SUN, custom antenna, custom metric and "
            "hybrid-routing examples."
        ),
        "usage_guide": (
            "Current manual SDK workflow."
        ),
        "mcp_interface_requirements": (
            "Proposed MCP boundary, contracts, security and "
            "implementation requirements."
        ),
        "exploration_workflow": (
            "Guided seven-question exploration of CISEI Planning."
        ),
    }

    def __init__(
        self,
        plugin_path: str | Path,
        *,
        strict: bool = True,
    ) -> None:
        self._plugin_path = (
            Path(plugin_path)
            .expanduser()
            .resolve()
        )

        self._references_path = (
            self._plugin_path / "references"
        )

        self._strict = strict

        self._validate_plugin_structure()

    # ---------------------------------------------------------
    # DomainContextProvider
    # ---------------------------------------------------------

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def provider_version(self) -> str:
        return self.PROVIDER_VERSION

    @property
    def context_version(self) -> str:
        return self.CONTEXT_VERSION

    # ---------------------------------------------------------
    # Paths
    # ---------------------------------------------------------

    @property
    def plugin_path(self) -> Path:
        return self._plugin_path

    @property
    def references_path(self) -> Path:
        return self._references_path

    # ---------------------------------------------------------
    # Structure
    # ---------------------------------------------------------

    def _validate_plugin_structure(self) -> None:
        if not self._plugin_path.exists():
            raise FileNotFoundError(
                f"Plugin não encontrado: {self._plugin_path}"
            )

        if not self._plugin_path.is_dir():
            raise NotADirectoryError(
                f"Plugin não é um diretório: {self._plugin_path}"
            )

        if not self._references_path.exists():
            raise FileNotFoundError(
                "Diretório references/ não encontrado: "
                f"{self._references_path}"
            )

        if not self._references_path.is_dir():
            raise NotADirectoryError(
                "references/ não é um diretório: "
                f"{self._references_path}"
            )

    # ---------------------------------------------------------
    # Documents
    # ---------------------------------------------------------

    def available_sections(self) -> tuple[str, ...]:
        return tuple(self.DOCUMENTS.keys())

    def _resolve_document(
        self,
        section: str,
    ) -> Path:
        if section not in self.DOCUMENTS:
            raise KeyError(
                f"Seção CISEI desconhecida: {section!r}"
            )

        return (
            self._references_path
            / self.DOCUMENTS[section]
        )

    def supports_section(
        self,
        section: str,
    ) -> bool:
        if section not in self.DOCUMENTS:
            return False

        path = self._resolve_document(section)

        return path.is_file()

    def _read_document(
        self,
        section: str,
    ) -> str | None:
        path = self._resolve_document(section)

        if not path.exists():
            if self._strict:
                raise FileNotFoundError(
                    f"Documento CISEI ausente: {path}"
                )

            return None

        if not path.is_file():
            if self._strict:
                raise FileNotFoundError(
                    f"Documento CISEI inválido: {path}"
                )

            return None

        return path.read_text(
            encoding="utf-8"
        ).strip()

    # ---------------------------------------------------------
    # Sections
    # ---------------------------------------------------------

    def _build_section(
        self,
        section: str,
    ) -> DomainKnowledgeSection | None:
        content = self._read_document(section)

        if content is None:
            return None

        path = self._resolve_document(section)

        return DomainKnowledgeSection(
            name=section,

            # A classificação aqui representa o papel do
            # documento dentro do knowledge package.
            #
            # O conteúdo original continua preservado.
            classification=(
                self._classification_for(section)
            ),

            content=content,

            source=str(
                path.relative_to(self._plugin_path)
            ),

            description=(
                self.DOCUMENT_DESCRIPTIONS[section]
            ),

            metadata={
                "plugin_name": self.PLUGIN_NAME,
                "plugin_version": self.PROVIDER_VERSION,
                "snapshot": self.PLUGIN_SNAPSHOT,
                "guidance_review": (
                    self.PLUGIN_GUIDANCE_REVIEW
                ),
                "filename": path.name,
                "knowledge_type": (
                    "engineering_reference"
                ),
                "examples_are_not_defaults": True,
                "proposals_are_not_implemented": True,
                "decisions_are_not_implementation": True,
            },
        )

    @staticmethod
    def _classification_for(
        section: str,
    ) -> str:
        """
        Classificação do papel predominante da referência.

        Importante:
        um documento pode conter Implemented,
        Decision, Proposal e Gap simultaneamente.

        Portanto essa classificação NÃO pretende
        classificar cada afirmação do documento.
        """

        classifications = {
            "agent_instructions": IMPLEMENTED,
            "current_architecture": IMPLEMENTED,
            "workspace_and_sdk": IMPLEMENTED,
            "scenario_format": IMPLEMENTED,
            "service_api_and_results": IMPLEMENTED,
            "assistant_workflow": PROPOSAL,
            "design_gaps_and_decisions": DECISION,
            "canonical_cases": IMPLEMENTED,
            "usage_guide": IMPLEMENTED,
            "mcp_interface_requirements": PROPOSAL,
            "exploration_workflow": IMPLEMENTED,
        }

        return classifications[section]

    # ---------------------------------------------------------
    # Context
    # ---------------------------------------------------------

    def get_context(
        self,
        *,
        sections: Sequence[str] | None = None,
    ) -> DomainContext:

        selected = (
            tuple(self.DOCUMENTS.keys())
            if sections is None
            else tuple(sections)
        )

        unknown = [
            section
            for section in selected
            if section not in self.DOCUMENTS
        ]

        if unknown:
            raise KeyError(
                "Seções CISEI desconhecidas: "
                + ", ".join(unknown)
            )

        loaded = []

        for section in selected:
            item = self._build_section(section)

            if item is not None:
                loaded.append(item)

        return DomainContext(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            context_version=self.context_version,
            sections=tuple(loaded),
            metadata={
                "plugin_name": self.PLUGIN_NAME,
                "plugin_version": self.PROVIDER_VERSION,
                "snapshot": self.PLUGIN_SNAPSHOT,
                "guidance_review": (
                    self.PLUGIN_GUIDANCE_REVIEW
                ),
                "section_count": len(loaded),
                "available_section_count": len(
                    self.DOCUMENTS
                ),
                "knowledge_only": True,
                "execution_enabled": False,
                "scenario_defaults_enabled": False,
            },
        )

    # ---------------------------------------------------------
    # Capabilities
    # ---------------------------------------------------------

    def capabilities(self) -> dict[str, bool]:
        return {
            "domain_context": True,
            "section_selection": True,
            "provenance": True,
            "versioning": True,

            "scenario_defaults": False,
            "scenario_mutation": False,
            "scenario_validation": False,
            "planning_execution": False,
            "mcp_execution": False,
            "llm_execution": False,
        }

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def validate_plugin(
        self,
    ) -> dict[str, object]:
        documents: dict[str, dict[str, object]] = {}
        missing: list[str] = []

        for section in self.DOCUMENTS:
            path = self._resolve_document(section)

            exists = path.is_file()

            documents[section] = {
                "filename": path.name,
                "exists": exists,
                "path": str(path),
            }

            if not exists:
                missing.append(section)

        return {
            "valid": not missing,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "context_version": self.context_version,
            "plugin_name": self.PLUGIN_NAME,
            "snapshot": self.PLUGIN_SNAPSHOT,
            "expected_documents": len(self.DOCUMENTS),
            "found_documents": (
                len(self.DOCUMENTS) - len(missing)
            ),
            "missing": missing,
            "documents": documents,
        }


__all__ = [
    "CISEIPluginDomainContextProvider",
]
