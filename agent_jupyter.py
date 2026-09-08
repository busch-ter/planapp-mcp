import asyncio
import json
import os
import re
from contextlib import AsyncExitStack

import requests

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp",
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b",
)

USER_ID = "jupyter-user"


DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
    ):
        self.progress_callback = progress_callback
        self.map_callback = map_callback
        self.log_callback = log_callback

        self.exit_stack = AsyncExitStack()

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

        self.link_parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # ----------------------------------------------------
        # Parâmetros exatamente como solicitados pelo usuário
        # ----------------------------------------------------

        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

    # ========================================================
    # LOGS
    # ========================================================

    def log(self, message):
        """
        Mensagens de andamento/status.
        """
        if self.progress_callback:
            try:
                self.progress_callback(message)
            except Exception:
                pass

    def log_detail(self, message):
        """
        Logs detalhados, principalmente resultados brutos
        das ferramentas MCP.
        """
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, um assistente especializado em planejamento
e avaliação técnica de enlaces de rádio.

REGRAS FUNDAMENTAIS:

1. O PlanApp é a fonte de verdade para resultados técnicos.

2. Nunca invente valores técnicos.

3. Nunca recalcule valores fornecidos pelo PlanApp usando fórmulas
   próprias, salvo quando explicitamente solicitado e quando isso
   não substituir o resultado do PlanApp.

4. Quando o usuário informar dois locais, geocodifique ambos usando
   a ferramenta geocode_place.

5. Depois que os dois pontos forem geocodificados, a avaliação técnica
   do enlace deve ser executada automaticamente pelo sistema.

6. Nunca peça ao usuário para executar manualmente a avaliação.

7. Nunca diga que precisa esperar uma próxima etapa para executar
   a avaliação.

8. Não solicite ao usuário uma chamada direta de evaluate_link.

9. Não faça chamadas diretas de evaluate_link através do modelo.
   A aplicação executará evaluate_link automaticamente.

10. Preserve exatamente os valores fornecidos pelo PlanApp.

11. Preserve as unidades fornecidas pelo PlanApp.

12. FSPL significa Free-Space Path Loss.

13. Não faça julgamentos sobre qualidade de clearance sem que exista
    um critério explícito fornecido pelo PlanApp ou pelo usuário.

14. Não conclua que um enlace é viável ou inviável apenas com base
    em distância, FSPL, difração ou clearance.

15. Uma conclusão de viabilidade exige os parâmetros e critérios
    técnicos necessários.

16. Não atribua significado físico a campos que não estejam definidos
    explicitamente pelo PlanApp.

17. Os campos:
    core
    fresnel
    boundary
    delta_diffra
    VV
    d_norm

    devem permanecer com seus nomes originais.

18. Não interprete esses campos usando conhecimento genérico de
    engenharia quando o significado não tiver sido explicitamente
    definido pelo PlanApp.

19. Não compare distância com core, fresnel ou boundary.

20. Não interprete d_norm como posição normalizada, percentual ou
    qualquer outro significado sem definição explícita.

21. Não interprete VV como altura de obstáculo, pico de terreno ou
    qualquer outra grandeza física sem definição explícita.

22. Não interprete delta_diffra como zona de difração ou perda de
    difração sem definição explícita.

23. Não conclua que um ponto está dentro ou fora da zona de Fresnel
    apenas com base em campos não definidos.

24. Não afirme que terreno, vegetação ou edificações afetam o sinal
    apenas porque existem valores numéricos nesses campos.

25. Diferencie claramente:
    - valores fornecidos pelo usuário;
    - valores usados pelo PlanApp;
    - resultados fornecidos pelo PlanApp;
    - conclusões tecnicamente suportadas;
    - conclusões que não podem ser obtidas com os dados disponíveis.

REGRAS DE PARÂMETROS:

26. Parâmetros explicitamente fornecidos pelo usuário têm prioridade
    absoluta sobre os valores padrão.

