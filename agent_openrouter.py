# ============================================================================
# PLANAPP AI — OPENROUTER
#
# Arquitetura:
#
#   Jupyter
#      |
#      v
#   OpenRouter
#      |
#      v
#   modelo configurado em OPENROUTER_MODEL
#      |
#      +--> geocode_place
#      |
#      v
#   APLICAÇÃO
#      |
#      +--> evaluate_link
#      |
#      +--> mapa
#      |
#      +--> visualizações
#
# Etapa 1:
#   - análise de um único enlace
#   - o modelo pode solicitar geocodificação
#   - evaluate_link é controlado pela aplicação
#   - mapa é controlado pela aplicação
#   - visualizações são controladas pela aplicação
#
# ============================================================================

import os
import re
import json
import base64

from openai import AsyncOpenAI
from ipywidgets import widgets

from agent_common import (
    PlanAppAgentCommon,
    APPLICATION_CONTROLLED_TOOLS,
)


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp",
)

OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL",
    "https://openrouter.ai/api/v1",
)

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free",
)

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

USER_ID = os.getenv(
    "PLANAPP_USER_ID",
    "jupyter-user",
)

DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False

MAX_AGENT_ITERATIONS = 8

# ============================================================================
# O modelo somente pode solicitar geocodificação.
#
# evaluate_link, mapa e visualizações permanecem sob controle da aplicação.
# ============================================================================

MODEL_ALLOWED_TOOLS = {
    "geocode_place",
}


# ============================================================================
# AGENTE
# ============================================================================

