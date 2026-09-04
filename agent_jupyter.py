# ============================================================
# agent_jupyter.py
# PlanApp Agent
#
# Jupyter
#   ↓
# Ollama / Qwen
#   ↓
# MCP
#   ↓
# PlanApp
# ============================================================

import asyncio
import json
from contextlib import AsyncExitStack

import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ============================================================
# CONFIGURAÇÃO
# ============================================================

OLLAMA_URL = "http://172.17.0.1:11434"
OLLAMA_MODEL = "qwen3:8b"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "jupyter-user"

OLLAMA_TIMEOUT = 300.0

# True somente para depuração técnica no terminal/kernel.
# A interface do Jupyter continua mostrando apenas o log amigável.
DEBUG = False


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(self, progress_callback=None):

        self.progress_callback = progress_callback

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None

        self.tools = []

        self.ollama_tools = []

        self.messages = []

        self.connected = False

        self.evaluate_link_executed = False

        self.geocoded_points = []

        self.current_stage = None

        self.tool_execution_count = 0

    # ========================================================
    # LOG
    # ========================================================

    def log(self, message):

        if self.progress_callback:

            self.progress_callback(message)

        if DEBUG:

            print(message)

    # ========================================================
    # CONEXÃO MCP
    # ========================================================

    async def connect(self):

        if self.connected:
            return

        try:

            # ------------------------------------------------
            # Conecta ao MCP via Streamable HTTP
            # ------------------------------------------------

            read_stream, write_stream = (
                await self.exit_stack.enter_async_context(
                    streamable_http_client(MCP_URL)
                )
            )

            self.mcp_session = (
                await self.exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream
                    )
                )
            )

            # ------------------------------------------------
            # Inicializa sessão MCP
            # ------------------------------------------------

            await self.mcp_session.initialize()

            # ------------------------------------------------
            # Descobre ferramentas
            # ------------------------------------------------

            tools_result = await self.mcp_session.list_tools()

            self.tools = tools_result.tools

            # ------------------------------------------------
            # Converte ferramentas MCP para formato Ollama
            # ------------------------------------------------

            self.ollama_tools = (
                self.build_ollama_tools()
            )

            self.connected = True

            self.log(
                f"🟢 MCP conectado — "
                f"{len(self.tools)} ferramentas disponíveis."
            )

            if DEBUG:

                print()
                print("========== MCP TOOLS ==========")

                for tool in self.tools:

                    print(
                        f"- {tool.name}"
                    )

                print()
                print("========== OLLAMA TOOLS ==========")

                print(
                    json.dumps(
                        self.ollama_tools,
                        indent=2,
                        ensure_ascii=False
                    )
                )

        except Exception as e:

            self.log(
                f"🔴 Erro ao conectar ao MCP: {e}"
            )

            raise

    # ========================================================
    # CONVERTE MCP → OLLAMA
    # ========================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.tools:

            # ------------------------------------------------
            # Schema de entrada MCP
            # ------------------------------------------------

            input_schema = getattr(
                tool,
                "inputSchema",
                None
            )

            # Algumas versões/clientes podem usar
            # input_schema.
            if input_schema is None:

                input_schema = getattr(
                    tool,
                    "input_schema",
                    None
                )

            if input_schema is None:

                input_schema = {
                    "type": "object",
                    "properties": {}
                }

            # ------------------------------------------------
            # Formato esperado pelo Ollama
            # ------------------------------------------------

            ollama_tool = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (
                        tool.description or ""
                    ),
                    "parameters": input_schema,
                },
            }

            tools.append(
                ollama_tool
            )

        return tools

    # ========================================================
    # FECHAR MCP
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        except Exception:

            pass

        self.connected = False

        self.mcp_session = None

        self.tools = []

        self.ollama_tools = []

    # ========================================================
    # RESET DA ANÁLISE
    # ========================================================

    def reset_state(self):

        self.messages = []

        self.evaluate_link_executed = False

        self.geocoded_points = []

        self.current_stage = None

        self.tool_execution_count = 0

    # ========================================================
    # TENTA INTERPRETAR JSON
    # ========================================================

    def try_json(self, value):

        if isinstance(
            value,
            (dict, list)
        ):

            return value

        if not isinstance(
            value,
            str
        ):

            return None

        text = value.strip()

        if not text:

            return None

        # ----------------------------------------------------
        # JSON direto
        # ----------------------------------------------------

        try:

            return json.loads(text)

        except Exception:

            pass

        # ----------------------------------------------------
        # JSON dentro de texto
        # ----------------------------------------------------

        start = text.find("{")

        end = text.rfind("}")

        if start >= 0 and end > start:

            candidate = text[
                start:end + 1
            ]

            try:

                return json.loads(
                    candidate
                )

            except Exception:

                pass

        # ----------------------------------------------------
        # Lista JSON
        # ----------------------------------------------------

        start = text.find("[")

        end = text.rfind("]")

        if start >= 0 and end > start:

            candidate = text[
                start:end + 1
            ]

            try:

                return json.loads(
                    candidate
                )

            except Exception:

                pass

        return None

    # ========================================================
    # EXTRAI RESULTADO DO MCP
    # ========================================================

    def extract_mcp_result(self, result):

        if result is None:

            return None

        # ----------------------------------------------------
        # Dict/list direto
        # ----------------------------------------------------

        if isinstance(
            result,
            (dict, list)
        ):

            return result

        # ----------------------------------------------------
        # structuredContent
        # ----------------------------------------------------

        structured = getattr(
            result,
            "structuredContent",
            None
        )

        if structured:

            return structured

        # ----------------------------------------------------
        # structured_content
        # ----------------------------------------------------

        structured = getattr(
            result,
            "structured_content",
            None
        )

        if structured:

            return structured

        # ----------------------------------------------------
        # Conteúdo MCP
        # ----------------------------------------------------

        content = getattr(
            result,
            "content",
            None
        )

        if content is not None:

            if isinstance(
                content,
                list
            ):

                for item in content:

                    # TextContent
                    text = getattr(
                        item,
                        "text",
                        None
                    )

                    if text is not None:

                        parsed = self.try_json(
                            text
                        )

                        if parsed is not None:

                            return parsed

                        return text

                    # Dict
                    if isinstance(
                        item,
                        dict
                    ):

                        if "text" in item:

                            parsed = self.try_json(
                                item["text"]
                            )

                            if parsed is not None:

                                return parsed

                            return item["text"]

                        if "json" in item:

                            return item["json"]

            # Content como string
            if isinstance(
                content,
                str
            ):

                parsed = self.try_json(
                    content
                )

                if parsed is not None:

                    return parsed

                return content

        # ----------------------------------------------------
        # Fallback text
        # ----------------------------------------------------

        text = getattr(
            result,
            "text",
            None
        )

        if text is not None:

            parsed = self.try_json(
                text
            )

            if parsed is not None:

                return parsed

            return text

        return result

    # ========================================================
    # BUSCA VALOR RECURSIVAMENTE
    # ========================================================

    def find_value(
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

                found = self.find_value(
                    value,
                    keys
                )

                if found is not None:

                    return found

        elif isinstance(
            obj,
            list
        ):

            for item in obj:

                found = self.find_value(
                    item,
                    keys
                )

                if found is not None:

                    return found

        return None

    # ========================================================
    # EXTRAI COORDENADAS
    # ========================================================

    def extract_coordinates(
        self,
        result
    ):

        data = self.extract_mcp_result(
            result
        )

        if not isinstance(
            data,
            dict
        ):

            return None

        # ----------------------------------------------------
        # Formato real do seu geocode.py:
        #
        # {
        #     "status": "OK",
        #     "query": "...",
        #     "results": [...]
        # }
        # ----------------------------------------------------

        results = data.get(
            "results"
        )

        if not isinstance(
            results,
            list
        ):

            return None

        if not results:

            return None

        candidate = results[0]

        if not isinstance(
            candidate,
            dict
        ):

            return None

        lat = candidate.get(
            "lat"
        )

        lon = candidate.get(
            "lon"
        )

        if lat is None or lon is None:

            return None

        try:

            return {
                "lat": float(lat),
                "lon": float(lon),
                "name": candidate.get(
                    "name"
                ),
                "display_name": candidate.get(
                    "display_name"
                ),
            }

        except (
            TypeError,
            ValueError
        ):

            return None

    # ========================================================
    # RESUMO GEOCODE
    # ========================================================

    def summarize_geocode(
        self,
        result
    ):

        data = self.extract_mcp_result(
            result
        )

        if not isinstance(
            data,
            dict
        ):

            return (
                "Resultado de geocodificação "
                "não reconhecido."
            )

        status = data.get(
            "status"
        )

        if status == "NOT_FOUND":

            query = data.get(
                "query",
                ""
            )

            return (
                f"{query} → não encontrado"
            )

        results = data.get(
            "results"
        )

        if not isinstance(
            results,
            list
        ):

            query = data.get(
                "query",
                ""
            )

            return (
                f"{query} → nenhum resultado"
            )

        if not results:

            query = data.get(
                "query",
                ""
            )

            return (
                f"{query} → nenhum resultado"
            )

        candidate = results[0]

        if not isinstance(
            candidate,
            dict
        ):

            return (
                "Resultado de geocodificação inválido."
            )

        name = (
            candidate.get("name")
            or data.get("query")
            or "Ponto"
        )

        lat = candidate.get(
            "lat"
        )

        lon = candidate.get(
            "lon"
        )

        if lat is None or lon is None:

            return (
                f"{name} → "
                "coordenadas não encontradas"
            )

        try:

            lat = float(lat)

            lon = float(lon)

            return (
                f"{name} → "
                f"{lat:.7f}, {lon:.7f}"
            )

        except (
            TypeError,
            ValueError
        ):

            return (
                f"{name} → "
                "coordenadas inválidas"
            )

    # ========================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(
        self,
        result
    ):

        point = self.extract_coordinates(
            result
        )

        if point is None:

            return None

        self.geocoded_points.append(
            point
        )

        return point

    # ========================================================
    # FORMATA NÚMERO BRASILEIRO
    # ========================================================

    def format_number(
        self,
        value,
        decimals=2
    ):

        try:

            text = (
                f"{float(value):,.{decimals}f}"
            )

            return (
                text
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

        except Exception:

            return str(value)

    # ========================================================
    # RESUMO DO EVALUATE_LINK
    # ========================================================

    def summarize_evaluate_link(
        self,
        result
    ):

        data = self.extract_mcp_result(
            result
        )

        if data is None:

            return (
                "📥 Resultado do enlace recebido."
            )

        # ----------------------------------------------------
        # Distância
        # ----------------------------------------------------

        dist = self.find_value(
            data,
            [
                "dist_m",
                "distance_m",
                "distance",
            ]
        )

        # ----------------------------------------------------
        # FSPL
        # ----------------------------------------------------

        fspl = self.find_value(
            data,
            [
                "fspl",
                "fspl_db",
            ]
        )

        # ----------------------------------------------------
        # Difração
        # ----------------------------------------------------

        diffraction = self.find_value(
            data,
            [
                "delta_diffra",
                "diffraction",
                "diffraction_db",
                "diffra",
            ]
        )

        # ----------------------------------------------------
        # Edificações
        # ----------------------------------------------------

        buildings = self.find_value(
            data,
            [
                "buildings",
                "building",
                "building_obstruction",
            ]
        )

        # ----------------------------------------------------
        # Terreno
        # ----------------------------------------------------

        terrain = self.find_value(
            data,
            [
                "terrain",
                "terrain_obstruction",
            ]
        )

        lines = []

        # ----------------------------------------------------
        # Distância
        # ----------------------------------------------------

        if isinstance(
            dist,
            (int, float)
        ):

            lines.append(
                "📥 Distância: "
                + self.format_number(
                    dist
                )
                + " m"
            )

        # ----------------------------------------------------
        # FSPL
        # ----------------------------------------------------

        if isinstance(
            fspl,
            (int, float)
        ):

            lines.append(
                "📥 FSPL: "
                + self.format_number(
                    fspl
                )
                + " dB"
            )

        # ----------------------------------------------------
        # Difração
        # ----------------------------------------------------

        if isinstance(
            diffraction,
            (int, float)
        ):

            if diffraction > 0:

                lines.append(
                    "📥 Difração: "
                    + self.format_number(
                        diffraction
                    )
                    + " dB"
                )

        # ----------------------------------------------------
        # Edificações
        # ----------------------------------------------------

        if self.has_obstruction(
            buildings
        ):

            lines.append(
                "📥 Obstrução por edifícios detectada"
            )

        # ----------------------------------------------------
        # Terreno
        # ----------------------------------------------------

        if self.has_obstruction(
            terrain
        ):

            lines.append(
                "📥 Obstrução por terreno detectada"
            )

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        if not lines:

            lines.append(
                "📥 Resultado do enlace recebido."
            )

        return "\n".join(lines)

    # ========================================================
    # DETECTA OBSTRUÇÃO
    # ========================================================

    def has_obstruction(
        self,
        value
    ):

        if value is None:

            return False

        # ----------------------------------------------------
        # Número
        # ----------------------------------------------------

        if isinstance(
            value,
            (int, float)
        ):

            return value > 0

        # ----------------------------------------------------
        # String
        # ----------------------------------------------------

        if isinstance(
            value,
            str
        ):

            text = value.lower()

            negative = [
                "false",
                "none",
                "no",
                "não",
                "nao",
                "clear",
                "livre",
            ]

            for item in negative:

                if item in text:

                    return False

            positive = [
                "true",
                "obstruction",
                "obstru",
                "blocked",
                "bloque",
            ]

            for item in positive:

                if item in text:

                    return True

            try:

                return (
                    float(value) > 0
                )

            except Exception:

                return False

        # ----------------------------------------------------
        # Dict
        # ----------------------------------------------------

        if isinstance(
            value,
            dict
        ):

            for key in [
                "core",
                "fresnel",
                "boundary",
                "value",
            ]:

                v = value.get(
                    key
                )

                if isinstance(
                    v,
                    (int, float)
                ):

                    if v > 0:

                        return True

            for v in value.values():

                if self.has_obstruction(
                    v
                ):

                    return True

            return False

        # ----------------------------------------------------
        # Lista
        # ----------------------------------------------------

        if isinstance(
            value,
            list
        ):

            for item in value:

                if self.has_obstruction(
                    item
                ):

                    return True

        return False

    # ========================================================
    # DETERMINA ETAPA
    # ========================================================

    def stage_for_tool(
        self,
        tool_name
    ):

        if tool_name == "geocode_place":

            return (
                "🔵 Etapa 1 — Localizando os pontos"
            )

        if tool_name == "evaluate_link":

            return (
                "🔵 Etapa 2 — Avaliando o enlace"
            )

        return None

    # ========================================================
    # EXECUTA FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments
    ):

        if self.mcp_session is None:

            raise RuntimeError(
                "Sessão MCP não inicializada."
            )

        # ----------------------------------------------------
        # Etapa visual
        # ----------------------------------------------------

        stage = self.stage_for_tool(
            tool_name
        )

        if (
            stage
            and stage != self.current_stage
        ):

            self.current_stage = stage

            self.log(stage)

        # ----------------------------------------------------
        # Log ferramenta
        # ----------------------------------------------------

        self.log(
            f"🔧 MCP: {tool_name}"
        )

        self.tool_execution_count += 1

        # ----------------------------------------------------
        # Executa MCP
        # ----------------------------------------------------

        result = await self.mcp_session.call_tool(
            tool_name,
            arguments=arguments
        )

        # ----------------------------------------------------
        # GEOCODE
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            summary = (
                self.summarize_geocode(
                    result
                )
            )

            self.register_geocoded_point(
                result
            )

            self.log(
                f"📥 {summary}"
            )

        # ----------------------------------------------------
        # EVALUATE LINK
        # ----------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_link_executed = True

            summary = (
                self.summarize_evaluate_link(
                    result
                )
            )

            self.log(summary)

        return result

    # ========================================================
    # CHAMADA OLLAMA
    #
    # AQUI ESTÁ A CORREÇÃO PRINCIPAL:
    #
    # "tools": self.ollama_tools
    #
    # Assim o Qwen recebe os schemas das ferramentas MCP.
    # ========================================================

    async def call_ollama(
        self,
        messages
    ):

        url = (
            f"{OLLAMA_URL}/api/chat"
        )

        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,

            # =================================================
            # CORREÇÃO FUNDAMENTAL
            # =================================================
            "tools": self.ollama_tools,

            "stream": False,

            "options": {
                "temperature": 0.1,
            },
        }

        if DEBUG:

            print()
            print(
                "========== OLLAMA REQUEST =========="
            )

            print(
                json.dumps(
                    payload,
                    indent=2,
                    ensure_ascii=False
                )
            )

        async with httpx.AsyncClient(
            timeout=OLLAMA_TIMEOUT
        ) as client:

            response = await client.post(
                url,
                json=payload
            )

            response.raise_for_status()

            data = response.json()

        if DEBUG:

            print()
            print(
                "========== OLLAMA RESPONSE =========="
            )

            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False
                )
            )

        return data.get(
            "message",
            {}
        )

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o agente de planejamento de enlaces de rádio do PlanApp.

