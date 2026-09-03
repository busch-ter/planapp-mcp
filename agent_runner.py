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

# Número máximo de ciclos de decisão/tool
MAX_AGENT_ITERATIONS = 10

# Timeout das chamadas ao Ollama
OLLAMA_TIMEOUT = 300


# ============================================================
# OLLAMA
# ============================================================

def ask_ollama(messages, tools=None):

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "think": False,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=OLLAMA_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MCP TOOLS → FORMATO OLLAMA
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
# NORMALIZA ARGUMENTOS DA TOOL CALL
# ============================================================

def normalize_tool_arguments(arguments):

    if isinstance(arguments, dict):
        return arguments

    if isinstance(arguments, str):

        try:
            return json.loads(arguments)

        except json.JSONDecodeError:

            print()
            print("ERRO: argumentos da tool não são JSON válido:")
            print(arguments)

            return {}

    return {}


# ============================================================
# EXECUTA UMA TOOL MCP
# ============================================================

async def execute_mcp_tool(session, tool_name, arguments):

    print()
    print("┌" + "─" * 68 + "┐")
    print(f"│ MCP TOOL: {tool_name:<57} │")
    print("└" + "─" * 68 + "┘")

    print("Argumentos:")

    print(
        json.dumps(
            arguments,
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print("Executando...")

    result = await session.call_tool(
        tool_name,
        arguments,
    )

    print("✓ Tool executada")

    tool_result = ""

    for item in result.content:

        if hasattr(item, "text"):
            tool_result += item.text

    return tool_result


# ============================================================
# EXTRAI DADOS DO RESULTADO DO evaluate_link
# ============================================================

def extract_evaluate_link_data(tool_result):

    try:

        data = json.loads(tool_result)

    except Exception:

        return tool_result

    # --------------------------------------------------------
    # Se o resultado possui a estrutura normal do PlanApp
    # --------------------------------------------------------

    link_features = (
        data
        .get("link_features", {})
        .get("data")
    )

    if link_features is not None:

        return json.dumps(
            link_features,
            indent=2,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # Caso a estrutura seja diferente
    # --------------------------------------------------------

    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )


# ============================================================
# CHAMADA FINAL DO QWEN
#
# IMPORTANTE:
#
# Não enviamos todo o histórico do agente novamente.
#
# Enviamos somente:
#
#   - pedido original
#   - resultado final do evaluate_link
#
# Isso reduz bastante o contexto que o qwen3:8b precisa
# processar.
# ============================================================

def generate_final_analysis(user_request, evaluate_result):

    final_messages = [

        {
            "role": "system",
            "content": (
                "Você é o agente de IA do PlanApp, "
                "especializado em planejamento e avaliação "
                "de enlaces de rádio.\n\n"

                "O PlanApp acabou de executar uma avaliação "
                "real de um enlace.\n\n"

                "Analise exclusivamente os dados fornecidos "
                "pelo PlanApp.\n\n"

                "Não invente valores.\n"
                "Não invente parâmetros.\n"
                "Não invente uma classificação de viabilidade "
                "que não esteja presente nos dados.\n\n"

                "Apresente uma análise objetiva em português.\n\n"

                "Quando disponíveis, destaque:\n"
                "- distância do enlace;\n"
                "- perda de espaço livre (FSPL);\n"
                "- obstrução por terreno;\n"
                "- obstrução por vegetação;\n"
                "- obstrução por edificações;\n"
                "- região de Fresnel;\n"
                "- clearance próximo aos terminais;\n"
                "- demais indicadores relevantes retornados "
                "pelo PlanApp.\n\n"

                "Se os dados indicarem claramente algum problema "
                "de visada ou obstrução, explique-o.\n\n"

                "Se os dados não permitirem concluir sobre a "
                "viabilidade do enlace, deixe isso explicitamente "
                "claro."
            ),
        },

        {
            "role": "user",
            "content": (
                "Solicitação original:\n"
                f"{user_request}\n\n"

                "Resultado da avaliação realizada pelo PlanApp:\n"
                f"{evaluate_result}\n\n"

                "Faça a análise final do enlace."
            ),
        },
    ]

    result = ask_ollama(
        final_messages,
        tools=None,
    )

    return result["message"].get(
        "content",
        "",
    )


# ============================================================
# LOOP DO AGENTE
# ============================================================

async def agent_turn(
    session,
    messages,
    ollama_tools,
    user_request,
):

    evaluate_result = None

    # ========================================================
    # LOOP DE DECISÃO DO AGENTE
    # ========================================================

    for iteration in range(MAX_AGENT_ITERATIONS):

        print()
        print(
            f"[QWEN] Rodada {iteration + 1}"
        )

        # ----------------------------------------------------
        # CHAMA QWEN
        # ----------------------------------------------------

        result = ask_ollama(
            messages,
            tools=ollama_tools,
        )

        assistant_message = result["message"]

        tool_calls = assistant_message.get(
            "tool_calls",
            [],
        )

        # ----------------------------------------------------
        # GUARDA RESPOSTA DO ASSISTENTE
        # ----------------------------------------------------

        messages.append(
            assistant_message
        )

        print(
            f"[QWEN] tool_calls: {len(tool_calls)}"
        )

        # ----------------------------------------------------
        # SE NÃO HOUVER TOOL CALL
        # ----------------------------------------------------

        if not tool_calls:

            return assistant_message.get(
                "content",
                "",
            )

        # ----------------------------------------------------
        # EXECUTA TOOLS
        # ----------------------------------------------------

        for tool_call in tool_calls:

            function = tool_call["function"]

            tool_name = function["name"]

            arguments = normalize_tool_arguments(
                function.get(
                    "arguments",
                    {},
                )
            )

            # -----------------------------------------------
            # EXECUTA MCP
            # -----------------------------------------------

            tool_result = await execute_mcp_tool(
                session,
                tool_name,
                arguments,
            )

            # -----------------------------------------------
            # MOSTRA RESULTADO
            # -----------------------------------------------

            print()
            print(
                "Resultado retornado pelo PlanApp:"
            )

            print("-" * 70)

            print(tool_result)

            print("-" * 70)

            # -----------------------------------------------
            # DETECTA evaluate_link
            # -----------------------------------------------

            if tool_name == "evaluate_link":

                evaluate_result = tool_result

            # -----------------------------------------------
            # DEVOLVE RESULTADO AO QWEN
            # -----------------------------------------------

            messages.append(
                {
                    "role": "tool",
                    "content": tool_result,
                }
            )

        # ----------------------------------------------------
        # Se evaluate_link foi executado, não precisamos
        # continuar reenviando todo o histórico pesado ao Qwen.
        #
        # A análise final será feita com contexto reduzido.
        # ----------------------------------------------------

        if evaluate_result is not None:

            print()
            print(
                "[QWEN] Avaliação do enlace concluída."
            )

            print(
                "[QWEN] Gerando análise final..."
            )

            # -----------------------------------------------
            # Extrai somente os dados relevantes
            # -----------------------------------------------

            final_result = extract_evaluate_link_data(
                evaluate_result
            )

            # -----------------------------------------------
            # Chamada final isolada
            # -----------------------------------------------

            return generate_final_analysis(
                user_request,
                final_result,
            )

    # ========================================================
    # LIMITE DE SEGURANÇA
    # ========================================================

    return (
        "O agente atingiu o limite máximo de "
        f"{MAX_AGENT_ITERATIONS} rodadas de execução "
        "de ferramentas sem concluir a solicitação."
    )


# ============================================================
# CHAT
# ============================================================

async def main():

    print()
    print("=" * 70)
    print("PLANAPP AI AGENT")
    print("=" * 70)
    print()
    print(f"Modelo : {OLLAMA_MODEL}")
    print(f"Ollama : {OLLAMA_URL}")
    print(f"MCP    : {MCP_URL}")
    print()
    print("Digite sua solicitação.")
    print("Digite 'sair' para encerrar.")
    print()

    # ========================================================
    # CONECTA AO MCP
    # ========================================================

    print("Conectando ao MCP Server...")

    async with streamable_http_client(MCP_URL) as streams:

        async with ClientSession(*streams) as session:

            await session.initialize()

            print("✓ MCP conectado")
            print()

            # =================================================
            # OBTÉM TOOLS
            # =================================================

            result = await session.list_tools()

            mcp_tools = result.tools

            print("Tools disponíveis:")

            for tool in mcp_tools:

                print(
                    f"  ✓ {tool.name}"
                )

            print()

            ollama_tools = mcp_tools_to_ollama(
                mcp_tools
            )

            # =================================================
            # HISTÓRICO
            # =================================================

            messages = [

                {
                    "role": "system",
                    "content": (

                        "Você é o agente de IA do sistema "
                        "PlanApp, especializado em planejamento "
                        "e avaliação de enlaces de rádio."

                        "\n\n"

                        "Você possui ferramentas MCP que executam "
                        "operações reais no PlanApp."

                        "\n\n"

                        "Quando o usuário solicitar a análise "
                        "ou avaliação de um enlace entre dois "
                        "locais, conduza o processo completo."

                        "\n\n"

                        "Se os locais forem fornecidos por nome, "
                        "utilize geocode_place para obter suas "
                        "coordenadas."

                        "\n\n"

                        "Quando houver vários resultados de "
                        "geocoding, escolha o resultado "
                        "correspondente à cidade e ao estado "
                        "solicitados pelo usuário."

                        "\n\n"

                        "Depois de obter as coordenadas dos dois "
                        "terminais, utilize evaluate_link para "
                        "avaliar efetivamente o enlace."

                        "\n\n"

                        "IMPORTANTE: o geocoding é apenas uma "
                        "etapa intermediária. Não finalize a "
                        "resposta depois de obter coordenadas."

                        "\n\n"

                        "Não invente coordenadas."

                        "\n\n"

                        "Não invente resultados."

                        "\n\n"

                        "Utilize exclusivamente dados retornados "
                        "pelas ferramentas do PlanApp."

                        "\n\n"

                        "Depois que evaluate_link for executado, "
                        "considere a avaliação concluída."

                        "\n\n"

                        "Responda em português."
                    ),
                }
            ]

            # =================================================
            # LOOP DO CHAT
            # =================================================

            while True:

                try:

                    user_input = input(
                        "\nVocê: "
                    ).strip()

                except (
                    KeyboardInterrupt,
                    EOFError,
                ):

                    print()
                    print(
                        "Encerrando..."
                    )

                    break

                # ------------------------------------------------
                # LINHA VAZIA
                # ------------------------------------------------

                if not user_input:

                    continue

                # ------------------------------------------------
                # SAIR
                # ------------------------------------------------

                if user_input.lower() in {
                    "sair",
                    "exit",
                    "quit",
                }:

                    print()
                    print(
                        "Encerrando o agente."
                    )

                    break

                # ------------------------------------------------
                # GUARDA POSIÇÃO DO HISTÓRICO
                # ------------------------------------------------

                history_start = len(messages)

                # ------------------------------------------------
                # ADICIONA USUÁRIO
                # ------------------------------------------------

                messages.append(
                    {
                        "role": "user",
                        "content": user_input,
                    }
                )

                # ------------------------------------------------
                # PROCESSAMENTO
                # ------------------------------------------------

                print()
                print(
                    "Agente está processando..."
                )

                try:

                    answer = await agent_turn(
                        session,
                        messages,
                        ollama_tools,
                        user_input,
                    )

                    print()
                    print("Agente:")
                    print("-" * 70)
                    print(answer)
                    print("-" * 70)

                except Exception as e:

                    print()
                    print("ERRO:")
                    print(e)

                    # ------------------------------------------------
                    # RESTAURA HISTÓRICO ANTES DESTE TURNO
                    # ------------------------------------------------

                    del messages[
                        history_start:
                    ]
id="e8h4wp"
# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())

