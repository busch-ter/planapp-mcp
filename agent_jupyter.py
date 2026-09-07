import asyncio
import json
import os
from contextlib import AsyncExitStack

import requests

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp"
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b"
)

USER_ID = "jupyter-user"


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(
        self,
        progress_callback=None,
        map_callback=None
    ):

        self.progress_callback = (
            progress_callback
        )

        self.map_callback = (
            map_callback
        )

        self.exit_stack = (
            AsyncExitStack()
        )

        self.mcp_session = None
        self.mcp_tools = []

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.tool_count = 0

        self.current_stage = 0

        self.map = None

        self.connected = False


    # ========================================================
    # LOG
    # ========================================================

    def log(self, message):

        if self.progress_callback:

            try:
                self.progress_callback(
                    message
                )

            except Exception:
                pass


    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o assistente de planejamento de enlaces de rádio do PlanApp.

Sua função é interpretar solicitações de planejamento de enlaces,
utilizando as ferramentas disponibilizadas pelo PlanApp.

REGRAS IMPORTANTES:

1. PlanApp é a fonte de verdade dos dados técnicos.

2. Nunca invente valores técnicos.

3. Nunca altere valores retornados pelo PlanApp.

4. Nunca recalcule parâmetros técnicos que já tenham sido calculados
   pelo PlanApp.

5. Quando o usuário fornecer dois locais, utilize geocode_place para
   localizar os pontos.

6. Depois que os dois pontos forem geocodificados, o PlanApp executará
   automaticamente a avaliação técnica do enlace.

7. Não solicite novamente evaluate_link.

8. Não tente executar evaluate_link diretamente.

9. Utilize exclusivamente os resultados técnicos fornecidos pelo
   PlanApp para interpretar o enlace.

10. Preserve os valores e unidades retornados pelo PlanApp.

11. FSPL significa:
    Free-Space Path Loss
    (Perda de Propagação no Espaço Livre).

12. Não trate clearance como altura de antena.

13. Não diga que um clearance é "adequado", "insuficiente",
    "seguro" ou equivalente sem que exista um critério técnico
    explícito fornecido pelo PlanApp.

14. Não conclua que um enlace é viável ou inviável apenas a partir
    de distância, FSPL, difração ou clearance.

15. Para afirmar viabilidade de um enlace de rádio, são necessários,
    conforme o caso, parâmetros como potência de transmissão,
    ganhos das antenas, frequência, perdas adicionais, sensibilidade
    do receptor e margem de enlace.

16. Não atribua significado físico a um campo cujo significado não
    esteja explicitamente informado pelo PlanApp.

17. Quando houver dúvida sobre o significado de um campo, mantenha
    o nome original do campo e informe que seu significado deve ser
    confirmado no PlanApp.

18. Responda em português.

19. Seja técnico, objetivo e claro.

20. Não mencione detalhes internos da implementação do agente,
    MCP ou Ollama ao usuário, a menos que ele pergunte explicitamente.
