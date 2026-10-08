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
#   - delegar a execução da ação ao ScenarioAgent;
#   - encaminhar intenções de planejamento ao PlannerOrchestrator.
#
# NÃO é responsabilidade deste módulo:
#   - alterar diretamente o ScenarioBuilder;
#   - escrever scenario.toml;
#   - executar Planning Service diretamente;
#   - executar MCP diretamente;
#   - executar ferramentas externas diretamente;
#   - inventar valores técnicos;
#   - definir defaults técnicos do cenário.
#
# O domínio é fornecido através de DomainContextProvider,
# mantendo o agente independente da implementação concreta
# do plugin CISEI.
# ============================================================

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

from openai import OpenAI

from cisei_planning_sdk.project import PlanningProject
from scenario_agent import ScenarioAgent
from scenario_domain.provider import DomainContextProvider
from planner_orchestrator import (
    PlannerOrchestrator,
    PlannerOrchestratorError,
)


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

    Para planejamento:

        LLM
         |
         v
        planning_run
         |
         v
        aplicação
         |
         v
        PlannerOrchestrator
         |
         v
        MCP
    """

    ALLOWED_ACTIONS = {
        "update_scenario",
        "ask_user",
        "confirm",
        "reject_confirmation",
        "finalize",
        "planning_run",
    }

    def __init__(
        self,
        project: PlanningProject,
        *,
        model: str | None = None,
        client: OpenAI | None = None,
        domain_context_provider: DomainContextProvider | None = None,
        domain_context_sections: tuple[str, ...] | None = None,
        planner_orchestrator: PlannerOrchestrator | None = None,
    ):

        if not isinstance(
            project,
            PlanningProject,
        ):
            raise TypeError(
                "project must be an instance of PlanningProject"
            )

        if domain_context_sections is not None:

            if not isinstance(
                domain_context_sections,
                tuple,
            ):
                raise TypeError(
                    "domain_context_sections must be "
                    "a tuple[str, ...] or None"
                )

            for section in domain_context_sections:

                if (
                    not isinstance(
                        section,
                        str,
                    )
                    or not section.strip()
                ):

                    raise ValueError(
                        "domain_context_sections must contain "
                        "non-empty strings"
                    )

        self.project = project

        self.model = (
            model
            or os.getenv(
                "SCENARIO_AGENT_OPENAI_MODEL"
            )
            or DEFAULT_MODEL
        )

        self.client = (
            client
            or OpenAI()
        )

        # ----------------------------------------------------
        # ScenarioAgent subjacente
        #
        # O ScenarioAgent continua sendo a autoridade para
        # construção/validação/finalização do cenário.
        # ----------------------------------------------------

        self.scenario_agent = ScenarioAgent(
            project
        )

        # ----------------------------------------------------
        # Planner
        #
        # A aplicação controla o PlannerOrchestrator.
        #
        # O LLM não recebe acesso ao objeto nem ao MCP.
        # ----------------------------------------------------

        self.planner_orchestrator = (
            planner_orchestrator
            if planner_orchestrator is not None
            else PlannerOrchestrator()
        )

        # ----------------------------------------------------
        # Domain Context
        # ----------------------------------------------------

        self.domain_context_provider = (
            domain_context_provider
        )

        self.domain_context_sections = (
            domain_context_sections
            if domain_context_sections is not None
            else DEFAULT_DOMAIN_CONTEXT_SECTIONS
        )

        # ----------------------------------------------------
        # Histórico conversacional do LLM.
        #
        # O contexto de domínio NÃO é armazenado aqui.
        # ----------------------------------------------------

        self.messages: list[
            dict[str, Any]
        ] = []

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def scenario_state(self) -> dict[str, Any]:

        return (
            self.scenario_agent
            .conversation_state()
        )

    @property
    def scenario(self) -> ScenarioAgent:

        return self.scenario_agent

    @property
    def project_path(self) -> Path:

        return Path(
            self.project.path
        )

    @property
    def scenario_path(self) -> Path:

        return (
            self.project_path
            / "scenario.toml"
        )

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def _system_prompt(self) -> str:

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

5. Never create technical defaults for scenario construction.

6. Never convert an example from documentation into a scenario value
   unless the user explicitly provides that value.

7. Never assume values from:
   - canonical examples;
   - documentation examples;
   - previous scenarios;
   - general engineering knowledge;
   - common LTE/Wi-SUN configurations;
   - plugin recommendations.

8. If a required scenario value is missing, ask the user.

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

If the current USER MESSAGE contains one or more explicit scenario
values, you MUST return "update_scenario".

This remains true even when the scenario is incomplete.

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

Only explicitly supplied values may be included.

Do not invent tx_power_dbm, antenna_id, devices, metrics,
CRS, CSV information, or other technical values.

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

Do not invent kind, model_id, azimuth, downtilt, beamwidth, or
other antenna values.

INCREMENTAL CONVERSATION
========================

Treat each user message as an incremental update to the current
application state.

If a value was explicitly provided earlier and is already present
in APPLICATION CONTEXT, do not invent or replace it.

If the current user message provides a NEW explicit value, update
only the values explicitly supplied by that message.

Do not erase existing values.

Do not replace existing values with documentation values.

If the user explicitly changes a previously supplied value, the new
explicit user value takes precedence.

EXPLICIT TECHNICAL VALUES — NO INFERENCE
=========================================

Every technical value, identifier, association, key, target, or
relationship introduced into "updates" must be explicitly stated
by the user in the CURRENT USER MESSAGE, unless it is already being
preserved unchanged from an existing scenario value.

The current application state may be used to understand what
already exists, what is missing, and what is valid, but it MUST NOT
be used to infer a NEW technical value.

Do NOT infer:

- technology from a metric;
- interface from a metric;
- metric target from an interface;
- antenna from an interface;
- interface from an antenna;
- device from an interface;
- site from an antenna;
- identifier from naming conventions;
- associations merely because they are technically plausible.

Existing application state is context, not permission to create
new technical values.

PARTIAL UPDATES
===============

update_scenario does NOT mean that the entire scenario must be
complete.

It is valid to return only a subset of scenario fields.

The application validation step reports remaining missing fields.

ASK_USER RULE
=============

Use "ask_user" when required information is missing or clarification
is needed AND the current user message does not contain a new
scenario value that must be persisted.

If the user message contains an explicit scenario value, preserve
that value through update_scenario whenever it can be represented
independently.

Do not invent missing values.

Do not use ask_user to discard explicit user values.

SCENARIO VALUES
===============

Only values explicitly provided by the user in the CURRENT USER
MESSAGE may be introduced as NEW scenario values.

Do not introduce additional technical values, identifiers,
associations, keys, targets, or relationships merely because they
are required by the application schema.

DOMAIN KNOWLEDGE
================

Domain context may contain:

- implemented behavior;
- decisions;
- proposals;
- gaps;
- examples;
- engineering documentation;
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

Respect the fields actually present in the current application.

Potential fields include:

- kind
- model_id
- description
- height_m
- azimuth_deg
- downtilt_deg
- beamwidth_deg

Do not silently move or reinterpret fields based only on domain
documentation.

A known documentation/design conflict must not be silently resolved.

PLANNING
========

There are two distinct operations:

1. BUILD OR MODIFY A SCENARIO
2. EXECUTE PLANNING FOR AN EXISTING SCENARIO

These operations MUST NOT be confused.

If the user asks to execute, run, calculate, perform, or start the
planning of an EXISTING scenario, this is a planning intent.

In that case:

- do NOT convert the request into update_scenario;
- do NOT ask again for the technical values already contained in
  the scenario;
- do NOT recreate the scenario;
- do NOT ask for CRS, antennas, interfaces, devices, metrics, or
  instances merely because those values belong to the existing
  scenario;
- do NOT execute MCP;
- do NOT execute Planning Service;
- return a "planning_run" action.

The application will execute the planning action.

Example:

User:
    "Quero executar o planejamento LTE do cenário curitiba_lte."

Correct:

{
    "action": "planning_run",
    "request": {
        "scenario_id": "curitiba_lte",
        "planner": "cell",
        "rank_threshold": 10,
        "primary_tech": "lte",
        "solution_kind": "graph"
    }
}

The scenario technical parameters are NOT copied into this action.

They remain in the scenario itself.

The planning execution parameters:

- planner;
- rank_threshold;
- primary_tech;
- solution_kind

belong to the execution request.

If the user explicitly supplies different execution parameters,
preserve those values.

Example:

User:
    "Execute curitiba_lte usando rank threshold 5."

Correct:

{
    "action": "planning_run",
    "request": {
        "scenario_id": "curitiba_lte",
        "rank_threshold": 5
    }
}

Do not invent or rewrite the scenario.

If the user explicitly identifies the scenario but does not provide
an execution parameter, the application may apply its established
planning execution contract.

Do NOT use scenario-domain examples as execution defaults.

If the user asks to execute a scenario and does not identify which
scenario, ask the user for the scenario identifier.

Example:

{
    "action": "ask_user",
    "questions": [
        "Qual cenário deve ser executado?"
    ]
}

PLANNING ACTION CONTRACT
========================

For planning execution, return:

{
    "action": "planning_run",
    "request": {
        "scenario_id": "..."
    }
}

Optional execution fields may include:

{
    "planner": "...",
    "rank_threshold": 10,
    "primary_tech": "...",
    "solution_kind": "..."
}

Only include an execution parameter explicitly supplied by the user,
unless that parameter is part of the established application-level
planning execution contract.

Do not copy scenario technical values into planning_run.

Do not place scenario updates inside planning_run.

Do not place planning parameters inside update_scenario unless the
user is explicitly modifying the scenario and the current schema
supports that field.

PLANNING DOES NOT MODIFY THE SCENARIO
=====================================

planning_run means:

    execute the existing scenario.

It does NOT mean:

    modify the scenario.

The scenario.toml remains the source of the scenario technical
configuration.

The planner execution result is an operational result and does not
become a scenario update automatically.

ACTIONS
=======

You may return ONLY one of:

1. update_scenario
2. ask_user
3. confirm
4. reject_confirmation
5. finalize
6. planning_run

Return valid JSON only.

ACTION MEANINGS
===============

update_scenario
---------------

Use when the user explicitly provides one or more scenario values
that can be represented by the current application schema.

ask_user
--------

Use when required information is missing or clarification is needed.

Do not put "updates" inside ask_user.

confirm
-------

Use only when the user explicitly confirms the current proposed
scenario.

reject_confirmation
-------------------

Use when the user explicitly rejects confirmation or asks to modify
the scenario.

finalize
--------

Use only when:

- the scenario is complete;
- the scenario is valid;
- the user explicitly confirmed it;
- the application indicates finalization is ready.

planning_run
------------

Use when the user explicitly requests execution of planning for an
existing scenario.

Do not use update_scenario for this intent.

Do not ask for scenario construction parameters again.

Do not execute MCP.

Do not execute Planning Service.

JSON CONTRACT
=============

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

For planning_run:

{
    "action": "planning_run",
    "request": {
        "scenario_id": "..."
    }
}

Return exactly one JSON object.

Do not return Markdown.

Do not return explanations outside JSON.

Do not return multiple actions.

The application will validate and execute the returned action.
""".strip()

    # ========================================================
    # DOMAIN CONTEXT
    # ========================================================

    def _domain_context(
        self,
    ) -> dict[str, Any]:

        provider = (
            self.domain_context_provider
        )

        if provider is None:
            return {}

        try:

            context = provider.get_context(
                sections=(
                    self.domain_context_sections
                )
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

It is NOT a source of scenario defaults.

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

    def _application_context(
        self,
    ) -> dict[str, Any]:

        return {

            "scenario_state":
                self.scenario_agent.conversation_state(),

            "scenario_snapshot":
                self.scenario_agent.snapshot(),
        }

    # ========================================================
    # OPENAI REQUEST
    # ========================================================

    def _request_model(
        self,
        user_message: str,
    ) -> dict[str, Any]:

        if not isinstance(
            user_message,
            str,
        ):

            raise TypeError(
                "user_message must be a string"
            )

        user_message = (
            user_message.strip()
        )

        if not user_message:

            raise ValueError(
                "user_message cannot be empty"
            )

        application_context = (
            self._application_context()
        )

        domain_context = (
            self._domain_context()
        )

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
                "role":
                    "system",

                "content":
                    self._system_prompt(),
            },

            {
                "role":
                    "system",

                "content":
                    self._domain_context_prompt(
                        domain_context
                    ),
            },

            *self.messages,
        ]

        try:

            response = (
                self.client.responses.create(
                    model=self.model,
                    reasoning={
                        "effort": "medium",
                    },
                    input=input_messages,
                )
            )

        except Exception as exc:

            raise ScenarioAgentOpenAIError(
                f"OpenAI request failed: {exc}"
            ) from exc

        output_text = getattr(
            response,
            "output_text",
            None,
        )

        if not output_text:

            raise ScenarioAgentOpenAIError(
                "OpenAI returned an empty response"
            )

        output_text = (
            output_text.strip()
        )

        try:

            action = json.loads(
                output_text
            )

        except json.JSONDecodeError as exc:

            raise ScenarioAgentOpenAIError(
                "OpenAI returned invalid JSON: "
                f"{output_text}"
            ) from exc

        if not isinstance(
            action,
            dict,
        ):

            raise ScenarioAgentOpenAIError(
                "OpenAI response must be a JSON object"
            )

        self.messages.append(
            {
                "role":
                    "assistant",

                "content":
                    output_text,
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

        if not isinstance(
            action,
            dict,
        ):

            raise ScenarioAgentOpenAIError(
                "Model action must be a JSON object"
            )

        action_name = action.get(
            "action"
        )

        if action_name not in (
            self.ALLOWED_ACTIONS
        ):

            raise ScenarioAgentOpenAIError(
                f"Unsupported model action: "
                f"{action_name!r}"
            )

        # ----------------------------------------------------
        # UPDATE SCENARIO
        # ----------------------------------------------------

        if action_name == "update_scenario":

            if "updates" not in action:

                raise ScenarioAgentOpenAIError(
                    "update_scenario action must "
                    "contain 'updates'"
                )

            if not isinstance(
                action["updates"],
                dict,
            ):

                raise ScenarioAgentOpenAIError(
                    "update_scenario 'updates' "
                    "must be a JSON object"
                )

        # ----------------------------------------------------
        # ASK USER
        # ----------------------------------------------------

        if action_name == "ask_user":

            if "updates" in action:

                raise ScenarioAgentOpenAIError(
                    "ask_user action must not "
                    "contain 'updates'"
                )

            questions = action.get(
                "questions"
            )

            if questions is not None:

                if not isinstance(
                    questions,
                    list,
                ):

                    raise ScenarioAgentOpenAIError(
                        "ask_user 'questions' "
                        "must be a list"
                    )

        # ----------------------------------------------------
        # PLANNING RUN
        # ----------------------------------------------------

        if action_name == "planning_run":

            if "request" not in action:

                raise ScenarioAgentOpenAIError(
                    "planning_run action must "
                    "contain 'request'"
                )

            request = action[
                "request"
            ]

            if not isinstance(
                request,
                dict,
            ):

                raise ScenarioAgentOpenAIError(
                    "planning_run 'request' "
                    "must be a JSON object"
                )

            scenario_id = request.get(
                "scenario_id"
            )

            if not isinstance(
                scenario_id,
                str,
            ) or not scenario_id.strip():

                raise ScenarioAgentOpenAIError(
                    "planning_run requires "
                    "scenario_id"
                )

            if (
                "planner" in request
                and not isinstance(
                    request["planner"],
                    str,
                )
            ):

                raise ScenarioAgentOpenAIError(
                    "planning_run planner "
                    "must be a string"
                )

            if (
                "rank_threshold"
                in request
            ):

                try:

                    int(
                        request[
                            "rank_threshold"
                        ]
                    )

                except (
                    TypeError,
                    ValueError,
                ) as exc:

                    raise ScenarioAgentOpenAIError(
                        "planning_run rank_threshold "
                        "must be an integer"
                    ) from exc

            if (
                "primary_tech"
                in request
                and not isinstance(
                    request[
                        "primary_tech"
                    ],
                    str,
                )
            ):

                raise ScenarioAgentOpenAIError(
                    "planning_run primary_tech "
                    "must be a string"
                )

            if (
                "solution_kind"
                in request
                and not isinstance(
                    request[
                        "solution_kind"
                    ],
                    str,
                )
            ):

                raise ScenarioAgentOpenAIError(
                    "planning_run solution_kind "
                    "must be a string"
                )

    # ========================================================
    # ASYNC EXECUTOR
    # ========================================================

    @staticmethod
    def _run_coroutine_sync(
        coroutine,
    ):
        """
        Executa uma coroutine a partir de código síncrono.

        O notebook Jupyter normalmente possui um event loop ativo.
        Nesse caso, executamos a coroutine em uma thread própria.

        Fora de um event loop ativo, asyncio.run() é utilizado
        diretamente.
        """

        try:

            asyncio.get_running_loop()

        except RuntimeError:

            return asyncio.run(
                coroutine
            )

        # ----------------------------------------------------
        # Já existe event loop.
        #
        # Não podemos chamar asyncio.run() no mesmo thread.
        # ----------------------------------------------------

        result = []
        error = []

        def runner():

            try:

                result.append(
                    asyncio.run(
                        coroutine
                    )
                )

            except BaseException as exc:

                error.append(
                    exc
                )

        thread = threading.Thread(
            target=runner,
            daemon=True,
        )

        thread.start()
        thread.join()

        if error:
            raise error[0]

        return (
            result[0]
            if result
            else None
        )

    # ========================================================
    # ACTION APPLICATION
    # ========================================================

    def _apply_action(
        self,
        action: dict[str, Any],
    ) -> dict[str, Any]:

        self._validate_action(
            action
        )

        action_name = action[
            "action"
        ]

        # ----------------------------------------------------
        # SCENARIO
        # ----------------------------------------------------

        if action_name == "update_scenario":

            return (
                self.scenario_agent.process_update(
                    action["updates"]
                )
            )

        # ----------------------------------------------------
        # ASK USER
        # ----------------------------------------------------

        if action_name == "ask_user":

            return action

        # ----------------------------------------------------
        # CONFIRM
        # ----------------------------------------------------

        if action_name == "confirm":

            return (
                self.scenario_agent
                .process_confirmation(
                    confirmed=True
                )
            )

        # ----------------------------------------------------
        # REJECT
        # ----------------------------------------------------

        if action_name == "reject_confirmation":

            return (
                self.scenario_agent
                .process_confirmation(
                    confirmed=False
                )
            )

        # ----------------------------------------------------
        # FINALIZE
        # ----------------------------------------------------

        if action_name == "finalize":

            return (
                self.scenario_agent
                .process_finalize()
            )

        # ----------------------------------------------------
        # PLANNING
        # ----------------------------------------------------

        if action_name == "planning_run":

            request = action[
                "request"
            ]

            try:

                result = (
                    self._run_coroutine_sync(
                        self.planner_orchestrator.execute(
                            request
                        )
                    )
                )

            except PlannerOrchestratorError as exc:

                return {

                    "action":
                        "planning_run",

                    "status":
                        "error",

                    "scenario_id":
                        request.get(
                            "scenario_id"
                        ),

                    "error":
                        str(exc),
                }

            except Exception as exc:

                return {

                    "action":
                        "planning_run",

                    "status":
                        "error",

                    "scenario_id":
                        request.get(
                            "scenario_id"
                        ),

                    "error":
                        str(exc),
                }

            return {

                "action":
                    "planning_run",

                **result,
            }

        # ----------------------------------------------------
        # PROTEÇÃO
        # ----------------------------------------------------

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

        action = (
            self._request_model(
                user_message
            )
        )

        return (
            self._apply_action(
                action
            )
        )

    # ========================================================
    # PUBLIC ASYNC CHAT API
    # ========================================================

    async def chat_async(
        self,
        user_message: str,
    ) -> dict[str, Any]:

        """
        Variante assíncrona para notebooks/aplicações que
        já trabalham nativamente com async.

        O request OpenAI continua síncrono porque o cliente
        atual é síncrono; apenas a execução do Planner é
        aguardada de forma assíncrona.
        """

        action = (
            self._request_model(
                user_message
            )
        )

        self._validate_action(
            action
        )

        if action.get(
            "action"
        ) != "planning_run":

            return (
                self._apply_action(
                    action
                )
            )

        try:

            result = await (
                self.planner_orchestrator.execute(
                    action[
                        "request"
                    ]
                )
            )

        except PlannerOrchestratorError as exc:

            return {

                "action":
                    "planning_run",

                "status":
                    "error",

                "scenario_id":
                    action[
                        "request"
                    ].get(
                        "scenario_id"
                    ),

                "error":
                    str(exc),
            }

        except Exception as exc:

            return {

                "action":
                    "planning_run",

                "status":
                    "error",

                "scenario_id":
                    action[
                        "request"
                    ].get(
                        "scenario_id"
                    ),

                "error":
                    str(exc),
            }

        return {

            "action":
                "planning_run",

            **result,
        }


# ============================================================
# FACTORY
# ============================================================

def create_scenario_agent_openai(
    project_path: str | Path,
    *,
    model: str | None = None,
    domain_context_provider: DomainContextProvider | None = None,
    domain_context_sections: tuple[str, ...] | None = None,
    planner_orchestrator: PlannerOrchestrator | None = None,
) -> ScenarioAgentOpenAI:

    project = PlanningProject(
        project_path
    )

    return ScenarioAgentOpenAI(
        project,
        model=model,
        domain_context_provider=domain_context_provider,
        domain_context_sections=domain_context_sections,
        planner_orchestrator=planner_orchestrator,
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
        Path(
            "/home/jovyan/work/planapp-mcp"
        )
        / "cisei-planning-engineering"
    )

    provider = (
        CISEIPluginDomainContextProvider(
            plugin_path
        )
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