import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ============================================================
# Configuração
# ============================================================

MCP_URL = "http://localhost:8010/mcp"

USER_ID = "fernando.busch@ter.grupomarista.org.br"


# ============================================================
# Teste MCP
# ============================================================

async def main():

    print("Conectando ao PlanApp MCP...")

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):

        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            # ------------------------------------------------
            # 1. Inicialização da sessão MCP
            # ------------------------------------------------

            print("\n=== MCP INITIALIZE ===")

            await session.initialize()

            print("Sessão MCP inicializada.")

            # ------------------------------------------------
            # 2. Lista as ferramentas
            # ------------------------------------------------

            print("\n=== TOOLS ===")

            tools_result = await session.list_tools()

            for tool in tools_result.tools:
                print(f"- {tool.name}")

            # ------------------------------------------------
            # 3. Registro do usuário
            # ------------------------------------------------

            print("\n=== REGISTER ===")

            register_result = await session.call_tool(
                "register",
                {
                    "user_id": USER_ID,
                },
            )

            print(register_result)

            # ------------------------------------------------
            # 4. Avaliação do enlace
            # ------------------------------------------------

            print("\n=== EVALUATE LINK ===")

            evaluate_result = await session.call_tool(
                "evaluate_link",
                {
                    "tx_lat": -25.4284,
                    "tx_lon": -49.2733,
                    "rx_lat": -25.4500,
                    "rx_lon": -49.3000,
                    "tx_ha": 7,
                    "rx_ha": 7,
                    "freq_mhz": 18000,
                },
            )

            print(evaluate_result)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())

