# ============================================================
# PLANAPP AI — JUPYTER / OPENAI
# agent_jupyter.py
#
# Arquitetura:
#
# Jupyter
#    ↓
# OpenAI / GPT-5.6 Luna
#    ↓
# MCP PlanApp
#    ↓
# FastAPI / PlanApp
#
# O mapa NÃO é renderizado aqui.
# O agente apenas cria e armazena self.map.
# A Cell 2 é responsável pelo display().
#
# IMPORTANTE:
# A chave OpenAI deve estar na variável de ambiente:
#
#     OPENAI_API_KEY
#
# Não coloque a chave diretamente neste arquivo.
# ============================================================

import asyncio
import json
import os

from contextlib import AsyncExitStack

from openai import AsyncOpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÃO
# ============================================================

OPENAI_MODEL = "gpt-5.6-luna"

# Para a POC vamos começar com medium.
# O GPT-5.6 Luna suporta:
# none, low, medium, high, xhigh, max
OPENAI_REASONING_EFFORT = "medium"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "jupyter-user"

DEBUG = False

# Limite de iterações do agente
MAX_AGENT_ITERATIONS = 12


# ============================================================
# PLANAPP AGENT
# ============================================================

class PlanAppAgent:

    def __init__(self, progress_callback=None):

        self.progress_callback = progress_callback

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None
        self.mcp_tools = []

        self.openai_client = None

        self.messages = []

        self.user_id = USER_ID

        self.registered = False

        self.evaluate_executed = False

        self.geocoded_points = []

        self.map = None

        self.current_stage = None

        self.tool_count = 0

        self.last_evaluate_result = None

        # ====================================================
        # CONTROLE DE CONSUMO
        # ====================================================

        self.total_input_tokens = 0
        self.total_cached_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0

        self.total_cost_usd = 0.0

    # ========================================================
    # LOG
    # ========================================================

    def log(self, texto, tipo="processing"):

        if DEBUG:
            print(texto)

        if self.progress_callback:

            try:
                self.progress_callback(texto, tipo)

            except TypeError:
                self.progress_callback(texto)

            except Exception:
                pass

    # ========================================================
    # CONECTAR OPENAI
    # ========================================================

    def connect_openai(self):

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:

            raise RuntimeError(
                "OPENAI_API_KEY não está configurada. "
                "Configure a variável de ambiente antes "
                "de executar o agente."
            )

        self.openai_client = AsyncOpenAI(
            api_key=api_key
        )

        self.log(
            f"🟢 OpenAI configurada — modelo: {OPENAI_MODEL}"
        )

    # ========================================================
    # CONECTAR MCP
    # ========================================================

    async def connect(self):

        try:

            # ----------------------------------------------
            # OpenAI
            # ----------------------------------------------

            self.connect_openai()

            # ----------------------------------------------
            # MCP
            # ----------------------------------------------

            transport = await self.exit_stack.enter_async_context(
                streamable_http_client(MCP_URL)
            )

            read_stream, write_stream = transport

            self.mcp_session = (
                await self.exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream
                    )
                )
            )

            await self.mcp_session.initialize()

            tools_result = (
                await self.mcp_session.list_tools()
            )

            self.mcp_tools = tools_result.tools

            self.log(
                f"🟢 MCP conectado — "
                f"{len(self.mcp_tools)} ferramentas disponíveis."
            )

        except Exception:
            raise

    # ========================================================
    # CONVERTER FERRAMENTAS MCP → OPENAI
    # ========================================================

    def build_openai_tools(self):

        tools = []

        for tool in self.mcp_tools:

            # register é executado diretamente pelo agente.
            # Não precisa ser exposto ao modelo.
            if tool.name == "register":
                continue

            schema = tool.input_schema

            tools.append(
                {
                    "type": "function",

                    "function": {
                        "name": tool.name,

                        "description": (
                            tool.description or ""
                        ),

                        "parameters": schema,
                    },
                }
            )

        return tools

    # ========================================================
    # RESET
    # ========================================================

    def reset_state(self):

        self.messages = []

        self.registered = False

        self.evaluate_executed = False

        self.geocoded_points = []

        self.map = None

        self.current_stage = None

        self.tool_count = 0

        self.last_evaluate_result = None

        # consumo
        self.total_input_tokens = 0
        self.total_cached_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0

        self.total_cost_usd = 0.0

    # ========================================================
    # REGISTRAR SESSÃO PLANAPP
    # ========================================================

    async def register_session(self):

        self.log(
            "🔵 Registrando sessão no PlanApp"
        )

        self.log(
            "🔧 MCP: register"
        )

        result = await self.mcp_session.call_tool(
            "register",
            {
                "user_id": self.user_id
            }
        )

        self.registered = True

        self.log(
            "🟢 Sessão PlanApp registrada."
        )

        return result

    # ========================================================
    # PARSE MCP RESULT
    # ========================================================

    def parse_mcp_result(self, result):

        if result is None:
            return None

        if hasattr(result, "content"):

            content = result.content

            if content:

                for item in content:

                    if hasattr(item, "text"):

                        text = item.text

                        try:
                            return json.loads(text)

                        except Exception:
                            return text

        if hasattr(result, "structuredContent"):

            return result.structuredContent

        return result

    # ========================================================
    # BUSCA RECURSIVA
    # ========================================================

    def recursive_find(self, obj, keys):

        if isinstance(obj, dict):

            for key in keys:

                if key in obj:
                    return obj[key]

            for value in obj.values():

                result = self.recursive_find(
                    value,
                    keys
                )

                if result is not None:
                    return result

        elif isinstance(obj, list):

            for item in obj:

                result = self.recursive_find(
                    item,
                    keys
                )

                if result is not None:
                    return result

        return None

    # ========================================================
    # EXTRAIR COORDENADAS
    # ========================================================

    def extract_coordinates(self, result):

        latitude = self.recursive_find(
            result,
            [
                "lat",
                "latitude",
                "y"
            ]
        )

        longitude = self.recursive_find(
            result,
            [
                "lon",
                "lng",
                "longitude",
                "x"
            ]
        )

        if latitude is None or longitude is None:
            return None

        try:

            return (
                float(latitude),
                float(longitude)
            )

        except Exception:

            return None

    # ========================================================
    # REGISTRAR PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(
        self,
        result,
        arguments
    ):

        coords = self.extract_coordinates(
            result
        )

        if coords is None:
            return

        lat, lon = coords

        name = (
            arguments.get("query")
            or arguments.get("place")
            or arguments.get("name")
            or f"Ponto {len(self.geocoded_points) + 1}"
        )

        point = {
            "name": str(name),
            "lat": lat,
            "lon": lon,
        }

        self.geocoded_points.append(point)

    # ========================================================
    # RESUMO GEOCODE
    # ========================================================

    def summarize_geocode(self, result):

        coords = self.extract_coordinates(
            result
        )

        if coords is None:
            return ""

        lat, lon = coords

        return (
            f"{lat:.7f}, {lon:.7f}"
        )

    # ========================================================
    # RESUMO EVALUATE
    # ========================================================

    def summarize_evaluate(self, result):

        fspl = self.recursive_find(
            result,
            [
                "fspl_db",
                "fspl",
                "FSPL"
            ]
        )

        if fspl is None:
            return None

        try:

            return float(fspl)

        except Exception:

            return fspl

    # ========================================================
    # CALCULAR CUSTO
    # ========================================================

    def update_usage(self, usage):

        if usage is None:
            return

        try:

            input_tokens = (
                getattr(
                    usage,
                    "prompt_tokens",
                    0
                )
                or 0
            )

            output_tokens = (
                getattr(
                    usage,
                    "completion_tokens",
                    0
                )
                or 0
            )

            cached_tokens = 0

            prompt_details = getattr(
                usage,
                "prompt_tokens_details",
                None
            )

            if prompt_details:

                cached_tokens = (
                    getattr(
                        prompt_details,
                        "cached_tokens",
                        0
                    )
                    or 0
                )

            self.total_input_tokens += (
                input_tokens
            )

            self.total_cached_tokens += (
                cached_tokens
            )

            self.total_output_tokens += (
                output_tokens
            )

            self.total_tokens += (
                input_tokens +
                output_tokens
            )

            # =================================================
            # GPT-5.6 Luna — preços atuais
            #
            # Input:
            # US$ 0.20 / 1M
            #
            # Cached input:
            # US$ 0.02 / 1M
            #
            # Output:
            # US$ 1.20 / 1M
            # =================================================

            non_cached_input = max(
                0,
                input_tokens - cached_tokens
            )

            cost_input = (
                non_cached_input
                / 1_000_000
                * 0.20
            )

            cost_cached = (
                cached_tokens
                / 1_000_000
                * 0.02
            )

            cost_output = (
                output_tokens
                / 1_000_000
                * 1.20
            )

            request_cost = (
                cost_input
                + cost_cached
                + cost_output
            )

            self.total_cost_usd += (
                request_cost
            )

            self.log(
                "💰 OpenAI — "
                f"input={input_tokens:,} "
                f"(cache={cached_tokens:,}), "
                f"output={output_tokens:,}, "
                f"custo≈US$ {request_cost:.6f}"
            )

        except Exception as e:

            self.log(
                f"⚠️ Não foi possível "
                f"calcular consumo: {e}"
            )

    # ========================================================
    # EXECUTAR FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments
    ):

        # ----------------------------------------------
        # Proteção contra evaluate duplicado
        # ----------------------------------------------

        if (
            tool_name == "evaluate_link"
            and self.evaluate_executed
        ):

            self.log(
                "⚠️ evaluate_link já foi executado. "
                "Ignorando chamada duplicada."
            )

            return self.last_evaluate_result

        self.tool_count += 1

        self.log(
            f"🔧 MCP: {tool_name}"
        )

        result = await self.mcp_session.call_tool(
            tool_name,
            arguments or {}
        )

        parsed = self.parse_mcp_result(
            result
        )

        # ----------------------------------------------
        # GEOCODE
        # ----------------------------------------------

        if tool_name == "geocode_place":

            summary = self.summarize_geocode(
                parsed
            )

            if summary:

                self.log(summary)

            self.register_geocoded_point(
                parsed,
                arguments or {}
            )

            if len(
                self.geocoded_points
            ) >= 2:

                await self.mostrar_mapa_apos_geocodificacao()

        # ----------------------------------------------
        # EVALUATE LINK
        # ----------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = (
                parsed
            )

            fspl = self.summarize_evaluate(
                parsed
            )

            if fspl is not None:

                try:

                    self.log(
                        f"📥 FSPL: "
                        f"{float(fspl):.2f} dB"
                    )

                except Exception:

                    self.log(
                        f"📥 FSPL: {fspl}"
                    )

        return parsed

    # ========================================================
    # MAPA
    # ========================================================

    async def mostrar_mapa_apos_geocodificacao(
        self
    ):

        if len(
            self.geocoded_points
        ) < 2:

            return

        try:

            self.log(
                "🗺️ Preparando enlace no mapa..."
            )

            self.map = (
                mostrar_mapa_enlace(
                    self
                )
            )

            self.log(
                "🟢 Mapa preparado."
            )

        except Exception as e:

            self.log(
                "⚠️ Não foi possível preparar "
                f"o mapa: {e}"
            )

    # ========================================================
    # GARANTIR EVALUATE LINK
    # ========================================================

    async def ensure_evaluate_link(self):

        if self.evaluate_executed:
            return

        if len(
            self.geocoded_points
        ) < 2:

            return

        tx = self.geocoded_points[0]

        rx = self.geocoded_points[1]

        arguments = {

            "tx_lat": tx["lat"],

            "tx_lon": tx["lon"],

            "rx_lat": rx["lat"],

            "rx_lon": rx["lon"],

            "tx_ha": 7,

            "rx_ha": 7,

            "freq_mhz": 900,

            "on_rooftop": False,
        }

        self.current_stage = 2

        self.log(
            "🔵 Etapa 2 — Avaliando o enlace"
        )

        await self.execute_mcp_tool(
            "evaluate_link",
            arguments
        )

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o agente de IA do PlanApp.

