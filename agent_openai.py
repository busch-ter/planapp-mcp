# ============================================================
# PLANAPP AI — OPENAI
#
# ETAPA 1 — REFATORAÇÃO
#
# Jupyter
#    |
#    v
# OpenAI Responses API / GPT-5.6 Luna
#    |
#    v
# geocode_place
#    |
#    v
# aplicação -> evaluate_link
#    |
#    +--> mapa
#    +--> visualizações
#    |
#    v
# análise técnica final
#
# NÃO implementa multi-hop.
# ============================================================

import asyncio
import json
import os

from openai import AsyncOpenAI

import ipywidgets as widgets

from agent_common import (
    PlanAppAgentCommon,
    MCP_URL,
    USER_ID,
    DEFAULT_FREQ_MHZ,
    DEFAULT_TX_HA,
    DEFAULT_RX_HA,
    DEFAULT_ON_ROOFTOP,
    APPLICATION_CONTROLLED_TOOLS,
)


# ============================================================
# OPENAI
# ============================================================

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)

OPENAI_REASONING_EFFORT = os.getenv(
    "OPENAI_REASONING_EFFORT",
    "medium",
)

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)


MAX_AGENT_ITERATIONS = 8


# ============================================================
# PREÇOS
# ============================================================

INPUT_PRICE_PER_MILLION = 0.20

CACHED_INPUT_PRICE_PER_MILLION = 0.02

OUTPUT_PRICE_PER_MILLION = 1.20


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent(
    PlanAppAgentCommon
):

    AGENT_NAME = "PLANAPP AI — OPENAI"

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


        # --------------------------------------------------------
        # OpenAI
        # --------------------------------------------------------

        self.client = None


        # --------------------------------------------------------
        # Estado OpenAI
        # --------------------------------------------------------

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        self.last_response_id = None


        # --------------------------------------------------------
        # Usage
        # --------------------------------------------------------

        self.input_tokens = 0

        self.cached_input_tokens = 0

        self.output_tokens = 0

        self.input_cost = 0.0

        self.cached_input_cost = 0.0

        self.output_cost = 0.0

        self.total_cost = 0.0


    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico do PlanApp.

O PlanApp é a fonte oficial dos resultados técnicos.

REGRAS:

1. Nunca invente valores.

2. Nunca invente unidades.

3. Nunca altere resultados retornados pelo PlanApp.

4. Não recalcule valores técnicos quando o PlanApp já os forneceu.

5. Quando o usuário fornecer duas localidades, utilize
   geocode_place para obter suas coordenadas.

6. Depois de obtidos os dois pontos, a aplicação executará
   automaticamente evaluate_link.

7. NÃO execute evaluate_link diretamente.

8. evaluate_link é controlado pela aplicação.

9. Mapa e visualizações também são controlados pela aplicação.

10. Não peça ao usuário para executar ferramentas.

11. Preserve frequência, TX, RX e rooftop solicitados.

12. Frequências podem ser informadas em GHz, MHz, kHz ou Hz.

13. Padrões:
       900 MHz
       TX 7 m
       RX 7 m
       rooftop=false

14. FSPL significa perda de percurso em espaço livre.

15. FSPL não significa interferência.

16. Não conclua viabilidade do enlace sem dados suficientes.

17. Não invente potência TX.

18. Não invente ganho de antena.

19. Não invente sensibilidade do receptor.

20. Não invente margem de enlace.

21. Não interprete campos sem definição explícita.

22. Não atribua significado próprio a core, fresnel,
    boundary, delta_diffra, VV, v_v ou d_norm.

23. Não converta radianos para graus.

24. status OK significa somente que a execução foi realizada
    com sucesso.

25. A resposta final deve ser em português do Brasil.

26. Seja técnico, claro e objetivo.

