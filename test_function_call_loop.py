import os
import json
from openai import OpenAI

MODEL = "gpt-5.6-luna"

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)


def get_link_distance(tx_lat, tx_lon, rx_lat, rx_lon):
    """
    Função simulada.
    Por enquanto não chama MCP.
    """

    # Resultado conhecido aproximadamente para os pontos usados.
    distance_m = 1252.24

    return {
        "status": "OK",
        "distance_m": distance_m,
        "tx": {
            "lat": tx_lat,
            "lon": tx_lon,
        },
        "rx": {
            "lat": rx_lat,
            "lon": rx_lon,
        },
    }


tools = [
    {
        "type": "function",
        "name": "get_link_distance",
        "description": (
            "Calcula a distância entre dois pontos "
            "geográficos."
        ),
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
                },
            },
            "required": [
                "tx_lat",
                "tx_lon",
                "rx_lat",
                "rx_lon",
            ],
            "additionalProperties": False,
        },
    }
]


input_items = [
    {
        "role": "user",
        "content": (
            "Calcule a distância entre "
            "Praça da Sé (-23.5503898, -46.633081) "
            "e Praça da República (-23.5431712, -46.6425205). "
            "Use a ferramenta disponível."
        ),
    }
]


print("=" * 70)
print("TESTE OPENAI — FUNCTION CALL LOOP")
print("=" * 70)
print(f"Modelo: {MODEL}")
print()

try:

    # ------------------------------------------------------------
    # 1. Primeira chamada
    # ------------------------------------------------------------

    print("1. Enviando solicitação para a OpenAI...")
    print()

    response = client.responses.create(
        model=MODEL,
        input=input_items,
        tools=tools,
        tool_choice="required",
        reasoning={
            "effort": "none"
        },
    )

    print("✅ Primeira resposta recebida.")
    print()

    function_calls = [
        item
        for item in response.output
        if item.type == "function_call"
    ]

    if not function_calls:
        print("❌ Nenhum function_call foi retornado.")
        print(response.output)
        raise SystemExit(1)

    # ------------------------------------------------------------
    # 2. Executar os function calls
    # ------------------------------------------------------------

    tool_outputs = []

    for call in function_calls:

        print("=" * 70)
        print("FUNCTION CALL")
        print("=" * 70)

        print("Nome:", call.name)
        print("Call ID:", call.call_id)

        arguments = json.loads(call.arguments)

        print("Argumentos:")
        print(
            json.dumps(
                arguments,
                indent=2,
                ensure_ascii=False,
            )
        )

        if call.name == "get_link_distance":

            result = get_link_distance(
                **arguments
            )

        else:

            result = {
                "status": "ERROR",
                "error": (
                    f"Ferramenta desconhecida: "
                    f"{call.name}"
                ),
            }

        print()
        print("Resultado da função:")
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        tool_outputs.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(
                    result,
                    ensure_ascii=False,
                ),
            }
        )

    # ------------------------------------------------------------
    # 3. Enviar resultado da ferramenta para a OpenAI
    # ------------------------------------------------------------

    print()
    print("=" * 70)
    print("2. Enviando function_call_output para a OpenAI...")
    print("=" * 70)
    print()

    second_input = list(response.output)
    second_input.extend(tool_outputs)

    final_response = client.responses.create(
        model=MODEL,
        input=second_input,
        tools=tools,
        reasoning={
            "effort": "none"
        },
    )

    # ------------------------------------------------------------
    # 4. Resposta final
    # ------------------------------------------------------------

    print("✅ Segunda resposta recebida.")
    print()

    print("=" * 70)
    print("RESPOSTA FINAL DO MODELO")
    print("=" * 70)

    print(final_response.output_text)

    print()
    print("=" * 70)
    print("USAGE")
    print("=" * 70)

    print(final_response.usage)

    print()
    print("=" * 70)
    print("STATUS")
    print("=" * 70)

    print("✅ FUNCTION CALL LOOP FUNCIONOU!")

except Exception as e:

    print()
    print("=" * 70)
    print("❌ ERRO OPENAI")
    print("=" * 70)

    print("Tipo:", type(e).__name__)
    print("Mensagem:")
    print(str(e))

    if hasattr(e, "status_code"):
        print()
        print("status_code:", e.status_code)

    if hasattr(e, "code"):
        print("code:", e.code)

    if hasattr(e, "type"):
        print("type:", e.type)

    if hasattr(e, "param"):
        print("param:", e.param)

    if hasattr(e, "body"):
        print()
        print("body:")
        print(
            json.dumps(
                e.body,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )