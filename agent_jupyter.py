# ============================================================
# agent_jupyter.py
# PlanApp AI Agent
# Jupyter + Ollama/Qwen3 + PlanApp MCP
#
# VERSÃO:
# - MCP Streamable HTTP
# - ClientSession com AsyncExitStack
# - Ollama via httpx.AsyncClient
# - progresso assíncrono para atualização da UI
# - log técnico separado do progresso visual
# ============================================================

import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any, Optional

import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ============================================================
# CONFIGURAÇÃO
# ============================================================

OLLAMA_URL = "http://172.17.0.1:11434"
OLLAMA_MODEL = "qwen3:8b"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "agent-jupyter"

OLLAMA_TIMEOUT = 300

# Mantemos DEBUG ligado para diagnóstico.
# O log técnico continua sendo armazenado em debug_log.
DEBUG = True


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(self, progress_callback=None):

        self.progress_callback = progress_callback

        self.stack = None
        self.session = None

        self.tools = []
        self.tools_ollama = []

        self.connected = False

        self.history = []

        # Log técnico completo
        self.debug_log = []


    # ========================================================
    # LOG TÉCNICO
    # ========================================================

    def log(self, texto):

        if texto is None:
            return

        texto = str(texto)

        self.debug_log.append(texto)

        # O print continua disponível para testes diretos
        # (test_agent), mas não é usado como interface visual.
        if DEBUG:
            print(texto)


    def clear_log(self):

        self.debug_log = []


    def get_log(self):

        return "\n".join(self.debug_log)


    # ========================================================
    # PROGRESSO VISUAL — SÍNCRONO
    # ========================================================

    def progress(self, texto, tipo="processing"):

        if texto is None:
            return

        texto = str(texto)

        # IMPORTANTE:
        # Não colocamos o progresso no debug_log aqui.
        #
        # O debug_log é reservado para diagnóstico técnico.
        # Isso evita duplicação e deixa o log técnico separado
        # do log visual.
        #
        # Entretanto, mantemos print() para compatibilidade
        # com test_agent() e execução pelo terminal.

        if DEBUG:
            print(texto)

        if self.progress_callback is not None:

            try:

                self.progress_callback(
                    texto,
                    tipo
                )

            except TypeError:

                # Compatibilidade com callback antigo que
                # aceita somente texto.

                try:

                    self.progress_callback(
                        texto
                    )

                except Exception:
                    pass

            except Exception:
                pass


    # ========================================================
    # PROGRESSO VISUAL — ASSÍNCRONO
    # ========================================================

    async def progress_async(
        self,
        texto,
        tipo="processing"
    ):
        """
        Envia uma mensagem de progresso e devolve
        temporariamente o controle ao event loop.

        Isso permite que o Jupyter/ipywidgets tenha
        oportunidade de enviar a atualização para o
        navegador antes da próxima operação.
        """

        self.progress(
            texto,
            tipo
        )

        # Pequeno yield para o event loop do Jupyter.
        await asyncio.sleep(0.05)


    # ========================================================
    # CONNECT
    # ========================================================

    async def connect(self):

        if self.connected and self.session is not None:

            return


        await self.progress_async(
            "🔵 Conectando ao PlanApp MCP...",
            "processing"
        )


        try:

            # ------------------------------------------------
            # EXIT STACK
            # ------------------------------------------------

            self.stack = AsyncExitStack()

            await self.stack.__aenter__()


            # ------------------------------------------------
            # TRANSPORTE STREAMABLE HTTP
            # ------------------------------------------------

            read_stream, write_stream = (
                await self.stack.enter_async_context(
                    streamable_http_client(
                        MCP_URL
                    )
                )
            )


            # ------------------------------------------------
            # CLIENT SESSION
            # ------------------------------------------------

            self.session = ClientSession(
                read_stream,
                write_stream
            )


            # =================================================
            # IMPORTANTE
            #
            # ClientSession inicia o
            # JSONRPCDispatcher.run()
            # dentro de __aenter__().
            #
            # Portanto:
            #
            # 1. cria ClientSession
            # 2. entra no contexto
            # 3. chama initialize()
            #
            # Não usar:
            #
            # await session.initialize()
            #
            # antes de entrar no contexto.
            # =================================================

            await self.stack.enter_async_context(
                self.session
            )


            # ------------------------------------------------
            # INITIALIZE
            # ------------------------------------------------

            await self.session.initialize()


            # ------------------------------------------------
            # LIST TOOLS
            # ------------------------------------------------

            result = await self.session.list_tools()

            self.tools = result.tools

            self.tools_ollama = []


            # ------------------------------------------------
            # CONVERTE TOOLS MCP → OLLAMA
            # ------------------------------------------------

            for tool in self.tools:

                schema = getattr(
                    tool,
                    "inputSchema",
                    None
                )


                # Compatibilidade com versões que usam
                # input_schema.

                if schema is None:

                    schema = getattr(
                        tool,
                        "input_schema",
                        None
                    )


                if schema is None:

                    schema = {
                        "type": "object",
                        "properties": {}
                    }


                description = getattr(
                    tool,
                    "description",
                    None
                )


                if description is None:

                    description = ""


                self.tools_ollama.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": description,
                            "parameters": schema,
                        },
                    }
                )


            # ------------------------------------------------
            # CONECTADO
            # ------------------------------------------------

            self.connected = True


            await self.progress_async(
                f"🟢 MCP conectado — "
                f"{len(self.tools)} ferramentas disponíveis.",
                "success"
            )


            # ------------------------------------------------
            # LISTA FERRAMENTAS — LOG TÉCNICO
            # ------------------------------------------------

            for tool in self.tools:

                self.log(
                    f"   • {tool.name}"
                )


        except Exception as e:

            self.connected = False


            self.log(
                "❌ ERRO AO CONECTAR AO MCP:"
            )

            self.log(
                repr(e)
            )


            # ------------------------------------------------
            # FECHA STACK SE CONEXÃO FALHOU
            # ------------------------------------------------

            try:

                if self.stack is not None:

                    await self.stack.__aexit__(
                        None,
                        None,
                        None
                    )

            except Exception:
                pass

            finally:

                self.session = None
                self.stack = None


            raise


    # ========================================================
    # INITIALIZE
    # ========================================================

    async def initialize(self):

        await self.connect()


    # ========================================================
    # FECHAR
    # ========================================================

    async def close(self):

        self.connected = False


        try:

            if self.stack is not None:

                await self.stack.__aexit__(
                    None,
                    None,
                    None
                )


        except Exception as e:

            self.log(
                f"⚠️ Erro ao fechar MCP: {repr(e)}"
            )


        finally:

            self.session = None
            self.stack = None


    # ========================================================
    # RESET
    # ========================================================

    def reset_history(self):

        self.history = []

        self.clear_log()


    # ========================================================
    # SERIALIZAÇÃO
    # ========================================================

    def _serialize_json(self, obj):

        try:

            return json.dumps(
                obj,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        except Exception:

            return str(obj)


    # ========================================================
    # EXTRAIR RESULTADO MCP
    # ========================================================

    def extract_mcp_result(self, result):

        partes = []


        # ----------------------------------------------------
        # isError
        # ----------------------------------------------------

        is_error = getattr(
            result,
            "isError",
            None
        )


        if is_error is None:

            is_error = getattr(
                result,
                "is_error",
                False
            )


        # ----------------------------------------------------
        # structuredContent
        # ----------------------------------------------------

        structured = getattr(
            result,
            "structuredContent",
            None
        )


        if structured is None:

            structured = getattr(
                result,
                "structured_content",
                None
            )


        if structured is not None:

            partes.append(
                self._serialize_json(
                    structured
                )
            )


        # ----------------------------------------------------
        # content
        # ----------------------------------------------------

        content = getattr(
            result,
            "content",
            None
        )


        if content:

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None
                )


                if text:

                    partes.append(
                        str(text)
                    )

                    continue


                data = getattr(
                    item,
                    "data",
                    None
                )


                if data:

                    partes.append(
                        str(data)
                    )

                    continue


                partes.append(
                    repr(item)
                )


        # ----------------------------------------------------
        # fallback
        # ----------------------------------------------------

        if not partes:

            partes.append(
                repr(result)
            )


        resultado = "\n".join(
            partes
        )


        return (
            resultado,
            bool(is_error)
        )


    # ========================================================
    # RESUMO DO RESULTADO MCP PARA A UI
    # ========================================================

    def summarize_tool_result(
        self,
        tool_name,
        result_text
    ):
        """
        Gera uma mensagem curta para o painel visual.

        O resultado completo continua disponível no
        debug_log.
        """

        texto = (
            str(result_text)
            .strip()
        )


        # ----------------------------------------------------
        # GEOCODIFICAÇÃO
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            # Tenta localizar latitude/longitude no texto.
            try:

                data = json.loads(texto)

                if isinstance(data, dict):

                    lat = (
                        data.get("lat")
                        or data.get("latitude")
                    )

                    lon = (
                        data.get("lon")
                        or data.get("longitude")
                    )

                    if lat is not None and lon is not None:

                        return (
                            f"📥 Coordenadas: "
                            f"{lat}, {lon}"
                        )

            except Exception:
                pass


            # Resultado textual
            primeira_linha = (
                texto.splitlines()[0]
                if texto
                else ""
            )

            if len(primeira_linha) > 180:

                primeira_linha = (
                    primeira_linha[:180]
                    + "..."
                )

            return (
                f"📥 {primeira_linha}"
                if primeira_linha
                else "📥 Resultado recebido."
            )


        # ----------------------------------------------------
        # EVALUATE LINK
        # ----------------------------------------------------

        if tool_name == "evaluate_link":

            # Procura distância no resultado.

            try:

                # Pode ser JSON
                data = json.loads(texto)

                if isinstance(data, dict):

                    dist = (
                        data.get("dist_m")
                        or data.get("distance_m")
                        or data.get("distance")
                    )

                    if dist is not None:

                        return (
                            f"📥 Análise concluída — "
                            f"{float(dist):,.2f} m"
                            .replace(",", "X")
                            .replace(".", ",")
                            .replace("X", ".")
                        )

            except Exception:
                pass


            # Procura "dist_m" em texto bruto.
            if "dist_m" in texto:

                return (
                    "📥 Análise do enlace concluída."
                )


            return (
                "📥 Análise do enlace concluída."
            )


        # ----------------------------------------------------
        # OUTRAS FERRAMENTAS
        # ----------------------------------------------------

        primeira_linha = (
            texto.splitlines()[0]
            if texto
            else ""
        )


        if len(primeira_linha) > 180:

            primeira_linha = (
                primeira_linha[:180]
                + "..."
            )


        return (
            f"📥 {primeira_linha}"
            if primeira_linha
            else "📥 Resultado recebido."
        )


    # ========================================================
    # EXECUTAR FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments
    ):

        # ----------------------------------------------------
        # PROGRESSO VISUAL
        # ----------------------------------------------------

        await self.progress_async(
            f"🔧 MCP: {tool_name}",
            "processing"
        )


        # ----------------------------------------------------
        # LOG TÉCNICO
        # ----------------------------------------------------

        self.log(
            "────────────────────────────────────────"
        )

        self.log(
            f"MCP TOOL: {tool_name}"
        )

        self.log(
            "ARGUMENTOS:"
        )

        self.log(
            self._serialize_json(
                arguments
            )
        )


        # ----------------------------------------------------
        # CALL TOOL
        # ----------------------------------------------------

        try:

            result = await self.session.call_tool(
                tool_name,
                arguments=arguments
            )


        except Exception as e:

            self.log(
                "❌ EXCEÇÃO DURANTE call_tool:"
            )

            self.log(
                repr(e)
            )

            raise


        # ====================================================
        # DEBUG RESULTADO MCP
        # ====================================================

        self.log(
            "DEBUG MCP RESULT"
        )

        self.log(
            f"TIPO: {type(result)}"
        )


        is_error = getattr(
            result,
            "isError",
            None
        )


        if is_error is None:

            is_error = getattr(
                result,
                "is_error",
                None
            )


        self.log(
            f"isError: {is_error}"
        )


        # ----------------------------------------------------
        # STRUCTURED CONTENT
        # ----------------------------------------------------

        structured = getattr(
            result,
            "structuredContent",
            None
        )


        if structured is None:

            structured = getattr(
                result,
                "structured_content",
                None
            )


        self.log(
            "structuredContent:"
        )


        self.log(
            self._serialize_json(
                structured
            )
            if structured is not None
            else "None"
        )


        # ----------------------------------------------------
        # CONTENT
        # ----------------------------------------------------

        content = getattr(
            result,
            "content",
            None
        )


        self.log(
            "content:"
        )


        if content:

            for i, item in enumerate(
                content
            ):

                self.log(
                    f"  [{i}] "
                    f"tipo={type(item)}"
                )

                self.log(
                    f"  [{i}] repr="
                    f"{repr(item)}"
                )


                text = getattr(
                    item,
                    "text",
                    None
                )


                if text is not None:

                    self.log(
                        f"  [{i}] text="
                        f"{text}"
                    )

        else:

            self.log(
                "  None"
            )


        # ====================================================
        # EXTRAIR RESULTADO
        # ====================================================

        result_text, is_error = (
            self.extract_mcp_result(
                result
            )
        )


        self.log(
            "RESULTADO NORMALIZADO:"
        )

        self.log(
            result_text
        )

        self.log(
            "────────────────────────────────────────"
        )


        # ----------------------------------------------------
        # ERRO MCP
        # ----------------------------------------------------

        if is_error:

            raise RuntimeError(
                f"MCP retornou isError=True "
                f"para {tool_name}:\n"
                f"{result_text}"
            )


        # ----------------------------------------------------
        # RESULTADO VAZIO
        # ----------------------------------------------------

        if not result_text.strip():

            raise RuntimeError(
                f"O MCP retornou resultado vazio "
                f"para {tool_name}."
            )


        # ----------------------------------------------------
        # PROGRESSO VISUAL — RESULTADO
        # ----------------------------------------------------

        await self.progress_async(
            self.summarize_tool_result(
                tool_name,
                result_text
            ),
            "processing"
        )


        return result_text


    # ========================================================
    # CHAMAR OLLAMA
    # ========================================================

    async def call_ollama(
        self,
        messages,
        tools=None
    ):

        payload = {

            "model": OLLAMA_MODEL,

            "messages": messages,

            "stream": False,

            "think": False,

        }


        if tools:

            payload["tools"] = tools


        # ====================================================
        # LOG TÉCNICO — REQUEST
        # ====================================================

        self.log(
            "================================================"
        )

        self.log(
            "OLLAMA REQUEST"
        )

        self.log(
            f"MODEL: {OLLAMA_MODEL}"
        )

        self.log(
            "THINK: False"
        )

        self.log(
            f"TOOLS: "
            f"{len(tools) if tools else 0}"
        )

        self.log(
            "MESSAGES:"
        )

        self.log(
            self._serialize_json(
                messages
            )
        )

        self.log(
            "================================================"
        )


        # ----------------------------------------------------
        # REQUEST
        # ----------------------------------------------------

        try:

            async with httpx.AsyncClient(
                timeout=OLLAMA_TIMEOUT
            ) as client:

                response = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json=payload
                )

                response.raise_for_status()

                data = response.json()


        except Exception as e:

            self.log(
                "❌ ERRO OLLAMA:"
            )

            self.log(
                repr(e)
            )

            raise


        # ====================================================
        # LOG TÉCNICO — RESPONSE
        # ====================================================

        self.log(
            "OLLAMA RESPONSE"
        )

        self.log(
            self._serialize_json(
                data
            )
        )

        self.log(
            "================================================"
        )


        return data


    # ========================================================
    # PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, um agente especializado em
