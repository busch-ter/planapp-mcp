import asyncio
import html
import importlib
import json

import ipywidgets as widgets
from IPython.display import display

import agent_jupyter

agent_jupyter = importlib.reload(agent_jupyter)

PlanAppAgent = agent_jupyter.PlanAppAgent


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
        )
    )

    # ========================================================
    # LOG MCP
    # ========================================================

    log_execucao = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="8px",
            max_height="350px",
            overflow="auto",
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
    # CALLBACK — STATUS
    # ========================================================

    def atualizar_status(mensagem):

        status.value = (
            "<b>Status:</b> "
            + html.escape(str(mensagem))
        )

        with historico_status:

            print(str(mensagem))

    # ========================================================
    # CALLBACK — LOG MCP
    # ========================================================

    def atualizar_log(mensagem):

        with log_execucao:

            print(str(mensagem))

    # ========================================================
    # CALLBACK — RESULTADO TÉCNICO
    # ========================================================

    def atualizar_resultado_tecnico(resultado):

        with resultado_tecnico_output:

            resultado_tecnico_output.clear_output(
                wait=True
            )

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

    # ========================================================
    # CALLBACK — MAPA
    # ========================================================

    def atualizar_mapa(mapa):

        mapa_output.children = []

        if mapa is not None:

            mapa_output.children = [
                mapa
            ]

    # ========================================================
    # CALLBACK — VISUALIZAÇÕES
    # ========================================================

    def atualizar_visualizacoes(visualizacoes):

        visualizacoes_output.children = []

        if not visualizacoes:
            return

        children = []

        for item in visualizacoes:

            if item is None:
                continue

            children.append(item)

        visualizacoes_output.children = children

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

            resultado = await agent.ask(
                texto
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

        finally:

            botao_analisar.disabled = False

    # ========================================================
    # BOTÃO ANALISAR
    # ========================================================

    def ao_clicar_analisar(_):

        asyncio.ensure_future(
            executar_analise_async()
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
        # Fecha o agente anterior
        # ----------------------------------------------------

        try:

            asyncio.ensure_future(
                agent.close()
            )

        except Exception:

            pass

        # ----------------------------------------------------
        # Cria nova instância
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
        ]
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
        ]
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
        ]
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
        ]
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
        ]
    )

    # ========================================================
    # PAINEL RESPOSTA
    # ========================================================

    painel_resposta = widgets.VBox(
        [
            resposta,
        ]
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