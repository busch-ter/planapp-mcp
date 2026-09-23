# ============================================================
# PLANAPP AI — OLLAMA / QWEN
#
# ETAPA 1 — REFATORAÇÃO
#
# Fluxo:
#   Jupyter
#      |
#      v
#   Ollama / Qwen
#      |
#      v
#   geocode_place
#      |
#      v
#   aplicação -> evaluate_link
#      |
#      +--> mapa interativo
#      +--> visualizações
#      +--> relatório técnico / PDF
#      |
#      v
#   Qwen analisa resultado técnico
#
# IMPORTANTE:
#   - comportamento de enlace único preservado
#   - NÃO implementa multi-hop
#   - evaluate_link é controlado pela aplicação
#   - mapa e visualizações são controlados pela aplicação
# ============================================================

import asyncio
import base64
import json
import os
import re

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

from report_generator import ReportGenerator


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

# Limites específicos da análise final.
# A chamada final não precisa das ferramentas MCP nem de uma resposta
# gigantesca: o trabalho técnico já foi executado pela aplicação.
OLLAMA_FINAL_TIMEOUT = int(os.getenv("OLLAMA_FINAL_TIMEOUT", "300"))
OLLAMA_FINAL_NUM_PREDICT = int(os.getenv("OLLAMA_FINAL_NUM_PREDICT", "2500"))


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent(PlanAppAgentCommon):

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

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        # Texto final produzido pelo Qwen.
        # Esse texto também será utilizado como
        # conteúdo principal do relatório técnico.
        self.technical_report = ""

        # ========================================================
        # SOLICITAÇÃO ORIGINAL DO USUÁRIO
        # ========================================================

        self.user_request = ""

        # ========================================================
        # RELATÓRIO
        # ========================================================

        self.report_pdf_path = None

        # ========================================================
        # MAPA
        # ========================================================

        self.map = None

        self.map_image_bytes = None

        # ========================================================
        # VISUALIZAÇÕES
        # ========================================================

        self.visualizations = []

        self.visualization_images = []

        # ========================================================
        # LOG
        # ========================================================

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
            f"OLLAMA_URL={OLLAMA_URL}"
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
    # LOGGER
    # ============================================================

    def _configure_logger(self):

        # O PlanAppAgentCommon já configura o logger.
        # Mantemos este método para compatibilidade.
        pass

    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico especializado em
planejamento e avaliação de enlaces de rádio.

O PlanApp é a fonte oficial dos resultados técnicos.

Seu papel é interpretar tecnicamente os dados retornados pelo
PlanApp sem inventar informações que não estejam presentes.

REGRAS FUNDAMENTAIS:

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

16. Não conclua viabilidade do enlace sem um critério técnico
    explícito e sustentado pelos dados disponíveis.

17. Não invente potência TX.

18. Não invente ganho de antena.

19. Não invente sensibilidade do receptor.

20. Não invente margem de enlace.

21. Não atribua significado físico a campos cuja definição não
    esteja explicitamente documentada pelo PlanApp.

22. Não atribua significado próprio a:

       core
       fresnel
       boundary
       delta_diffra
       VV
       v_v
       d_norm

23. Não converta radianos para graus.

24. status OK significa somente que a execução foi realizada
    com sucesso.

25. O resultado fornecido pela aplicação é a fonte de verdade.

26. O relatório técnico fornecido pela aplicação, quando existir,
    é apenas uma apresentação estruturada dos dados reais do
    PlanApp.

27. Não altere, recalcule ou contradiga os valores presentes
    nos resultados do PlanApp.

28. Diferencie claramente:

       - parâmetros solicitados pelo usuário;
       - parâmetros efetivamente utilizados;
       - resultados retornados pelo PlanApp;
       - interpretação técnica;
       - limitações da análise.

29. Se um campo técnico não tiver definição explícita, apresente
    o valor somente como resultado retornado pelo PlanApp,
    sem atribuir significado adicional.

30. A resposta técnica NÃO deve ser apenas uma reprodução
    do JSON.

31. Organize os resultados em seções claras.

32. Faça uma síntese objetiva dos resultados efetivamente
    retornados.

33. Pode comparar numericamente valores que já foram retornados
    pelo PlanApp.

34. Pode destacar diferenças entre parâmetros solicitados e
    parâmetros efetivamente utilizados.

35. Pode destacar distância, FSPL, delta_diffra, resultados
    de terreno, vegetação, edificações e resultados geométricos
    quando esses valores estiverem presentes.

36. Ao apresentar conjuntos como terreno, vegetação ou
    edificações, deixe claro que são resultados retornados
    pelo PlanApp.

37. Não atribua interpretação física adicional aos nomes dos
    campos quando sua definição não estiver documentada.

38. Informe quais etapas foram efetivamente executadas quando
    essa informação estiver disponível.

39. Diferencie claramente dados fornecidos pelo usuário,
    parâmetros utilizados, resultados calculados e limitações.

40. Não declare o enlace como viável ou inviável sem um
    critério técnico explícito.

41. Não invente uma margem, limiar, classificação ou conclusão
    de engenharia que não esteja presente nos dados.

42. A resposta final deve ser em português do Brasil.

43. Seja técnico, claro, objetivo e informativo.

44. Prefira uma análise estruturada a uma simples listagem
    de campos.

45. A análise deve considerar conjuntamente os dados disponíveis
    de propagação, geometria, terreno, vegetação, edificações
    e demais resultados fornecidos pelo PlanApp.

46. Não trate um único indicador isoladamente como suficiente
    para determinar a qualidade do enlace.

47. Quando houver dados suficientes e um critério técnico
    documentado pelo PlanApp, apresente claramente a conclusão
    correspondente.

48. Quando não houver critério suficiente para uma conclusão de
    viabilidade, declare explicitamente essa limitação.

49. Sugestões de alteração de frequência, altura de antena,
    posicionamento ou outras alternativas devem ser apresentadas
    como sugestões, e não como soluções comprovadas.

50. Não diga que uma alternativa resolve o problema se ela não
    tiver sido efetivamente testada pelo PlanApp.

51. Diferencie claramente:

       - alternativa sugerida;
       - alternativa efetivamente testada pelo PlanApp.

52. A análise deve procurar relações entre os diferentes
    resultados retornados, mas sem inventar significado para
    campos cuja semântica não esteja documentada.
"""

    # ============================================================
    # OLLAMA
    # ============================================================

    async def connect_ollama(self):

        # O Ollama é acessado via HTTP.
        # Não existe uma sessão persistente como na OpenAI.

        try:

            response = await asyncio.to_thread(
                requests.get,
                f"{OLLAMA_URL}/api/tags",
                timeout=10,
            )

            response.raise_for_status()

            self.log_detail(
                "Ollama conectado."
            )

        except Exception as exc:

            raise RuntimeError(
                f"Não foi possível conectar ao Ollama: {exc}"
            )

    # ============================================================
    # FERRAMENTAS OLLAMA
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

            # Ferramentas controladas pela aplicação
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

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            getattr(
                                tool,
                                "description",
                                "",
                            )
                            or ""
                        ),
                        "parameters": schema,
                    },
                }
            )

        return tools

    # ============================================================
    # CHAT OLLAMA
    # ============================================================

    async def ollama_chat(
        self,
        *,
        use_tools=True,
        options=None,
    ):
        """Envia uma conversa ao Ollama.

        Durante o agente normal, as ferramentas MCP são enviadas.
        Na análise final, porém, não há nenhuma ferramenta a executar;
        portanto a chamada final pode ser muito menor e mais previsível.
        """

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "stream": False,
            "think": False,
        }

        if use_tools:
            payload["tools"] = self.build_ollama_tools()

        if options:
            payload["options"] = options

        self.log_detail(
            f"Enviando requisição ao Ollama: {OLLAMA_MODEL}"
        )

        if not use_tools:
            self.log_detail(
                "Análise final: chamada ao Ollama sem ferramentas MCP."
            )

        try:

            timeout = (
                OLLAMA_FINAL_TIMEOUT
                if not use_tools
                else 600
            )

            response = await asyncio.to_thread(
                requests.post,
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=timeout,
            )

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                raise RuntimeError(
                    "Ollama retornou uma resposta em formato inesperado."
                )

            if not use_tools:
                final_text = self.response_text(data)
                self.log_detail(
                    "Resposta final do Qwen recebida: "
                    f"{len(final_text)} caracteres."
                )

                if not final_text:
                    self.log_detail(
                        "⚠️ O Qwen respondeu sem texto na análise final."
                    )

            return data

        except requests.Timeout as exc:

            self.log_detail(
                "⚠️ Timeout na análise final do Qwen: "
                f"{exc}"
            )

            raise RuntimeError(
                "O Ollama não concluiu a análise final dentro do "
                f"tempo limite de {OLLAMA_FINAL_TIMEOUT}s."
            )

        except requests.RequestException as exc:

            raise RuntimeError(
                f"Erro na comunicação com Ollama: {exc}"
            )

        except Exception as exc:

            raise RuntimeError(
                f"Erro ao processar resposta do Ollama: {exc}"
            )

    # ============================================================
    # EXTRAÇÃO DA RESPOSTA OLLAMA
    # ============================================================

    def response_message(
        self,
        response,
    ):

        if not isinstance(
            response,
            dict,
        ):
            return {}

        message = response.get(
            "message",
            {},
        )

        if not isinstance(
            message,
            dict,
        ):
            return {}

        return message

    def response_text(
        self,
        response,
    ):

        message = self.response_message(
            response
        )

        content = message.get(
            "content",
            "",
        )

        if content is None:
            return ""

        return str(
            content
        ).strip()

    def response_tool_calls(
        self,
        response,
    ):

        message = self.response_message(
            response
        )

        tool_calls = message.get(
            "tool_calls",
            [],
        )

        if not isinstance(
            tool_calls,
            list,
        ):
            return []

        return tool_calls

    # ============================================================
    # CONTEXTO TÉCNICO
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

        self.messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )

        self.technical_context_added = True

        self.log_detail(
            "Contexto técnico do PlanApp enviado ao Qwen."
        )

    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(
        self,
    ):

        if len(
            self.geocoded_points
        ) < 2:

            return

        try:

            from map_utils import (
                mostrar_mapa_enlace,
                gerar_imagem_mapa_enlace,
            )

            p1 = (
                self.geocoded_points[0]
            )

            p2 = (
                self.geocoded_points[1]
            )

            tx_lat = p1["lat"]
            tx_lon = p1["lon"]

            rx_lat = p2["lat"]
            rx_lon = p2["lon"]

            # ----------------------------------------------------
            # MAPA INTERATIVO
            # ----------------------------------------------------

            self.map = (
                mostrar_mapa_enlace(
                    tx_lat,
                    tx_lon,
                    rx_lat,
                    rx_lon,
                )
            )

            if self.map_callback:

                self.map_callback(
                    self.map
                )

            # ----------------------------------------------------
            # IMAGEM ESTÁTICA PARA PDF
            # ----------------------------------------------------

            self.map_image_bytes = (
                gerar_imagem_mapa_enlace(
                    tx_lat,
                    tx_lon,
                    rx_lat,
                    rx_lon,
                )
            )

            self.log_detail(
                "Mapa interativo preparado."
            )

            self.log_detail(
                "Imagem estática do mapa OSM "
                "preparada para o relatório."
            )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no mapa: {exc}"
            )

    # ============================================================
    # VISUALIZAÇÕES
    # ============================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.evaluate_executed:

            self.log_detail(
                "Visualizações não executadas: "
                "evaluate_link ainda não foi executado."
            )

            return

        if self.evaluate_error:

            self.log_detail(
                "Visualizações não executadas: "
                "evaluate_link apresentou erro."
            )

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

        self.visualization_images = []

        for (
            tool_name,
            arguments,
            title,
        ) in tools:

            try:

                self.log_detail(
                    f"Preparando visualização: {title}"
                )

                raw = (
                    await self.execute_mcp_tool_raw(
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

                    self.log_detail(
                        f"⚠️ {title}: "
                        "resultado não é um objeto."
                    )

                    continue

                if parsed.get(
                    "kind"
                ) != "image":

                    self.log_detail(
                        f"⚠️ {title}: "
                        "resultado não contém imagem."
                    )

                    continue

                data = parsed.get(
                    "data"
                )

                if not data:

                    self.log_detail(
                        f"⚠️ {title}: "
                        "imagem sem dados."
                    )

                    continue

                image_bytes = (
                    base64.b64decode(
                        data
                    )
                )

                # ------------------------------------------------
                # WIDGET JUPYTER
                # ------------------------------------------------

                image = widgets.Image(
                    value=image_bytes,
                    format="png",
                    layout=widgets.Layout(
                        width="100%",
                        height="auto",
                    ),
                )

                self.visualizations.append(
                    image
                )

                # ------------------------------------------------
                # DADOS BRUTOS PARA O PDF
                # ------------------------------------------------

                self.visualization_images.append(
                    {
                        "title": title,
                        "data": image_bytes,
                        "mime_type": "image/png",
                    }
                )

                # ------------------------------------------------
                # CALLBACK INCREMENTAL
                #
                # notebook_ui.py espera:
                #
                #   callback(imagem, titulo)
                #
                # e não:
                #
                #   callback(lista)
                # ------------------------------------------------

                if self.visualization_callback:

                    self.visualization_callback(
                        image,
                        title,
                    )

                self.log_detail(
                    f"Visualização preparada: {title}"
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Visualização "
                    f"{title}: {exc}"
                )

        self.log_detail(
            "Total de visualizações "
            f"preparadas: "
            f"{len(self.visualization_images)}"
        )

    # ============================================================
    # RELATÓRIO
    # ============================================================

    def build_report(
        self,
        technical_result,
        analysis_text=None,
    ):

        # --------------------------------------------------------
        # PARÂMETROS SOLICITADOS
        # --------------------------------------------------------

        requested_parameters = {

            "frequency": getattr(
                self,
                "requested_frequency",
                None,
            ),

            "frequency_unit": getattr(
                self,
                "requested_frequency_unit",
                None,
            ),

            "frequency_text": getattr(
                self,
                "requested_frequency_text",
                None,
            ),

            "tx_ha": getattr(
                self,
                "requested_tx_ha",
                None,
            ),

            "rx_ha": getattr(
                self,
                "requested_rx_ha",
                None,
            ),

            "on_rooftop": getattr(
                self,
                "requested_on_rooftop",
                None,
            ),
        }

        # --------------------------------------------------------
        # PARÂMETROS EFETIVOS
        # --------------------------------------------------------

        link_parameters = getattr(
            self,
            "link_parameters",
            {},
        )

        if not isinstance(
            link_parameters,
            dict,
        ):

            link_parameters = {}

        effective_parameters = {

            "freq_mhz": link_parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ,
            ),

            "tx_ha": link_parameters.get(
                "tx_ha",
                DEFAULT_TX_HA,
            ),

            "rx_ha": link_parameters.get(
                "rx_ha",
                DEFAULT_RX_HA,
            ),

            "on_rooftop": link_parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP,
            ),
        }

        # --------------------------------------------------------
        # GARANTIR IMAGEM DO MAPA
        # --------------------------------------------------------

        if (
            self.map_image_bytes is None
            and len(
                self.geocoded_points
            ) >= 2
        ):

            try:

                from map_utils import (
                    gerar_imagem_mapa_enlace
                )

                p1 = (
                    self.geocoded_points[0]
                )

                p2 = (
                    self.geocoded_points[1]
                )

                self.map_image_bytes = (
                    gerar_imagem_mapa_enlace(
                        p1["lat"],
                        p1["lon"],
                        p2["lat"],
                        p2["lon"],
                    )
                )

            except Exception as exc:

                self.log_detail(
                    "⚠️ Não foi possível "
                    "gerar imagem do mapa "
                    "para o relatório: "
                    f"{exc}"
                )

        # --------------------------------------------------------
        # GERADOR
        # --------------------------------------------------------

        generator = ReportGenerator(

            requested_params=(
                requested_parameters
            ),

            effective_params=(
                effective_parameters
            ),

            technical_result=(
                technical_result
            ),

            geocoded_points=(
                self.geocoded_points
            ),

            map_image=(
                self.map_image_bytes
            ),

            visualization_images=(
                self.visualization_images
            ),

            user_request=(
                self.user_request
            ),

            # ----------------------------------------------------
            # NOVO:
            # a análise final do Qwen é o conteúdo principal
            # do relatório.
            # ----------------------------------------------------
            analysis_text=(
                analysis_text
                if analysis_text
                else None
            ),
        )

        # --------------------------------------------------------
        # TEXTO DO RELATÓRIO
        # --------------------------------------------------------

        report = generator.generate_report(
            include_raw_result=False
        )

        self.technical_report = report

        # --------------------------------------------------------
        # PDF
        # --------------------------------------------------------

        pdf_path = generator.generate_pdf(
            report_text=report,
            include_raw_result=False,
        )

        self.report_pdf_path = pdf_path

        self.log_detail(
            "Relatório PDF gerado: "
            f"{pdf_path}"
        )

        self.log_detail(
            "Mapa no relatório: "
            + (
                "SIM"
                if self.map_image_bytes
                else "NÃO"
            )
        )

        self.log_detail(
            "Visualizações no relatório: "
            f"{len(self.visualization_images)}"
        )

        return report

    # ============================================================
    # AGENT TURN
    # ============================================================

    async def agent_turn(
        self,
    ):

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.log_detail(
                f"Iteração do agente: "
                f"{iteration + 1}/"
                f"{MAX_AGENT_ITERATIONS}"
            )

            response = (
                await self.ollama_chat()
            )

            text = (
                self.response_text(
                    response
                )
            )

            if text:

                self.last_agent_text = (
                    text
                )

            tool_calls = (
                self.response_tool_calls(
                    response
                )
            )

            # ----------------------------------------------------
            # NENHUMA FERRAMENTA
            # ----------------------------------------------------

            if not tool_calls:

                # Se já temos os dois pontos, mas
                # evaluate_link ainda não foi executado,
                # a aplicação executa.
                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    result = (
                        await self.ensure_evaluate_link()
                    )

                    if result is not None:

                        self.append_technical_context(
                            result
                        )

                        continue

                return text

            # ----------------------------------------------------
            # EXECUÇÃO DAS FERRAMENTAS MCP
            # ----------------------------------------------------

            tool_messages = []

            for call in tool_calls:

                function = call.get(
                    "function",
                    {},
                )

                if not isinstance(
                    function,
                    dict,
                ):
                    continue

                name = function.get(
                    "name"
                )

                if not name:
                    continue

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

                    except Exception as exc:

                        self.log_detail(
                            f"⚠️ Argumentos inválidos "
                            f"para {name}: {exc}"
                        )

                        arguments = {}

                if not isinstance(
                    arguments,
                    dict,
                ):

                    arguments = {}

                # ------------------------------------------------
                # SEGURANÇA
                # ------------------------------------------------

                if name in APPLICATION_CONTROLLED_TOOLS:

                    self.log_detail(
                        f"⚠️ Ferramenta {name} "
                        "é controlada pela aplicação."
                    )

                    # Não executamos a ferramenta.
                    # Não pedimos ao usuário para executá-la.
                    continue

                # ------------------------------------------------
                # EXECUTA MCP
                # ------------------------------------------------

                self.log_detail(
                    "Executando ferramenta MCP: "
                    f"{name}"
                )

                try:

                    result = (
                        await self.execute_mcp_tool(
                            name,
                            arguments,
                        )
                    )

                    tool_messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result,
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Erro na ferramenta "
                        f"{name}: {exc}"
                    )

                    tool_messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {
                                    "error": str(
                                        exc
                                    )
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )

            # ----------------------------------------------------
            # ADICIONA RESULTADOS DAS FERRAMENTAS
            # ----------------------------------------------------

            if tool_messages:

                self.messages.extend(
                    tool_messages
                )

                # Se já temos os dois pontos,
                # a aplicação executa evaluate_link.
                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    result = (
                        await self.ensure_evaluate_link()
                    )

                    if result is not None:

                        self.append_technical_context(
                            result
                        )

                continue

            # ----------------------------------------------------
            # GARANTIA FINAL DO EVALUATE
            # ----------------------------------------------------

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                result = (
                    await self.ensure_evaluate_link()
                )

                if result is not None:

                    self.append_technical_context(
                        result
                    )

                    continue

            return text

        return (
            "Não foi possível concluir "
            "o processamento dentro do "
            "limite de iterações."
        )

    # ============================================================
    # RESPOSTA FINAL
    # ============================================================

    async def generate_final_response(
        self,
        original_text,
        technical_result,
        technical_report=None,
    ):

        context = (
            self.build_technical_context(
                technical_result
            )
        )

        if technical_report is None:
            technical_report = ""

        # --------------------------------------------------------
        # MENSAGENS EXCLUSIVAS PARA A ANÁLISE FINAL
        # --------------------------------------------------------

        final_messages = [

            {
                "role": "system",
                "content": self.system_prompt(),
            },

            {
                "role": "user",
                "content": original_text,
            },

            {
                "role": "user",
                "content": json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]

        if technical_report:

            final_messages.append(
                {
                    "role": "user",
                    "content": (
                        "RELATÓRIO TÉCNICO "
                        "GERADO PELA APLICAÇÃO:\n\n"
                        + technical_report
                    ),
                }
            )

        final_messages.append(
            {
                "role": "user",
                "content": """