Sua função é interpretar solicitações de planejamento
e utilizar as ferramentas MCP do PlanApp para obter
informações geoespaciais e de enlaces de rádio.

REGRAS IMPORTANTES:

1. O PlanApp é a fonte de verdade para os cálculos.

2. Nunca invente valores técnicos.

3. Nunca recalcule valores fornecidos pelo PlanApp
   usando fórmulas próprias.

4. Não altere ou substitua valores retornados pelas
   ferramentas.

5. Utilize geocode_place para localizar os pontos
   solicitados pelo usuário.

6. Depois que os dois pontos forem localizados,
   utilize evaluate_link para obter os resultados
   técnicos do enlace.

7. Distância, FSPL, difração, obstruções, clearance,
   terreno, edifícios e demais parâmetros devem ser
   apresentados exatamente de acordo com os dados
   retornados pelo PlanApp.

8. Não interprete clearance como altura de antena.

9. Não invente potência, ganho de antena, sensibilidade,
   margem de enlace ou qualquer outro parâmetro que
   não tenha sido fornecido.

10. Não declare que um enlace é viável ou inviável
    apenas com base em distância, FSPL, difração ou
    obstruções.

11. Se os dados disponíveis não forem suficientes para
    determinar a viabilidade completa do enlace, diga
    explicitamente que são necessários outros parâmetros.