planejamento e avaliação de enlaces de rádio.

Você possui acesso às ferramentas MCP do PlanApp.

REGRAS IMPORTANTES:

1. Quando o usuário informar nomes de lugares, NÃO invente
   coordenadas.

2. Para transformar nomes de lugares em coordenadas,
   utilize obrigatoriamente a ferramenta geocode_place.

3. O resultado retornado por geocode_place é a fonte correta
   das coordenadas.

4. Quando geocode_place retornar latitude e longitude,
   utilize exatamente esses valores.

5. NÃO peça ao usuário para fornecer coordenadas se
   geocode_place já tiver conseguido localizar o lugar.

6. Depois de obter as coordenadas dos dois pontos, utilize
   as ferramentas disponíveis para realizar a análise do
   enlace.

7. Não diga que houve erro ao obter coordenadas apenas porque
   o resultado da ferramenta possui JSON, structuredContent,
   texto ou outro formato técnico. Interprete o resultado
   retornado pela ferramenta.

8. Não invente resultados técnicos.

9. Explique o resultado final de forma objetiva.

10. Se uma ferramenta retornar erro real, informe qual
    ferramenta falhou e qual foi o erro.

11. Quando houver necessidade de chamar uma ferramenta,
    chame-a. Não descreva simplesmente o que deveria ser feito.
