
# ============================================================
# SCENARIO AGENT — OPENAI
#
# Adapter OpenAI para o ScenarioAgent.
#
# Responsabilidades:
#   - conversar com o usuário via OpenAI Responses API;
#   - fornecer contexto de domínio ao LLM, quando configurado;
#   - fornecer o estado atual da aplicação;
#   - interpretar a mensagem do usuário em uma ação estruturada;
#   - delegar a execução da ação ao ScenarioAgent.
#
# NÃO é responsabilidade deste módulo:
#   - alterar diretamente o ScenarioBuilder;
#   - escrever scenario.toml;
#   - executar Planning Service;
#   - executar MCP;
#   - executar ferramentas externas;
#   - inventar valores técnicos;
#   - definir defaults técnicos.
#
# O domínio é fornecido através de DomainContextProvider,
# mantendo o agente independente da implementação concreta
# do plugin CISEI.
# ============================================================

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from openai import OpenAI

from cisei_planning_sdk.project import PlanningProject
from scenario_agent import ScenarioAgent
from scenario_domain.provider import DomainContextProvider


DEFAULT_MODEL = "gpt-5.6-luna"

DEFAULT_DOMAIN_CONTEXT_SECTIONS = (
    "scenario_format",
    "assistant_workflow",
    "design_gaps_and_decisions",
)


class ScenarioAgentOpenAIError(RuntimeError):
    """Erro específico do adapter OpenAI do ScenarioAgent."""


