import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://172.17.0.1:8010/mcp"
USER_ID = "test-mcp"


def print_result(title, result):
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)

    print("isError:", getattr(result, "isError", None))

    structured = getattr(
        result,
        "structuredContent",
        None,
    )

    if structured is not None:
        print(json.dumps(
            structured,
            indent=2,
            ensure_ascii=False,
            default=str,
        ))
        return structured

    content = getattr(
        result,
        "content",
        None,
    )

    if content:

        for item in content:

            text = getattr(
                item,
                "text",
                None,
            )

            if not text:
                continue

            try:
                data = json.loads(text)

                print(json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ))

                return data

            except Exception:

                print(text)
                return text

    print("(resultado vazio)")

    return None


def contains_error(value):

    if isinstance(value, dict):

        status = str(
            value.get("status", "")
        ).lower()

        if status in {
            "error",
            "failed",
            "failure",
        }:
            return True

        if value.get("error"):
            return True

        for child in value.values():

            if contains_error(child):
                return True

    elif isinstance(value, list):

        for child in value:

            if contains_error(child):
                return True

    return False


async def main():

    print("=" * 80)
    print("PLANAPP MCP TEST")
    print("=" * 80)

    print(f"MCP URL: {MCP_URL}")
    print(f"USER ID: {USER_ID}")

    async with streamable_http_client(MCP_URL) as transport:

        read_stream, write_stream = transport

        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            # ================================================================
            # INITIALIZE
            # ================================================================

            print()
            print("Inicializando MCP...")

            await session.initialize()

            print("✅ MCP inicializado.")

            # ================================================================
            # LIST TOOLS
            # ================================================================

            tools_result = await session.list_tools()

            print()
            print("Ferramentas disponíveis:")

            for tool in tools_result.tools:

                print(
                    f"  • {tool.name}"
                )

            # ================================================================
            # 1. REGISTER
            # ================================================================

            result = await session.call_tool(
                "register",
                {
                    "user_id": USER_ID,
                },
            )

            register_data = print_result(
                "1. REGISTER",
                result,
            )

            if getattr(
                result,
                "isError",
                False,
            ):

                print(
                    "❌ REGISTER retornou erro."
                )

                return

            if contains_error(register_data):

                print(
                    "❌ REGISTER retornou erro no payload."
                )

                return

            print("✅ REGISTER OK")

            # ================================================================
            # 2. GEOCODE TX
            # ================================================================

            result = await session.call_tool(
                "geocode_place",
                {
                    "query": "Praça da Sé, São Paulo",
                },
            )

            tx_data = print_result(
                "2. GEOCODE TX — Praça da Sé",
                result,
            )

            if getattr(
                result,
                "isError",
                False,
            ):

                print(
                    "❌ Geocodificação TX retornou erro."
                )

                return

            if contains_error(tx_data):

                print(
                    "❌ Geocodificação TX retornou erro no payload."
                )

                return

            print("✅ GEOCODE TX OK")

            # ================================================================
            # 3. GEOCODE RX
            # ================================================================

            result = await session.call_tool(
                "geocode_place",
                {
                    "query": "Praça da República, São Paulo",
                },
            )

            rx_data = print_result(
                "3. GEOCODE RX — Praça da República",
                result,
            )

            if getattr(
                result,
                "isError",
                False,
            ):

                print(
                    "❌ Geocodificação RX retornou erro."
                )

                return

            if contains_error(rx_data):

                print(
                    "❌ Geocodificação RX retornou erro no payload."
                )

                return

            print("✅ GEOCODE RX OK")

            # ================================================================
            # COORDENADAS
            # ================================================================

            def extract_coordinates(value):

                if isinstance(value, dict):

                    lat = None
                    lon = None

                    for key in (
                        "lat",
                        "latitude",
                    ):

                        if key in value:

                            try:
                                lat = float(value[key])
                                break
                            except Exception:
                                pass

                    for key in (
                        "lon",
                        "lng",
                        "longitude",
                    ):

                        if key in value:

                            try:
                                lon = float(value[key])
                                break
                            except Exception:
                                pass

                    if (
                        lat is not None
                        and lon is not None
                    ):
                        return lat, lon

                    for child in value.values():

                        coordinates = extract_coordinates(
                            child
                        )

                        if coordinates:
                            return coordinates

                elif isinstance(value, list):

                    for child in value:

                        coordinates = extract_coordinates(
                            child
                        )

                        if coordinates:
                            return coordinates

                return None

            tx = extract_coordinates(
                tx_data
            )

            rx = extract_coordinates(
                rx_data
            )

            print()
            print("=" * 80)
            print("COORDENADAS")
            print("=" * 80)

            print("TX:", tx)
            print("RX:", rx)

            if not tx or not rx:

                print(
                    "❌ Não foi possível extrair as coordenadas."
                )

                return

            # ================================================================
            # 4. EVALUATE LINK
            # ================================================================

            evaluate_args = {
                "tx_lat": tx[0],
                "tx_lon": tx[1],
                "rx_lat": rx[0],
                "rx_lon": rx[1],

                # Valores padrão da aplicação
                "tx_ha": 7,
                "rx_ha": 7,
                "freq_mhz": 900,
                "on_rooftop": False,
            }

            print()
            print("=" * 80)
            print("4. EVALUATE LINK")
            print("=" * 80)

            print(
                json.dumps(
                    evaluate_args,
                    indent=2,
                    ensure_ascii=False,
                )
            )

            result = await session.call_tool(
                "evaluate_link",
                evaluate_args,
            )

            evaluate_data = print_result(
                "RESULTADO EVALUATE_LINK",
                result,
            )

            # ================================================================
            # STATUS FINAL
            # ================================================================

            print()
            print("=" * 80)
            print("STATUS FINAL")
            print("=" * 80)

            mcp_error = getattr(
                result,
                "isError",
                False,
            )

            payload_error = contains_error(
                evaluate_data
            )

            if mcp_error or payload_error:

                print(
                    "❌ TESTE FALHOU"
                )

            else:

                print(
                    "✅ TESTE MCP CONCLUÍDO COM SUCESSO"
                )


if __name__ == "__main__":
    asyncio.run(main())