Produza agora a análise técnica final do enlace em português
do Brasil.

Você recebeu os resultados efetivamente produzidos pelo PlanApp.
Analise esses resultados como um engenheiro responsável pela
interpretação técnica dos dados.

A resposta NÃO deve ser apenas uma reprodução do JSON.

Considere conjuntamente, quando disponíveis:

- geometria do enlace;
- distância;
- frequência;
- alturas das antenas;
- FSPL;
- resultados de terreno;
- resultados de vegetação/COVER;
- resultados de edificações;
- resultados de Fresnel;
- resultados geométricos;
- demais indicadores retornados pelo PlanApp.

Não atribua significado físico a campos cuja definição não esteja
documentada.

A análise deve distinguir claramente dados, interpretação e
limitações.

Use exatamente esta estrutura de seções, adaptando o conteúdo
àquilo que efetivamente estiver disponível:

## 1. RESUMO EXECUTIVO

Apresente uma síntese técnica objetiva do resultado.

Se houver critério técnico explícito suficiente nos dados,
apresente a conclusão correspondente.

Se não houver critério suficiente para classificar a viabilidade,
declare explicitamente que a viabilidade não pode ser determinada
a partir dos dados disponíveis.

## 2. IDENTIFICAÇÃO DO ENLACE

Apresente:

- localidade TX;
- coordenadas TX;
- localidade RX;
- coordenadas RX;
- distância, quando retornada.

## 3. PARÂMETROS UTILIZADOS

Diferencie:

- parâmetros solicitados pelo usuário;
- parâmetros efetivamente utilizados pelo PlanApp.

Apresente:

- frequência;
- altura TX;
- altura RX;
- rooftop;
- demais parâmetros relevantes efetivamente retornados.

## 4. ANÁLISE DE PROPAGAÇÃO

Analise os resultados de propagação efetivamente retornados.

Quando disponível, apresente:

- FSPL;
- delta_diffra;
- outros resultados de propagação.

Não invente significado para campos não documentados.

## 5. ANÁLISE DO TERRENO

Apresente os resultados retornados para terreno.

Compare numericamente os valores quando isso for útil.

Não atribua significado adicional a core, fresnel, boundary,
v_v, VV ou d_norm sem documentação explícita.

## 6. ANÁLISE DA FRESNEL

Apresente os resultados relacionados à Fresnel que estejam
efetivamente disponíveis.

Não invente um critério de obstrução.

Não transforme indicadores não documentados em percentuais,
margens ou classificações.

## 7. VEGETAÇÃO / COBERTURA

Apresente os resultados de COVER/LULC retornados pelo PlanApp.

Deixe claro que são resultados computacionais retornados pelo
PlanApp e não invente classificação adicional.

## 8. EDIFICAÇÕES

Apresente os resultados relacionados a edificações.

Destaque numericamente os valores disponíveis.

Não atribua significado físico adicional aos campos sem
documentação.

## 9. GEOMETRIA E OBSTÁCULOS

Apresente os resultados geométricos retornados pelo PlanApp.

Inclua, quando presentes:

- ângulos;
- clearance;
- obstáculos;
- demais valores geométricos.

Não converta radianos para graus.

## 10. PRINCIPAIS FATORES LIMITANTES

Identifique quais resultados efetivamente disponíveis merecem
atenção técnica.

Não invente fatores que não estejam sustentados pelos dados.

## 11. DIAGNÓSTICO TÉCNICO

Faça uma síntese integrada dos resultados.

Relacione, quando possível, os diferentes conjuntos de dados:
propagação, terreno, vegetação, edificações e geometria.

Não trate um único indicador isoladamente como suficiente.

## 12. CONCLUSÃO DE VIABILIDADE

Use uma das seguintes classificações SOMENTE quando houver
critério técnico explícito e suficiente nos dados:

- VIÁVEL
- NÃO VIÁVEL
- VIÁVEL COM RESSALVAS
- INDETERMINADO

Se não houver critério suficiente, utilize:

INDETERMINADO

e explique objetivamente quais informações ou critérios estão
faltando.

Não invente limiares de engenharia.

## 13. ALTERNATIVAS

Quando apropriado, sugira alternativas como:

- alteração de altura;
- alteração de frequência;
- alteração de posicionamento;
- alteração de parâmetros.

Porém:

- identifique-as como sugestões;
- não diga que resolvem o problema;
- não diga que foram testadas se não foram;
- se uma alternativa tiver sido efetivamente testada pelo PlanApp,
  deixe isso explícito.

## 14. RECOMENDAÇÕES

Apresente recomendações técnicas baseadas exclusivamente nos
dados disponíveis.

Diferencie claramente recomendações de resultados efetivamente
testados.

## 15. LIMITAÇÕES

Liste as limitações da análise.

Inclua especialmente qualquer critério de engenharia necessário
para uma conclusão definitiva que não esteja presente nos dados
fornecidos pelo PlanApp.

REGRAS ABSOLUTAS:

- Não invente valores.
- Não altere valores.
- Não altere unidades.
- Não faça cálculos técnicos adicionais.
- Não converta radianos para graus.
- Não invente potência.
- Não invente ganho.
- Não invente sensibilidade.
- Não invente margem.
- Não invente limiares.
- Não invente critérios de viabilidade.
- Não atribua significado próprio a core.
- Não atribua significado próprio a fresnel.
- Não atribua significado próprio a boundary.
- Não atribua significado próprio a delta_diffra.
- Não atribua significado próprio a VV.
- Não atribua significado próprio a v_v.
- Não atribua significado próprio a d_norm.
- Não confunda status OK com viabilidade.
- Não diga que uma alternativa resolve o problema sem que ela
  tenha sido testada.
- Não apresente uma sugestão como se fosse um resultado do
  PlanApp.