class ScenarioAgentOpenAI:
    """
    Adapter OpenAI para o ScenarioAgent.

    O ScenarioAgent continua sendo a autoridade da aplicação.

    O modelo OpenAI:
        - interpreta linguagem natural;
        - identifica valores explicitamente fornecidos pelo usuário;
        - solicita valores ausentes;
        - retorna ações estruturadas.

    O modelo NÃO:
        - executa ferramentas;
        - executa MCP;
        - altera diretamente o cenário;
        - escreve arquivos;
        - executa Planning Service;
        - cria defaults técnicos.
    """

    ALLOWED_ACTIONS = {
        "update_scenario",
        "ask_user",
        "confirm",
        "reject_confirmation",
        "finalize",
    }

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(
        self,
        project: PlanningProject,
        *,
        model: str | None = None,
        client: OpenAI | None = None,
        domain_context_provider: DomainContextProvider | None = None,
        domain_context_sections: tuple[str, ...] | None = None,
    ):
        if not isinstance(project, PlanningProject):
            raise TypeError(
                "project must be an instance of PlanningProject"
            )

        if domain_context_sections is not None:
            if not isinstance(domain_context_sections, tuple):
                raise TypeError(
                    "domain_context_sections must be a tuple[str, ...] or None"
                )

            for section in domain_context_sections:
                if not isinstance(section, str) or not section.strip():
                    raise ValueError(
                        "domain_context_sections must contain "
                        "non-empty strings"
                    )

        self.project = project

        self.model = (
            model
            or os.getenv("SCENARIO_AGENT_OPENAI_MODEL")
            or DEFAULT_MODEL
        )

        self.client = client or OpenAI()

        # ----------------------------------------------------
        # ScenarioAgent subjacente
        # ----------------------------------------------------

        self.scenario_agent = ScenarioAgent(project)

        # ----------------------------------------------------
        # Domain Context
        # ----------------------------------------------------

        self.domain_context_provider = domain_context_provider

        self.domain_context_sections = (
            domain_context_sections
            if domain_context_sections is not None
            else DEFAULT_DOMAIN_CONTEXT_SECTIONS
        )

        # Histórico conversacional do LLM.
        #
        # O contexto de domínio NÃO é armazenado aqui.
        self.messages: list[dict[str, Any]] = []

        # Contexto explícito da última pergunta feita ao usuário.
        self.pending_question: dict[str, Any] | None = None

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def scenario_state(self) -> dict[str, Any]:
        """Retorna o estado conversacional atual do ScenarioAgent."""
        return self.scenario_agent.conversation_state()

    @property
    def scenario(self) -> ScenarioAgent:
        """Retorna o ScenarioAgent subjacente."""
        return self.scenario_agent

    @property
    def project_path(self) -> Path:
        """Retorna o caminho do projeto."""
        return Path(self.project.path)

    @property
    def scenario_path(self) -> Path:
        """Retorna o caminho do scenario.toml."""
        return self.project_path / "scenario.toml"

    # ========================================================
    # EXPLICIT CONFIRMATION GUARD
    # ========================================================

    @staticmethod
    def _normalize_confirmation_text(user_message: str) -> str:
        """
        Normaliza o texto para comparar frases de confirmação.

        Remove diferenças de maiúsculas, acentos e pontuação.
        Não interpreta a intenção por meio do LLM.
        """
        normalized = unicodedata.normalize(
            "NFKD",
            user_message.casefold(),
        )

        normalized = "".join(
            char
            for char in normalized
            if not unicodedata.combining(char)
        )

        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            normalized,
        ).strip()

        return normalized

    @classmethod
    def _is_explicit_confirmation(
        cls,
        user_message: str,
    ) -> bool:
        """
        Retorna True somente para frases explícitas reconhecidas.

        Mensagens ambíguas como "ok", "entendi" e "certo" não
        constituem autorização para confirmar o cenário.

        A comparação exata também impede que frases como
        "não confirmo" sejam aceitas por conterem "confirmo".
        """
        if not isinstance(user_message, str):
            return False

        normalized = cls._normalize_confirmation_text(
            user_message.strip()
        )

        explicit_phrases = {
            # Português
            "confirmo",
            "eu confirmo",
            "confirmo o cenario",
            "eu confirmo o cenario",
            "confirmo este cenario",
            "eu confirmo este cenario",
            "confirmo o cenario atual",
            "eu confirmo o cenario atual",
            "pode confirmar",
            "pode confirmar o cenario",
            "pode prosseguir",
            "pode prosseguir com o cenario",
            "pode finalizar",
            "pode finalizar o cenario",
            "aprovo o cenario",
            "eu aprovo o cenario",

            # Inglês
            "confirm",
            "i confirm",
            "i confirm the scenario",
            "i confirm this scenario",
            "confirm the scenario",
            "confirm this scenario",
            "approve this scenario",
            "i approve this scenario",
            "proceed with this scenario",
            "finalize the scenario",
        }

        return normalized in explicit_phrases

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def _system_prompt(self) -> str:
        """
        Prompt de comportamento do agente.

        As regras operacionais permanecem aqui.
        O plugin/domain context fornece conhecimento técnico,
        mas não substitui estas regras.
        """

        return """
You are the OpenAI conversational adapter for the CISEI Scenario Agent.

Your role is to interpret the user's natural-language request and
return exactly one structured JSON action for the application.

IMPORTANT AUTHORITY RULES
=========================

1. The application state is authoritative for the CURRENT scenario.
2. Explicit values provided by the USER are authoritative for the
   desired scenario.
3. Domain context is reference knowledge only.
4. Never invent technical values.
5. Never create technical defaults.
6. Never convert an example from documentation into a scenario value
   unless the user explicitly provides that value.
7. Never assume values from examples, previous scenarios, engineering
   knowledge, or plugin recommendations.
8. If a required value is missing, ask the user.
9. Do not directly mutate application state.
10. Do not write files.
11. Do not execute Planning Service.
12. Do not execute MCP.
13. Do not call tools.
14. Do not fabricate APIs, fields, endpoints, or functionality.
15. Do not treat proposals or design gaps as implemented functionality.
16. Do not treat MCP interface requirements as available MCP tools.
17. Do not resolve conflicts between documentation and implementation
    by guessing.

SCENARIO VALUES
===============

Only values explicitly provided by the user may be proposed as
scenario values.

If domain context contains LTE frequency 915 MHz and the user says
"create an LTE interface", do not set freq_mhz to 915.
Ask the user for the frequency.

If the user explicitly says "create an LTE interface at 915 MHz",
915 MHz may be included in the proposed update.

The same rule applies to technology, frequency, power, antennas,
heights, azimuth, downtilt, beamwidth, relay capability, routing,
rank, metrics, instances, connectivity, candidate edges, sites,
CSV-related values, and every other technical parameter.

DOMAIN KNOWLEDGE
================

Domain context may contain implemented behavior, decisions, proposals,
gaps, examples, engineering documentation, and workflow descriptions.

These categories must remain distinct.

Examples are not defaults.
Proposals are not implementation.
Design gaps are not functionality.
Documentation is not current application state.
MCP requirements do not imply that MCP tools are available.

APPLICATION STATE
=================

The application context supplied with each request contains the
current ScenarioAgent state and scenario snapshot.

Use it as the source of truth for current values, missing values,
validation, completeness, confirmation state, errors, next action,
and current scenario structure.

Do not reconstruct application state from memory.
Do not assume a field exists merely because it appears in documentation.

CANONICAL SCENARIO CONTRACT
===========================

Use the domain context and current scenario builder contract together.

The canonical contract says antenna model_id, azimuth_deg, downtilt_deg,
beamwidth_deg, and the legacy antenna height_m are not universally
required. Do not ask for them solely because an earlier validation
implementation listed them as required.

Interfaces require tech, freq_mhz, tx_power_dbm, and antenna_id.
Devices require a non-empty interfaces list.

instances.source is required when using the external CSV representation.
instances.format and instances.profile_column are required by the
ScenarioBuilder contract. When using external CSV representation,
explicitly provide all three fields. Never omit them based on SDK defaults.

scenario.working_crs is always required.

The scenario may use external instances or embedded sites.
Preserve net.connectivity and net.candidate_edges when supplied.

Do not add SDK defaults into updates unless the user explicitly asks for
those values to be written into the scenario.

Optional omissions should remain omitted.

Installation mount_height_m belongs to devices/sites;
antenna height_m is a legacy antenna-profile field.

PENDING QUESTION
================

The application context may include pending_question, containing the
prior question and its target fields.

If the user's current message answers that question, map the answer
only to those target fields. Do not apply the answer to unrelated fields.

If the answer is ambiguous, return ask_user for clarification.

When asking for missing information, include a concise question and
a fields array of canonical dotted field paths whenever the targets
are known.

When returning update_scenario, use:
{
  "action": "update_scenario",
  "updates": { ...only the explicitly supplied values... }
}

ACTIONS
======

Return only one of these actions:

1. update_scenario
2. ask_user
3. confirm
4. reject_confirmation
5. finalize

Return valid JSON only.

ACTION MEANINGS
===============

update_scenario
---------------

Use when the user explicitly provides scenario values that can be
applied to the current scenario.

ask_user
--------

Use when required information is missing or clarification is needed.

confirm
-------

Use only when the user explicitly confirms the current proposed scenario.

Examples include:
- "confirm"
- "I confirm"
- "confirm the scenario"
- "confirmo"
- "confirmo o cenário"
- "pode prosseguir"
- "pode finalizar"

Do not infer confirmation from unrelated statements.

The application independently validates explicit confirmation against
the current user message. Returning this action does not grant authority.

reject_confirmation
-------------------

Use when the user explicitly rejects a confirmation request or asks
to modify the scenario instead.

finalize
--------

Use only when:
- the scenario is complete;
- the scenario is valid;
- the user explicitly confirmed it;
- the application indicates that finalization is ready.

Do not finalize merely because the model believes the scenario
looks complete.

JSON CONTRACT
=============

Return exactly one JSON object containing an action.

Do not return Markdown.
Do not return explanations outside JSON.
Do not return multiple actions.

The application will validate and execute the returned action.
""".strip()

    # ========================================================
    # DOMAIN CONTEXT
    # ========================================================

    def _domain_context(self) -> dict[str, Any]:
        """Obtém o contexto de domínio através do provider genérico."""

        provider = self.domain_context_provider

        if provider is None:
            return {}

        try:
            context = provider.get_context(
                sections=self.domain_context_sections
            )
        except Exception as exc:
            raise ScenarioAgentOpenAIError(
                f"Failed to load domain context: {exc}"
            ) from exc

        return context.to_dict()

    def _domain_context_prompt(
        self,
        domain_context: dict[str, Any],
    ) -> str:
        """Converte o DomainContext em uma mensagem de contexto."""

        if not domain_context:
            return """
DOMAIN CONTEXT
==============

No domain context provider is configured.

Do not assume technical values from external knowledge.
Use only explicit user values and the application state.
""".strip()

        serialized = json.dumps(
            domain_context,
            ensure_ascii=False,
            indent=2,
        )

        return f"""
DOMAIN CONTEXT
==============

The following information is engineering/domain reference material.

It is NOT the current scenario state.
It is NOT user-provided scenario data.
It is NOT a source of defaults.
It is NOT permission to execute functionality.
It is NOT permission to call MCP or tools.

Examples are not current values.
Proposals are not implementation.
Design gaps are not functionality.

If domain context conflicts with application state, application state
takes precedence.

If domain context conflicts with an explicit user value, the explicit
user value takes precedence.

If a required scenario value is absent from both the user request and
the current application state, ask the user.

BEGIN DOMAIN CONTEXT
--------------------

{serialized}

------------------
END DOMAIN CONTEXT
""".strip()

    # ========================================================
    # APPLICATION CONTEXT
    # ========================================================

    def _application_context(self) -> dict[str, Any]:
        """Obtém o estado atual da aplicação, sem domain context."""

        return {
            "scenario_state": self.scenario_agent.conversation_state(),
            "scenario_snapshot": self.scenario_agent.snapshot(),
            "pending_question": self.pending_question,
        }

    # ========================================================
    # OPENAI REQUEST
    # ========================================================

    def _request_model(
        self,
        user_message: str,
    ) -> dict[str, Any]:
        """Envia a mensagem ao modelo OpenAI e retorna a ação JSON."""

        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        user_message = user_message.strip()

        if not user_message:
            raise ValueError("user_message cannot be empty")

        application_context = self._application_context()
        domain_context = self._domain_context()

        user_content = (
            "USER MESSAGE\n"
            "============\n\n"
            f"{user_message}\n\n"
            "APPLICATION CONTEXT\n"
            "===================\n\n"
            f"{json.dumps(application_context, ensure_ascii=False, indent=2)}"
        )

        self.messages.append(
            {
                "role": "user",
                "content": user_content,
            }
        )

        input_messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "system",
                "content": self._domain_context_prompt(domain_context),
            },
            *self.messages,
        ]

        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": "medium"},
                input=input_messages,
            )
        except Exception as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenAI request failed: {exc}"
            ) from exc

        output_text = getattr(response, "output_text", None)

        if not output_text:
            raise ScenarioAgentOpenAIError(
                "OpenAI returned an empty response"
            )

        output_text = output_text.strip()

        try:
            action = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenAI returned invalid JSON: {output_text}"
            ) from exc

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "OpenAI response must be a JSON object"
            )

        self.messages.append(
            {
                "role": "assistant",
                "content": output_text,
            }
        )

        return action

    # ========================================================
    # ACTION VALIDATION
    # ========================================================

    def _validate_action(
        self,
        action: dict[str, Any],
    ) -> None:
        """Valida a estrutura mínima da ação retornada pelo LLM."""

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "Model action must be a JSON object"
            )

        action_name = action.get("action")

        if action_name not in self.ALLOWED_ACTIONS:
            raise ScenarioAgentOpenAIError(
                f"Unsupported model action: {action_name!r}"
            )

    # ========================================================
    # ACTION APPLICATION
    # ========================================================

    def _apply_action(
        self,
        action: dict[str, Any],
        user_message: str,
    ) -> dict[str, Any]:
        """
        Delega a ação ao ScenarioAgent.

        A confirmação depende da mensagem atual do usuário,
        nunca apenas da ação solicitada pelo modelo.
        """

        self._validate_action(action)

        action_name = action["action"]

        if action_name == "update_scenario":
            updates = action.get("updates")

            if not isinstance(updates, dict) or not updates:
                raise ScenarioAgentOpenAIError(
                    "update_scenario action requires a non-empty "
                    "'updates' dictionary"
                )

            result = self.scenario_agent.process_update(updates)
            self.pending_question = None
            return result

        if action_name == "ask_user":
            question = action.get("question")

            if not isinstance(question, str) or not question.strip():
                raise ScenarioAgentOpenAIError(
                    "ask_user action requires a non-empty "
                    "'question' string"
                )

            fields = action.get("fields", [])

            if fields is not None and not isinstance(fields, list):
                raise ScenarioAgentOpenAIError(
                    "ask_user 'fields' must be a list when provided"
                )

            self.pending_question = {
                "question": question.strip(),
                "fields": [
                    field
                    for field in (fields or [])
                    if isinstance(field, str)
                ],
            }

            return action

        if action_name == "confirm":
            if not self._is_explicit_confirmation(user_message):
                raise ScenarioAgentOpenAIError(
                    "Confirmação recusada: a mensagem atual do usuário "
                    "não contém uma confirmação explícita do cenário."
                )

            self.pending_question = None

            return self.scenario_agent.process_confirmation(
                confirmed=True
            )

        if action_name == "reject_confirmation":
            self.pending_question = None

            return self.scenario_agent.process_confirmation(
                confirmed=False
            )

        if action_name == "finalize":
            # A autorização do usuário para confirmar e o estado
            # confirmado são condições distintas.
            #
            # A validação final e a persistência continuam sob
            # responsabilidade do ScenarioSession.
            self.pending_question = None

            return self.scenario_agent.process_finalize()

        raise ScenarioAgentOpenAIError(
            f"Unhandled action: {action_name}"
        )

    # ========================================================
    # PUBLIC CHAT API
    # ========================================================

    def chat(
        self,
        user_message: str,
    ) -> dict[str, Any]:
        """Processa uma mensagem do usuário."""

        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        normalized_message = user_message.strip()

        if not normalized_message:
            raise ValueError("user_message cannot be empty")

        action = self._request_model(normalized_message)

        return self._apply_action(
            action,
            normalized_message,
        )


