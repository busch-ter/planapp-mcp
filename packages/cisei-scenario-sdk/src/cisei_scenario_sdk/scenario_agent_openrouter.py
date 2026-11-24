"""Adaptador OpenRouter para o CISEI Scenario Agent."""

import json
import os
import re
from typing import Any

from openai import OpenAI

from .scenario_agent_openai import (
    ScenarioAgentOpenAI,
    ScenarioAgentOpenAIError,
)


class ScenarioAgentOpenRouter(ScenarioAgentOpenAI):
    """Reutiliza o agente CISEI com transporte OpenRouter."""

    def __init__(
        self,
        project,
        *,
        model: str | None = None,
        client: OpenAI | None = None,
        domain_context_provider=None,
        domain_context_sections: tuple[str, ...] | None = None,
    ):
        selected_model = (
            model
            or os.getenv("SCENARIO_AGENT_OPENROUTER_MODEL")
            or "openrouter/free"
        )

        if not selected_model:
            raise ValueError(
                "Configure SCENARIO_AGENT_OPENROUTER_MODEL "
                "ou informe model explicitamente."
            )

        if client is None:
            api_key = os.getenv("OPENROUTER_API_KEY")

            if not api_key:
                raise ValueError(
                    "OPENROUTER_API_KEY não configurada."
                )

            client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )

        super().__init__(
            project,
            model=selected_model,
            client=client,
            domain_context_provider=domain_context_provider,
            domain_context_sections=domain_context_sections,
        )

    def _system_prompt(self) -> str:
        """Complementa o contrato compartilhado para OpenRouter."""
        base = super()._system_prompt()

        return base + """

ORIENTAÇÕES DE EXECUÇÃO PARA OPENROUTER
- Priorize update_scenario quando a mensagem atual contiver
  valores explícitos que possam ser registrados com segurança.
- Não escolha ask_user apenas porque o cenário completo
  ainda possui campos obrigatórios ausentes.
- Registre primeiro os valores explícitos disponíveis.
- A validação do ScenarioBuilder identificará os campos
  que ainda precisam ser fornecidos.
- Não solicite novamente valores que já constem das mensagens
  anteriores ou do estado canônico.
- Não invente parâmetros para completar uma atualização.
- Não crie antenas individuais por instalação quando o usuário
  definiu perfis de antenas reutilizáveis.
- Preserve os identificadores e as referências informados.
- Não substitua especificações explícitas de métricas por
  valores genéricos ou defaults.
- Uma mensagem que fornece requisitos técnicos não equivale
  a uma confirmação do cenário.
- Somente confirme ou finalize quando houver autorização
  explícita do usuário e o estado permitir.
"""


    def _guard_update_action(
        self,
        action: dict[str, Any],
        user_message: str,
    ) -> dict[str, Any]:
        """Bloqueia criação de perfis sem identificador explícito."""

        if action.get("action") != "update_scenario":
            return action

        updates = action.get("updates")

        if not isinstance(updates, dict):
            return action

        sections = ("antennas", "interfaces", "devices", "metrics")
        unsupported = []

        for section in sections:
            entries = updates.get(section, {})

            if not isinstance(entries, dict):
                continue

            for identifier in entries:
                pattern = (
                    r"(?<![A-Za-z0-9_])"
                    + re.escape(identifier)
                    + r"(?![A-Za-z0-9_])"
                )

                if re.search(pattern, user_message) is None:
                    unsupported.append(f"{section}.{identifier}")

        if not unsupported:
            return action

        return {
            "action": "ask_user",
            "question": (
                "A atualização proposta contém perfis cujos "
                "identificadores não foram informados explicitamente "
                "na mensagem atual: "
                + ", ".join(unsupported)
                + ". Nenhuma alteração foi aplicada. "
                "Forneça as definições técnicas explicitamente."
            ),
            "fields": unsupported,
        }

    def _request_model(self, user_message: str) -> dict[str, Any]:
        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        user_message = user_message.strip()

        if not user_message:
            raise ValueError("user_message cannot be empty")

        app_context = self._application_context()
        domain_context = self._domain_context()

        current_user_message = {
            "role": "user",
            "content": (
                "MENSAGEM ATUAL DO USUÁRIO\n"
                f"{user_message}\n\n"
                "CONTEXTO ATUAL DA APLICAÇÃO\n"
                f"{json.dumps(app_context, ensure_ascii=False, indent=2)}"
            ),
        }

        messages = [
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
            current_user_message,
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenRouter request failed: {exc}"
            ) from exc

        if not response.choices:
            raise ScenarioAgentOpenAIError(
                "OpenRouter returned no choices"
            )

        choice = response.choices[0]

        if choice.finish_reason == "length":
            raise ScenarioAgentOpenAIError(
                "OpenRouter response was truncated"
            )

        output = choice.message.content

        if not isinstance(output, str) or not output.strip():
            raise ScenarioAgentOpenAIError(
                "OpenRouter returned an empty response"
            )

        output = output.strip()

        try:
            action = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenRouter returned invalid JSON: "
                f"{output[:2000]!r}"
            ) from exc

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "OpenRouter response must be a JSON object"
            )

        if action.get("action") == "ask_user":
            review_messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": output,
                },
                {
                    "role": "user",
                    "content": (
                        "REVISÃO DE AÇÃO OPENROUTER\n"
                        "Antes de perguntar pelos campos restantes, "
                        "verifique exclusivamente a MENSAGEM ATUAL "
                        "DO USUÁRIO e o estado canônico. "
                        "Se houver valores técnicos explícitos ainda "
                        "não registrados, retorne update_scenario "
                        "com somente esses valores. "
                        "Não invente valores, não use defaults e "
                        "não antecipe perguntas sobre parâmetros "
                        "que serão fornecidos posteriormente. "
                        "Se não houver atualização segura, "
                        "mantenha a ação ask_user. "
                        "Responda somente com JSON."
                    ),
                },
            ]

            try:
                review_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=review_messages,
                    response_format={"type": "json_object"},
                )

                if (
                    review_response.choices
                    and review_response.choices[0].finish_reason != "length"
                ):
                    review_output = (
                        review_response.choices[0].message.content
                    )

                    if isinstance(review_output, str):
                        review_action = json.loads(review_output)

                        if (
                            isinstance(review_action, dict)
                            and review_action.get("action")
                            == "update_scenario"
                            and isinstance(
                                review_action.get("updates"), dict
                            )
                            and review_action["updates"]
                        ):
                            action = review_action
                            output = review_output

            except (ValueError, AttributeError, IndexError):
                pass

        guarded_action = self._guard_update_action(
            action,
            user_message,
        )

        if guarded_action is not action:
            action = guarded_action
            output = json.dumps(
                action,
                ensure_ascii=False,
            )

        self._pending_exchange = [
            current_user_message,
            {
                "role": "assistant",
                "content": output,
            },
        ]

        return action