27. Valores padrão só podem ser usados quando o usuário não informar
    aquele parâmetro.

28. Frequência padrão:
    900 MHz.

29. Altura padrão da antena TX:
    7 m.

30. Altura padrão da antena RX:
    7 m.

31. on_rooftop padrão:
    false.

32. Preserve a unidade original informada pelo usuário.

33. A conversão interna da frequência para MHz deve ser feita somente
    para o parâmetro freq_mhz enviado ao PlanApp.

34. Exemplo:
    "450 MHz" significa 450 MHz.

35. Exemplo:
    "450 Hz" pode ser convertido internamente para
    0.00045 MHz.

36. Exemplo:
    "450 kHz" pode ser convertido internamente para
    0.45 MHz.

37. Exemplo:
    "450 GHz" pode ser convertido internamente para
    450000 MHz.

38. Entretanto, a solicitação original deve continuar sendo apresentada
    como foi informada pelo usuário.

39. Nunca escreva uma unidade que não foi informada pelo usuário.

40. Não escreva:
    "450 MHz (Hz)"
    se o usuário informou apenas "450 Hz".

41. Quando o usuário disser algo como:
    "duas antenas de 10 metros"
    interprete como:
    TX = 10 m
    RX = 10 m.

42. Quando o usuário informar alturas diferentes, preserve
    individualmente TX e RX.

43. Se houver divergência entre o parâmetro solicitado pelo usuário
    e o parâmetro efetivamente utilizado pelo PlanApp, informe
    explicitamente a divergência.

COMPORTAMENTO DA RESPOSTA:

44. A resposta final deve ser clara e objetiva.

45. Não apresente JSON bruto como resposta final quando houver
    informação técnica que possa ser apresentada de forma legível.

46. Use os resultados reais fornecidos pelo PlanApp.

47. Não invente informações ausentes.

48. Não transforme campos técnicos desconhecidos em conceitos conhecidos
    apenas pelo nome.

49. Se um campo não possui definição suficiente, informe que seu
    significado não foi definido nos dados retornados.

50. Quando apropriado, apresente:
    - origem/destino;
    - coordenadas;
    - distância;
    - frequência;
    - alturas das antenas;
    - FSPL;
    - demais resultados técnicos relevantes.

51. Não esconda divergências entre os parâmetros solicitados e utilizados.

52. Não apresente conclusões que não possam ser sustentadas pelos
    resultados retornados pelo PlanApp.

53. A análise deve distinguir claramente dados e interpretação.

54. O mapa é preparado automaticamente depois que os dois pontos
    são geocodificados.

55. A avaliação técnica é executada automaticamente depois da
    geocodificação.

56. Não diga ao usuário para aguardar uma execução futura.

57. Não interrompa o fluxo depois da geocodificação.

58. Depois da avaliação técnica, interprete os resultados retornados.

59. Quando houver FSPL, apresente-o como:
    "FSPL (Free-Space Path Loss)".

60. Não invente unidade para campos que não tenham unidade explícita.

61. Não faça comparações de valores técnicos sem contexto.

62. Não faça afirmações sobre desempenho do enlace sem parâmetros
    suficientes.

63. Não considere apenas FSPL para determinar viabilidade.

64. Não considere apenas distância para determinar viabilidade.

65. Não considere apenas clearance para determinar viabilidade.

66. Não considere apenas difração para determinar viabilidade.

67. Não transforme uma análise parcial em uma conclusão definitiva.

68. Caso o usuário solicite apenas uma informação específica,
    responda diretamente com aquela informação.

69. Caso o usuário solicite uma análise completa, apresente os
    principais resultados disponíveis.

70. Sempre utilize os nomes originais dos campos retornados.

71. Não altere valores numéricos.

72. Não arredonde valores internamente.

73. Arredondamentos apresentados ao usuário devem ser apenas
    formatação visual.

74. Se o PlanApp fornecer valores com casas decimais, preserve a
    precisão disponível quando relevante.

