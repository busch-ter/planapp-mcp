# ============================================================
# PLANAPP AI — JUPYTER
# agent_jupyter.py
# ============================================================

import asyncio
import json

from contextlib import AsyncExitStack

import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÃO
# ============================================================

OLLAMA_URL = "http://172.17.0.1:11434"

OLLAMA_MODEL = "qwen3:8b"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "jupyter-user"

OLLAMA_TIMEOUT = 300.0

DEBUG = False


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(self, progress_callback=None):

        self.progress_callback = progress_callback

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None

        self.mcp_tools = []

        self.messages = []

        self.user_id = USER_ID

        self.registered = False

        self.evaluate_executed = False

        self.geocoded_points = []

        # ----------------------------------------------------
        # Objeto ipyleaflet.Map
        # ----------------------------------------------------

        self.map = None

        self.current_stage = None

        self.tool_count = 0

        self.last_evaluate_result = None

    # ========================================================
    # LOG
    # ========================================================

    def log(
        self,
        texto,
        tipo="processing"
    ):

        if DEBUG:
            print(texto)

        if self.progress_callback:

            try:

                self.progress_callback(
                    texto,
                    tipo
                )

            except TypeError:

                try:

                    self.progress_callback(
                        texto
                    )

                except Exception:
                    pass

            except Exception:

                pass

    # ========================================================
    # CONNECT
    # ========================================================

    async def connect(self):
    
        transport = (
            await self.exit_stack.enter_async_context(
                streamable_http_client(
                    MCP_URL
                )
            )
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

    # ========================================================
    # BUILD OLLAMA TOOLS
    # ========================================================
    def build_ollama_tools(self):
    
        tools = []
    
        for tool in self.mcp_tools:
    
            # ----------------------------------------------------
            # register:
            # executado diretamente pelo agente.
            # ----------------------------------------------------
    
            if tool.name == "register":
                continue
    
            # ----------------------------------------------------
            # evaluate_link:
            # executado automaticamente pelo agente quando os
            # dois pontos forem geocodificados.
            #
            # Não deve ser exposto ao Qwen, para evitar chamada
            # duplicada.
            # ----------------------------------------------------
    
            if tool.name == "evaluate_link":
                continue
    
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": (
                            tool.description
                            or ""
                        ),
                        "parameters": (
                            tool.input_schema
                        ),
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

    # ========================================================
    # REGISTER
    # ========================================================

    async def register_session(self):

        self.log(
            "🔵 Registrando sessão no PlanApp"
        )

        self.log(
            "🔧 MCP: register"
        )

        await self.mcp_session.call_tool(
            "register",
            {
                "user_id": self.user_id
            }
        )

        self.registered = True

        self.log(
            "🟢 Sessão PlanApp registrada."
        )

    # ========================================================
    # PARSE MCP RESULT
    # ========================================================

    def parse_mcp_result(
        self,
        result
    ):

        if result is None:
            return None

        if hasattr(
            result,
            "content"
        ):

            content = result.content

            if content:

                for item in content:

                    if hasattr(
                        item,
                        "text"
                    ):

                        text = item.text

                        try:

                            return json.loads(
                                text
                            )

                        except Exception:

                            return text

        if hasattr(
            result,
            "structuredContent"
        ):

            return result.structuredContent

        return result

    # ========================================================
    # RECURSIVE FIND
    # ========================================================

    def recursive_find(
        self,
        obj,
        keys
    ):

        if isinstance(
            obj,
            dict
        ):

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

        elif isinstance(
            obj,
            list
        ):

            for item in obj:

                result = self.recursive_find(
                    item,
                    keys
                )

                if result is not None:

                    return result

        return None

    # ========================================================
    # EXTRACT COORDINATES
    # ========================================================

    def extract_coordinates(
        self,
        result
    ):

        latitude = self.recursive_find(
            result,
            [
                "lat",
                "latitude",
                "y",
            ]
        )

        longitude = self.recursive_find(
            result,
            [
                "lon",
                "lng",
                "longitude",
                "x",
            ]
        )

        if (
            latitude is None
            or longitude is None
        ):

            return None

        try:

            return (
                float(latitude),
                float(longitude)
            )

        except Exception:

            return None

    # ========================================================
    # REGISTER GEOCODED POINT
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
            or (
                f"Ponto "
                f"{len(self.geocoded_points) + 1}"
            )
        )

        self.geocoded_points.append(
            {
                "name": str(name),
                "lat": lat,
                "lon": lon,
            }
        )

    # ========================================================
    # GEOCODE SUMMARY
    # ========================================================

    def summarize_geocode(
        self,
        result
    ):

        coords = self.extract_coordinates(
            result
        )

        if coords is None:
            return ""

        lat, lon = coords

        return (
            f"{lat:.7f}, "
            f"{lon:.7f}"
        )

    # ========================================================
    # EVALUATE SUMMARY
    # ========================================================

    def summarize_evaluate(
        self,
        result
    ):

        fspl = self.recursive_find(
            result,
            [
                "fspl_db",
                "fspl",
                "FSPL",
            ]
        )

        if fspl is None:
            return None

        try:

            return float(fspl)

        except Exception:

            return fspl

    # ========================================================
    # EXECUTE MCP TOOL
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments
    ):

        # ----------------------------------------------------
        # Evita evaluate_link duplicado
        # ----------------------------------------------------

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

        result = (
            await self.mcp_session.call_tool(
                tool_name,
                arguments or {}
            )
        )

        parsed = self.parse_mcp_result(
            result
        )

        # ====================================================
        # GEOCODE
        # ====================================================

        if tool_name == "geocode_place":

            summary = self.summarize_geocode(
                parsed
            )

            if summary:

                self.log(
                    summary
                )

            self.register_geocoded_point(
                parsed,
                arguments or {}
            )

            # ------------------------------------------------
            # Quando os dois pontos existem,
            # cria o mapa.
            # ------------------------------------------------

            if len(
                self.geocoded_points
            ) >= 2:

                await self.mostrar_mapa_apos_geocodificacao()

        # ====================================================
        # EVALUATE
        # ====================================================

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = parsed

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
    # PREPARA MAPA
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

            # ------------------------------------------------
            # Diagnóstico interno
            # ------------------------------------------------

            self.log(
                "🟢 Mapa preparado."
            )

        except Exception as e:

            self.map = None

            self.log(
                f"⚠️ Não foi possível preparar "
                f"o mapa: {e}"
            )

    # ========================================================
    # ENSURE EVALUATE
    # ========================================================

    async def ensure_evaluate_link(
        self
    ):

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

    def system_prompt(
        self
    ):

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
    # OLLAMA CHAT
    # ========================================================

    async def ollama_chat(
        self
    ):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
        }

        async with httpx.AsyncClient(
            timeout=OLLAMA_TIMEOUT
        ) as client:

            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload
            )

            response.raise_for_status()

            return response.json()

    # ========================================================
    # AGENT TURN
    # ========================================================
    async def agent_turn(
            self
        ):
    
            for _ in range(12):
    
                response = (
                    await self.ollama_chat()
                )
    
                message = response.get(
                    "message",
                    {}
                )
    
                tool_calls = message.get(
                    "tool_calls",
                    []
                )
    
                content = message.get(
                    "content",
                    ""
                )
    
                assistant_message = {
                    "role": "assistant",
                    "content": content,
                }
    
                if tool_calls:
    
                    assistant_message[
                        "tool_calls"
                    ] = tool_calls
    
                self.messages.append(
                    assistant_message
                )
    
                # ------------------------------------------------
                # SEM FERRAMENTAS
                # ------------------------------------------------
    
                if not tool_calls:
    
                    # ------------------------------------------------
                    # Se os dois pontos já foram encontrados e o
                    # enlace ainda não foi avaliado, executa agora.
                    # ------------------------------------------------
    
                    if (
                        len(
                            self.geocoded_points
                        ) >= 2
                        and not self.evaluate_executed
                    ):
    
                        await self.ensure_evaluate_link()
    
                        self.messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "O PlanApp já executou a "
                                    "avaliação do enlace. "
                                    "Agora interprete exclusivamente "
                                    "os resultados retornados pelo "
                                    "PlanApp, sem recalcular os "
                                    "valores."
                                ),
                            }
                        )
    
                        continue
    
                    # ------------------------------------------------
                    # Avaliação já realizada.
                    # Agora estamos na interpretação.
                    # ------------------------------------------------
    
                    self.current_stage = 3
    
                    self.log(
                        "🔵 Etapa 3 — "
                        "Interpretando resultados"
                    )
    
                    return content
    
                # ------------------------------------------------
                # FERRAMENTAS
                # ------------------------------------------------
    
                for tool_call in tool_calls:
    
                    function = tool_call.get(
                        "function",
                        {}
                    )
    
                    tool_name = function.get(
                        "name"
                    )
    
                    arguments = function.get(
                        "arguments",
                        {}
                    )
    
                    if isinstance(
                        arguments,
                        str
                    ):
    
                        try:
    
                            arguments = json.loads(
                                arguments
                            )
    
                        except Exception:
    
                            arguments = {}
    
                    result = (
                        await self.execute_mcp_tool(
                            tool_name,
                            arguments
                        )
                    )
    
                    self.messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result,
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                    )
    
                # ------------------------------------------------
                # GARANTIA DE EVALUATE
                #
                # Depois que todas as ferramentas solicitadas
                # pelo Qwen foram executadas, verificamos se já
                # existem dois pontos.
                # ------------------------------------------------
    
                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):
    
                    await self.ensure_evaluate_link()
    
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Os dois pontos foram "
                                "localizados e o PlanApp "
                                "já executou a avaliação "
                                "do enlace. Utilize agora "
                                "os dados retornados pelo "
                                "PlanApp para interpretar "
                                "os resultados. Não execute "
                                "novamente nenhuma avaliação."
                            ),
                        }
                    )
    
            return (
                "O agente atingiu o limite de iterações "
                "sem concluir a análise."
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
                    "content": self.system_prompt(),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ]

            try:

                answer = (
                    await self.agent_turn()
                )

            except Exception as e:

                import traceback

                self.log(
                    f"❌ Erro durante execução "
                    f"do agente: "
                    f"{type(e).__name__}: {e}",
                    "error"
                )

                traceback.print_exc()

                return (
                    f"Erro durante a execução: "
                    f"{type(e).__name__}: {e}"
                )

            # =================================================
            # DIAGNÓSTICO FINAL DO MAPA
            # =================================================

            if self.map is not None:

                self.log(
                    "🗺️ Objeto do mapa disponível."
                )

            else:

                self.log(
                    "⚠️ Nenhum objeto de mapa disponível."
                )

            # =================================================
            # CONCLUSÃO
            # =================================================

            if self.evaluate_executed:

                self.log(
                    "🟢 Análise concluída",
                    "success"
                )

            return answer

        except Exception as e:

            import traceback

            self.log(
                f"❌ Erro durante execução "
                f"do agente: "
                f"{type(e).__name__}: {e}",
                "error"
            )

            traceback.print_exc()

            return (
                f"Erro durante a execução: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(
        self
    ):

        try:

            await self.exit_stack.aclose()

        except Exception:

            pass


# ============================================================
# RUN AGENT
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