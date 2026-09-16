# ============================================================
# PLANAPP AI — OLLAMA / QWEN
#
# ETAPA 1 — REFATORAÇÃO
#
# Fluxo:
#
#   Jupyter
#      |
#      v
#   Ollama / Qwen
#      |
#      v
#   geocode_place
#      |
#      v
#   aplicação executa evaluate_link
#      |
#      +--> mapa
#      |
#      +--> visualizações
#      |
#      v
#   Qwen analisa resultado técnico
#
# IMPORTANTE:
#   - comportamento de enlace único preservado
#   - NÃO implementa multi-hop
# ============================================================

import asyncio
import json
import os
import requests

import ipywidgets as widgets

from agent_common import (
    PlanAppAgentCommon,
    MCP_URL,
    USER_ID,
    DEFAULT_FREQ_MHZ,
    DEFAULT_TX_HA,
    DEFAULT_RX_HA,
    DEFAULT_ON_ROOFTOP,
    MAX_AGENT_ITERATIONS,
    LOG_DIR,
    APPLICATION_CONTROLLED_TOOLS,
)


# ============================================================
# CONFIGURAÇÃO OLLAMA
# ============================================================

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b",
)


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent(
    PlanAppAgentCommon
):

    AGENT_NAME = "PLANAPP AI — OLLAMA / QWEN"

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):

        super().__init__(
            progress_callback=progress_callback,
            map_callback=map_callback,
            log_callback=log_callback,
            result_callback=result_callback,
            visualization_callback=visualization_callback,
        )

        self._configure_logger()

        self.logger.info(
            "============================================================"
        )

        self.logger.info(
            "PLANAPP AI — OLLAMA / QWEN"
        )

        self.logger.info(
            f"MODEL={OLLAMA_MODEL}"
        )

        self.logger.info(
            f"MCP_URL={MCP_URL}"
        )

        self.logger.info(
            f"USER_ID={USER_ID}"
        )

        self.logger.info(
            "============================================================"
        )


    # ============================================================
    # LOG
    # ============================================================

    def _configure_logger(self):

        # O common já criou o handler.
        # O comportamento de log do Ollama continua usando
        # arquivo + callback.

        pass


    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico do sistema PlanApp.

REGRAS FUNDAMENTAIS:

1. O PlanApp é a fonte de verdade dos resultados técnicos.

2. Nunca invente valores.

3. Nunca invente unidades.

4. Nunca altere valores retornados pelo PlanApp.

5. Não faça cálculos técnicos por conta própria se o resultado
   correspondente já foi fornecido pelo PlanApp.

6. Quando o usuário fornecer duas localidades, elas devem ser
   geocodificadas.

7. Depois que as duas localidades forem obtidas, a aplicação
   executará automaticamente o evaluate_link.

8. NÃO execute evaluate_link diretamente.

9. A aplicação controla evaluate_link.

10. A aplicação também controla mapa e visualizações.

11. Não peça ao usuário para executar ferramentas.

12. Não diga ao usuário para aguardar.

13. Preserve exatamente frequência, alturas e rooftop solicitados.

14. Se a frequência estiver em GHz, MHz, kHz ou Hz, use a
    conversão correta para MHz.

15. Os valores padrão são:
       frequência = 900 MHz
       TX = 7 m
       RX = 7 m
       rooftop = false

16. FSPL significa perda de percurso em espaço livre.

17. FSPL não significa interferência.

18. Não conclua viabilidade do enlace sem dados suficientes.

19. Não invente potência TX.

20. Não invente ganho de antena.

21. Não invente sensibilidade do receptor.

22. Não invente margem de enlace.

23. Não interprete campos cujo significado não esteja explicitamente
    definido pelo PlanApp.

24. Não transforme core, fresnel, boundary ou delta_diffra em
    unidades que não estejam presentes no resultado.

25. Não converta radianos para graus por conta própria.

26. Não interprete VV, v_v ou d_norm sem definição explícita.

27. status=OK significa que a operação foi executada com sucesso.
    Não significa necessariamente que o enlace seja viável.

28. Responda em português do Brasil.

29. Seja técnico e objetivo.

30. Não apresente JSON bruto como resposta final.

