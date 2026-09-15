import asyncio
import json
import os

from openai import OpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


OPENAI_MODEL = "gpt-5.6-luna"
MCP_URL = "http://172.17.0.1:8010/mcp"
USER_ID = "openai-test"


def parse_mcp_result(result):
    structured = getattr(result, "structuredContent", None)

    if structured is not None:
        return structured

    content = getattr(result, "content", None)

    if content:
        for item in content:
            text = getattr(item, "text", None)

            if text:
                try:
                    return json.loads(text)
                except Exception:
                    return text

    return None


async def main():

    print("=" * 70)
    print("TESTE OPENAI + MCP")
    print("=" * 70)

    print(f"OpenAI model: {OPENAI_MODEL}")
    print(f"MCP URL:      {MCP_URL}")
    print()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY não está definida."
        )

    openai = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"]
    )

    async with streamable_http_client(MCP_URL) as transport:

        read_stream, write_stream = transport

        async with ClientSession(
            read_stream,
            write_stream,
        ) as mcp:

            # --------------------------------------------------
            # 1. Inicializar MCP
            # --------------------------------------------------

            print("Inicializando MCP...")

            await mcp.initialize()

            print("✅ MCP inicializado.")
            print()

            # --------------------------------------------------
            # 2. Registrar usuário
            # --------------------------------------------------

            print("Registrando usuário...")

            register_result = await mcp.call_tool(
                "register",
                {
                    "user_id": USER_ID
                },
            )

            register_data = parse_mcp_result(
                register_result
            )

            print(
                json.dumps(
                    register_data,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            print("✅ REGISTER OK")
            print()

            # --------------------------------------------------
            # 3. Obter ferramentas MCP
            # --------------------------------------------------

            tools_result = await mcp.list_tools()

            print("Ferramentas MCP disponíveis:")

            for tool in tools_result.tools:
                print(f"  • {tool.name}")

            print()

            # --------------------------------------------------
            # 4. Converter geocode_place para OpenAI Tool
            # --------------------------------------------------

            geocode_tool = None

            for tool in tools_result.tools:

                if tool.name == "geocode_place":
                    geocode_tool = tool
                    break

            if geocode_tool is None:
                raise RuntimeError(
                    "Ferramenta geocode_place não encontrada."
                )

            openai_tool = {
                "type": "function",
                "name": geocode_tool.name,
                "description": (
                    geocode_tool.description
                    or "Geocodifica um local."
                ),
                "parameters": geocode_tool.input_schema,
            }

            print("=" * 70)
            print("OPENAI TOOL")
            print("=" * 70)

            print(
                json.dumps(
                    openai_tool,
                    indent=2,
                    ensure_ascii=False,
                )
            )

            print()

            # --------------------------------------------------
            # 5. Primeira chamada OpenAI
            # --------------------------------------------------

            user_request = (
                "Encontre as coordenadas da "
                "Praça da Sé, São Paulo. "
                "Use a ferramenta geocode_place."
            )

            print("=" * 70)
            print("1. OPENAI — FUNCTION CALL")
            print("=" * 70)

            print("Usuário:")
            print(user_request)
            print()

            response = openai.responses.create(
                model=OPENAI_MODEL,
                input=user_request,
                tools=[openai_tool],
                tool_choice="required",
                reasoning={
                    "effort": "none"
                },
            )

            function_calls = [
                item
                for item in response.output
                if item.type == "function_call"
            ]

            if not function_calls:
                print("❌ OpenAI não gerou function_call.")
                print(response.output)
                return

            # --------------------------------------------------
            # 6. Executar chamadas através do MCP
            # --------------------------------------------------

            tool_outputs = []

            for call in function_calls:

                print("Function:", call.name)
                print("Call ID:", call.call_id)

                arguments = json.loads(
                    call.arguments
                )

                print("Argumentos:")
                print(
                    json.dumps(
                        arguments,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

                print()
                print("Chamando MCP...")

                mcp_result = await mcp.call_tool(
                    call.name,
                    arguments,
                )

                mcp_data = parse_mcp_result(
                    mcp_result
                )

                print()
                print("Resultado MCP:")
                print(
                    json.dumps(
                        mcp_data,
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    )
                )

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(
                            mcp_data,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

            # --------------------------------------------------
            # 7. Segunda chamada OpenAI
            # --------------------------------------------------

            print()
            print("=" * 70)
            print("2. OPENAI — FUNCTION CALL OUTPUT")
            print("=" * 70)

            second_input = list(
                response.output
            )

            second_input.extend(
                tool_outputs
            )

            final_response = openai.responses.create(
                model=OPENAI_MODEL,
                input=second_input,
                tools=[openai_tool],
                reasoning={
                    "effort": "none"
                },
            )

            print()
            print("Resposta final:")
            print(
                final_response.output_text
            )

            print()
            print("=" * 70)
            print("USAGE")
            print("=" * 70)

            print(final_response.usage)

            print()
            print("=" * 70)
            print("STATUS")
            print("=" * 70)

            print(
                "✅ OPENAI + MCP FUNCIONOU!"
            )


if __name__ == "__main__":
    asyncio.run(main())