# ============================================================
# FACTORY
# ============================================================

def create_scenario_agent_openai(
    project_path: str | Path,
    *,
    model: str | None = None,
    domain_context_provider: DomainContextProvider | None = None,
    domain_context_sections: tuple[str, ...] | None = None,
) -> ScenarioAgentOpenAI:
    """Cria um ScenarioAgentOpenAI."""

    project = PlanningProject(project_path)

    return ScenarioAgentOpenAI(
        project,
        model=model,
        domain_context_provider=domain_context_provider,
        domain_context_sections=domain_context_sections,
    )


# ============================================================
# EXEMPLO DE USO COM O PLUGIN CISEI
# ============================================================

if __name__ == "__main__":
    from scenario_domain.providers import (
        CISEIPluginDomainContextProvider,
    )

    project_path = Path(
        os.getenv(
            "SCENARIO_PROJECT_PATH",
            ".",
        )
    )

    plugin_path = (
        Path("/home/jovyan/work/planapp-mcp")
        / "cisei-planning-engineering"
    )

    provider = CISEIPluginDomainContextProvider(plugin_path)

    agent = create_scenario_agent_openai(
        project_path,
        domain_context_provider=provider,
    )

    print("ScenarioAgentOpenAI criado com sucesso.")
    print("Domain provider:", provider.provider_id)
    print("Domain version:", provider.provider_version)
    print("Domain sections:", agent.domain_context_sections)
