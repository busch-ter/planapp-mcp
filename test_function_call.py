import os
import json
from openai import OpenAI

MODEL = "gpt-5.6-luna"

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

print("=" * 70)
print("TESTE OPENAI — FUNCTION CALLING")
print("=" * 70)
print(f"Modelo: {MODEL}")
print()

tools = [
    {
        "type": "function",
        "name": "get_link_distance",
        "description": "Calcula a distância entre dois pontos geográficos.",
        "parameters": {
            "type": "object",
            "properties": {
                "tx_lat": {
                    "type": "number"
                },
                "tx_lon": {
                    "type": "number"
                },
                "rx_lat": {
                    "type": "number"
                },
                "rx_lon": {
                    "type": "number"
                }
            },
            "required": [
                "tx_lat",
                "tx_lon",
                "rx_lat",
                "rx_lon"
            ],
            "additionalProperties": False
        }
    }
]

try:

    print("Enviando request para a OpenAI...")
    print()

    response = client.responses.create(
        model=MODEL,

        input=(
            "Calcule a distância entre "
            "Praça da Sé (-23.5503898, -46.633081) "
            "e Praça da República (-23.5431712, -46.6425205). "
            "Use a ferramenta disponível."
        ),

        tools=tools,

        tool_choice="required",

        reasoning={
            "effort": "none"
        },
    )

    print("✅ OpenAI respondeu.")
    print()

    print("=" * 70)
    print("OUTPUT")
    print("=" * 70)

    for item in response.output:

        print()
        print("Tipo:", item.type)

        if item.type == "function_call":

            print("Function:", item.name)
            print("Call ID:", item.call_id)

            print("Arguments:")

            try:
                print(
                    json.dumps(
                        json.loads(item.arguments),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            except Exception:
                print(item.arguments)

        elif item.type == "message":

            print("Mensagem:")
            print(response.output_text)

    print()
    print("=" * 70)
    print("USAGE")
    print("=" * 70)
    print(response.usage)

    print()
    print("✅ FUNCTION CALLING FUNCIONOU")

except Exception as e:

    print()
    print("=" * 70)
    print("❌ ERRO OPENAI")
    print("=" * 70)

    print("Tipo:", type(e).__name__)
    print("Mensagem:")
    print(str(e))

    print()
    print("Detalhes do erro:")

    if hasattr(e, "status_code"):
        print("status_code:", e.status_code)

    if hasattr(e, "code"):
        print("code:", e.code)

    if hasattr(e, "type"):
        print("type:", e.type)

    if hasattr(e, "param"):
        print("param:", e.param)

    if hasattr(e, "body"):
        print("body:")
        print(
            json.dumps(
                e.body,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

    print()
    print("=" * 70)