Você deve utilizar obrigatoriamente as ferramentas MCP disponíveis
para realizar a análise técnica.

FERRAMENTAS:

- geocode_place:
  Localiza endereços, cidades e pontos de interesse e retorna
  coordenadas geográficas.

- evaluate_link:
  Executa a análise real do enlace através do PlanApp.

- register:
  Ferramenta auxiliar de sessão. Não é necessário chamá-la
  para uma análise normal se a sessão já estiver funcionando.

============================================================
FLUXO OBRIGATÓRIO
============================================================

Quando o usuário pedir uma análise entre dois locais:

1. Identifique o TX.
2. Identifique o RX.
3. Execute geocode_place para o TX.
4. Execute geocode_place para o RX.
5. Aguarde os resultados reais das duas geocodificações.
6. Execute obrigatoriamente evaluate_link.
7. Aguarde o resultado real do PlanApp.
8. Somente então produza a análise técnica.

NÃO produza uma análise técnica antes de executar evaluate_link.

============================================================
PARÂMETROS PADRÃO
============================================================

Se o usuário não informar parâmetros de rádio, utilize:

frequência:
900 MHz

altura TX:
7 metros

altura RX:
7 metros

on_rooftop:
false

Não pergunte esses parâmetros ao usuário quando eles não forem
informados.

