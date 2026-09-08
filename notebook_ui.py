import asyncio
import html
import importlib

import ipywidgets as widgets
from IPython.display import display

import agent_jupyter

agent_jupyter = importlib.reload(agent_jupyter)

PlanAppAgent = agent_jupyter.PlanAppAgent


# ============================================================
# INTERFACE PLANAPP
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
        placeholder=(
            "Exemplo: Analise um enlace entre "
            "a Praça da República e o Largo do Paissandu "
            "em São Paulo."
        ),
        layout=widgets.Layout(
            width="100%",
            height="100px",
        ),
    )

    # ========================================================
    # BOTÕES
    # ========================================================

    botao_analisar = widgets.Button(
        description="🚀 Analisar enlace",
        button_style="primary",
        layout=widgets.Layout(
            width="180px",
        ),
    )

    botao_nova = widgets.Button(
        description="🆕 Nova análise",
        layout=widgets.Layout(
            width="140px",
        ),
    )

    botoes = widgets.HBox(
        [
            botao_analisar,
            botao_nova,
        ],
        layout=widgets.Layout(
            margin="8px 0 8px 0",
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
            width="100%",
            max_height="260px",
            overflow="auto",
            border="1px solid #ddd",
            padding="6px",
        )
    )

    # ========================================================
    # LOG DETALHADO MCP
    # ========================================================

    log_execucao = widgets.Output(
        layout=widgets.Layout(
            width="100%",
            max_height="400px",
            overflow="auto",
            border="1px solid #ddd",
            padding="6px",
        )
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
    # RESPOSTA FINAL
    # ========================================================

    resposta = widgets.HTML(
        value="",
        layout=widgets.Layout(
            width="100%",
        ),
    )

    # ========================================================
    # CALLBACK STATUS
    # ========================================================

    def atualizar_status(mensagem):

        status.value = (
            "<b>Status:</b> "
            + html.escape(str(mensagem))
        )

        with historico_status:

            print(str(mensagem))

    # ========================================================
    # CALLBACK LOG DETALHADO
    # ========================================================

    def atualizar_log(mensagem):

        with log_execucao:

            print(str(mensagem))

    # ========================================================
    # CALLBACK MAPA
    # ========================================================

    def atualizar_mapa(mapa):

        mapa_output.children = [
            mapa
        ]

    # ========================================================
    # AGENTE
    # ========================================================

    agent = PlanAppAgent(
        progress_callback=atualizar_status,
        map_callback=atualizar_mapa,
        log_callback=atualizar_log,
    )

    # ========================================================
    # EXECUÇÃO ASSÍNCRONA
    # ========================================================

    async def executar_analise_async():

        texto = entrada.value.strip()

        if not texto:

            status.value = (
                "<b>Status:</b> "
                "⚠️ Digite uma solicitação."
            )

            return

        # ----------------------------------------------------
        # Limpa execução anterior
        # ----------------------------------------------------

        resposta.value = ""

        mapa_output.children = []

        with historico_status:

            print("")
            print("=" * 70)
            print("🆕 NOVA ANÁLISE")
            print("=" * 70)

        with log_execucao:

            print("")
            print("=" * 70)
            print("🔧 LOG MCP")
            print("=" * 70)

        botao_analisar.disabled = True
        botao_nova.disabled = True

        status.value = (
            "<b>Status:</b> ⏳ Processando..."
        )

        try:

            resultado = await agent.ask(
                texto
            )

            # ------------------------------------------------
            # Resposta final
            # ------------------------------------------------

            resposta.value = (
                "<div style='"
                "border:1px solid #ddd;"
                "padding:12px;"
                "margin-top:10px;"
                "background:#fafafa;"
                "'>"
                "<h3 style='margin-top:0;'>"
                "💬 Resposta do PlanApp AI"
                "</h3>"
                "<div style='white-space:pre-wrap;'>"
                + html.escape(
                    str(resultado)
                )
                + "</div>"
                "</div>"
            )

            status.value = (
                "<b>Status:</b> "
                "✅ Análise concluída."
            )

        except Exception as exc:

            resposta.value = (
                "<div style='"
                "border:1px solid #f00;"
                "padding:12px;"
                "margin-top:10px;"
                "'>"
                "<h3 style='margin-top:0;'>"
                "❌ Erro"
                "</h3>"
                "<div style='white-space:pre-wrap;'>"
                + html.escape(
                    str(exc)
                )
                + "</div>"
                "</div>"
            )

            status.value = (
                "<b>Status:</b> "
                "❌ Erro durante a análise."
            )

        finally:

            botao_analisar.disabled = False
            botao_nova.disabled = False

    # ========================================================
    # CALLBACK BOTÃO ANALISAR
    # ========================================================

    def executar_analise(_):

        asyncio.create_task(
            executar_analise_async()
        )

    botao_analisar.on_click(
        executar_analise
    )

    # ========================================================
    # NOVA ANÁLISE
    # ========================================================

    def nova_analise(_):

        entrada.value = ""

        resposta.value = ""

        status.value = (
            "<b>Status:</b> "
            "Aguardando nova solicitação."
        )

        mapa_output.children = []

        historico_status.clear_output()

        log_execucao.clear_output()

        # Novo agente para garantir estado limpo
        nonlocal agent

        try:

            agent = PlanAppAgent(
                progress_callback=atualizar_status,
                map_callback=atualizar_mapa,
                log_callback=atualizar_log,
            )

        except Exception as exc:

            status.value = (
                "<b>Status:</b> "
                f"❌ Erro ao criar agente: "
                f"{html.escape(str(exc))}"
            )

    botao_nova.on_click(
        nova_analise
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
            background:#fafafa;
        ">
            <b>Exemplos:</b>

            <ul>
                <li>
                    Analise um enlace entre a Praça da República
                    e o Largo do Paissandu em São Paulo.
                </li>

                <li>
                    Analise um enlace entre Curitiba e São José
                    dos Pinhais usando 2,4 GHz.
                </li>

                <li>
                    Analise o enlace entre dois pontos usando
                    antenas de 10 metros e frequência de 900 MHz.
                </li>

                <li>
                    Analise um enlace com antena TX de 12 metros,
                    antena RX de 8 metros e frequência de 5 GHz.
                </li>
            </ul>
        </div>
        """
    )

    # ========================================================
    # PAINEL DE STATUS
    # ========================================================

    painel_status = widgets.VBox(
        [
            widgets.HTML(
                "<h3 style='margin-bottom:5px;'>"
                "📋 Andamento"
                "</h3>"
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
                "<h3 style='margin-bottom:5px;'>"
                "🔧 Execução MCP"
                "</h3>"
            ),
            log_execucao,
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
                "<h3 style='margin-bottom:5px;'>"
                "🗺️ Enlace"
                "</h3>"
            ),
            mapa_output,
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
    # INTERFACE COMPLETA
    # ========================================================

    interface = widgets.VBox(
        [
            titulo,

            widgets.HTML(
                "<b>Solicitação:</b>"
            ),

            entrada,

            botoes,

            painel_status,

            widgets.HTML(
                "<hr style='margin:15px 0;'>"
            ),

            painel_mcp,

            widgets.HTML(
                "<hr style='margin:15px 0;'>"
            ),

            painel_mapa,

            widgets.HTML(
                "<hr style='margin:15px 0;'>"
            ),

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

    # ========================================================
    # RETORNO
    # ========================================================

    return interface, agent