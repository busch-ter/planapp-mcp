import asyncio
import json

import requests

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ============================================================
# CONFIGURAÇÃO
# ============================================================

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"

MCP_URL = "http://localhost:8010/mcp"

USER_ID = "agent-runner"


# ============================================================
# OLLAMA
# ============================================================

def ask_ollama(messages, tools=None):

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=300,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# CONVERSÃO DAS TOOLS MCP → FORMATO OLLAMA
# ============================================================

def mcp_tools_to_ollama(mcp_tools):

    tools = []

    for tool in mcp_tools:

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
        )

    return tools


# ============================================================
# AGENT RUNNER
# ============================================================

async def main():

    print("=" * 70)
    print("PLANAPP AI AGENT - TESTE LOCAL")
    print("=" * 70)
    print()
    print(f"Ollama : {OLLAMA_URL}")
    print(f"Modelo : {OLLAMA_MODEL}")
    print(f"MCP    : {MCP_URL}")
    print()

    # --------------------------------------------------------
    # CONECTA AO MCP SERVER
    # --------------------------------------------------------

    print("Conectando ao MCP Server...")

    async with streamable_http_client(MCP_URL) as streams:

        async with ClientSession(*streams) as session:

            await session.initialize()

            print("✓ MCP conectado")
            print()

            # ------------------------------------------------
            # OBTÉM AS TOOLS
            # ------------------------------------------------

            result = await session.list_tools()

            mcp_tools = result.tools

            print("Tools MCP disponíveis:")

            for tool in mcp_tools:
                print(f"  - {tool.name}")

            print()

            ollama_tools = mcp_tools_to_ollama(mcp_tools)

            # ------------------------------------------------
            # MENSAGENS INICIAIS
            # ------------------------------------------------

            messages = [
                {
                    "role": "system",
                    "content": (
                        "Você é um agente de planejamento de enlaces "
                        "de rádio do sistema PlanApp. "
                        "Você possui ferramentas MCP para interagir "
                        "com o PlanApp. "
                        "Quando o usuário solicitar a avaliação de um "
                        "enlace, utilize a ferramenta evaluate_link. "
                        "Não invente resultados. "
                        "Utilize os dados retornados pelo PlanApp."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Avalie um enlace entre TX em "
                        "latitude -25.9284, longitude -49.2733 "
                        "e RX em latitude -25.5500, longitude -49.2900. "
                        "Use altura de antena de 7 metros nos dois lados "
                        "e frequência de 900 MHz."
                    ),
                },
            ]

            # ------------------------------------------------
            # PRIMEIRA CHAMADA AO QWEN
            # ------------------------------------------------

            print("Enviando solicitação para o Qwen...")
            print()

            ollama_result = ask_ollama(
                messages,
                tools=ollama_tools,
            )

            assistant_message = ollama_result["message"]

            print("RESPOSTA INICIAL DO QWEN:")
            print("-" * 70)
            print(assistant_message)
            print("-" * 70)
            print()

            # ------------------------------------------------
            # VERIFICA SE O QWEN SOLICITOU UMA TOOL
            # ------------------------------------------------

            tool_calls = assistant_message.get("tool_calls", [])

            if not tool_calls:

                print("O Qwen não solicitou nenhuma ferramenta MCP.")
                print()
                print("Resposta final:")
                print(assistant_message.get("content", ""))

                return

            # ------------------------------------------------
            # PROCESSA AS TOOL CALLS
            # ------------------------------------------------

            messages.append(assistant_message)

            for tool_call in tool_calls:

                function = tool_call["function"]

                tool_name = function["name"]

                arguments = function.get("arguments", {})

                print("Qwen solicitou:")
                print(f"  Tool: {tool_name}")
                print(f"  Arguments: {json.dumps(arguments, indent=2)}")
                print()

                # --------------------------------------------
                # CHAMADA MCP
                # --------------------------------------------

                print(f"Executando MCP tool → {tool_name}...")

                result = await session.call_tool(
                    tool_name,
                    arguments,
                )

                print("✓ MCP tool executada")
                print()

                # --------------------------------------------
                # EXTRAI RESULTADO
                # --------------------------------------------

                tool_result = ""

                for item in result.content:

                    if hasattr(item, "text"):
                        tool_result += item.text

                print("RESULTADO DO MCP:")
                print("-" * 70)
                print(tool_result)
                print("-" * 70)
                print()

                # --------------------------------------------
                # DEVOLVE RESULTADO AO QWEN
                # --------------------------------------------

                messages.append(
                    {
                        "role": "tool",
                        "content": tool_result,
                    }
                )

            # ------------------------------------------------
            # SEGUNDA CHAMADA AO QWEN
            # ------------------------------------------------

            print("Enviando resultado do PlanApp novamente ao Qwen...")
            print()

            final_result = ask_ollama(
                messages,
                tools=ollama_tools,
            )

            final_message = final_result["message"]

            print("=" * 70)
            print("RESPOSTA FINAL DO AGENTE")
            print("=" * 70)
            print()

            print(final_message.get("content", ""))

            print()
            print("=" * 70)
            print("TESTE CONCLUÍDO")
            print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