27. O resultado fornecido pela aplicação é a fonte de verdade.
"""


    # ============================================================
    # OPENAI CLIENT
    # ============================================================

    async def connect_openai(self):

        if not OPENAI_API_KEY:

            raise RuntimeError(
                "OPENAI_API_KEY não encontrada."
            )


        self.client = AsyncOpenAI(
            api_key=OPENAI_API_KEY
        )


    # ============================================================
    # OPENAI TOOLS
    # ============================================================

    def build_openai_tools(self):

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
                    "type":
                        "object",

                    "properties":
                        {},
                }


            tools.append({

                "type":
                    "function",

                "name":
                    name,

                "description":
                    getattr(
                        tool,
                        "description",
                        "",
                    )
                    or "",

                "parameters":
                    schema,
            })


        return tools


    # ============================================================
    # USAGE
    # ============================================================

    def update_usage(
        self,
        response,
    ):

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is None:
            return


        input_tokens = getattr(
            usage,
            "input_tokens",
            0,
        ) or 0


        output_tokens = getattr(
            usage,
            "output_tokens",
            0,
        ) or 0


        cached_tokens = 0


        details = getattr(
            usage,
            "input_tokens_details",
            None,
        )


        if details:

            cached_tokens = getattr(
                details,
                "cached_tokens",
                0,
            ) or 0


        self.input_tokens += (
            input_tokens
        )

        self.output_tokens += (
            output_tokens
        )

        self.cached_input_tokens += (
            cached_tokens
        )


        normal_input_tokens = max(
            input_tokens
            - cached_tokens,
            0,
        )


        self.input_cost += (
            normal_input_tokens
            / 1_000_000
            * INPUT_PRICE_PER_MILLION
        )


        self.cached_input_cost += (
            cached_tokens
            / 1_000_000
            * CACHED_INPUT_PRICE_PER_MILLION
        )


        self.output_cost += (
            output_tokens
            / 1_000_000
            * OUTPUT_PRICE_PER_MILLION
        )


        self.total_cost = (
            self.input_cost
            + self.cached_input_cost
            + self.output_cost
        )


        self.log_detail(
            "OpenAI usage: "
            f"input={input_tokens}, "
            f"cached={cached_tokens}, "
            f"output={output_tokens}, "
            f"cost=${self.total_cost:.6f}"
        )


    # ============================================================
    # RESPONSES API
    # ============================================================

    async def openai_chat(
        self,
        input_data,
        tools=None,
        previous_response_id=None,
    ):

        if self.client is None:

            await self.connect_openai()


        kwargs = {

            "model":
                OPENAI_MODEL,

            "input":
                input_data,

            "reasoning": {

                "effort":
                    OPENAI_REASONING_EFFORT,
            },
        }


        if tools:

            kwargs["tools"] = tools


        if previous_response_id:

            kwargs[
                "previous_response_id"
            ] = previous_response_id


        response = await (
            self.client.responses.create(
                **kwargs
            )
        )


        self.update_usage(
            response
        )


        self.last_response_id = (
            getattr(
                response,
                "id",
                None,
            )
        )


        return response


    # ============================================================
    # NORMALIZA OUTPUT
    # ============================================================

    def response_text(
        self,
        response,
    ):

        text = getattr(
            response,
            "output_text",
            None,
        )


        if text:

            return text


        parts = []


        output = getattr(
            response,
            "output",
            None,
        ) or []


        for item in output:

            item_type = getattr(
                item,
                "type",
                None,
            )


            if item_type == "message":

                content = getattr(
                    item,
                    "content",
                    None,
                ) or []


                for block in content:

                    block_text = getattr(
                        block,
                        "text",
                        None,
                    )


                    if block_text:

                        parts.append(
                            block_text
                        )


        return "\n".join(
            parts
        ).strip()


    # ============================================================
    # TOOL CALLS
    # ============================================================

    def response_tool_calls(
        self,
        response,
    ):

        calls = []


        output = getattr(
            response,
            "output",
            None,
        ) or []


        for item in output:

            item_type = getattr(
                item,
                "type",
                None,
            )


            if item_type != "function_call":
                continue


            name = getattr(
                item,
                "name",
                None,
            )


            arguments = getattr(
                item,
                "arguments",
                "{}",
            )


            call_id = getattr(
                item,
                "call_id",
                None,
            )


            calls.append({

                "name":
                    name,

                "arguments":
                    arguments,

                "call_id":
                    call_id,
            })


        return calls


    # ============================================================
    # APPEND TECHNICAL CONTEXT
    # ============================================================

    def append_technical_context(
        self,
        result,
    ):

        context = (
            self.build_technical_context(
                result
            )
        )


        self.messages.append({

            "role":
                "user",

            "content":
                json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                ),
        })


        self.technical_context_added = True


    # ============================================================
    # AGENT TURN
    # ============================================================

    async def agent_turn(self):

        for _ in range(
            MAX_AGENT_ITERATIONS
        ):

            response = await (
                self.openai_chat(
                    self.messages,
                    self.build_openai_tools(),
                    self.last_response_id,
                )
            )


            tool_calls = (
                self.response_tool_calls(
                    response
                )
            )


            text = self.response_text(
                response
            )


            if text:

                self.last_agent_text = (
                    text
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

                        self.append_technical_context(
                            result
                        )

                        self.last_response_id = None

                        continue


                return text


            # ----------------------------------------------------
            # Tool calls
            # ----------------------------------------------------

            tool_outputs = []


            for call in tool_calls:

                name = call["name"]


                if name in APPLICATION_CONTROLLED_TOOLS:

                    self.log_detail(
                        "⚠️ Ferramenta "
                        f"{name} é controlada "
                        "pela aplicação."
                    )

                    continue


                try:

                    arguments = json.loads(
                        call["arguments"]
                        or "{}"
                    )

                except Exception:

                    arguments = {}


                result = await (
                    self.execute_mcp_tool(
                        name,
                        arguments,
                    )
                )


                tool_outputs.append({

                    "type":
                        "function_call_output",

                    "call_id":
                        call["call_id"],

                    "output":
                        json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        ),
                })


            if tool_outputs:

                self.messages.extend(
                    tool_outputs
                )


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

                    self.append_technical_context(
                        result
                    )

                    self.last_response_id = None


        return (
            "Não foi possível concluir "
            "o processamento dentro do "
            "limite de iterações."
        )


    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(
        self
    ):

        if len(
            self.geocoded_points
        ) < 2:

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
    #
    # Mantida como ponto específico do agente.
    # ============================================================

    async def gerar_visualizacoes(
        self
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


                image_bytes = (
                    __import__(
                        "base64"
                    ).b64decode(
                        data
                    )
                )


                image = widgets.Image(
                    value=image_bytes
                )


                self.visualizations.append(
                    image
                )


                if self.visualization_callback:

                    self.visualization_callback(
                        image,
                        title,
                    )


            except Exception as exc:

                self.log_detail(
                    f"⚠️ Visualização "
                    f"{title}: {exc}"
                )


    # ============================================================
    # FINAL RESPONSE
    # ============================================================

    async def generate_final_response(
        self,
        original_text,
        technical_result,
    ):

        context = (
            self.build_technical_context(
                technical_result
            )
        )


        input_data = [

            {
                "role":
                    "system",

                "content":
                    self.system_prompt(),
            },

            {
                "role":
                    "user",

                "content":
                    original_text,
            },

            {
                "role":
                    "user",

                "content":
                    json.dumps(
                        context,
                        ensure_ascii=False,
                        default=str,
                    ),
            },

            {
                "role":
                    "user",

                "content":
                    (
                        "Produza a resposta técnica "
                        "final em português do Brasil. "
                        "Use exclusivamente os dados "
                        "retornados pelo PlanApp."
                    ),
            },
        ]


        response = await (
            self.openai_chat(
                input_data,
                tools=None,
                previous_response_id=None,
            )
        )


        return self.response_text(
            response
        )


    # ============================================================
    # ASK
    # ============================================================

    async def ask(
        self,
        text,
    ):

        if not OPENAI_API_KEY:

            raise RuntimeError(
                "OPENAI_API_KEY não encontrada."
            )


        self.reset_common_state()


        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        self.last_response_id = None


        self.input_tokens = 0

        self.cached_input_tokens = 0

        self.output_tokens = 0

        self.input_cost = 0.0

        self.cached_input_cost = 0.0

        self.output_cost = 0.0

        self.total_cost = 0.0


        self.extract_link_parameters(
            text
        )


        await self.connect_openai()

        await self.connect()

        await self.register()


        self.messages = [

            {
                "role":
                    "system",

                "content":
                    self.system_prompt(),
            },

            {
                "role":
                    "user",

                "content":
                    text,
            },
        ]


        await self.agent_turn()


        # --------------------------------------------------------
        # Garantia final de evaluate_link
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

                self.append_technical_context(
                    result
                )


        # --------------------------------------------------------
        # Resposta técnica final
        # --------------------------------------------------------

        if self.evaluate_executed:

            answer = await (
                self.generate_final_response(
                    text,
                    self.last_evaluate_result,
                )
            )

        else:

            answer = self.last_agent_text


        # --------------------------------------------------------
        # Mapa final
        # --------------------------------------------------------

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


    # ============================================================
    # CLOSE
    # ============================================================

    async def close(
        self
    ):

        await super().close()

        self.client = None