75. Nunca substitua um resultado do PlanApp por uma estimativa própria.

76. Nunca diga que uma ferramenta foi executada se ela não foi realmente
    executada.

77. Nunca invente sucesso de uma ferramenta.

78. Nunca invente erro de uma ferramenta.

79. Se uma ferramenta retornar erro, informe o erro real.

80. Se uma ferramenta retornar sucesso, utilize o resultado real.

81. Se houver dados insuficientes para uma conclusão, diga explicitamente
    que os dados disponíveis não são suficientes.

82. O objetivo é produzir uma análise técnica fiel aos dados do PlanApp.

83. Não extrapole além dos resultados.

84. A resposta final deve priorizar precisão técnica sobre interpretações
    genéricas.
"""

    # ========================================================
    # EXTRAÇÃO DOS PARÂMETROS
    # ========================================================

    def extract_link_parameters(self, text):

        parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # Reset dos parâmetros solicitados
        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None
        self.requested_tx_ha = None
        self.requested_rx_ha = None

        # ----------------------------------------------------
        # Frequência
        # ----------------------------------------------------

        freq_pattern = re.compile(
            r"(\d+(?:[.,]\d+)?)\s*"
            r"(ghz|mhz|khz|hz)\b",
            re.IGNORECASE,
        )

        freq_match = freq_pattern.search(text)

        if freq_match:

            value_text = freq_match.group(1)
            unit = freq_match.group(2).lower()

            value = float(value_text.replace(",", "."))

            self.requested_frequency = value
            self.requested_frequency_unit = unit
            self.requested_frequency_text = freq_match.group(0)

            if unit == "ghz":
                parameters["freq_mhz"] = value * 1000.0

            elif unit == "mhz":
                parameters["freq_mhz"] = value

            elif unit == "khz":
                parameters["freq_mhz"] = value / 1000.0

            elif unit == "hz":
                parameters["freq_mhz"] = value / 1_000_000.0

        # ----------------------------------------------------
        # Duas antenas com mesma altura
        # ----------------------------------------------------

        same_height_patterns = [
            r"duas\s+antenas?\s+de\s+(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
            r"antenas?\s+de\s+(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
        ]

        same_height_match = None

        for pattern in same_height_patterns:
            same_height_match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if same_height_match:
                break

        if same_height_match:

            height = float(
                same_height_match.group(1).replace(",", ".")
            )

            parameters["tx_ha"] = height
            parameters["rx_ha"] = height

            self.requested_tx_ha = height
            self.requested_rx_ha = height

        else:

            # ------------------------------------------------
            # TX / RX separados
            # ------------------------------------------------

            tx_match = re.search(
                r"(?:tx|transmissora?|transmissor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            rx_match = re.search(
                r"(?:rx|receptora?|receptor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            if tx_match:
                height = float(
                    tx_match.group(1).replace(",", ".")
                )

                parameters["tx_ha"] = height
                self.requested_tx_ha = height

            if rx_match:
                height = float(
                    rx_match.group(1).replace(",", ".")
                )

                parameters["rx_ha"] = height
                self.requested_rx_ha = height

        # ----------------------------------------------------
        # Rooftop
        # ----------------------------------------------------

        rooftop_patterns = [
            r"\bno\s+telhado\b",
            r"\bem\s+cima\s+do\s+telhado\b",
            r"\bsobre\s+o\s+telhado\b",
            r"\brooftop\b",
        ]

        for pattern in rooftop_patterns:

            if re.search(pattern, text, re.IGNORECASE):
                parameters["on_rooftop"] = True
                break

        self.link_parameters = parameters

        return parameters

    # ========================================================
    # CONEXÃO MCP
    # ========================================================

    async def connect(self):

        self.log("🔌 Conectando ao PlanApp MCP...")

        transport = await self.exit_stack.enter_async_context(
            streamable_http_client(MCP_URL)
        )

        read_stream, write_stream = transport

        self.mcp_session = await self.exit_stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
            )
        )

        await self.mcp_session.initialize()

        tools_result = await self.mcp_session.list_tools()

        self.mcp_tools = tools_result.tools

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

            if tool.name in {
                "register",
                "evaluate_link",
            }:
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

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": (
                            getattr(
                                tool,
                                "description",
                                None,
                            )
                            or ""
                        ),
                        "parameters": schema or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            )

        return tools

    # ========================================================
    # OLLAMA
    # ========================================================

    async def ollama_chat(self):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
        }

        def do_request():

            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=300,
            )

            response.raise_for_status()

            return response.json()

        return await asyncio.to_thread(do_request)

    # ========================================================
    # PARSE RESULTADO MCP
    # ========================================================

    def parse_mcp_result(self, result):

        structured = getattr(
            result,
            "structuredContent",
            None,
        )

        if structured is None:
            structured = getattr(
                result,
                "structured_content",
                None,
            )

        if structured is not None:
            return structured

        content = getattr(
            result,
            "content",
            None,
        )

        if content:

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None,
                )

                if text:

                    try:
                        return json.loads(text)

                    except Exception:
                        return text

        return result

    # ========================================================
    # RESUMO GEOCODE
    # ========================================================

    def summarize_geocode(self, parsed):

        if not isinstance(parsed, dict):
            return None

        results = parsed.get("results")

        if not results:
            return None

        first = results[0]

        if not isinstance(first, dict):
            return None

        name = first.get("name")

        lat = first.get("lat")
        lon = first.get("lon")

        if lat is None or lon is None:
            return None

        return {
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
        }

    # ========================================================
    # RESUMO EVALUATE
    # ========================================================

    def summarize_evaluate(self, parsed):

        if not isinstance(parsed, dict):
            return None

        if "fspl" in parsed:
            return parsed["fspl"]

        technical = parsed.get("technical")

        if isinstance(technical, dict):

            if "fspl" in technical:
                return technical["fspl"]

        data = parsed.get("data")

        if isinstance(data, dict):

            if "fspl" in data:
                return data["fspl"]

        return None

    # ========================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(self, parsed):

        point = self.summarize_geocode(parsed)

        if point is None:
            return

        self.geocoded_points.append(point)

        self.log(
            "📍 "
            f"{point['name']} — "
            f"{point['lat']:.6f}, "
            f"{point['lon']:.6f}"
        )

    # ========================================================
    # PREPARAÇÃO DO MAPA
    # ========================================================

    async def mostrar_mapa_apos_geocodificacao(self):

        if len(self.geocoded_points) < 2:
            return

        self.log("🗺️ Preparando enlace no mapa...")

        try:

            self.map = mostrar_mapa_enlace(self)

            if self.map_callback:

                try:
                    self.map_callback(self.map)

                except Exception as exc:

                    self.log(
                        f"⚠️ Erro ao atualizar mapa: {exc}"
                    )

            self.log("🟢 Mapa preparado.")

        except Exception as exc:

            self.log(
                f"❌ Erro ao preparar mapa: {exc}"
            )

    # ========================================================
    # EXECUÇÃO DE FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments,
    ):

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

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        self.log(
            f"🔧 MCP: {tool_name}"
        )

        self.log(
            "   Argumentos: "
            + json.dumps(
                arguments or {},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        # ----------------------------------------------------
        # EXECUTA MCP
        # ----------------------------------------------------

        result = await self.mcp_session.call_tool(
            tool_name,
            arguments or {},
        )

        parsed = self.parse_mcp_result(result)

        # ----------------------------------------------------
        # RESULTADO BRUTO VAI PARA LOG DETALHADO
        # ----------------------------------------------------

        self.log_detail(
            "   Resultado: "
            + json.dumps(
                parsed,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        # ----------------------------------------------------
        # GEOCODE
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            self.register_geocoded_point(parsed)

            if len(self.geocoded_points) == 2:

                await self.mostrar_mapa_apos_geocodificacao()

        # ----------------------------------------------------
        # EVALUATE
        # ----------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = parsed

            fspl = self.summarize_evaluate(parsed)

            if fspl is not None:

                self.log(
                    f"📥 FSPL: {float(fspl):.2f} dB"
                )

        return parsed

    # ========================================================
    # REGISTER
    # ========================================================

    async def register(self):

        self.log(
            "👤 Registrando usuário no PlanApp..."
        )

        await self.execute_mcp_tool(
            "register",
            {
                "user_id": USER_ID,
            },
        )

        self.log(
            "🟢 Usuário registrado."
        )

    # ========================================================
    # EVALUATE AUTOMÁTICO
    # ========================================================

    async def ensure_evaluate_link(
        self,
        parameters=None,
    ):

        if self.evaluate_executed:
            return self.last_evaluate_result

        if len(self.geocoded_points) < 2:
            return None

        if parameters is None:
            parameters = self.link_parameters

        tx = self.geocoded_points[0]
        rx = self.geocoded_points[1]

        arguments = {
            "tx_lat": tx["lat"],
            "tx_lon": tx["lon"],
            "rx_lat": rx["lat"],
            "rx_lon": rx["lon"],
            "tx_ha": parameters.get(
                "tx_ha",
                DEFAULT_TX_HA,
            ),
            "rx_ha": parameters.get(
                "rx_ha",
                DEFAULT_RX_HA,
            ),
            "freq_mhz": parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ,
            ),
            "on_rooftop": parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP,
            ),
        }

        self.log(
            "📡 Executando avaliação técnica do enlace..."
        )

        self.log(
            "📤 Parâmetros enviados ao PlanApp: "
            + json.dumps(
                arguments,
                ensure_ascii=False,
                indent=2,
            )
        )

        return await self.execute_mcp_tool(
            "evaluate_link",
            arguments,
        )

    # ========================================================
    # CONTEXTO TÉCNICO PARA O QWEN
    # ========================================================

    def append_technical_context(
        self,
        technical_result,
    ):

        effective = {
            "freq_mhz": self.link_parameters.get(
                "freq_mhz"
            ),
            "tx_ha": self.link_parameters.get(
                "tx_ha"
            ),
            "rx_ha": self.link_parameters.get(
                "rx_ha"
            ),
            "on_rooftop": self.link_parameters.get(
                "on_rooftop"
            ),
        }

        requested = {
            "frequency": self.requested_frequency,
            "frequency_unit": self.requested_frequency_unit,
            "frequency_text": self.requested_frequency_text,
            "tx_ha": self.requested_tx_ha,
            "rx_ha": self.requested_rx_ha,
        }

        conversion_text = ""

        if (
            self.requested_frequency is not None
            and self.requested_frequency_unit is not None
        ):

            conversion_text = (
                f"A frequência foi solicitada pelo usuário como "
                f"{self.requested_frequency_text}. "
                f"Apenas internamente ela foi convertida para "
                f"{effective['freq_mhz']} MHz para o parâmetro "
                f"freq_mhz do PlanApp. "
                f"Na resposta ao usuário, preserve a unidade original "
                f"{self.requested_frequency_unit}."
            )

        context = {
            "parametros_solicitados_pelo_usuario": requested,
            "parametros_efetivos_enviados_ao_planapp": effective,
            "conversao_de_frequencia": conversion_text,
            "resultado_tecnico_real_do_planapp": technical_result,
            "regras_de_interpretacao": [
                "Use o resultado real do PlanApp.",
                "Não invente valores.",
                "Não recalcule FSPL.",
                "Não altere unidades.",
                "Não interprete core, fresnel, boundary, "
                "delta_diffra, VV ou d_norm sem definição explícita.",
                "Não conclua viabilidade sem critérios suficientes.",
                "Diferencie parâmetros solicitados dos parâmetros efetivos.",
            ],
        }

        self.messages.append(
            {
                "role": "user",
                "content": (
                    "CONTEXTO TÉCNICO OBTIDO AUTOMATICAMENTE "
                    "PELO PLANAPP.\n\n"
                    + json.dumps(
                        context,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                ),
            }
        )

    # ========================================================
    # TURNO DO AGENTE
    # ========================================================

    async def agent_turn(self):

        for _ in range(12):

            response = await self.ollama_chat()

            message = response.get(
                "message",
                {},
            )

            content = message.get(
                "content",
                "",
            )

            tool_calls = message.get(
                "tool_calls",
                [],
            )

            assistant_message = {
                "role": "assistant",
                "content": content,
            }

            if tool_calls:
                assistant_message["tool_calls"] = tool_calls

            self.messages.append(
                assistant_message
            )

            # ------------------------------------------------
            # Sem chamada de ferramenta
            # ------------------------------------------------

            if not tool_calls:

                if (
                    len(self.geocoded_points) >= 2
                    and not self.evaluate_executed
                ):

                    technical_result = (
                        await self.ensure_evaluate_link(
                            self.link_parameters
                        )
                    )

                    self.append_technical_context(
                        technical_result
                    )

                    continue

                if self.evaluate_executed:

                    return content

                return content

            # ------------------------------------------------
            # Executa chamadas de ferramentas
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

                if isinstance(arguments, str):

                    try:
                        arguments = json.loads(arguments)

                    except Exception:
                        arguments = {}

                result = await self.execute_mcp_tool(
                    tool_name,
                    arguments,
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
            # Após as ferramentas
            # ------------------------------------------------

            if (
                len(self.geocoded_points) >= 2
                and not self.evaluate_executed
            ):

                technical_result = (
                    await self.ensure_evaluate_link(
                        self.link_parameters
                    )
                )

                self.append_technical_context(
                    technical_result
                )

                continue

            if self.evaluate_executed:

                # Faz uma nova chamada ao Qwen para produzir
                # a resposta final usando o resultado técnico.
                continue

        return (
            "A análise foi executada, mas o modelo atingiu "
            "o limite de processamento da resposta."
        )

    # ========================================================
    # ASK
    # ========================================================

    async def ask(self, text):

        # ----------------------------------------------------
        # Reset da execução
        # ----------------------------------------------------

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False
        self.last_evaluate_result = None

        self.tool_count = 0
        self.current_stage = 0

        self.map = None

        # ----------------------------------------------------
        # Parâmetros
        # ----------------------------------------------------

        parameters = self.extract_link_parameters(
            text
        )

        self.log(
            "🟡 Etapa 1 — Processando solicitação"
        )

        self.log(
            "⚙️ Parâmetros detectados: "
            + json.dumps(
                parameters,
                ensure_ascii=False,
                indent=2,
            )
        )

        # ----------------------------------------------------
        # MCP
        # ----------------------------------------------------

        await self.connect()

        await self.register()

        # ----------------------------------------------------
        # Mensagens iniciais
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

        # ----------------------------------------------------
        # Agente
        # ----------------------------------------------------

        resultado = await self.agent_turn()

        # ----------------------------------------------------
        # Garantias finais
        # ----------------------------------------------------

        if (
            len(self.geocoded_points) >= 2
            and not self.evaluate_executed
        ):

            technical_result = (
                await self.ensure_evaluate_link(
                    parameters
                )
            )

            self.append_technical_context(
                technical_result
            )

            # Última resposta do modelo
            resultado = await self.agent_turn()

        if (
            len(self.geocoded_points) >= 2
            and self.map is None
        ):

            await self.mostrar_mapa_apos_geocodificacao()

        if self.map is not None:

            self.log(
                "🗺️ Mapa disponível."
            )

        self.current_stage = 3

        self.log(
            "🔵 Etapa 3 — Interpretando resultados"
        )

        self.log(
            "🟢 Análise concluída."
        )

        return resultado

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        finally:

            self.mcp_session = None
            self.mcp_tools = []
            self.connected = False