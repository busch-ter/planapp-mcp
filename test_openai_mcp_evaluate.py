import os
import json
import asyncio

from openai import OpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


OPENAI_MODEL = "gpt-5.6-luna"
MCP_URL = "http://localhost:8010/mcp"
USER_ID = "openai-evaluate-test"


def mcp_tool_to_openai(tool):
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description or "",
        "parameters": tool.input_schema,
    }


def parse_mcp_result(result):
    # Primeiro tenta structuredContent
    structured = getattr(result, "structuredContent", None)

    if structured:
        return structured

    # Depois tenta structured_content
    structured = getattr(result, "structured_content", None)

    if structured:
        return structured

    # Finalmente tenta content/text
    content = getattr(result, "content", None)

    if content:
        for item in content:
            text = getattr(item, "text", None)

            if text:
                try:
                    return json.loads(text)
                except Exception:
                    return {"text": text}

    return {}


async def main():

    print("=" * 70)
    print("OPENAI + MCP + REAL EVALUATE_LINK")
    print("=" * 70)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY não está definida."
        )

    client = OpenAI(api_key=api_key)

    print("\n🔌 Conectando ao MCP...")
    print(f"   {MCP_URL}")

    async with streamable_http_client(MCP_URL) as transport:

        # A versão instalada do MCP retorna 2 streams
        read_stream, write_stream = transport

        async with ClientSession(
            read_stream,
            write_stream
        ) as session:

            await session.initialize()

            print("✅ MCP inicializado")

            # ------------------------------------------------------------
            # Lista ferramentas
            # ------------------------------------------------------------

            tools_result = await session.list_tools()

            print("\n🛠️ Ferramentas MCP disponíveis:")

            for tool in tools_result.tools:
                print(f"   - {tool.name}")

            # ------------------------------------------------------------
            # Registra usuário
            # ------------------------------------------------------------

            print(f"\n👤 Registrando usuário: {USER_ID}")

            register_result = await session.call_tool(
                "register",
                {
                    "user_id": USER_ID
                }
            )

            register_data = parse_mcp_result(register_result)

            print(
                json.dumps(
                    register_data,
                    indent=2,
                    ensure_ascii=False
                )
            )

            # ------------------------------------------------------------
            # Seleciona somente ferramentas controladas pelo LLM
            # ------------------------------------------------------------

            allowed_tools = {
                "geocode_place",
                "evaluate_link",
            }

            mcp_tools = [
                tool
                for tool in tools_result.tools
                if tool.name in allowed_tools
            ]

            openai_tools = [
                mcp_tool_to_openai(tool)
                for tool in mcp_tools
            ]

            print("\n🤖 Ferramentas entregues ao OpenAI:")

            for tool in openai_tools:
                print(f"   - {tool['name']}")

            # ------------------------------------------------------------
            # Prompt
            # ------------------------------------------------------------

            user_request = """
Analise um enlace de rádio entre a Praça da Sé e a Praça da República,
em São Paulo.

Use obrigatoriamente a ferramenta geocode_place para localizar os dois
pontos antes de executar a avaliação.

Depois use evaluate_link com:

- TX: Praça da Sé
- RX: Praça da República
- altura TX: 7 metros
- altura RX: 7 metros
- frequência: 900 MHz
- on_rooftop: false

Depois da avaliação, apresente os principais resultados técnicos,
incluindo distância, FSPL e eventuais obstruções.
"""

            conversation = [
                {
                    "role": "user",
                    "content": user_request,
                }
            ]

            total_input_tokens = 0
            total_output_tokens = 0

            # ------------------------------------------------------------
            # LOOP AGENTE
            # ------------------------------------------------------------

            for iteration in range(1, 10):

                print("\n" + "=" * 70)
                print(f"🤖 ITERAÇÃO {iteration}")
                print("=" * 70)

                response = client.responses.create(
                    model=OPENAI_MODEL,
                    input=conversation,
                    tools=openai_tools,
                    reasoning={
                        "effort": "none"
                    },
                )

                # --------------------------------------------------------
                # Usage
                # --------------------------------------------------------

                if response.usage:

                    input_tokens = (
                        getattr(
                            response.usage,
                            "input_tokens",
                            0
                        ) or 0
                    )

                    output_tokens = (
                        getattr(
                            response.usage,
                            "output_tokens",
                            0
                        ) or 0
                    )

                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens

                    print(
                        f"Tokens: input={input_tokens}, "
                        f"output={output_tokens}"
                    )

                # --------------------------------------------------------
                # Preserva a resposta do modelo
                # --------------------------------------------------------

                conversation.extend(response.output)

                # --------------------------------------------------------
                # Procura function calls
                # --------------------------------------------------------

                function_calls = [
                    item
                    for item in response.output
                    if getattr(item, "type", None)
                    == "function_call"
                ]

                if not function_calls:

                    print("\n" + "-" * 70)
                    print("🎯 RESPOSTA FINAL DO OPENAI")
                    print("-" * 70)

                    print(response.output_text)

                    break

                # --------------------------------------------------------
                # Executa chamadas MCP
                # --------------------------------------------------------

                tool_outputs = []

                for call in function_calls:

                    print("\n" + "-" * 70)
                    print("🔧 FUNCTION CALL")
                    print("-" * 70)

                    print(f"Ferramenta: {call.name}")

                    try:
                        arguments = json.loads(
                            call.arguments
                        )
                    except Exception:
                        arguments = {}

                    print(
                        json.dumps(
                            arguments,
                            indent=2,
                            ensure_ascii=False
                        )
                    )

                    # ----------------------------------------------------
                    # MCP
                    # ----------------------------------------------------

                    print("\n➡️ Executando MCP...")

                    mcp_result = await session.call_tool(
                        call.name,
                        arguments
                    )

                    parsed = parse_mcp_result(
                        mcp_result
                    )

                    print("\n⬅️ Resultado MCP:")

                    print(
                        json.dumps(
                            parsed,
                            indent=2,
                            ensure_ascii=False
                        )
                    )

                    # ----------------------------------------------------
                    # Erro MCP
                    # ----------------------------------------------------

                    is_error = getattr(
                        mcp_result,
                        "isError",
                        False
                    )

                    if is_error:
                        print(
                            "\n❌ MCP informou erro."
                        )

                    # ----------------------------------------------------
                    # Devolve resultado ao OpenAI
                    # ----------------------------------------------------

                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(
                                parsed,
                                ensure_ascii=False
                            ),
                        }
                    )

                # --------------------------------------------------------
                # Adiciona resultados ao histórico
                # --------------------------------------------------------

                conversation.extend(
                    tool_outputs
                )

            else:

                print(
                    "\n❌ Limite de iterações atingido."
                )

            # ------------------------------------------------------------
            # TOTAL
            # ------------------------------------------------------------

            print("\n" + "=" * 70)
            print("📊 USO TOTAL")
            print("=" * 70)

            print(
                f"Input tokens : {total_input_tokens}"
            )

            print(
                f"Output tokens: {total_output_tokens}"
            )

            print(
                f"Total tokens : "
                f"{total_input_tokens + total_output_tokens}"
            )

            print("\n✅ TESTE OPENAI + MCP + EVALUATE CONCLUÍDO")


if __name__ == "__main__":
    asyncio.run(main())