import json
from pathlib import Path
import ipywidgets as widgets
from IPython.display import display
from .project import create_state, prepare_nodes, save_uploads, uploaded_entries
from .agent import initialize_agent, conversation_state, chat, response_text
from .workflow import confirm, generate
from .validation import validate_existing, validate_profiles


class ScenarioBuilderApp:
    """Controlador de widgets; nenhuma chamada ao LLM é feita na construção."""

    def __init__(self, project_name, *, workspace, code_root, sdk_base_url):
        self.state = create_state(project_name, Path(workspace), Path(code_root))
        self.sdk_base_url = sdk_base_url
        self.upload = widgets.FileUpload(accept="", multiple=True, description="Selecionar arquivos",
                                         layout=widgets.Layout(width="100%"))
        self.replace_uploads = widgets.Checkbox(value=False, description="Permitir substituir arquivos em data/", indent=False)
        self.nodes_output = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px"))
        self.prepare_button = widgets.Button(description="Preparar nodes.csv", button_style="success")
        self.upload_button = widgets.Button(description="Salvar uploads em data/ e preparar", button_style="primary")
        self.init_button = widgets.Button(description="INICIALIZAR AGENTE", button_style="info")
        self.init_output = widgets.Output()
        self.entry = widgets.Textarea(placeholder="Digite sua mensagem para o ScenarioAgentOpenAI...",
                                      layout=widgets.Layout(width="100%", min_height="100px"))
        self.send_button = widgets.Button(description="ENVIAR", button_style="primary")
        self.clear_button = widgets.Button(description="LIMPAR")
        self.reply_output = widgets.Output(layout=widgets.Layout(border="1px solid #8aa4c8", padding="10px", min_height="70px"))
        self.history_output = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px", max_height="500px", overflow="auto"))
        self.state_output = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px", max_height="350px", overflow="auto"))
        self.confirm_button = widgets.Button(description="CONFIRMAR CENÁRIO", button_style="warning")
        self.generate_button = widgets.Button(description="GERAR scenario.toml", button_style="success")
        self.replace_toml = widgets.Checkbox(value=False, description="Permitir substituir scenario.toml existente", indent=False)
        self.action_output = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px"))
        self.existing_name = widgets.Text(value=self.state.project_name, description="Projeto:", layout=widgets.Layout(width="70%"))
        self.existing_button = widgets.Button(description="VALIDAR CENÁRIO EXISTENTE", button_style="info")
        self.existing_output = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px"))
        self.prepare_button.on_click(self._prepare)
        self.upload_button.on_click(self._upload)
        self.init_button.on_click(self._initialize)
        self.send_button.on_click(self._send)
        self.clear_button.on_click(self._clear)
        self.confirm_button.on_click(self._confirm)
        self.generate_button.on_click(self._generate)
        self.existing_button.on_click(self._validate_existing)

    def _prepare(self, _):
        with self.nodes_output:
            self.nodes_output.clear_output(wait=True)
            prepare_nodes(self.state)

    def _upload(self, _):
        with self.nodes_output:
            self.nodes_output.clear_output(wait=True)
            try:
                entries = uploaded_entries(self.upload.value)
                if entries:
                    save_uploads(self.state, entries, overwrite=self.replace_uploads.value)
                else:
                    print("Nenhum arquivo novo selecionado; usando fontes existentes.")
                prepare_nodes(self.state)
            except Exception as exc:
                print(f"Falha ao salvar/preparar: {type(exc).__name__}: {exc}")

    def _initialize(self, _):
        with self.init_output:
            self.init_output.clear_output(wait=True)
            try:
                if self.state.agent is not None:
                    print("Agente já inicializado; sessão atual preservada.")
                    return
                initialize_agent(self.state)
                self._show_state()
            except Exception as exc:
                print(f"Inicialização bloqueada: {type(exc).__name__}: {exc}")

    def _show_state(self):
        with self.state_output:
            self.state_output.clear_output(wait=True)
            try:
                print(json.dumps(conversation_state(self.state), indent=2, ensure_ascii=False, default=str))
            except Exception as exc:
                print(f"Estado indisponível: {type(exc).__name__}: {exc}")

    def _history(self, message, answer):
        with self.history_output:
            print("=" * 72)
            print("USUÁRIO")
            print("=" * 72)
            print(message)
            print("\n" + "=" * 72)
            print("RETORNO DO AGENTE IA")
            print("=" * 72)
            print(answer)
            print()

    def _send(self, _):
        message = self.entry.value.strip()
        if not message:
            return
        self.reply_output.clear_output(wait=True)
        with self.reply_output:
            print("Retorno do agente IA")
            print("=" * 48)
            try:
                answer = response_text(chat(self.state, message))
            except Exception as exc:
                answer = f"ERRO: {type(exc).__name__}: {exc}"
            print(answer)
        self._history(message, answer)
        self.entry.value = ""
        self._show_state()

    def _clear(self, _):
        # Mantém o estado interno do agente, exatamente como o notebook original.
        self.reply_output.clear_output()
        self.history_output.clear_output()
        self.state_output.clear_output()

    def _confirm(self, _):
        with self.action_output:
            self.action_output.clear_output(wait=True)
            try:
                result = confirm(self.state)
                answer = response_text(result)
                print(answer)
                self._history("Confirmo o cenário.", answer)
                self._show_state()
            except Exception as exc:
                print(f"Confirmação bloqueada: {type(exc).__name__}: {exc}")

    def _generate(self, _):
        with self.action_output:
            self.action_output.clear_output(wait=True)
            try:
                generate(self.state, overwrite=self.replace_toml.value,
                         base_url=self.sdk_base_url, workspace=self.state.workspace)
            except Exception as exc:
                print(f"Geração bloqueada: {type(exc).__name__}: {exc}")

    def _validate_existing(self, _):
        with self.existing_output:
            self.existing_output.clear_output(wait=True)
            try:
                report = validate_existing(self.existing_name.value, self.state.workspace / "projects",
                                           base_url=self.sdk_base_url, workspace=self.state.workspace)
                print("RESULTADO:", "APROVADO PELO SDK" if report["sdk_ok"] else "REPROVADO PELO SDK")
                print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
            except Exception as exc:
                print(f"VALIDAÇÃO NÃO CONCLUÍDA: {type(exc).__name__}: {exc}")

    def render(self):
        state = self.state
        display(widgets.VBox([
            widgets.HTML("<h3>1. Projeto e preparação de nodes.csv</h3>"),
            widgets.HTML(f"<p>Projeto: <code>{state.project_root}</code><br>Fontes: <code>{state.data_root}</code></p>"),
            self.upload, self.replace_uploads, widgets.HBox([self.upload_button, self.prepare_button]), self.nodes_output,
            widgets.HTML("<h3>2. Validação independente de projeto existente (SDK)</h3>"),
            self.existing_name, self.existing_button, self.existing_output,
            widgets.HTML("<h3>3. Inicializar agente</h3>"), self.init_button, self.init_output,
            widgets.HTML("<h3>4. Conversar com o agente</h3>"),
            self.entry, widgets.HBox([self.send_button, self.clear_button]),
            widgets.HTML("<h3>Retorno do agente IA</h3>"), self.reply_output,
            widgets.HTML("<h3>Histórico da conversa</h3>"), self.history_output,
            widgets.HTML("<h3>Estado atual do cenário</h3>"), self.state_output,
            widgets.HTML("<h3>5. Confirmar e gerar scenario.toml</h3>"),
            widgets.HBox([self.confirm_button, self.generate_button]), self.replace_toml, self.action_output,
        ]))
        # O comportamento de preparação inicial é preservado, mas o agente só inicia por ação explícita.
        self._prepare(None)
        return self
