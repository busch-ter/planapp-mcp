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
        #
        # IMPORTANTE:
        # O POC-07b utiliza self.scenario_agent como objeto
        # interno. A propriedade scenario abaixo expõe esse
        # objeto sem permitir atribuição direta.
        # ----------------------------------------------------

        self.scenario_agent = ScenarioAgent(project)

        # ----------------------------------------------------
        # Domain Context
        #
        # O provider é opcional.
        # O adapter conhece somente a interface genérica
        # DomainContextProvider, nunca a implementação concreta
        # do plugin CISEI.
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
        # Ele é carregado novamente a cada request para garantir
        # que o contexto seja independente do histórico da conversa.
        self.messages: list[dict[str, Any]] = []

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def scenario_state(self) -> dict[str, Any]:
        """
        Retorna o estado conversacional atual do ScenarioAgent.
        """
        return self.scenario_agent.conversation_state()

    @property
    def scenario(self) -> ScenarioAgent:
        """
        Retorna o ScenarioAgent subjacente.
        """
        return self.scenario_agent

    @property
    def project_path(self) -> Path:
        """
        Retorna o caminho do projeto.
        """
        return Path(self.project.path)

    @property
    def scenario_path(self) -> Path:
        """
        Retorna o caminho do scenario.toml.
        """
        return self.project_path / "scenario.toml"

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

7. Never assume values from:
   - canonical examples;
   - documentation examples;
   - previous scenarios;
   - general engineering knowledge;
   - common LTE/Wi-SUN configurations;
   - plugin recommendations.

8. If a required value is missing, ask the user.

9. Do not directly mutate application state.

10. Do not write files.

11. Do not execute Planning Service.

12. Do not execute MCP.

13. Do not call tools.

14. Do not fabricate APIs, fields, endpoints, or functionality.

15. Do not treat proposals or design gaps as implemented functionality.

16. Do not treat MCP interface requirements as available MCP tools.

17. Do not resolve conflicts between documentation and the current
    application implementation by guessing.

EXPLICIT USER VALUES — MANDATORY UPDATE RULE
=============================================

This rule has priority when choosing between update_scenario
and ask_user.

If the current USER MESSAGE contains one or more explicit scenario
values, you MUST return "update_scenario".

This remains true even when the scenario is incomplete and other
required values are still missing.

An incomplete scenario is NOT a reason to discard explicit values
provided by the user.

The correct behavior is:

    explicit user values
        -> update_scenario
        -> application applies the values
        -> application validates the scenario
        -> remaining missing values are reported

Do NOT return only "ask_user" when the user has already supplied
one or more valid scenario values.

Examples:

User:
    "Crie uma interface LTE em 915 MHz."

Correct:

    {
        "action": "update_scenario",
        "updates": {
            "interfaces": {
                "lte": {
                    "tech": "LTE",
                    "freq_mhz": 915
                }
            }
        }
    }

Even if tx_power_dbm, antenna_id, devices, metrics, CRS, or CSV
information is still missing.

The missing values must be requested by the APPLICATION after the
update is applied.

Another example:

User:
    "A potência de transmissão é 43 dBm."

Correct:

    {
        "action": "update_scenario",
        "updates": {
            "interfaces": {
                "lte": {
                    "tx_power_dbm": 43
                }
            }
        }
    }

Do not return "ask_user" merely because other required fields are
missing.

Another example:

User:
    "Use a antena antena_lte_01 com altura de 7 metros e ganho de
    17 dBi."

Correct:

    {
        "action": "update_scenario",
        "updates": {
            "antennas": {
                "antena_lte_01": {
                    "height_m": 7,
                    "gain_dbi": 17
                }
            }
        }
    }

Only the explicitly supplied values may be included.

Do not invent kind, model_id, azimuth, downtilt, beamwidth, or any
other antenna value.

If a user message contains multiple explicit values, include all
explicitly supplied values in the same update_scenario action when
they can be represented by the current scenario schema.

INCREMENTAL CONVERSATION
========================

Treat each user message as an incremental update to the current
application state.

If a value was explicitly provided in an earlier user message and
is already present in APPLICATION CONTEXT, do not invent or replace
it.

If the current user message provides a NEW explicit value, update
only the values explicitly supplied by that message.

Do not erase existing values.

Do not replace existing values with documentation values.