============================================================
REGRA ABSOLUTA SOBRE RESULTADOS
============================================================

Nunca invente resultados do PlanApp.

Nunca estime ou simule:

- distância;
- FSPL;
- difração;
- obstrução;
- Fresnel;
- folga;
- ganho de antena;
- potência;
- margem;
- alturas;
- qualquer outro indicador técnico.

Use somente valores efetivamente retornados pelo evaluate_link.

Se um valor não estiver no resultado do PlanApp, diga que ele
não foi fornecido.

============================================================
INTERPRETAÇÃO
============================================================

Analise tecnicamente os resultados reais retornados pelo PlanApp.

Considere, quando disponíveis:

- distância;
- FSPL;
- difração;
- terreno;
- edificações;
- zona de Fresnel;
- folga;
- obstáculos;
- demais indicadores retornados.

Se houver obstrução por edifícios, mencione explicitamente.

Se houver obstrução por terreno, mencione explicitamente.

Não declare que um enlace é viável simplesmente porque a distância
é pequena.

Não declare que um enlace é inviável sem base nos resultados.

============================================================
FREQUÊNCIA E FSPL
============================================================

Para a mesma distância, frequências maiores produzem maior perda
de espaço livre.

Portanto, nunca diga que aumentar a frequência reduz a FSPL.