"""


    # ========================================================
    # CONEXÃO MCP
    # ========================================================

    async def connect(self):

        if self.connected:
            return

        self.log(
            "🔌 Conectando ao PlanApp MCP..."
        )

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

        self.mcp_tools = (
            tools_result.tools
        )

        self.connected = True

        self.log(
            f"🟢 MCP conectado — "
            f"{len(self.mcp_tools)} ferramentas disponíveis."
        )


    # ========================================================
    # FERRAMENTAS PARA O OLLAMA
    # ========================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.mcp_tools:

            # register é executado diretamente pelo agente
            if tool.name == "register":
                continue

            # evaluate_link é executado automaticamente pelo agente
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
    # CHAMADA AO OLLAMA
    # ========================================================

    async def ollama_chat(self):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
        }

        response = await asyncio.to_thread(
            requests.post,
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=300,
        )

        response.raise_for_status()

        return response.json()


    # ========================================================
    # PARSE RESULTADO MCP
    # ========================================================

    def parse_mcp_result(self, result):

        # ----------------------------------------------------
        # MCP moderno
        # ----------------------------------------------------

        if hasattr(result, "structuredContent"):

            structured = (
                result.structuredContent
            )

            if structured:
                return structured

        # Alguns clientes utilizam structured_content

        if hasattr(result, "structured_content"):

            structured = (
                result.structured_content
            )

            if structured:
                return structured

        # ----------------------------------------------------
        # Conteúdo textual
        # ----------------------------------------------------

        content = getattr(
            result,
            "content",
            None
        )

        if content:

            texts = []

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None
                )

                if text is not None:
                    texts.append(text)

            if texts:

                text = "\n".join(texts)

                try:
                    return json.loads(text)

                except Exception:
                    return {
                        "text": text
                    }

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        return result


    # ========================================================
    # RESUMO GEOCODIFICAÇÃO
    # ========================================================

    def summarize_geocode(self, result):

        if not isinstance(
            result,
            dict
        ):
            return None

        name = (
            result.get("name")
            or result.get("place")
            or result.get("query")
        )

        lat = result.get("lat")
        lon = result.get("lon")

        if lat is not None and lon is not None:

            if name:

                return (
                    f"📍 {name}: "
                    f"{float(lat):.6f}, "
                    f"{float(lon):.6f}"
                )

            return (
                f"📍 Ponto localizado: "
                f"{float(lat):.6f}, "
                f"{float(lon):.6f}"
            )

        return None


    # ========================================================
    # RESUMO EVALUATE
    # ========================================================

    def summarize_evaluate(self, result):

        if not isinstance(
            result,
            dict
        ):
            return None

        # Procura FSPL em possíveis estruturas

        fspl = result.get(
            "fspl"
        )

        if fspl is None:

            fspl = result.get(
                "FSPL"
            )

        if fspl is None:

            technical = result.get(
                "technical"
            )

            if isinstance(
                technical,
                dict
            ):

                fspl = technical.get(
                    "fspl"
                )

        return fspl


    # ========================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(
        self,
        result,
        arguments
    ):

        if not isinstance(
            result,
            dict
        ):
            return

        lat = result.get(
            "lat"
        )

        lon = result.get(
            "lon"
        )

        if lat is None:
            lat = result.get(
                "latitude"
            )

        if lon is None:
            lon = result.get(
                "longitude"
            )

        if lat is None or lon is None:
            return

        name = (
            result.get("name")
            or result.get("place")
            or result.get("query")
            or arguments.get("query")
            or f"Ponto {len(self.geocoded_points) + 1}"
        )

        point = {
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
        }

        self.geocoded_points.append(
            point
        )


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

        self.log(
            "🗺️ Preparando enlace no mapa..."
        )

        try:

            self.map = (
                mostrar_mapa_enlace(
                    self
                )
            )

            # ------------------------------------------------
            # ATUALIZA A INTERFACE IMEDIATAMENTE
            # ------------------------------------------------

            if self.map_callback:

                try:

                    self.map_callback(
                        self.map
                    )

                except Exception as exc:

                    self.log(
                        f"⚠️ Erro ao atualizar mapa: "
                        f"{exc}"
                    )

            self.log(
                "🟢 Mapa preparado."
            )

        except Exception as exc:

            self.log(
                f"❌ Erro ao preparar mapa: "
                f"{exc}"
            )


    # ========================================================
    # EXECUTA FERRAMENTA MCP
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

            return (
                self.last_evaluate_result
            )

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

        parsed = (
            self.parse_mcp_result(
                result
            )
        )

        # ----------------------------------------------------
        # GEOCODE
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            summary = (
                self.summarize_geocode(
                    parsed
                )
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
            # SEGUNDO PONTO
            # ------------------------------------------------

            if len(
                self.geocoded_points
            ) >= 2:

                await (
                    self.mostrar_mapa_apos_geocodificacao()
                )

        # ----------------------------------------------------
        # EVALUATE
        # ----------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = (
                parsed
            )

            fspl = (
                self.summarize_evaluate(
                    parsed
                )
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
    # REGISTER
    # ========================================================

    async def register(self):

        self.log(
            "👤 Registrando usuário no PlanApp..."
        )

        result = (
            await self.execute_mcp_tool(
                "register",
                {
                    "user_id": USER_ID
                }
            )
        )

        self.log(
            "🟢 Usuário registrado."
        )

        return result


    # ========================================================
    # EVALUATE AUTOMÁTICO
    # ========================================================

    async def ensure_evaluate_link(
        self
    ):

        if self.evaluate_executed:

            return (
                self.last_evaluate_result
            )

        if len(
            self.geocoded_points
        ) < 2:

            return None

        self.log(
            "📡 Executando avaliação técnica do enlace..."
        )

        tx = (
            self.geocoded_points[0]
        )

        rx = (
            self.geocoded_points[1]
        )

        result = (
            await self.execute_mcp_tool(
                "evaluate_link",
                {
                    "tx": tx,
                    "rx": rx,
                }
            )
        )

        return result


    # ========================================================
    # TURNO DO AGENTE
    # ========================================================

    async def agent_turn(self):

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
            # QWEN TERMINOU
            # ------------------------------------------------

            if not tool_calls:

                # ------------------------------------------------
                # Dois pontos encontrados, mas avaliação ainda
                # não executada
                # ------------------------------------------------

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    await (
                        self.ensure_evaluate_link()
                    )

                    resultado_json = (
                        json.dumps(
                            self.last_evaluate_result,
                            ensure_ascii=False,
                            default=str,
                        )
                    )

                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "O PlanApp executou a avaliação "
                                "técnica do enlace.\n\n"
                                "RESULTADO TÉCNICO DO PLANAPP:\n"
                                f"{resultado_json}\n\n"
                                "Utilize exclusivamente esses "
                                "dados retornados pelo PlanApp "
                                "para interpretar o enlace. "
                                "Não invente valores, não "
                                "recalcule os parâmetros e não "
                                "solicite novamente "
                                "evaluate_link."
                            ),
                        }
                    )

                    continue

                self.current_stage = 3

                self.log(
                    "🔵 Etapa 3 — "
                    "Interpretando resultados"
                )

                return content

            # ------------------------------------------------
            # EXECUTA TOOL CALLS
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

                        arguments = (
                            json.loads(
                                arguments
                            )
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
            # APÓS TOOLS
            # ------------------------------------------------

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                await (
                    self.ensure_evaluate_link()
                )

                resultado_json = (
                    json.dumps(
                        self.last_evaluate_result,
                        ensure_ascii=False,
                        default=str,
                    )
                )

                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Os dois pontos foram localizados "
                            "e o PlanApp já executou a avaliação "
                            "técnica do enlace.\n\n"
                            "RESULTADO TÉCNICO DO PLANAPP:\n"
                            f"{resultado_json}\n\n"
                            "Agora interprete os resultados "
                            "retornados pelo PlanApp. "
                            "O PlanApp é a fonte de verdade "
                            "para distância, FSPL, difração, "
                            "obstruções, clearance, terreno "
                            "e edifícios. "
                            "Não recalcule os valores, "
                            "não invente parâmetros e não "
                            "solicite novamente "
                            "evaluate_link."
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
        text
    ):

        # ----------------------------------------------------
        # RESET DO ESTADO DA ANÁLISE
        # ----------------------------------------------------

        self.geocoded_points = []

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.tool_count = 0

        self.current_stage = 0

        self.map = None

        # ----------------------------------------------------
        # CONEXÃO
        # ----------------------------------------------------

        await self.connect()

        # ----------------------------------------------------
        # REGISTER
        # ----------------------------------------------------

        await self.register()

        # ----------------------------------------------------
        # MENSAGENS
        # ----------------------------------------------------

        self.messages = [
            {
                "role": "system",
                "content": self.system_prompt(),
            },
            {
                "role": "user",
                "content": text,
            },
        ]

        self.current_stage = 1

        self.log(
            "🟡 Etapa 1 — "
            "Processando solicitação"
        )

        # ----------------------------------------------------
        # AGENTE
        # ----------------------------------------------------

        result = (
            await self.agent_turn()
        )

        # ----------------------------------------------------
        # GARANTIA FINAL
        # ----------------------------------------------------

        if (
            len(
                self.geocoded_points
            ) >= 2
            and not self.evaluate_executed
        ):

            await (
                self.ensure_evaluate_link()
            )

        # ----------------------------------------------------
        # SEGURANÇA: GARANTE QUE O MAPA EXISTE
        # ----------------------------------------------------

        if (
            self.map is None
            and len(
                self.geocoded_points
            ) >= 2
        ):

            await (
                self.mostrar_mapa_apos_geocodificacao()
            )

        self.log(
            "🗺️ Objeto do mapa disponível."
            if self.map is not None
            else "⚠️ Mapa não disponível."
        )

        self.log(
            "🟢 Análise concluída."
        )

        return result


    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        except Exception:
            pass

        self.connected = False
        self.mcp_session = None
        self.mcp_tools = []