Do not repeat unrelated technical values merely because they are
present in the domain context.

If the user explicitly changes a previously supplied value, the
new explicit user value takes precedence and may replace the
existing value.

EXPLICIT TECHNICAL VALUES — NO INFERENCE
=========================================

Every technical value, identifier, association, key, target, or
relationship introduced into "updates" must be explicitly stated by
the user in the CURRENT USER MESSAGE, unless it is already being
preserved unchanged from an existing scenario value.

The current application state may be used to understand what
already exists, what is missing, and what is valid, but it MUST NOT
be used to infer a NEW technical value.

In particular, do NOT infer:

- a technology from a metric;
- an interface from a metric;
- a metric target from an existing interface;
- an antenna from an interface;
- an interface from an antenna;
- a device from an interface;
- a site from an antenna;
- an identifier from a naming convention;
- an association merely because it is technically plausible;
- a relationship merely because only one compatible object currently
  exists.

The existence of an object in APPLICATION CONTEXT does not mean that
the user selected that object in the current message.

Example:

Current application state:

    interfaces:
        lte:
            tech: LTE

User:

    "Quero avaliar a métrica RSRP."

The user explicitly supplied:

    RSRP

The user did NOT explicitly supply:

    LTE

Therefore the model MUST NOT produce:

    {
        "action": "update_scenario",
        "updates": {
            "metrics": {
                "LTE": {
                    "spec": "RSRP"
                }
            }
        }
    }

If the application schema requires a metric target and the target
was not explicitly provided, the model MUST ask the user to specify
that target.

For example:

    {
        "action": "ask_user",
        "questions": [
            "Para qual interface ou tecnologia a métrica RSRP deve ser avaliada?"
        ]
    }

Only if the user explicitly says:

    "Quero avaliar RSRP para a interface LTE."

may the model introduce:

    LTE

into the update.

The same principle applies to every technical association.

For example, if the application contains:

    antennas:
        antena_lte_01: ...

and the user says:

    "A interface LTE deve usar uma antena."

do NOT automatically choose:

    antena_lte_01

The user must explicitly identify the antenna if the association is
required by the application.

Likewise, if the application contains:

    interfaces:
        lte: ...

and the user says:

    "Crie um dispositivo."

do NOT automatically assign the LTE interface to that device unless
the user explicitly requests that association.

Existing application state is context, not permission to create new
technical values.

PARTIAL UPDATES
===============

update_scenario does NOT mean that the entire scenario must be
complete.

It is valid and expected to return an update containing only a
subset of scenario fields.

For example:

    "Crie uma interface LTE."

contains the technology but no explicit frequency, power, or
antenna information.

Therefore the model must NOT invent those missing values.

However, because "LTE" itself is an explicit user-provided value,
the model should preserve it in an update_scenario action when it
can be represented by the current application schema.

A subsequent application validation step may then report the
remaining missing fields.

ASK_USER RULE
=============

Use "ask_user" when required information is missing or clarification
is needed AND the current user message does not contain a new
scenario value that must be persisted.

If the current user message contains an explicit scenario value but
also requires an additional missing value to complete its meaning,
do not invent the missing value.

In that case, preserve only the explicit value if it can be
represented independently. If it cannot be represented without
introducing an additional technical value, ask the user for the
missing value instead.

Do NOT use an "ask_user" action as a container for scenario updates.

For example:

    "Quero avaliar a métrica RSRP."

contains the explicit metric value:

    RSRP

but does not explicitly identify a target interface or technology.

If the current application schema requires that target, do not infer
it from APPLICATION CONTEXT. Ask the user to provide the target.

If an explicit value can be persisted independently, it must still
be preserved through "update_scenario".

For example:

    "Use 915 MHz. O que ainda falta?"

must preserve 915 MHz through "update_scenario".

Do not use "ask_user" to discard the explicit 915 MHz value.

SCENARIO VALUES
===============

Only values explicitly provided by the user in the CURRENT USER
MESSAGE may be introduced as NEW scenario values.

Do not introduce additional technical values, identifiers,
associations, keys, targets, or relationships merely because they
are required by the application schema.

If an explicit user value cannot be represented without another
missing technical value, ask the user for that missing value.

For example:

If the domain context contains:

    LTE frequency: 915 MHz