"""


    # ========================================================
    # AGENT TURN
    # ========================================================

    async def agent_turn(
        self,
        user_input
    ):

        messages = [

            {
                "role": "system",
                "content": self.system_prompt(),
            },

            {
                "role": "user",
                "content": user_input,
            },

        ]


        max_iterations = 8


        for iteration in range(
            1,
            max_iterations + 1
        ):

            await self.progress_async(
                f"🔵 Processando etapa "
                f"{iteration}...",
                "processing"
            )


            # ------------------------------------------------
            # QWEN
            # ------------------------------------------------

            data = await self.call_ollama(
                messages,
                tools=self.tools_ollama
            )


            message = data.get(
                "message",
                {}
            )


            # ------------------------------------------------
            # LOG QWEN
            # ------------------------------------------------

            self.log(
                "MENSAGEM QWEN:"
            )

            self.log(
                self._serialize_json(
                    message
                )
            )


            # ------------------------------------------------
            # TOOL CALLS
            # ------------------------------------------------

            tool_calls = message.get(
                "tool_calls"
            )


            if tool_calls:

                self.log(
                    f"🔧 Qwen solicitou "
                    f"{len(tool_calls)} ferramenta(s)."
                )


                messages.append(
                    message
                )


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


                    # ----------------------------------------
                    # ARGUMENTOS STRING → JSON
                    # ----------------------------------------

                    if isinstance(
                        arguments,
                        str
                    ):

                        try:

                            arguments = json.loads(
                                arguments
                            )


                        except json.JSONDecodeError:

                            raise RuntimeError(
                                "O Qwen retornou argumentos "
                                f"inválidos para {tool_name}:\n"
                                f"{arguments}"
                            )


                    # ----------------------------------------
                    # VALIDAR ARGUMENTOS
                    # ----------------------------------------

                    if not isinstance(
                        arguments,
                        dict
                    ):

                        raise RuntimeError(
                            f"Argumentos inválidos para "
                            f"{tool_name}: "
                            f"{repr(arguments)}"
                        )


                    # ----------------------------------------
                    # EXECUTAR MCP
                    # ----------------------------------------

                    result_text = (
                        await self.execute_mcp_tool(
                            tool_name,
                            arguments
                        )
                    )


                    # ----------------------------------------
                    # RESULTADO PARA QWEN
                    # ----------------------------------------

                    messages.append(
                        {
                            "role": "tool",
                            "content": result_text,
                        }
                    )


                # ------------------------------------------------
                # PRÓXIMA RODADA
                # ------------------------------------------------

                continue


            # ------------------------------------------------
            # RESPOSTA FINAL
            # ------------------------------------------------

            resposta = message.get(
                "content",
                ""
            )


            if resposta is None:

                resposta = ""


            resposta = str(
                resposta
            ).strip()


            if resposta:

                return resposta


            raise RuntimeError(
                "O Qwen retornou uma resposta vazia."
            )


        raise RuntimeError(
            f"O agente atingiu o limite de "
            f"{max_iterations} etapas."
        )


    # ========================================================
    # ASK
    # ========================================================

    async def ask(
        self,
        user_input
    ):

        self.clear_log()


        await self.progress_async(
            "🔵 Iniciando agente Qwen...",
            "processing"
        )


        try:

            # ------------------------------------------------
            # MCP
            # ------------------------------------------------

            await self.connect()


            # ------------------------------------------------
            # AGENTE
            # ------------------------------------------------

            resultado = await self.agent_turn(
                user_input
            )


            await self.progress_async(
                "🟢 Análise concluída",
                "success"
            )


            # ------------------------------------------------
            # RETORNO
            # ------------------------------------------------

            # IMPORTANTE:
            # Não montamos mais o <details> aqui.
            #
            # O agente retorna somente a resposta.
            # A interface Jupyter decide como apresentar
            # o resultado e o log técnico.
            #

            return resultado


        except Exception as e:

            self.log(
                "================================================"
            )

            self.log(
                "❌ ERRO FINAL DO AGENTE"
            )

            self.log(
                repr(e)
            )

            self.log(
                "================================================"
            )


            # ------------------------------------------------
            # IMPORTANTE
            #
            # Mantemos a exceção para a interface tratar.
            # Não misturamos o log técnico com o resultado.
            # ------------------------------------------------

            raise


# ============================================================
# TESTE DIRETO
# ============================================================

async def test_agent():

    agent = PlanAppAgent()

    try:

        await agent.connect()

        resultado = await agent.ask(
            "Analise um enlace entre a Praça da Sé "
            "e o Largo do Paissandu em São Paulo."
        )

        print()
        print("=" * 70)
        print("RESULTADO")
        print("=" * 70)
        print(resultado)

        print()
        print("=" * 70)
        print("LOG TÉCNICO")
        print("=" * 70)
        print(agent.get_log())

    finally:

        await agent.close()