12. Faça uma interpretação técnica objetiva dos dados
    efetivamente fornecidos pelo PlanApp.

13. Não mencione detalhes internos de MCP, chamadas HTTP,
    sessões ou implementação, a menos que o usuário
    pergunte especificamente.

14. Responda em português.

A análise deve ser baseada nos dados reais retornados
pelas ferramentas.
"""

    # ========================================================
    # OPENAI CHAT
    # ========================================================

    async def openai_chat(self):

        tools = self.build_openai_tools()

        response = await (
            self.openai_client.chat.completions.create(

                model=OPENAI_MODEL,

                messages=self.messages,

                tools=tools,

                tool_choice="auto",

                reasoning_effort=(
                    OPENAI_REASONING_EFFORT
                ),
            )
        )

        self.update_usage(
            response.usage
        )

        return response

    # ========================================================
    # AGENT TURN
    # ========================================================

    async def agent_turn(self):

        for _ in range(
            MAX_AGENT_ITERATIONS
        ):

            response = await (
                self.openai_chat()
            )

            message = (
                response.choices[0].message
            )

            # ----------------------------------------------
            # ASSISTANT MESSAGE
            # ----------------------------------------------

            assistant_message = {

                "role": "assistant",

                "content": (
                    message.content
                    or ""
                ),
            }

            # ----------------------------------------------
            # TOOL CALLS
            # ----------------------------------------------

            tool_calls = (
                message.tool_calls
                or []
            )

            if tool_calls:

                assistant_message[
                    "tool_calls"
                ] = [

                    {
                        "id": tool_call.id,

                        "type": "function",

                        "function": {

                            "name": (
                                tool_call.function.name
                            ),

                            "arguments": (
                                tool_call.function.arguments
                            ),
                        },
                    }

                    for tool_call
                    in tool_calls
                ]

            self.messages.append(
                assistant_message
            )

            # ----------------------------------------------
            # SEM TOOL CALL
            # ----------------------------------------------

            if not tool_calls:

                if (
                    len(
                        self.geocoded_points
                    ) >= 2

                    and not self.evaluate_executed
                ):

                    await (
                        self.ensure_evaluate_link()
                    )

                    self.messages.append(
                        {
                            "role": "user",

                            "content": (
                                "Agora interprete "
                                "os resultados "
                                "retornados "
                                "pelo PlanApp."
                            ),
                        }
                    )

                    continue

                self.current_stage = 3

                self.log(
                    "🔵 Etapa 3 — "
                    "Interpretando resultados"
                )

                return (
                    message.content
                    or ""
                )

            # ----------------------------------------------
            # EXECUTAR TODAS AS TOOLS
            # ----------------------------------------------

            for tool_call in tool_calls:

                function = (
                    tool_call.function
                )

                tool_name = (
                    function.name
                )

                arguments_text = (
                    function.arguments
                )

                try:

                    arguments = json.loads(
                        arguments_text
                    )

                except Exception:

                    arguments = {}

                result = await (
                    self.execute_mcp_tool(
                        tool_name,
                        arguments
                    )
                )

                # ------------------------------------------
                # FORMATO EXIGIDO PELA OPENAI
                # ------------------------------------------

                self.messages.append(
                    {
                        "role": "tool",

                        "tool_call_id": (
                            tool_call.id
                        ),

                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

            # ----------------------------------------------
            # GARANTIR EVALUATE
            # ----------------------------------------------

            if (
                len(
                    self.geocoded_points
                ) >= 2

                and not self.evaluate_executed
            ):

                await (
                    self.ensure_evaluate_link()
                )

                self.messages.append(
                    {
                        "role": "user",

                        "content": (
                            "Os dois pontos "
                            "foram localizados. "
                            "Utilize agora os "
                            "dados do PlanApp "
                            "para interpretar "
                            "o enlace."
                        ),
                    }
                )

        return (
            "O agente atingiu o limite de "
            "iterações sem concluir a análise."
        )

    # ========================================================
    # ASK
    # ========================================================

    async def ask(
        self,
        user_message
    ):

        try:

            self.reset_state()

            await self.connect()

            await self.register_session()

            self.current_stage = 1

            self.log(
                "🔵 Etapa 1 — "
                "Localizando os pontos"
            )

            self.messages = [

                {
                    "role": "system",

                    "content": (
                        self.system_prompt()
                    ),
                },

                {
                    "role": "user",

                    "content": user_message,
                },
            ]

            try:

                answer = await (
                    self.agent_turn()
                )

            except Exception as e:

                import traceback

                self.log(
                    "❌ Erro durante execução "
                    "do agente: "
                    f"{type(e).__name__}: {e}"
                )

                traceback.print_exc()

                return (
                    "Erro durante a execução: "
                    f"{type(e).__name__}: {e}"
                )

            # ------------------------------------------
            # RESUMO DE CONSUMO
            # ------------------------------------------

            self.log(
                "📊 Consumo desta análise — "
                f"input={self.total_input_tokens:,}, "
                f"cache={self.total_cached_tokens:,}, "
                f"output={self.total_output_tokens:,}, "
                f"total={self.total_tokens:,}, "
                f"custo≈US$ {self.total_cost_usd:.6f}"
            )

            if self.evaluate_executed:

                self.log(
                    "🟢 Análise concluída",
                    "success"
                )

            return answer

        except Exception as e:

            import traceback

            self.log(
                "❌ Erro durante execução "
                f"do agente: "
                f"{type(e).__name__}: {e}",

                "error"
            )

            traceback.print_exc()

            return (
                "Erro durante a execução: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        except Exception:

            pass


# ============================================================
# FUNÇÃO PRINCIPAL USADA PELO JUPYTER
# ============================================================

async def run_agent(
    user_message,
    progress_callback=None
):

    agent = PlanAppAgent(
        progress_callback=progress_callback
    )

    try:

        return await agent.ask(
            user_message
        )

    finally:

        await agent.close()