and the user says:

    "create an LTE interface"

you MUST NOT set:

    freq_mhz = 915

However, "LTE" itself was explicitly provided and may be represented
as the technology value if the current application schema supports it.

If the user explicitly says:

    "create an LTE interface at 915 MHz"

then both LTE and 915 MHz may be included in the proposed update.

The same rule applies to:

- technology;
- frequency;
- transmit power;
- antenna model;
- antenna height;
- azimuth;
- downtilt;
- beamwidth;
- relay capability;
- routing;
- rank;
- metrics;
- instances;
- connectivity;
- candidate edges;
- sites;
- CSV-related values;
- any other technical parameter.

Never infer a value merely because another value makes it likely.

For example:

    "LTE"

does not imply:

    915 MHz

and:

    "antenna_lte_01"

does not imply:

    17 dBi

DOMAIN KNOWLEDGE
================

Domain context may contain:

- implemented behavior;
- decisions;
- proposals;
- gaps;
- examples;
- engineering documentation;
- architecture descriptions;
- workflow descriptions.

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

Use it as the source of truth for:

- current values;
- missing values;
- validation;
- completeness;
- confirmation state;
- errors;
- next action;
- current scenario structure.

Do not reconstruct application state from memory.

Do not assume that a field exists merely because it appears in
domain documentation.

ANTENNAS
========

When discussing antenna configuration, respect the fields actually
present in the current application.

Potential fields include:

- kind
- model_id
- description
- height_m
- azimuth_deg
- downtilt_deg
- beamwidth_deg

Do not move or reinterpret fields based only on domain documentation.

If the current application requires a field, respect the current
application behavior.

A known documentation/design conflict must not be silently resolved.

ACTIONS
=======

You may return ONLY one of the following actions:

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

Use when the user explicitly provides one or more scenario values
that can be represented by the current application schema.

This action is valid even when the scenario remains incomplete.

The "updates" object must contain only values explicitly supplied
by the user in the current user message.

Do not include technical defaults.

Do not include values copied from domain examples.

Do not include values merely because they are common engineering
choices.

Do not introduce technical identifiers, associations, targets, or
relationships from APPLICATION CONTEXT unless the user explicitly
provides them in the current user message.

ask_user
--------

Use when required information is missing or clarification is needed
AND the current user message contains no new scenario value that
needs to be persisted.

If the user has provided an explicit value but another value required
to interpret or associate it is missing, do not invent that missing
value.

If the explicit value can be persisted independently, use
update_scenario for that explicit value.

Do not use ask_user to discard explicit user values.

Do not put "updates" inside an ask_user action.

confirm
-------

Use only when the user explicitly confirms the current proposed
scenario.

Examples:

- "yes"
- "confirm"
- "I confirm"
- "pode prosseguir"
- "pode finalizar"

Do not infer confirmation from unrelated statements.

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

Return exactly one JSON object.

For update_scenario:

    {
        "action": "update_scenario",
        "updates": {
            ...
        }
    }

For ask_user:

    {
        "action": "ask_user",
        "questions": [
            "..."
        ]
    }

For confirm:

    {
        "action": "confirm"
    }

For reject_confirmation:

    {
        "action": "reject_confirmation"
    }

For finalize:

    {
        "action": "finalize"
    }

Do not return Markdown.

Do not return explanations outside JSON.

Do not return multiple actions.

Do not put application validation questions inside update_scenario.

Do not put scenario updates inside ask_user.

The application will validate and execute the returned action.
""".strip()

    # ========================================================
    # DOMAIN CONTEXT
    # ========================================================

    def _domain_context(self) -> dict[str, Any]:
        """
        Obtém o contexto de domínio através do provider genérico.

        O ScenarioAgentOpenAI não conhece a implementação concreta
        do plugin CISEI.
        """

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
        """
        Converte o DomainContext em uma mensagem de contexto para o LLM.

        O contexto de domínio é deliberadamente separado do
        application context.
        """

        if not domain_context:
            return """
DOMAIN CONTEXT
==============

No domain context provider is configured.

Therefore, do not assume technical values from external knowledge.
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

It is NOT permission to call MCP.

It is NOT permission to call tools.

Examples are not current values.

Proposals are not implementation.

Design gaps are not functionality.

If domain context conflicts with the application state, the
application state takes precedence.

