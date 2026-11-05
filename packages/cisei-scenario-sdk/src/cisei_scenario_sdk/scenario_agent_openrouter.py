"""Adaptador OpenRouter para o CISEI Scenario Agent."""

import json
import os
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

        self._pending_exchange = [
            current_user_message,
            {
                "role": "assistant",
                "content": output,
            },
        ]

        return action
