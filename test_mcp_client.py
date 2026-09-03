import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://localhost:8010/mcp"


async def main():

    print("=" * 60)
    print("MCP CLIENT - TESTE")
    print("=" * 60)

    print(f"MCP Server: {MCP_URL}")
    print()

    async with streamable_http_client(MCP_URL) as streams:

        print("✓ Conexão HTTP estabelecida")

        async with ClientSession(*streams) as session:

            print("✓ ClientSession criada")
            print()

            print("Inicializando MCP...")

            await session.initialize()

            print("✓ MCP inicializado")
            print()

            print("Consultando tools/list...")
            print()

            result = await session.list_tools()

            tools = result.tools

            print("FERRAMENTAS DISPONÍVEIS:")
            print("-" * 60)

            for tool in tools:

                print()
                print(f"Nome: {tool.name}")
                print(f"Descrição: {tool.description}")
                print(f"Schema: {tool.input_schema}")

            print()
            print("-" * 60)

            # =====================================================
            # TESTE 1 - REGISTER
            # =====================================================

            print()
            print("Testando tools/call → register")
            print()

            result = await session.call_tool(
                "register",
                {
                    "user_id": "test-mcp-client",
                },
            )

            print("RESULTADO DO REGISTER:")
            print(result)

            # =====================================================
            # TESTE 2 - EVALUATE LINK
            # =====================================================

            print()
            print("=" * 60)
            print("Testando tools/call → evaluate_link")
            print("=" * 60)
            print()

            result = await session.call_tool(
                "evaluate_link",
                {
                    "tx_lat": -25.4284,
                    "tx_lon": -49.2733,
                    "rx_lat": -25.4500,
                    "rx_lon": -49.2900,
                    "tx_ha": 7,
                    "rx_ha": 7,
                    "freq_mhz": 900,
                    "on_rooftop": False,
                },
            )

            print("RESULTADO DO EVALUATE_LINK:")
            print("-" * 60)

            for item in result.content:

                if hasattr(item, "text"):

                    try:

                        data = json.loads(item.text)

                        print(
                            json.dumps(
                                data,
                                indent=2,
                                ensure_ascii=False,
                            )
                        )

                    except json.JSONDecodeError:

                        print(item.text)

            # =====================================================
            # TESTE 3 - GEOCODE PLACE
            # =====================================================

            print()
            print("=" * 60)
            print("Testando tools/call → geocode_place")
            print("=" * 60)
            print()

            result = await session.call_tool(
                "geocode_place",
                {
                    "query": "Praça da Sé",
                    "city": "São Paulo",
                    "state": "SP",
                    "country": "Brasil",
                },
            )

            print("RESULTADO DO GEOCODE:")
            print("-" * 60)

            for item in result.content:

                if hasattr(item, "text"):

                    try:

                        data = json.loads(item.text)

                        print(
                            json.dumps(
                                data,
                                indent=2,
                                ensure_ascii=False,
                            )
                        )

                    except json.JSONDecodeError:

                        print(item.text)

            print()
            print("=" * 60)
            print("TESTE CONCLUÍDO")
            print("=" * 60)


if __name__ == "__main__":

    asyncio.run(main())