O resultado técnico fornecido posteriormente pela aplicação deve
ser tratado como a fonte oficial para a análise.
"""


    # ============================================================
    # OLLAMA TOOLS
    # ============================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.mcp_tools:

            name = getattr(
                tool,
                "name",
                None,
            )

            if not name:
                continue

            if name in APPLICATION_CONTROLLED_TOOLS:
                continue

            schema = getattr(
                tool,
                "input_schema",
                None,
            )

            if schema is None:

                schema = getattr(
                    tool,
                    "inputSchema",
                    None,
                )

            if schema is None:

                schema = {
                    "type": "object",
                    "properties": {},
                }

            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": (
                        getattr(
                            tool,
                            "description",
                            ""
                        )
                        or ""
                    ),
                    "parameters": schema,
                },
            })

        return tools


    # ============================================================
    # OLLAMA CHAT
    # ============================================================

    async def ollama_chat(self):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
            "think": False,
        }

        response = await asyncio.to_thread(
            requests.post,
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=300,
        )

        response.raise_for_status()

        return response.json()


    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(self):

        if len(self.geocoded_points) < 2:
            return

        try:

            from map_utils import (
                mostrar_mapa_enlace,
            )

            p1 = self.geocoded_points[0]
            p2 = self.geocoded_points[1]

            self.map = (
                mostrar_mapa_enlace(
                    p1["lat"],
                    p1["lon"],
                    p2["lat"],
                    p2["lon"],
                )
            )

            if self.map_callback:

                self.map_callback(
                    self.map
                )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no mapa: {exc}"
            )


    # ============================================================
    # VISUALIZAÇÕES
    # ============================================================

    async def gerar_visualizacoes(self):

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

        for tool_name, args, title in tools:

            try:

                raw = await (
                    self.execute_mcp_tool_raw(
                        tool_name,
                        args,
                    )
                )

                parsed = self.parse_mcp_result(
                    raw
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
                        __import__(
                            "base64"
                        ).b64decode(
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

        # --------------------------------------------------------
        # CORREÇÃO:
        # envia a lista completa para a interface somente depois
        # que todas as visualizações foram geradas.
        # --------------------------------------------------------

        if self.visualization_callback:

            self.visualization_callback(
                self.visualizations
            )


    # ============================================================
    # AGENT TURN
    # ============================================================

    async def agent_turn(self):

        for _ in range(
            MAX_AGENT_ITERATIONS
        ):

            response = await (
                self.ollama_chat()
            )

            message = response.get(
                "message",
                {},
            )

            self.messages.append(
                message
            )

            tool_calls = message.get(
                "tool_calls",
                [],
            )


            if not tool_calls:

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and
                    not self.evaluate_executed
                ):

                    result = await (
                        self.ensure_evaluate_link()
                    )

                    if result is not None:

                        self.messages.append({
                            "role": "user",
                            "content": json.dumps(
                                self.build_technical_context(
                                    result
                                ),
                                ensure_ascii=False,
                                default=str,
                            ),
                        })

                        continue


                return message.get(
                    "content",
                    "",
                )


            for tool_call in tool_calls:

                function = (
                    tool_call.get(
                        "function",
                        {}
                    )
                )

                name = function.get(
                    "name"
                )

                arguments = function.get(
                    "arguments",
                    {},
                )


                if isinstance(
                    arguments,
                    str,
                ):

                    try:

                        arguments = json.loads(
                            arguments
                        )

                    except Exception:

                        arguments = {}


                if name in APPLICATION_CONTROLLED_TOOLS:

                    self.log_detail(
                        "⚠️ Ferramenta "
                        f"{name} é controlada "
                        "pela aplicação."
                    )

                    continue


                result = await (
                    self.execute_mcp_tool(
                        name,
                        arguments,
                    )
                )


                self.messages.append({
                    "role": "tool",
                    "content": json.dumps(
                        result,
                        ensure_ascii=False,
                        default=str,
                    ),
                })


            if (
                len(
                    self.geocoded_points
                ) >= 2
                and
                not self.evaluate_executed
            ):

                result = await (
                    self.ensure_evaluate_link()
                )

                if result is not None:

                    self.messages.append({
                        "role": "user",
                        "content": json.dumps(
                            self.build_technical_context(
                                result
                            ),
                            ensure_ascii=False,
                            default=str,
                        ),
                    })


        return (
            "Não foi possível concluir "
            "o processamento dentro do "
            "limite de iterações."
        )


    # ============================================================
    # ASK
    # ============================================================

    async def ask(
        self,
        text,
    ):

        self.reset_common_state()

        self.extract_link_parameters(
            text
        )

        await self.connect()

        await self.register()


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


        answer = await self.agent_turn()


        # --------------------------------------------------------
        # Garantia final — exatamente como o comportamento atual
        # --------------------------------------------------------

        if (
            len(
                self.geocoded_points
            ) >= 2
            and
            not self.evaluate_executed
        ):

            result = await (
                self.ensure_evaluate_link()
            )

            if result is not None:

                self.messages.append({
                    "role": "user",
                    "content": json.dumps(
                        self.build_technical_context(
                            result
                        ),
                        ensure_ascii=False,
                        default=str,
                    ),
                })

                answer = await self.agent_turn()


        if (
            len(
                self.geocoded_points
            ) >= 2
            and
            self.map is None
        ):

            await (
                self.mostrar_mapa_apos_geocodificacao()
            )


        return answer