class PlanAppAgent(PlanAppAgentCommon):

    # ========================================================================
    # INIT
    # ========================================================================

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
        debug=False,
    ):
    
        super().__init__(
            progress_callback=progress_callback,
            map_callback=map_callback,
            log_callback=log_callback,
            result_callback=result_callback,
            visualization_callback=visualization_callback,
        )
    
        self.debug = debug

        self._planapp_agent_type = "openrouter"

        self.model = OPENROUTER_MODEL

        self.client = None

        self.messages = []

        self.last_agent_text = ""

        self.max_agent_iterations = (
            MAX_AGENT_ITERATIONS
        )

        if not OPENROUTER_API_KEY:

            raise RuntimeError(
                "OPENROUTER_API_KEY não encontrada."
            )

    # ========================================================================
    # CLIENTE OPENROUTER
    # ========================================================================

    def create_client(self):

        return AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_URL,
            default_headers={
                "HTTP-Referer":
                    "https://planapp.cisei.pucpr.br",

                "X-Title":
                    "PlanApp AI",
            },
        )

    # ========================================================================
    # TOOLS DISPONÍVEIS PARA O MODELO
    # ========================================================================

    def build_openrouter_tools(self):

        tools = []

        if "geocode_place" in MODEL_ALLOWED_TOOLS:

            tools.append(
                {
                    "type": "function",

                    "function": {

                        "name":
                            "geocode_place",

                        "description":
                            (
                                "Geocodifica um local informado "
                                "pelo usuário e retorna latitude "
                                "e longitude."
                            ),

                        "parameters": {

                            "type": "object",

                            "properties": {

                                "query": {

                                    "type": "string",

                                    "description":
                                        (
                                            "Nome ou endereço "
                                            "do local."
                                        ),
                                }
                            },

                            "required": [
                                "query"
                            ],
                        },
                    },
                }
            )

        return tools

    # ========================================================================
    # SYSTEM PROMPT
    # ========================================================================

    def build_system_prompt(self):

        return f"""
Você é o PlanApp AI, um assistente técnico para planejamento
e avaliação de enlaces de rádio.

Você deve responder em português.

O PlanApp é a fonte de verdade para os resultados técnicos.

REGRAS IMPORTANTES:

1. Você pode utilizar geocode_place para transformar nomes de
   locais em coordenadas geográficas.

2. Você NÃO deve executar evaluate_link diretamente.

3. evaluate_link é executado exclusivamente pela aplicação.

4. Você NÃO deve escolher ou executar as visualizações.

5. O mapa é controlado pela aplicação.

6. As visualizações são controladas pela aplicação.

7. Não invente coordenadas.

8. Não invente resultados técnicos.

9. Não invente valores para frequência, alturas ou parâmetros.

10. Quando o usuário não informar frequência, utilize:
       {DEFAULT_FREQ_MHZ} MHz

11. Quando o usuário não informar altura da antena TX, utilize:
       {DEFAULT_TX_HA} m

12. Quando o usuário não informar altura da antena RX, utilize:
       {DEFAULT_RX_HA} m

13. Quando o usuário não informar instalação sobre cobertura,
    utilize:
       {DEFAULT_ON_ROOFTOP}

14. O resultado técnico retornado pelo PlanApp deve ser
    tratado como fonte de verdade.

15. Não transforme valores técnicos retornados pelo PlanApp
    em interpretações não suportadas.

16. Não converta valores que o PlanApp fornece em radianos
    para graus, a menos que isso seja explicitamente solicitado
    e suportado.

17. Não transforme core, fresnel ou boundary em dB.

18. Não invente conclusões de viabilidade.

19. Se o PlanApp retornar erro, informe o erro real.

20. Para um enlace, utilize os dois primeiros pontos
    geocodificados como TX e RX.

Seu papel é interpretar a solicitação do usuário,
solicitar a geocodificação quando necessário e,
depois que a aplicação executar a avaliação,
explicar tecnicamente os resultados fornecidos pelo PlanApp.
"""

    # ========================================================================
    # OPENROUTER CHAT COMPLETIONS
    # ========================================================================

    async def openrouter_chat(
        self,
        messages,
        tools=None,
    ):

        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if tools:

            kwargs["tools"] = tools

            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(
            **kwargs
        )

        return response

    # ========================================================================
    # LIMPEZA DA RESPOSTA
    # ========================================================================

    def clean_final_response(
        self,
        text,
    ):

        if not text:
            return ""

        text = re.sub(
            r"<think>.*?</think>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(
            r"<reasoning>.*?</reasoning>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(
            r"<analysis>.*?</analysis>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        return text.strip()

    # ========================================================================
    # MAPA APÓS GEOCODIFICAÇÃO
    # ========================================================================

    async def mostrar_mapa_apos_geocodificacao(
        self,
    ):

        if len(self.geocoded_points) < 2:

            return

        try:

            from map_utils import mostrar_mapa_enlace

            p1 = self.geocoded_points[0]

            p2 = self.geocoded_points[1]

            self.map = mostrar_mapa_enlace(
                p1["lat"],
                p1["lon"],
                p2["lat"],
                p2["lon"],
            )

            if self.map_callback:

                self.map_callback(
                    self.map
                )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no mapa: {exc}"
            )

    # ========================================================================
    # VISUALIZAÇÕES
    #
    # IMPORTANTE:
    # O callback recebe a LISTA COMPLETA de visualizações.
    #
    # Antes estava sendo chamado como:
    #
    #     callback(image, title)
    #
    # Agora:
    #
    #     callback(self.visualizations)
    #
    # ========================================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.evaluate_executed:

            return

        if self.evaluate_error:

            return

        tools = [

            (
                "link_area",
                {
                    "ds_string": "DTM"
                },
                "DTM",
            ),

            (
                "link_area",
                {
                    "ds_string": "DSM"
                },
                "DSM",
            ),

            (
                "link_area",
                {
                    "ds_string": "COVER"
                },
                "COVER",
            ),

            (
                "link_profile",
                {},
                "Perfil",
            ),

            (
                "lulc_fresnel",
                {},
                "LULC / Fresnel",
            ),

            (
                "bldg_prepare",
                {},
                "Buildings prepare",
            ),

            (
                "bldg_fresnel",
                {},
                "Buildings / Fresnel",
            ),

            (
                "bldg_profile",
                {},
                "Buildings profile",
            ),
        ]

        self.visualizations = []

        for (
            tool_name,
            arguments,
            title,
        ) in tools:

            try:

                raw = await (
                    self.execute_mcp_tool_raw(
                        tool_name,
                        arguments,
                    )
                )

                parsed = (
                    self.parse_mcp_result(
                        raw
                    )
                )

                if not isinstance(
                    parsed,
                    dict,
                ):

                    continue

                if parsed.get(
                    "kind"
                ) != "image":

                    continue

                data = parsed.get(
                    "data"
                )

                if not data:

                    continue

                try:

                    image_bytes = (
                        base64.b64decode(
                            data
                        )
                    )

                except Exception:

                    continue

                image = widgets.Image(
                    value=image_bytes
                )

                self.visualizations.append(
                    image
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Visualização "
                    f"{title}: {exc}"
                )

        # ====================================================================
        # ENTREGA TODAS AS IMAGENS PARA A INTERFACE DE UMA VEZ
        # ====================================================================

        if self.visualization_callback:

            self.visualization_callback(
                self.visualizations
            )

    # ========================================================================
    # RESPOSTA FINAL
    # ========================================================================

    async def generate_final_response(
        self,
        user_text,
        technical_context,
    ):

        context_json = json.dumps(
            technical_context,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        prompt = f"""
Responda ao usuário sobre a avaliação do enlace realizada
pelo PlanApp.

Solicitação original:

{user_text}

Contexto técnico real retornado pelo PlanApp:

{context_json}

Produza uma resposta técnica clara em português.

IMPORTANTE:

- Utilize somente os dados presentes no contexto.
- Não invente valores.
- Não invente unidades.
- Não invente conclusões.
- Informe frequência e alturas efetivamente utilizadas.
- Diferencie parâmetros solicitados dos parâmetros efetivamente
  enviados ao PlanApp.
- Se houver conversão de frequência, explique-a.
- Apresente os principais resultados técnicos retornados.
- Se houver erro, informe o erro real.
- Não diga que o enlace é viável ou inviável se isso não estiver
  explicitamente determinado pelos dados fornecidos.
"""

        messages = [

            {
                "role": "system",
                "content":
                    self.build_system_prompt(),
            },

            {
                "role": "user",
                "content": prompt,
            },
        ]

        response = await self.openrouter_chat(
            messages
        )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        return self.clean_final_response(
            content
        )

    # ========================================================================
    # UMA RODADA DO AGENTE
    # ========================================================================

    async def agent_turn(
        self,
        user_text,
    ):

        tools = self.build_openrouter_tools()

        self.messages = [

            {
                "role": "system",
                "content":
                    self.build_system_prompt(),
            },

            {
                "role": "user",
                "content": user_text,
            },
        ]

        for iteration in range(
            self.max_agent_iterations
        ):

            self.log_detail(
                f"OpenRouter iteration "
                f"{iteration + 1}/"
                f"{self.max_agent_iterations}"
            )

            response = await self.openrouter_chat(
                self.messages,
                tools=tools,
            )

            message = response.choices[0].message

            self.messages.append(
                message.model_dump(
                    exclude_none=True
                )
            )

            tool_calls = (
                message.tool_calls
            )

            # ================================================================
            # MODELO TERMINOU
            # ================================================================

            if not tool_calls:

                content = (
                    message.content
                    or ""
                )

                self.last_agent_text = (
                    self.clean_final_response(
                        content
                    )
                )

                # ============================================================
                # Se já temos dois pontos, a aplicação executa
                # evaluate_link.
                # ============================================================

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    technical_result = (
                        await self.ensure_evaluate_link()
                    )

                    technical_context = (
                        self.build_technical_context(
                            technical_result
                        )
                    )

                    return (
                        await self.generate_final_response(
                            user_text,
                            technical_context,
                        )
                    )

                return self.last_agent_text

            # ================================================================
            # PROCESSAMENTO DOS TOOL CALLS
            # ================================================================

            for tool_call in tool_calls:

                tool_name = (
                    tool_call.function.name
                )

                arguments_text = (
                    tool_call.function.arguments
                    or "{}"
                )

                try:

                    arguments = json.loads(
                        arguments_text
                    )

                except Exception:

                    arguments = {}

                self.log_detail(
                    f"MCP TOOL: {tool_name}"
                )

                self.log_detail(
                    f"Argumentos: "
                    f"{arguments}"
                )

                # ============================================================
                # PROTEÇÃO:
                # o modelo NÃO pode executar ferramentas
                # controladas pela aplicação.
                # ============================================================

                if (
                    tool_name
                    in APPLICATION_CONTROLLED_TOOLS
                ):

                    tool_result = {
                        "error":
                            (
                                "Esta ferramenta é "
                                "controlada pela aplicação "
                                "e não pode ser executada "
                                "diretamente pelo modelo."
                            )
                    }

                elif (
                    tool_name
                    not in MODEL_ALLOWED_TOOLS
                ):

                    tool_result = {
                        "error":
                            (
                                "Ferramenta não permitida "
                                "para o modelo."
                            )
                    }

                else:

                    tool_result = (
                        await self.execute_mcp_tool(
                            tool_name,
                            arguments,
                        )
                    )

                # ============================================================
                # Resultado da ferramenta
                # ============================================================

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id":
                            tool_call.id,
                        "content":
                            json.dumps(
                                tool_result,
                                ensure_ascii=False,
                                default=str,
                            ),
                    }
                )

            # ================================================================
            # Depois das ferramentas, se já temos dois pontos,
            # a aplicação executa evaluate_link.
            # ================================================================

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                technical_result = (
                    await self.ensure_evaluate_link()
                )

                technical_context = (
                    self.build_technical_context(
                        technical_result
                    )
                )

                return (
                    await self.generate_final_response(
                        user_text,
                        technical_context,
                    )
                )

        return (
            "Não foi possível concluir a análise "
            "dentro do limite de iterações."
        )

    # ========================================================================
    # ASK
    # ========================================================================

    async def ask(
        self,
        user_text,
    ):

        if not OPENROUTER_API_KEY:

            raise RuntimeError(
                "OPENROUTER_API_KEY não encontrada."
            )

        # ====================================================================
        # CLIENTE
        # ====================================================================

        self.client = (
            self.create_client()
        )

        # ====================================================================
        # RESET DO ESTADO COMUM
        # ====================================================================

        self.reset_common_state()

        self.messages = []

        self.last_agent_text = ""

        # ====================================================================
        # EXTRAÇÃO DOS PARÂMETROS
        # ====================================================================

        self.extract_link_parameters(
            user_text
        )

        # ====================================================================
        # CONEXÃO MCP
        # ====================================================================

        await self.connect()

        # ====================================================================
        # REGISTER
        # ====================================================================

        await self.register()

        # ====================================================================
        # AGENTE
        # ====================================================================

        try:

            resultado = await self.agent_turn(
                user_text
            )

            # ================================================================
            # SEGURANÇA:
            # se por algum motivo ainda houver dois pontos mas
            # evaluate_link não tiver sido executado, executamos
            # pela aplicação.
            # ================================================================

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                technical_result = (
                    await self.ensure_evaluate_link()
                )

                technical_context = (
                    self.build_technical_context(
                        technical_result
                    )
                )

                resultado = (
                    await self.generate_final_response(
                        user_text,
                        technical_context,
                    )
                )

            return self.clean_final_response(
                resultado
            )

        finally:

            # ================================================================
            # Não fechamos aqui o MCP explicitamente,
            # pois o notebook controla o ciclo de vida do agente.
            # ================================================================

            pass

    # ========================================================================
    # CLOSE
    # ========================================================================

    async def close(
        self,
    ):

        if self.client:

            try:

                await self.client.close()

            except Exception:

                pass

            self.client = None

        await super().close()