If domain context conflicts with an explicit user value, the
explicit user value takes precedence.

If a required scenario value is absent from both the user request
and the current application state, ask the user.

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
        """
        Obtém o estado atual da aplicação.

        Este método não incorpora domain context.
        """

        return {
            "scenario_state": self.scenario_agent.conversation_state(),
            "scenario_snapshot": self.scenario_agent.snapshot(),
        }

    # ========================================================
    # OPENAI REQUEST
    # ========================================================

    def _request_model(
        self,
        user_message: str,
    ) -> dict[str, Any]:
        """
        Envia a mensagem para o modelo OpenAI e retorna a ação JSON.
        """

        if not isinstance(user_message, str):
            raise TypeError(
                "user_message must be a string"
            )

        user_message = user_message.strip()

        if not user_message:
            raise ValueError(
                "user_message cannot be empty"
            )

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

        # Mantém o comportamento conversacional existente.
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
                "content": self._domain_context_prompt(
                    domain_context
                ),
            },
            *self.messages,
        ]

        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={
                    "effort": "medium",
                },
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
                "OpenAI returned invalid JSON: "
                f"{output_text}"
            ) from exc

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "OpenAI response must be a JSON object"
            )

        # Guarda a resposta do modelo no histórico.
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
        """
        Valida minimamente a estrutura da ação retornada pelo LLM.

        A validação semântica permanece sob responsabilidade do
        ScenarioAgent/ScenarioBuilder.

        Esta validação também protege o contrato entre o LLM e a
        aplicação, evitando que ask_user seja utilizado para
        transportar atualizações de cenário.
        """

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "Model action must be a JSON object"
            )

        action_name = action.get("action")

        if action_name not in self.ALLOWED_ACTIONS:
            raise ScenarioAgentOpenAIError(
                f"Unsupported model action: {action_name!r}"
            )

        if action_name == "update_scenario":
            if "updates" not in action:
                raise ScenarioAgentOpenAIError(
                    "update_scenario action must contain 'updates'"
                )

            if not isinstance(action["updates"], dict):
                raise ScenarioAgentOpenAIError(
                    "update_scenario 'updates' must be a JSON object"
                )

        if action_name == "ask_user":
            if "updates" in action:
                raise ScenarioAgentOpenAIError(
                    "ask_user action must not contain 'updates'"
                )

            questions = action.get("questions")

            if questions is not None and not isinstance(
                questions,
                list,
            ):
                raise ScenarioAgentOpenAIError(
                    "ask_user 'questions' must be a list"
                )

    # ========================================================
    # ACTION APPLICATION
    # ========================================================

    def _apply_action(
        self,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Delega a ação ao ScenarioAgent.

        Este adapter não modifica diretamente o ScenarioBuilder.
        """

        self._validate_action(action)

        action_name = action["action"]

        if action_name == "update_scenario":
            return self.scenario_agent.process_update(action["updates"])

        if action_name == "ask_user":
            return action

        if action_name == "confirm":
            return self.scenario_agent.process_confirmation(
                confirmed=True
            )

        if action_name == "reject_confirmation":
            return self.scenario_agent.process_confirmation(
                confirmed=False
            )

        if action_name == "finalize":
            return self.scenario_agent.process_finalize()

        # Proteção adicional.
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
        """
        Processa uma mensagem do usuário.

        Fluxo:

            usuário
                |
                v
            OpenAI
                |
                v
            JSON action
                |
                v
            ScenarioAgent
                |
                v
            resultado da aplicação
        """

        action = self._request_model(
            user_message
        )

        return self._apply_action(
            action
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
    """
    Cria um ScenarioAgentOpenAI.

    O provider de domínio é opcional.

    Quando não informado, o agente funciona normalmente sem
    contexto adicional de domínio.
    """

    project = PlanningProject(
        project_path
    )

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

    provider = CISEIPluginDomainContextProvider(
        plugin_path
    )

    agent = create_scenario_agent_openai(
        project_path,
        domain_context_provider=provider,
    )

    print(
        "ScenarioAgentOpenAI criado com sucesso."
    )

    print(
        "Domain provider:",
        provider.provider_id,
    )

    print(
        "Domain version:",
        provider.provider_version,
    )

    print(
        "Domain sections:",
        agent.domain_context_sections,
    )