============================================================
RESPOSTA FINAL
============================================================

Depois que evaluate_link for executado, apresente uma conclusão
técnica objetiva.

Não invente dados ausentes.

Não chame ferramentas desnecessariamente.

Não peça parâmetros que possuem valores padrão.
"""

    # ========================================================
    # GARANTE EVALUATE_LINK
    #
    # Segurança adicional:
    # se o Qwen geocodificar os dois pontos mas não chamar
    # evaluate_link, executamos automaticamente.
    # ========================================================

    async def ensure_evaluate_link(self):

        if self.evaluate_link_executed:

            return None

        # ----------------------------------------------------
        # Necessários dois pontos
        # ----------------------------------------------------

        if len(
            self.geocoded_points
        ) < 2:

            return None

        tx = self.geocoded_points[0]

        rx = self.geocoded_points[1]

        # ----------------------------------------------------
        # Mensagem de etapa
        # ----------------------------------------------------

        if self.current_stage != (
            "🔵 Etapa 2 — Avaliando o enlace"
        ):

            self.current_stage = (
                "🔵 Etapa 2 — Avaliando o enlace"
            )

            self.log(
                "🔵 Etapa 2 — Avaliando o enlace"
            )

        # ----------------------------------------------------
        # Parâmetros padrão
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Executa
        # ----------------------------------------------------

        result = await self.execute_mcp_tool(
            "evaluate_link",
            arguments
        )

        # ----------------------------------------------------
        # Resultado real para o Qwen
        # ----------------------------------------------------

        extracted = (
            self.extract_mcp_result(
                result
            )
        )

        # ----------------------------------------------------
        # Adiciona chamada de ferramenta ao histórico
        # ----------------------------------------------------

        self.messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "evaluate_link",
                            "arguments": arguments,
                        }
                    }
                ],
            }
        )

        self.messages.append(
            {
                "role": "tool",
                "content": json.dumps(
                    extracted,
                    ensure_ascii=False
                ),
            }
        )

        return result

    # ========================================================
    # PROCESSA UMA RODADA DO AGENTE
    # ========================================================

    async def agent_turn(self):

        max_iterations = 12

        for iteration in range(
            max_iterations
        ):

            if DEBUG:

                print(
                    f"\n========== "
                    f"AGENT ITERATION "
                    f"{iteration + 1}"
                    f" =========="
                )

            # ------------------------------------------------
            # Qwen
            # ------------------------------------------------

            assistant_message = (
                await self.call_ollama(
                    self.messages
                )
            )

            if not isinstance(
                assistant_message,
                dict
            ):

                assistant_message = {}

            # ------------------------------------------------
            # Guarda mensagem
            # ------------------------------------------------

            self.messages.append(
                assistant_message
            )

            # ------------------------------------------------
            # Tool calls
            # ------------------------------------------------

            tool_calls = (
                assistant_message.get(
                    "tool_calls"
                )
            )

            if tool_calls:

                for tool_call in tool_calls:

                    function = (
                        tool_call.get(
                            "function",
                            {}
                        )
                    )

                    tool_name = (
                        function.get(
                            "name"
                        )
                    )

                    arguments = (
                        function.get(
                            "arguments",
                            {}
                        )
                    )

                    # ----------------------------------------
                    # Argumentos podem vir como string JSON
                    # ----------------------------------------

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

                    if not isinstance(
                        arguments,
                        dict
                    ):

                        arguments = {}

                    if not tool_name:

                        continue

                    # ----------------------------------------
                    # Segurança:
                    # só executa ferramentas realmente
                    # descobertas no MCP.
                    # ----------------------------------------

                    available_names = {
                        tool.name
                        for tool in self.tools
                    }

                    if (
                        tool_name
                        not in available_names
                    ):

                        if DEBUG:

                            print(
                                "Ferramenta solicitada "
                                "pelo Qwen não encontrada "
                                f"no MCP: {tool_name}"
                            )

                        continue

                    # ----------------------------------------
                    # Executa MCP
                    # ----------------------------------------

                    result = (
                        await self.execute_mcp_tool(
                            tool_name,
                            arguments
                        )
                    )

                    # ----------------------------------------
                    # Resultado para Qwen
                    # ----------------------------------------

                    extracted = (
                        self.extract_mcp_result(
                            result
                        )
                    )

                    self.messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                extracted,
                                ensure_ascii=False
                            ),
                        }
                    )

                # ------------------------------------------------
                # Depois de qualquer rodada de ferramentas,
                # verificar se temos os dois pontos.
                # ------------------------------------------------

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_link_executed
                ):

                    await self.ensure_evaluate_link()

                continue

            # ------------------------------------------------
            # Qwen não chamou ferramenta.
            #
            # Se já temos os dois pontos, não permitimos
            # que ele finalize sem evaluate_link.
            # ------------------------------------------------

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_link_executed
            ):

                await self.ensure_evaluate_link()

                continue

            # ------------------------------------------------
            # Se evaluate_link foi executado, pode finalizar.
            # ------------------------------------------------

            if self.evaluate_link_executed:

                return assistant_message.get(
                    "content",
                    ""
                )

            # ------------------------------------------------
            # Caso não tenha conseguido geocodificar os dois
            # pontos, retorna a resposta do Qwen.
            # ------------------------------------------------

            return assistant_message.get(
                "content",
                ""
            )

        return (
            "Não foi possível concluir a análise "
            "dentro do número máximo de etapas."
        )

    # ========================================================
    # ASK
    # ========================================================

    async def ask(
        self,
        user_text
    ):

        # ----------------------------------------------------
        # Conecta MCP
        # ----------------------------------------------------

        await self.connect()

        # ----------------------------------------------------
        # Limpa estado da análise
        # ----------------------------------------------------

        self.reset_state()

        # ----------------------------------------------------
        # Mensagens
        # ----------------------------------------------------

        self.messages = [

            {
                "role": "system",
                "content": self.system_prompt(),
            },

            {
                "role": "user",
                "content": user_text,
            },

        ]

        # ----------------------------------------------------
        # Executa
        # ----------------------------------------------------

        answer = await self.agent_turn()

        # ----------------------------------------------------
        # Etapa 3
        # ----------------------------------------------------

        if self.evaluate_link_executed:

            self.current_stage = (
                "🔵 Etapa 3 — Interpretando resultados"
            )

            self.log(
                "🔵 Etapa 3 — Interpretando resultados"
            )

            self.log(
                "🟢 Análise concluída"
            )

        return answer

    # ========================================================
    # TESTE
    # ========================================================

    async def test_agent(self):

        return await self.ask(
            "Analise um enlace entre "
            "a Praça da Sé e o Largo do Paissandu "
            "em São Paulo."
        )


# ============================================================
# FIM
# ============================================================