import asyncio
import html
import importlib
import json
import traceback

import ipywidgets as widgets
from IPython.display import display

import agent_openai

agent_openai = importlib.reload(agent_openai)

PlanAppAgent = agent_openai.PlanAppAgent


# ============================================================
# INTERFACE PLANAPP AI
# ============================================================

def iniciar_planapp():

    # ========================================================
    # TÍTULO
    # ========================================================

    titulo = widgets.HTML(
        value="""
        <h2 style="margin:0 0 10px 0;">
            🛰️ PlanApp AI — Planejamento de Enlaces
        </h2>
        """
    )

    # ========================================================
    # ENTRADA
    # ========================================================

    entrada = widgets.Textarea(
        value="",
        placeholder=(
            "Exemplo: Analise um enlace entre a Praça da República "
            "e o Largo do Paissandu em São Paulo."
        ),
        layout=widgets.Layout(
            width="100%",
            height="90px",
        ),
    )

    # ========================================================
    # BOTÕES
    # ========================================================

    botao_analisar = widgets.Button(
        description="📡 Analisar enlace",
        button_style="primary",
        icon="search",
        layout=widgets.Layout(
            width="180px",
        ),
    )

    botao_nova = widgets.Button(
        description="🔄 Nova análise",
        icon="refresh",
        layout=widgets.Layout(
            width="150px",
        ),
    )

    botoes = widgets.HBox(
        [
            botao_analisar,
            botao_nova,
        ],
        layout=widgets.Layout(
            margin="8px 0 12px 0",
        ),
    )

    # ========================================================
    # STATUS
    # ========================================================

    status = widgets.HTML(
        value="<b>Status:</b> Aguardando solicitação."
    )

    historico_status = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="8px",
            max_height="180px",
            overflow="auto",
            width="100%",
        )
    )

    # ========================================================
    # LOG MCP
    # ========================================================

    log_execucao = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="8px",
            height="350px",
            overflow="auto",
            width="100%",
        )
    )

    # ========================================================
    # RESULTADO TÉCNICO
    # ========================================================

    resultado_tecnico_output = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="10px",
            max_height="500px",
            overflow="auto",
            width="100%",
        )
    )

    # ========================================================
    # VISUALIZAÇÕES
    # ========================================================

    visualizacoes_output = widgets.VBox(
        [],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # MAPA
    # ========================================================

    mapa_output = widgets.VBox(
        [],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # RESPOSTA DO AGENTE
    # ========================================================

    resposta = widgets.HTML(
        value=""
    )

    # ========================================================
    # CONTADORES
    # ========================================================

    estado = {
        "status_count": 0,
        "log_count": 0,
        "visualizacao_count": 0,
        "mapa_count": 0,
        "resultado_count": 0,
    }

    # ========================================================
    # CALLBACK — STATUS
    # ========================================================

    def atualizar_status(mensagem):

        estado["status_count"] += 1

        texto = str(mensagem)

        status.value = (
            "<b>Status:</b> "
            + html.escape(texto)
        )

        try:

            with historico_status:

                print(
                    f"[STATUS #{estado['status_count']}] "
                    f"{texto}"
                )

        except Exception as exc:

            print(
                f"[ERRO CALLBACK STATUS] {repr(exc)}"
            )

    # ========================================================
    # CALLBACK — LOG MCP
    # ========================================================

    def atualizar_log(mensagem):

        estado["log_count"] += 1

        texto = str(mensagem)

        try:

            with log_execucao:

                print(
                    f"[LOG #{estado['log_count']}] "
                    f"{texto}"
                )

        except Exception as exc:

            # Último recurso: não deixar a exceção desaparecer.
            print(
                f"[ERRO CALLBACK LOG] {repr(exc)}"
            )

    # ========================================================
    # CALLBACK — RESULTADO TÉCNICO
    # ========================================================

    def atualizar_resultado_tecnico(resultado):

        estado["resultado_count"] += 1

        try:

            resultado_tecnico_output.clear_output(
                wait=True
            )

            with resultado_tecnico_output:

                print(
                    "=================================================="
                )

                print(
                    "📊 RESULTADO TÉCNICO REAL DO PLANAPP"
                )

                print(
                    "=================================================="
                )

                if resultado is None:

                    print(
                        "Nenhum resultado técnico foi retornado."
                    )

                    return

                try:

                    print(
                        json.dumps(
                            resultado,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )
                    )

                except Exception:

                    print(
                        str(resultado)
                    )

        except Exception as exc:

            print(
                "[ERRO CALLBACK RESULTADO]"
            )

            print(
                repr(exc)
            )

            traceback.print_exc()

    # ========================================================
    # CALLBACK — MAPA
    # ========================================================

    def atualizar_mapa(mapa):

        estado["mapa_count"] += 1

        try:

            mapa_output.children = []

            if mapa is None:

                return

            # ------------------------------------------------
            # O mapa precisa ser um Widget.
            # ------------------------------------------------

            if isinstance(mapa, widgets.Widget):

                mapa_output.children = [
                    mapa
                ]

                return

            # ------------------------------------------------
            # Caso venha um objeto de display/IPython,
            # colocamos dentro de Output.
            # ------------------------------------------------

            output = widgets.Output(
                layout=widgets.Layout(
                    width="100%",
                )
            )

            with output:

                display(mapa)

            mapa_output.children = [
                output
            ]

        except Exception as exc:

            output = widgets.Output()

            with output:

                print(
                    "❌ Erro ao exibir mapa:"
                )

                print(
                    repr(exc)
                )

                traceback.print_exc()

            mapa_output.children = [
                output
            ]

    # ========================================================
    # CONVERSÃO DE IMAGEM
    # ========================================================

    def converter_visualizacao(item):

        # ----------------------------------------------------
        # Já é um Widget
        # ----------------------------------------------------

        if isinstance(item, widgets.Widget):

            return item

        # ----------------------------------------------------
        # Dicionário retornado pelo MCP
        # ----------------------------------------------------

        if isinstance(item, dict):

            kind = item.get("kind")

            if kind == "image":

                encoding = item.get(
                    "encoding"
                )

                data = item.get(
                    "data"
                )

                if encoding == "base64" and data:

                    import base64

                    image_bytes = base64.b64decode(
                        data
                    )

                    return widgets.Image(
                        value=image_bytes,
                        format="png",
                        layout=widgets.Layout(
                            width="100%",
                            height="auto",
                        ),
                    )

            # ------------------------------------------------
            # Qualquer outro resultado textual
            # ------------------------------------------------

            texto = json.dumps(
                item,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            return widgets.HTML(
                value=(
                    "<pre style='"
                    "white-space:pre-wrap;"
                    "margin:10px 0;"
                    "'>"
                    + html.escape(texto)
                    + "</pre>"
                )
            )

        # ----------------------------------------------------
        # Bytes diretamente
        # ----------------------------------------------------

        if isinstance(item, bytes):

            return widgets.Image(
                value=item,
                format="png",
                layout=widgets.Layout(
                    width="100%",
                    height="auto",
                ),
            )

        # ----------------------------------------------------
        # Objeto desconhecido
        # ----------------------------------------------------

        return widgets.HTML(
            value=(
                "<pre>"
                + html.escape(str(item))
                + "</pre>"
            )
        )

    # ========================================================
    # CALLBACK — VISUALIZAÇÕES
    # ========================================================

    def atualizar_visualizacoes(visualizacoes):

        estado["visualizacao_count"] += 1

        try:

            if not visualizacoes:

                visualizacoes_output.children = []

                return

            children = []

            for index, item in enumerate(
                visualizacoes,
                start=1,
            ):

                if item is None:
                    continue

                try:

                    widget = converter_visualizacao(
                        item
                    )

                    if widget is not None:

                        children.append(
                            widget
                        )

                except Exception as exc:

                    erro = widgets.Output()

                    with erro:

                        print(
                            f"❌ Erro na visualização #{index}"
                        )

                        print(
                            repr(exc)
                        )

                        traceback.print_exc()

                    children.append(
                        erro
                    )

            visualizacoes_output.children = (
                tuple(children)
            )

        except Exception as exc:

            erro = widgets.Output()

            with erro:

                print(
                    "❌ ERRO NO CALLBACK DE VISUALIZAÇÕES"
                )

                print(
                    repr(exc)
                )

                traceback.print_exc()

            visualizacoes_output.children = [
                erro
            ]

    # ========================================================
    # CRIA AGENTE
    # ========================================================

    agent = PlanAppAgent(
        progress_callback=atualizar_status,
        map_callback=atualizar_mapa,
        log_callback=atualizar_log,
        result_callback=atualizar_resultado_tecnico,
        visualization_callback=atualizar_visualizacoes,
    )

    # ========================================================
    # EXECUÇÃO
    # ========================================================

    async def executar_analise_async():

        texto = entrada.value.strip()

        if not texto:

            atualizar_status(
                "⚠️ Digite uma solicitação."
            )

            return

        botao_analisar.disabled = True

        resposta.value = ""

        mapa_output.children = []

        visualizacoes_output.children = []

        resultado_tecnico_output.clear_output(
            wait=True
        )

        try:

            atualizar_status(
                "🟡 Iniciando análise..."
            )

            atualizar_log(
                "=================================================="
            )

            atualizar_log(
                "🚀 INÍCIO DA EXECUÇÃO"
            )

            atualizar_log(
                "=================================================="
            )

            atualizar_log(
                f"Solicitação: {texto}"
            )

            resultado = await agent.ask(
                texto
            )

            atualizar_log(
                "=================================================="
            )

            atualizar_log(
                "🏁 EXECUÇÃO FINALIZADA"
            )

            atualizar_log(
                "=================================================="
            )

            resposta.value = (
                "<div style='"
                "border:1px solid #ddd;"
                "padding:12px;"
                "margin-top:10px;"
                "border-radius:6px;"
                "'>"
                "<b>💬 Resposta do PlanApp AI</b>"
                "<div style='margin-top:10px;'>"
                + html.escape(
                    str(resultado)
                ).replace(
                    "\n",
                    "<br>"
                )
                + "</div>"
                "</div>"
            )

        except Exception as exc:

            atualizar_status(
                f"❌ Erro na execução: {exc}"
            )

            try:

                with log_execucao:

                    print("")
                    print(
                        "=================================================="
                    )
                    print(
                        "❌ EXCEÇÃO NA INTERFACE"
                    )
                    print(
                        "=================================================="
                    )
                    print(
                        repr(exc)
                    )

                    traceback.print_exc()

            except Exception:

                pass

        finally:

            botao_analisar.disabled = False

    # ========================================================
    # BOTÃO ANALISAR
    # ========================================================

    def ao_clicar_analisar(_):

        try:

            asyncio.ensure_future(
                executar_analise_async()
            )

        except Exception as exc:

            atualizar_status(
                f"❌ Não foi possível iniciar: {exc}"
            )

            with log_execucao:

                print(
                    "❌ ERRO AO CRIAR TASK"
                )

                print(
                    repr(exc)
                )

    botao_analisar.on_click(
        ao_clicar_analisar
    )

    # ========================================================
    # NOVA ANÁLISE
    # ========================================================

    def nova_analise(_):

        nonlocal agent

        entrada.value = ""

        resposta.value = ""

        status.value = (
            "<b>Status:</b> Aguardando solicitação."
        )

        historico_status.clear_output(
            wait=True
        )

        log_execucao.clear_output(
            wait=True
        )

        resultado_tecnico_output.clear_output(
            wait=True
        )

        mapa_output.children = []

        visualizacoes_output.children = []

        # ----------------------------------------------------
        # Fecha agente anterior
        # ----------------------------------------------------

        try:

            asyncio.ensure_future(
                agent.close()
            )

        except Exception:

            pass

        # ----------------------------------------------------
        # Novo agente
        # ----------------------------------------------------

        agent = PlanAppAgent(
            progress_callback=atualizar_status,
            map_callback=atualizar_mapa,
            log_callback=atualizar_log,
            result_callback=atualizar_resultado_tecnico,
            visualization_callback=atualizar_visualizacoes,
        )

        atualizar_status(
            "🔄 Nova análise pronta."
        )

    botao_nova.on_click(
        nova_analise
    )

    # ========================================================
    # PAINEL STATUS
    # ========================================================

    painel_status = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📋 Status</h4>"
            ),
            status,
            historico_status,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # PAINEL MCP
    # ========================================================

    painel_mcp = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>🔧 MCP / Log de execução</h4>"
            ),
            log_execucao,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # PAINEL RESULTADO TÉCNICO
    # ========================================================

    painel_resultado = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📊 Resultado técnico</h4>"
            ),
            resultado_tecnico_output,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # PAINEL MAPA
    # ========================================================

    painel_mapa = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>🗺️ Mapa do enlace</h4>"
            ),
            mapa_output,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # PAINEL VISUALIZAÇÕES
    # ========================================================

    painel_visualizacoes = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📈 Visualizações técnicas</h4>"
            ),
            visualizacoes_output,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # PAINEL RESPOSTA
    # ========================================================

    painel_resposta = widgets.VBox(
        [
            resposta,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # EXEMPLOS
    # ========================================================

    exemplos = widgets.HTML(
        value="""
        <div style="
            margin-top:15px;
            padding:10px;
            border:1px solid #ddd;
            border-radius:6px;
        ">
        <b>Exemplos:</b>
        <ul>
            <li>
                Analise um enlace entre a Praça da República
                e o Largo do Paissandu em São Paulo.
            </li>
            <li>
                Analise um enlace entre Curitiba e São José dos Pinhais
                usando 450 MHz.
            </li>
            <li>
                Analise o enlace com duas antenas de 10 metros
                em 2.4 GHz, sobre o telhado.
            </li>
        </ul>
        </div>
        """
    )

    # ========================================================
    # INTERFACE COMPLETA
    # ========================================================

    interface = widgets.VBox(
        [
            titulo,
            entrada,
            botoes,
            painel_status,
            painel_mcp,
            painel_resultado,
            painel_mapa,
            painel_visualizacoes,
            painel_resposta,
            exemplos,
        ],
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # DISPLAY
    # ========================================================

    display(interface)

    return interface, agent