- Seja técnico, objetivo e claro.
"""
            }
        )

        # --------------------------------------------------------
        # CHAT FINAL
        # --------------------------------------------------------

        old_messages = self.messages

        try:

            self.messages = final_messages

            response = (
                await self.ollama_chat()
            )

            answer = (
                self.response_text(
                    response
                )
            )

            if answer:

                self.last_agent_text = (
                    answer
                )

            return answer

        finally:

            self.messages = old_messages

    # ============================================================
    # ASK
    # ============================================================

    async def ask(
        self,
        text,
    ):

        # --------------------------------------------------------
        # RESET
        # --------------------------------------------------------

        self.reset_common_state()

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        self.technical_report = ""

        self.report_pdf_path = None

        # --------------------------------------------------------
        # SOLICITAÇÃO ORIGINAL
        # --------------------------------------------------------

        self.user_request = text

        # --------------------------------------------------------
        # MAPA
        # --------------------------------------------------------

        self.map = None

        self.map_image_bytes = None

        # --------------------------------------------------------
        # VISUALIZAÇÕES
        # --------------------------------------------------------

        self.visualizations = []

        self.visualization_images = []

        # --------------------------------------------------------
        # PARÂMETROS
        # --------------------------------------------------------

        self.extract_link_parameters(
            text
        )

        # --------------------------------------------------------
        # CONEXÕES
        # --------------------------------------------------------

        await self.connect_ollama()

        await self.connect()

        await self.register()

        # --------------------------------------------------------
        # MENSAGENS INICIAIS
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # EXECUTA AGENTE
        # --------------------------------------------------------

        await self.agent_turn()

        # --------------------------------------------------------
        # GARANTIA:
        # se temos dois pontos, evaluate_link precisa
        # ter sido executado pela aplicação.
        # --------------------------------------------------------

        if (
            len(
                self.geocoded_points
            ) >= 2
            and not self.evaluate_executed
        ):

            result = (
                await self.ensure_evaluate_link()
            )

            if result is not None:

                self.append_technical_context(
                    result
                )

        # --------------------------------------------------------
        # MAPA
        # --------------------------------------------------------

        if len(
            self.geocoded_points
        ) >= 2:

            await self.mostrar_mapa_apos_geocodificacao()

        # --------------------------------------------------------
        # VISUALIZAÇÕES
        # --------------------------------------------------------

        if (
            self.evaluate_executed
            and not self.evaluate_error
        ):

            await self.gerar_visualizacoes()

        # --------------------------------------------------------
        # RESPOSTA FINAL
        # --------------------------------------------------------

        if self.evaluate_executed:

            answer = (
                await self.generate_final_response(
                    text,
                    self.last_evaluate_result,
                    technical_report=None,
                )
            )

            # ----------------------------------------------------
            # NOVO FLUXO:
            #
            # A resposta final do Qwen é agora o conteúdo
            # principal do relatório técnico e do PDF.
            #
            # O ReportGenerator continua responsável por:
            #   - PDF
            #   - mapa
            #   - visualizações
            #
            # mas não substitui a análise do Qwen por um
            # relatório puramente orientado aos dados.
            # ----------------------------------------------------

            if answer:

                self.build_report(
                    self.last_evaluate_result,
                    analysis_text=answer,
                )

        else:

            answer = self.last_agent_text

        return answer


    # ============================================================
    # ETAPA 2 — MULTI-HOP
    # ============================================================

    def detect_multi_hop_request(
            self,
            text,
        ):
            """
            Detecta se a solicitação do usuário aparenta descrever
            uma rota com três ou mais pontos.

            Esta função NÃO identifica as localidades.

            A identificação das localidades continua sendo responsabilidade
            do LLM através de geocode_place.

            O objetivo aqui é somente impedir que o fluxo da ETAPA 1
            execute A -> B antes de o agente terminar de obter os demais
            pontos da rota.
            """

            if not text:
                return False

            normalized = (
                str(text)
                .strip()
                .lower()
            )

            # ------------------------------------------------------------
            # Indicadores explícitos de multi-hop
            # ------------------------------------------------------------

            explicit_patterns = [
                r"\bmulti[\s-]?hop\b",
                r"\bmulti[\s-]?enlace\b",
                r"\bmulti[\s-]?link\b",
                r"\bpor\s+.+\s+passando\s+por\b",
                r"\bpassando\s+por\b",
                r"\batrav[eé]s\s+de\b",
                r"\bvia\b",
                r"\brota\b",
                r"\btrajeto\b",
                r"\bsequ[eê]ncia\s+de\s+enlaces\b",
                r"\bv[aá]rios\s+enlaces\b",
                r"\bv[aá]rios\s+saltos\b",
                r"\bsaltos\b",
                r"\bhops?\b",
            ]

            for pattern in explicit_patterns:

                if re.search(
                    pattern,
                    normalized,
                ):
                    return True

            # ------------------------------------------------------------
            # Notação explícita:
            #
            # A -> B -> C
            # A → B → C
            # ------------------------------------------------------------

            arrow_count = len(
                re.findall(
                    r"(?:->|→|⇒|⟶)",
                    normalized,
                )
            )

            if arrow_count >= 2:
                return True

            # ------------------------------------------------------------
            # Listas com três ou mais localidades
            # ------------------------------------------------------------

            multi_point_patterns = [

                r"\bentre\s+.+,\s*.+\s+e\s+.+",

                r"\bentre\s+.+,\s*.+,\s*.+",

                r"\bde\s+.+\s+até\s+.+\s+passando\s+por\s+.+",

                r"\banalise\s+.+,\s*.+\s+e\s+.+",

                r"\banalisar\s+.+,\s*.+\s+e\s+.+",

                r"\bavalie\s+.+,\s*.+\s+e\s+.+",

                r"\bavaliar\s+.+,\s*.+\s+e\s+.+",

                # Exemplos adicionais:
                #
                # "faça uma análise entre A, B e C"
                # "faca uma analise entre A, B e C"
                # "faça uma análise de A, B e C"
                # "analise os enlaces entre A, B e C"
                #

                r"\bfa[cç]a\s+(?:uma\s+)?an[aá]lise\b.+,\s*.+\s+e\s+.+",

                r"\ban[aá]lise\s+(?:dos\s+enlaces\s+)?entre\s+.+,\s*.+\s+e\s+.+",

                r"\banalis[ea]\s+.+\bentre\s+.+,\s*.+\s+e\s+.+",

                r"\bavalie\s+.+\bentre\s+.+,\s*.+\s+e\s+.+",
            ]

            for pattern in multi_point_patterns:

                if re.search(
                    pattern,
                    normalized,
                ):
                    return True

            # ------------------------------------------------------------
            # Indicador adicional:
            #
            # uma solicitação contendo duas vírgulas ou mais junto com
            # uma conjunção "e" normalmente representa uma sequência
            # de três elementos.
            #
            # Não usamos isso isoladamente: exigimos também um verbo/
            # contexto de análise ou de rota.
            # ------------------------------------------------------------

            comma_count = normalized.count(",")

            route_context = re.search(
                r"\b("
                r"analise|analisar|análise|analise|"
                r"avalie|avaliar|enlace|enlaces|"
                r"link|links|rota|trajeto|"
                r"pontos?|localidades?"
                r")\b",
                normalized,
            )

            if (
                comma_count >= 2
                and re.search(
                    r"\be\b",
                    normalized,
                )
                and route_context
            ):
                return True

            return False

    async def ensure_application_evaluation(
            self,
        ):
            """
            Decide qual orquestrador deve ser utilizado.

            2 pontos:
                ensure_evaluate_link()

            3+ pontos:
                ensure_multi_hop_evaluation()

            A função nunca transforma evaluate_link em super-tool.

            IMPORTANTE:
            Se 3 ou mais pontos já foram geocodificados, a aplicação
            promove automaticamente a solicitação para multi-hop.

            Isso funciona como uma proteção adicional caso a detecção
            textual inicial não tenha identificado corretamente a intenção.
            """

            point_count = len(
                self.geocoded_points
            )

            # ------------------------------------------------------------
            # PROTEÇÃO MULTI-HOP
            #
            # Se a aplicação já possui 3 ou mais pontos, não existe
            # justificativa para executar somente o primeiro enlace.
            #
            # A rota é formada pelos pontos consecutivos:
            #
            # A -> B
            # B -> C
            # C -> D
            #
            # etc.
            # ------------------------------------------------------------

            if (
                point_count >= 3
                and not self.multi_hop_requested
            ):

                self.multi_hop_requested = True

                self.log_detail(
                    "🔗 Três ou mais pontos geocodificados; "
                    "solicitação promovida automaticamente "
                    "para multi-hop."
                )

            # ------------------------------------------------------------
            # MULTI-HOP
            # ------------------------------------------------------------

            if self.multi_hop_requested:

                if point_count < 3:

                    self.log_detail(
                        "⏳ Solicitação multi-hop detectada. "
                        f"Aguardando pontos adicionais "
                        f"(atualmente {point_count})."
                    )

                    return None

                if getattr(
                    self,
                    "multi_hop_executed",
                    False,
                ):

                    return self.global_result

                return await (
                    self.ensure_multi_hop_evaluation(
                        route_points=self.geocoded_points,
                        parameters=self.link_parameters,
                    )
                )

            # ------------------------------------------------------------
            # ETAPA 1 — ENLACE ÚNICO
            # ------------------------------------------------------------

            if point_count >= 2:

                if self.evaluate_executed:

                    return self.last_evaluate_result

                return await (
                    self.ensure_evaluate_link()
                )

            return None

    def _get_current_hop_info(
            self,
        ):
            """
            Retorna informações do hop atualmente em processamento.
            """

            if not self.multi_hop_requested:

                return {
                    "key": "single",
                    "index": None,
                    "name": None,
                }

            current_hop = getattr(
                self,
                "current_hop",
                None,
            )

            if isinstance(
                current_hop,
                dict,
            ):

                index = current_hop.get(
                    "index"
                )

                hop_id = current_hop.get(
                    "id"
                )

                name = current_hop.get(
                    "name"
                )

                if index is not None:

                    key = (
                        f"hop_{index}"
                    )

                elif hop_id:

                    key = str(
                        hop_id
                    )

                else:

                    key = (
                        f"hop_{id(current_hop)}"
                    )

                return {
                    "key": key,
                    "index": index,
                    "name": name,
                }

            return None

    async def gerar_visualizacoes(
            self,
        ):

            if not self.multi_hop_requested:

                if not self.evaluate_executed:
                    return

                if self.evaluate_error:
                    return

                hop_info = {
                    "key": "single",
                    "index": None,
                    "name": None,
                }

            else:

                if self.multi_hop_error:
                    return

                hop_info = (
                    self._get_current_hop_info()
                )

                if hop_info is None:

                    self.log_detail(
                        "⚠️ Não foi possível identificar "
                        "o hop atual para gerar "
                        "as visualizações."
                    )

                    return

            hop_key = hop_info["key"]

            if hop_key in (
                self.visualizations_generated_hops
            ):

                self.log_detail(
                    "Visualizações já preparadas "
                    f"para {hop_key}; "
                    "nova geração ignorada."
                )

                return

            if self.multi_hop_requested:

                hop_index = (
                    hop_info.get("index")
                )

                hop_name = (
                    hop_info.get("name")
                )

                if hop_name:

                    if hop_index is not None:

                        hop_title = (
                            f"Hop {hop_index} — "
                            f"{hop_name}"
                        )

                    else:

                        hop_title = (
                            str(hop_name)
                        )

                else:

                    if hop_index is not None:

                        hop_title = (
                            f"Hop {hop_index}"
                        )

                    else:

                        hop_title = "Hop"

            else:

                hop_title = None

            tools = [
                (
                    "link_area",
                    {"ds_string": "DTM"},
                    "DTM",
                ),
                (
                    "link_area",
                    {"ds_string": "DSM"},
                    "DSM",
                ),
                (
                    "link_area",
                    {"ds_string": "COVER"},
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

            generated_count = 0

            for (
                tool_name,
                arguments,
                image_type,
            ) in tools:

                try:

                    raw = (
                        await self.execute_mcp_tool_raw(
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

                        self.log_detail(
                            f"⚠️ {image_type}: "
                            "resultado não é um objeto."
                        )

                        continue

                    if parsed.get(
                        "kind"
                    ) != "image":

                        self.log_detail(
                            f"⚠️ {image_type}: "
                            "resultado não contém imagem."
                        )

                        continue

                    data = parsed.get(
                        "data"
                    )

                    if not data:

                        self.log_detail(
                            f"⚠️ {image_type}: "
                            "imagem sem dados."
                        )

                        continue

                    image_bytes = (
                        base64.b64decode(
                            data
                        )
                    )

                    image = widgets.Image(
                        value=image_bytes,
                        format="png",
                        layout=widgets.Layout(
                            width="100%",
                            height="auto",
                        ),
                    )

                    if hop_title:

                        title = (
                            f"{hop_title} — "
                            f"{image_type}"
                        )

                    else:

                        title = image_type

                    self.visualizations.append(
                        image
                    )

                    self.visualization_images.append(
                        {
                            "title": title,
                            "data": image_bytes,
                            "mime_type": "image/png",
                        }
                    )

                    generated_count += 1

                    if self.visualization_callback:

                        self.visualization_callback(
                            image,
                            title,
                        )

                    self.log_detail(
                        f"Visualização preparada: "
                        f"{title}"
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Visualização "
                        f"{image_type}: {exc}"
                    )

            self.visualizations_generated_hops.add(
                hop_key
            )

            self.log_detail(
                "Visualizações do "
                f"{hop_title or 'enlace único'} "
                f"preparadas: {generated_count}"
            )

            self.log_detail(
                "Total acumulado de visualizações: "
                f"{len(self.visualization_images)}"
            )

    def build_report(
            self,
            technical_result,
            analysis_text=None,
        ):

            requested_parameters = {
                "frequency": getattr(
                    self,
                    "requested_frequency",
                    None,
                ),
                "frequency_unit": getattr(
                    self,
                    "requested_frequency_unit",
                    None,
                ),
                "frequency_text": getattr(
                    self,
                    "requested_frequency_text",
                    None,
                ),
                "tx_ha": getattr(
                    self,
                    "requested_tx_ha",
                    None,
                ),
                "rx_ha": getattr(
                    self,
                    "requested_rx_ha",
                    None,
                ),
            }

            link_parameters = getattr(
                self,
                "link_parameters",
                {},
            )

            if not isinstance(
                link_parameters,
                dict,
            ):

                link_parameters = {}

            effective_parameters = {
                "freq_mhz": link_parameters.get(
                    "freq_mhz",
                    DEFAULT_FREQ_MHZ,
                ),
                "tx_ha": link_parameters.get(
                    "tx_ha",
                    DEFAULT_TX_HA,
                ),
                "rx_ha": link_parameters.get(
                    "rx_ha",
                    DEFAULT_RX_HA,
                ),
                "on_rooftop": link_parameters.get(
                    "on_rooftop",
                    DEFAULT_ON_ROOFTOP,
                ),
            }

            if (
                self.map_image_bytes is None
                and len(
                    self.geocoded_points
                ) >= 2
            ):

                try:

                    if (
                        self.multi_hop_requested
                        and getattr(
                            self,
                            "hops",
                            None,
                        )
                    ):

                        from map_utils import (
                            gerar_imagem_mapa_multihop,
                        )

                        self.map_image_bytes = (
                            gerar_imagem_mapa_multihop(
                                self.hops
                            )
                        )

                    else:

                        from map_utils import (
                            gerar_imagem_mapa_enlace,
                        )

                        p1 = (
                            self.geocoded_points[0]
                        )

                        p2 = (
                            self.geocoded_points[1]
                        )

                        self.map_image_bytes = (
                            gerar_imagem_mapa_enlace(
                                p1["lat"],
                                p1["lon"],
                                p2["lat"],
                                p2["lon"],
                            )
                        )

                except Exception as exc:

                    self.log_detail(
                        "⚠️ Não foi possível "
                        "gerar imagem do mapa "
                        "para o relatório: "
                        f"{exc}"
                    )

            if analysis_text is None:
                analysis_text = self.technical_report or None

            generator = ReportGenerator(
                requested_params=requested_parameters,
                effective_params=effective_parameters,
                technical_result=technical_result,
                geocoded_points=self.geocoded_points,
                map_image=self.map_image_bytes,
                visualization_images=self.visualization_images,
                user_request=self.user_request,
                analysis_text=analysis_text,
            )

            report = generator.generate_report(
                include_raw_result=False
            )

            self.technical_report = report

            pdf_path = generator.generate_pdf(
                report_text=report,
                include_raw_result=False,
            )

            self.report_pdf_path = pdf_path

            self.log_detail(
                "Relatório PDF gerado: "
                f"{pdf_path}"
            )

            self.log_detail(
                "Mapa no relatório: "
                + (
                    "SIM"
                    if self.map_image_bytes
                    else "NÃO"
                )
            )

            self.log_detail(
                "Visualizações no relatório: "
                f"{len(self.visualization_images)}"
            )

            return report

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico especializado em planejamento e avaliação de enlaces de rádio.

O PlanApp é a fonte oficial dos resultados técnicos.

REGRAS:
1. Nunca invente valores, unidades ou resultados.
2. Nunca altere resultados retornados pelo PlanApp.
3. Não recalcule valores técnicos quando o PlanApp já os forneceu.
4. Use geocode_place para todas as localidades informadas pelo usuário.
5. Em uma rota com 3 ou mais localidades, geocodifique TODAS na ordem informada antes da avaliação.
6. Preserve rigorosamente a ordem dos pontos.
7. A -> B -> C representa Hop 1 A -> B e Hop 2 B -> C.
8. Não pare a geocodificação depois dos dois primeiros pontos em uma rota multi-hop.
9. NÃO execute evaluate_link diretamente. A aplicação controla a avaliação.
10. Em multi-hop, evaluate_link continua representando somente UM enlace.
11. Mapa e visualizações são controlados pela aplicação.
12. Preserve frequência, TX, RX e rooftop solicitados.
13. Padrões: 900 MHz, TX 7 m, RX 7 m, rooftop=false.
14. FSPL significa perda de percurso em espaço livre; não significa interferência.
15. Não invente potência TX, ganho, sensibilidade, margem ou limiares.
16. Não atribua significado físico próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.
17. Não converta radianos para graus.
18. status=OK significa sucesso de execução, não viabilidade.
19. Não declare enlace ou rota viável/inviável sem critério técnico explícito.
20. Em multi-hop, apresente os resultados de cada hop separadamente e compare os hops.
21. Pode comparar maior/menor e diferenças entre valores efetivamente retornados.
22. Destaque valores negativos, especialmente clearances negativas, sem inventar sua causa.
23. Identifique pontos de atenção sustentados pelos próprios dados.
24. Diferencie parâmetros solicitados, parâmetros efetivos, resultados, interpretação e limitações.
25. Sugestões não testadas devem ser apresentadas como sugestões.
26. Responda em português do Brasil.
27. Seja técnico, claro, objetivo e informativo.
"""


    async def agent_turn(self):

        for iteration in range(MAX_AGENT_ITERATIONS):

            self.log_detail(
                f"Iteração do agente: {iteration + 1}/{MAX_AGENT_ITERATIONS}"
            )

            response = await self.ollama_chat()
            message = self.response_message(response)
            text = self.response_text(response)
            tool_calls = self.response_tool_calls(response)

            if text:
                self.last_agent_text = text

            if message:
                self.messages.append(message)

            # ------------------------------------------------------------
            # SEM TOOL CALLS
            # ------------------------------------------------------------
            if not tool_calls:

                result = await self.ensure_application_evaluation()

                if result is not None:
                    self.append_technical_context(result)

                    # ----------------------------------------------------
                    # MULTI-HOP CONCLUÍDO
                    #
                    # A avaliação dos hops já foi executada pela aplicação.
                    # NÃO voltar ao Qwen neste ponto: isso fazia o agente
                    # continuar em novas iterações e impedia que ask()
                    # chegasse à preparação do mapa multi-hop e à análise
                    # final.
                    # ----------------------------------------------------
                    if (
                        self.multi_hop_requested
                        and getattr(
                            self,
                            "multi_hop_executed",
                            False,
                        )
                    ):
                        self.log_detail(
                            "🟢 Multi-hop concluído após a geocodificação."
                        )
                        self.log_detail(
                            "Encerrando agent_turn()."
                        )
                        return text

                    continue

                if (
                    self.multi_hop_requested
                    and len(self.geocoded_points) < 3
                    and not self.geocoding_followup_sent
                ):
                    self.geocoding_followup_sent = True
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "A solicitação atual descreve uma rota multi-hop. "
                            "Ainda existem menos de três pontos geocodificados. "
                            "Continue identificando e geocodificando, na ordem "
                            "solicitada pelo usuário, todas as localidades restantes. "
                            "Não execute avaliação técnica."
                        ),
                    })
                    continue

                return text

            # ------------------------------------------------------------
            # EXECUÇÃO DAS TOOLS
            # ------------------------------------------------------------
            tool_messages=[]

            for call in tool_calls:
                function=call.get("function",{})
                if not isinstance(function,dict):
                    continue

                name=function.get("name")
                if not name:
                    continue

                arguments=function.get("arguments",{})
                if isinstance(arguments,str):
                    try:
                        arguments=json.loads(arguments or "{}")
                    except Exception as exc:
                        self.log_detail(f"⚠️ Argumentos inválidos para {name}: {exc}")
                        arguments={}

                if not isinstance(arguments,dict):
                    arguments={}

                if name in APPLICATION_CONTROLLED_TOOLS:
                    self.log_detail(
                        f"⚠️ Ferramenta {name} é controlada pela aplicação."
                    )
                    continue

                self.log_detail(f"Executando ferramenta MCP: {name}")

                try:
                    result=await self.execute_mcp_tool(name,arguments)
                    tool_messages.append({
                        "role":"tool",
                        "content":json.dumps(result,ensure_ascii=False,default=str),
                    })
                except Exception as exc:
                    self.log_detail(f"⚠️ Erro na ferramenta {name}: {exc}")
                    tool_messages.append({
                        "role":"tool",
                        "content":json.dumps({"error":str(exc)},ensure_ascii=False),
                    })

            if tool_messages:
                self.messages.extend(tool_messages)
                # Não avaliar aqui: o Qwen precisa ter a oportunidade de
                # geocodificar todos os pontos da rota.
                continue

            result=await self.ensure_application_evaluation()
            if result is not None:
                self.append_technical_context(result)

                if (
                    self.multi_hop_requested
                    and getattr(
                        self,
                        "multi_hop_executed",
                        False,
                    )
                ):
                    self.log_detail(
                        "🟢 Multi-hop concluído após a execução das ferramentas."
                    )
                    self.log_detail(
                        "Encerrando agent_turn()."
                    )
                    return text

                continue

            if (
                self.multi_hop_requested
                and len(self.geocoded_points)<3
                and not self.geocoding_followup_sent
            ):
                self.geocoding_followup_sent=True
                self.messages.append({
                    "role":"user",
                    "content":(
                        "Continue a geocodificação da rota multi-hop solicitada. "
                        "Use geocode_place para os pontos restantes na ordem original. "
                        "Não execute avaliação técnica."
                    ),
                })
                continue

            return text

        return (
            "Não foi possível concluir o processamento dentro do "
            "limite de iterações."
        )


    def _compact_analysis_context(self, technical_result):
        """Remove somente conteúdo pesado que não é necessário ao Qwen.

        O resultado técnico continua sendo o resultado real do PlanApp.
        A compactação evita enviar imagens/base64/geometrias gigantescas
        para a análise textual final.
        """

        def compact(value, key="", depth=0):

            key_lower = str(key).lower()

            # Conteúdo visual não deve ser enviado ao modelo textual.
            if key_lower in {
                "data",
                "image",
                "image_data",
                "image_bytes",
                "base64",
                "png",
                "jpeg",
                "jpg",
            }:
                return "[conteúdo visual omitido da análise textual]"

            if isinstance(value, dict):
                result = {}
                for k, v in value.items():
                    result[k] = compact(v, k, depth + 1)
                return result

            if isinstance(value, list):
                # Não cortar listas pequenas. Para listas enormes de
                # coordenadas/geometrias, preservar apenas uma amostra.
                if len(value) > 200:
                    return {
                        "_total_itens": len(value),
                        "_amostra_inicial": [
                            compact(v, key, depth + 1)
                            for v in value[:20]
                        ],
                        "_amostra_final": [
                            compact(v, key, depth + 1)
                            for v in value[-5:]
                        ],
                        "_observacao": "lista extensa compactada para análise textual",
                    }
                return [compact(v, key, depth + 1) for v in value]

            if isinstance(value, str) and len(value) > 20000:
                return (
                    value[:20000]
                    + "\n[texto extenso truncado para análise final]"
                )

            return value

        return compact(technical_result)

    async def generate_final_response(
        self,
        original_text,
        technical_result,
        technical_report=None,
    ):
        """Gera somente a interpretação final dos resultados já calculados.

        Esta chamada é deliberadamente independente do histórico do agente:
        não reutiliza self.messages e não envia ferramentas MCP ao Qwen.
        """

        context = self._compact_analysis_context(
            self.build_technical_context(technical_result)
        )

        context_json = json.dumps(
            context,
            ensure_ascii=False,
            default=str,
        )

        self.log_detail(
            "Contexto compacto preparado para a análise final: "
            f"{len(context_json)} caracteres."
        )

        final_instruction = """
Produza agora a análise técnica final do PlanApp, em português do Brasil.

IMPORTANTE: a avaliação técnica já foi executada pela aplicação. Você NÃO
precisa e NÃO deve executar ferramentas. Apenas interprete os resultados
fornecidos abaixo.

Use somente valores efetivamente retornados pelo PlanApp.
Não invente potência, ganho, sensibilidade, margem, limiar ou critério de
viabilidade.
Não atribua significado físico a campos cuja definição não esteja
explicitamente documentada.
Não trate status OK como indicação de viabilidade.

Para uma rota multi-hop:

## 1. IDENTIFICAÇÃO DA ROTA
Liste os pontos na ordem e os hops consecutivos.

## 2. PARÂMETROS UTILIZADOS
Diferencie, quando disponível, parâmetros solicitados e efetivamente usados.

## 3. ANÁLISE POR HOP
Para cada hop, destaque distância, FSPL, delta_diffra e outros resultados
relevantes efetivamente retornados.

## 4. COMPARAÇÃO ENTRE OS HOPS
Compare objetivamente os valores disponíveis. Destaque maior/menor valor e
combinações de indicadores que ocorram no mesmo hop. Não crie métricas novas.

## 5. TERRENO, VEGETAÇÃO, FRESNEL E EDIFICAÇÕES
Apresente os resultados disponíveis dessas etapas. Não invente semântica para
campos não documentados.

## 6. PRINCIPAIS PONTOS DE ATENÇÃO
Identifique quais resultados/hops merecem atenção e justifique com os dados.
Valores negativos ou muito diferentes entre hops podem ser destacados como
pontos de atenção, sem transformá-los automaticamente em inviabilidade.

## 7. CONCLUSÃO TÉCNICA
Explique o que os dados permitem afirmar sobre a rota e quais limitações
permanecem. Se não houver critério técnico explícito para viabilidade,
declare essa limitação claramente.

Se houver apenas um enlace, adapte a estrutura para um único enlace.

Seja técnico, objetivo e claro. Não reproduza o JSON integralmente.
"""

        final_messages = [
            {
                "role": "system",
                "content": self.system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "SOLICITAÇÃO ORIGINAL DO USUÁRIO:\n"
                    + str(original_text)
                ),
            },
            {
                "role": "user",
                "content": (
                    "RESULTADOS TÉCNICOS DO PLANAPP:\n"
                    + context_json
                ),
            },
            {
                "role": "user",
                "content": final_instruction,
            },
        ]

        old_messages = self.messages

        try:
            self.messages = final_messages

            response = await self.ollama_chat(
                use_tools=False,
                options={
                    "temperature": 0.2,
                    "num_predict": OLLAMA_FINAL_NUM_PREDICT,
                },
            )

            answer = self.response_text(response)

            if answer:
                self.last_agent_text = answer
                self.log_detail(
                    "🧠 Análise final do Qwen concluída."
                )
            else:
                self.log_detail(
                    "⚠️ Análise final do Qwen retornou texto vazio."
                )

            return answer

        finally:
            self.messages = old_messages


    async def ask(self,text):

        self.reset_common_state()
        self.registered=False
        self.technical_context_added=False
        self.last_agent_text=""
        self.technical_report=""
        self.report_pdf_path=None
        self.user_request=text

        self.multi_hop_requested=self.detect_multi_hop_request(text)
        self.geocoding_followup_sent=False

        self.log_detail(
            "🔗 Solicitação multi-hop detectada."
            if self.multi_hop_requested
            else "🔗 Solicitação de enlace único."
        )

        self.map=None
        self.map_image_bytes=None
        self.visualizations=[]
        self.visualization_images=[]
        self.visualizations_generated_hops=set()

        self.extract_link_parameters(text)

        await self.connect_ollama()
        await self.connect()
        await self.register()

        self.messages=[
            {"role":"system","content":self.system_prompt()},
            {"role":"user","content":text},
        ]

        await self.agent_turn()

        result=await self.ensure_application_evaluation()

        if result is not None:
            if not self.technical_context_added:
                self.append_technical_context(result)

            final_result=(
                getattr(self,"global_result",result)
                if self.multi_hop_requested
                else self.last_evaluate_result
            )
        else:
            final_result=None

        if self.multi_hop_requested:
            if (
                getattr(self,"multi_hop_executed",False)
                and getattr(self,"hops",None)
            ):
                try:
                    from map_utils import mostrar_mapa_multihop, gerar_imagem_mapa_multihop
                    self.map=mostrar_mapa_multihop(self.hops)
                    if self.map_callback:
                        self.map_callback(self.map)
                    self.map_image_bytes=gerar_imagem_mapa_multihop(self.hops)
                    self.log_detail(
                        "Mapa multi-hop preparado "
                        f"com {len(self.hops)} hops."
                    )
                except Exception as exc:
                    self.log_detail(f"⚠️ Erro no mapa multi-hop: {exc}")
        elif len(self.geocoded_points)>=2:
            await self.mostrar_mapa_apos_geocodificacao()

        if final_result is not None:
            answer=await self.generate_final_response(
                text,
                final_result,
                technical_report=None,
            )
            self.technical_report=answer
            self.build_report(final_result,analysis_text=answer)
        else:
            answer=self.last_agent_text

        return answer


    # ============================================================
    # CLOSE
    # ============================================================

    async def close(
        self,
    ):

        await super().close()