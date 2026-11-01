# ============================================================
# PLANAPP / VIBEPLANNER AI
#
# SCENARIO DOMAIN CONTEXT
#
# provider.py
#
# Contrato abstrato entre o agente e qualquer fonte externa
# de conhecimento de domínio.
#
# IMPORTANTE:
#
# O agente conhece SOMENTE este contrato.
#
# O agente NÃO deve conhecer:
#   - arquivos internos do plugin;
#   - estrutura do ZIP;
#   - implementação do provider;
#   - OpenAI;
#   - Ollama;
#   - OpenRouter;
#   - MCP;
#   - Planning Service.
#
# Qualquer implementação que cumpra este contrato pode ser
# utilizada pelo agente.
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .models import DomainContext


class DomainContextProvider(ABC):
    """
    Interface abstrata para providers de conhecimento de domínio.

    Um provider pode obter conhecimento de qualquer fonte:

        - plugin local;
        - plugin ZIP;
        - OpenAI Skill;
        - MCP Resource;
        - arquivos;
        - banco de conhecimento;
        - outro mecanismo futuro.

    O agente não precisa saber qual mecanismo está sendo usado.

    O provider é READ-ONLY do ponto de vista do Scenario Agent.

    Ele não deve:
        - modificar ScenarioBuilder;
        - modificar ScenarioAgent;
        - modificar estado da aplicação;
        - criar arquivos de cenário;
        - executar Planning Service;
        - executar MCP;
        - definir parâmetros do cenário atual.
    """

    # ========================================================
    # IDENTIDADE
    # ========================================================

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """
        Identificador estável do provider.

        Exemplo:

            cisei-planning-engineering
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def provider_version(self) -> str:
        """
        Versão da implementação do provider/plugin.
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def context_version(self) -> str:
        """
        Versão do contrato DomainContext fornecido.

        Não representa a versão do plugin.

        Exemplo:

            "1"
        """

        raise NotImplementedError

    # ========================================================
    # CONTEXTO
    # ========================================================

    @abstractmethod
    def get_context(
        self,
        *,
        sections: Sequence[str] | None = None,
    ) -> DomainContext:
        """
        Retorna conhecimento de domínio normalizado.

        Parameters
        ----------
        sections:
            Lista opcional de seções desejadas.

            None:
                provider decide o conjunto padrão.

            Exemplo:

                [
                    "scenario_format",
                    "architecture",
                    "assistant_workflow",
                ]

        Returns
        -------
        DomainContext
            Contexto normalizado e independente do LLM.
        """

        raise NotImplementedError

    # ========================================================
    # CAPABILITIES
    # ========================================================

    def capabilities(self) -> dict[str, bool]:
        """
        Retorna capacidades declaradas pelo provider.

        O método possui implementação padrão deliberadamente
        conservadora.

        Providers podem sobrescrever quando necessário.

        IMPORTANTE:

        capabilities descrevem conhecimento/contexto disponível.

        Elas NÃO autorizam o agente a executar ferramentas.
        """

        return {
            "domain_context": True,
        }

    # ========================================================
    # HELPERS
    # ========================================================

    def get_default_context(self) -> DomainContext:
        """
        Retorna o contexto padrão do provider.

        Método auxiliar para consumidores simples.
        """

        return self.get_context()

    def supports_section(
        self,
        section: str,
    ) -> bool:
        """
        Verifica se uma seção está disponível.

        A implementação padrão consulta o contexto retornado
        pelo provider.

        Providers podem sobrescrever para evitar carregamento
        desnecessário.
        """

        context = self.get_context(
            sections=[section]
        )

        return context.has_section(section)


class NullDomainContextProvider(
    DomainContextProvider
):
    """
    Provider vazio.

    Permite que os agentes funcionem sem plugin/contexto
    de domínio externo.

    Essa classe é importante para compatibilidade com o POC atual.

    Exemplo:

        provider = NullDomainContextProvider()

    ou simplesmente usar:

        NullDomainContextProvider()
    """

    @property
    def provider_id(self) -> str:
        return "none"

    @property
    def provider_version(self) -> str:
        return "0"

    @property
    def context_version(self) -> str:
        return "1"

    def get_context(
        self,
        *,
        sections: Sequence[str] | None = None,
    ) -> DomainContext:
        """
        Retorna um contexto vazio.

        O parâmetro sections é aceito para manter exatamente
        o mesmo contrato dos demais providers.
        """

        return DomainContext.empty(
            context_version=self.context_version
        )
