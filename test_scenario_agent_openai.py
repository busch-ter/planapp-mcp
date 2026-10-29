
# ============================================================
# TESTE — SCENARIO AGENT OPENAI
#
# POC-07b
#
# Testa o adaptador OpenAI do Scenario Agent.
#
# IMPORTANTE:
# Este teste NÃO faz chamadas reais à OpenAI.
#
# Fluxo:
#   Fake OpenAI
#       ↓
#   ScenarioAgentOpenAI
#       ↓
#   ScenarioAgent
#       ↓
#   ScenarioConversation
#       ↓
#   ScenarioSession
#       ↓
#   ScenarioBuilder
#       ↓
#   PlanningProject
#       ↓
#   scenario.toml
#
# ============================================================

from pathlib import Path
import json
import shutil
import tomllib

from cisei_planning_sdk.project import PlanningProject
from scenario_agent_openai import ScenarioAgentOpenAI


# ============================================================
# CAMINHOS
# ============================================================

WORKSPACE = Path(
    "/home/jovyan/work/cisei_workspace"
)

GOLDEN_PATH = (
    WORKSPACE
    / "projects"
    / "example1_LTE_planning_basic"
    / "scenario.toml"
)

PROJECT_PATH = (
    WORKSPACE
    / "projects"
    / "scenario_agent_openai_poc"
)


# ============================================================
# UTILITÁRIOS
# ============================================================

def reset_project():
    """Remove o projeto de teste anterior."""
    if PROJECT_PATH.exists():
        shutil.rmtree(PROJECT_PATH)


def load_toml(path: Path):
    """Carrega um arquivo TOML."""
    return tomllib.loads(
        path.read_text(encoding="utf-8")
    )


# ============================================================
# FAKE OPENAI
# ============================================================

class FakeResponse:
    """Resposta simulada da OpenAI Responses API."""

    def __init__(self, payload):
        self.output_text = json.dumps(
            payload,
            ensure_ascii=False,
        )


class FakeResponses:
    """Simula client.responses da OpenAI."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    def create(self, **kwargs):
        """Registra a chamada e devolve a próxima ação."""

        self.calls.append(kwargs)

        if not self.actions:
            raise RuntimeError(
                "FakeResponses não possui mais ações disponíveis."
            )

        action = self.actions.pop(0)

        return FakeResponse(action)


class FakeOpenAI:
    """Cliente OpenAI falso utilizado pelo teste."""

    def __init__(self, actions):
        self.responses = FakeResponses(actions)


# ============================================================
# TESTE PRINCIPAL
# ============================================================

def main():

    print("=" * 60)
    print(
        "SCENARIO AGENT OPENAI — "
        "POC-07b — TESTE"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Preparação
    # --------------------------------------------------------

    reset_project()

    assert WORKSPACE.exists(), (
        f"Workspace não encontrado: {WORKSPACE}"
    )

    assert GOLDEN_PATH.exists(), (
        f"Golden reference não encontrado: {GOLDEN_PATH}"
    )

    golden_data = load_toml(GOLDEN_PATH)

    # Garantir que o arquivo de referência contém as seções
    # utilizadas pelas ações simuladas.
    required_sections = [
        "scenario",
        "antennas",
        "interfaces",
        "devices",
        "metrics",
        "instances",
    ]

    for section in required_sections:
        assert section in golden_data, (
            f"Seção ausente no golden reference: {section}"
        )

    # ========================================================
    # AÇÕES SIMULADAS DO LLM
    #
    # 1  ask_user
    # 2  update scenario
    # 3  update antennas
    # 4  update interfaces
    # 5  update devices
    # 6  update metrics
    # 7  update instances
    # 8  confirm
    # 9  finalize
    #
    # ========================================================

    actions = [

        # ----------------------------------------------------
        # 1 — início da conversa
        # ----------------------------------------------------

        {
            "action": "ask_user",
            "question": (
                "Quais são os parâmetros "
                "do cenário que deseja utilizar?"
            ),
        },

        # ----------------------------------------------------
        # 2 — scenario
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "scenario": golden_data["scenario"],
            },
        },

        # ----------------------------------------------------
        # 3 — antennas
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "antennas": golden_data["antennas"],
            },
        },

        # ----------------------------------------------------
        # 4 — interfaces
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "interfaces": golden_data["interfaces"],
            },
        },

        # ----------------------------------------------------
        # 5 — devices
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "devices": golden_data["devices"],
            },
        },

        # ----------------------------------------------------
        # 6 — metrics
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "metrics": golden_data["metrics"],
            },
        },

        # ----------------------------------------------------
        # 7 — instances
        # ----------------------------------------------------

        {
            "action": "update_scenario",
            "updates": {
                "instances": golden_data["instances"],
            },
        },

        # ----------------------------------------------------
        # 8 — confirmação
        # ----------------------------------------------------

        {
            "action": "confirm",
        },

        # ----------------------------------------------------
        # 9 — finalização
        # ----------------------------------------------------

        {
            "action": "finalize",
        },
    ]

    fake_client = FakeOpenAI(actions)

    # ========================================================
    # CRIAÇÃO DO PROJETO
    # ========================================================

    project = PlanningProject(
        PROJECT_PATH
    )

    # ========================================================
    # CRIAÇÃO DO SCENARIO AGENT OPENAI
    # ========================================================

    agent = ScenarioAgentOpenAI(
        project,
        model="gpt-5.6-luna",
        client=fake_client,
    )

    print("\n[1] Adaptador criado")

    print(f"  modelo: {agent.model}")
    print(f"  projeto: {agent.project_path}")
    print(f"  scenario: {agent.scenario_path}")

    assert agent.model == "gpt-5.6-luna"
    assert agent.scenario.valid is True
    assert agent.scenario.complete is False
    assert agent.scenario.confirmed is False

    print("  OK")

    # ========================================================
    # INÍCIO DA CONVERSA
    # ========================================================

    print("\n[2] Início da conversa")

    result = agent.chat(
        "Quero criar um cenário LTE."
    )

    print(f"  action: {result['action']}")
    print(f"  question: {result.get('question', '')}")

    assert result["action"] == "ask_user"
    assert isinstance(result.get("question"), str)
    assert result["question"].strip()

    state = agent.scenario.conversation_state()

    assert state["valid"] is True
    assert state["complete"] is False
    assert state["confirmed"] is False
    assert len(state["missing"]) == 8

    print(f"  missing: {len(state['missing'])}")
    print("  OK")

    # ========================================================
    # COLETA INCREMENTAL
    # ========================================================

    messages = [
        "O CRS de trabalho é EPSG:31982.",
        "Estas são as antenas que quero utilizar.",
        "Estas são as interfaces.",
        "Estes são os dispositivos.",
        "Esta é a métrica.",
        "Estas são as instâncias.",
    ]

    print("\n[3] Conversa simulada — coleta")

    results = []

    for index, message in enumerate(
        messages,
        start=1,
    ):

        result = agent.chat(message)
        results.append(result)

        # O adapter retorna diretamente o resultado de
        # process_update(). A chave "action" representa
        # a próxima ação da conversa, não a ação do modelo.
        print(
            f"  [{index}] "
            f"next_action={result['action']} "
            f"complete={result['complete']} "
            f"confirmed={result['confirmed']} "
            f"missing={len(result['missing'])}"
        )

        assert result["valid"] is True
        assert result["confirmed"] is False
        assert isinstance(result["missing"], list)
        assert isinstance(result["errors"], list)

    # --------------------------------------------------------
    # Verificação após coleta
    # --------------------------------------------------------

    state = agent.scenario.conversation_state()

    print("\n[4] Estado após coleta")

    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {state['missing']}")

    assert state["valid"] is True
    assert state["complete"] is True
    assert state["confirmed"] is False
    assert state["missing"] == []

    print("  OK")

    # ========================================================
    # CONFIRMAÇÃO
    # ========================================================

    print("\n[5] Confirmação explícita")

    result = agent.chat(
        "Confirmo o cenário."
    )

    # process_confirmation(True) retorna a próxima ação
    # do fluxo ("finalize"), além do estado confirmado.
    print(f"  action: {result['action']}")

    assert result["action"] == "finalize"
    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True
    assert result["missing"] == []

    state = agent.scenario.conversation_state()

    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {state['missing']}")

    assert state["valid"] is True
    assert state["complete"] is True
    assert state["confirmed"] is True
    assert state["missing"] == []

    print("  OK")

    # ========================================================
    # FINALIZAÇÃO
    # ========================================================

    print("\n[6] Finalização")

    result = agent.chat(
        "Finalize o cenário."
    )

    # process_finalize() retorna o resultado diretamente.
    print(f"  action: {result['action']}")

    assert result["action"] == "completed"
    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True

    scenario_path = Path(
        result["scenario_path"]
    )

    print(f"  salvo em: {scenario_path}")

    assert scenario_path.exists()

    print("  OK")

    # ========================================================
    # COMPARAÇÃO COM GOLDEN REFERENCE
    # ========================================================

    print("\n[7] Comparação com golden reference")

    generated = load_toml(
        scenario_path
    )

    assert generated == golden_data, (
        "O scenario.toml gerado difere do golden reference."
    )

    print("  RESULTADO: IDENTICOS")
    print("  OK")

    # ========================================================
    # VERIFICAÇÃO DO CLIENTE OPENAI
    # ========================================================

    print("\n[8] Verificação do cliente OpenAI")

    calls = fake_client.responses.calls

    print(f"  total de chamadas: {len(calls)}")

    assert len(calls) == 9
    assert fake_client.responses.actions == []

    for call in calls:

        assert call["model"] == "gpt-5.6-luna"

        assert call["reasoning"] == {
            "effort": "medium"
        }

    print("  todas as chamadas utilizaram:")
    print("    model = gpt-5.6-luna")
    print("    reasoning = medium")
    print("  OK")

    # ========================================================
    # VERIFICAÇÃO DO CONTRATO DO PROMPT
    # ========================================================

    print("\n[9] Verificação do contrato do prompt")

    prompt = agent._system_prompt()
    prompt_lower = prompt.lower()

    # Validar conceitos essenciais sem depender de frases
    # literais em português ou inglês.
    required_prompt_tokens = [
        "scenario.working_crs",
        "instances.source",
        "instances.format",
        "instances.profile_column",
        "mcp",
        "planning service",
        "json",
    ]

    for token in required_prompt_tokens:

        assert token in prompt_lower, (
            f"Elemento obrigatório ausente no prompt: {token}"
        )

    assert (
        "invent" in prompt_lower
        or "make up" in prompt_lower
    ), "Regra contra invenção de valores ausente no prompt."

    assert "default" in prompt_lower, (
        "Regra sobre defaults ausente no prompt."
    )

    print("  contrato técnico e limites de atuação presentes")
    print("  OK")

    # ========================================================
    # VERIFICAÇÃO DO ISOLAMENTO
    # ========================================================

    print("\n[10] Verificação do isolamento")

    assert not hasattr(agent, "mcp")
    assert not hasattr(agent, "planning_service")

    print("  nenhuma dependência MCP/Planning Service")
    print("  OK")

    # ========================================================
    # RESULTADO FINAL
    # ========================================================

    print()
    print("=" * 60)
    print(
        "SCENARIO AGENT OPENAI — "
        "POC-07b — TESTE PASSOU"
    )
    print("=" * 60)

    print()
    print("Fluxo validado:")
    print("  Fake OpenAI")
    print("       ↓")
    print("  ScenarioAgentOpenAI")
    print("       ↓")
    print("  ScenarioAgent")
    print("       ↓")
    print("  ScenarioConversation")
    print("       ↓")
    print("  ScenarioSession")
    print("       ↓")
    print("  ScenarioBuilder")
    print("       ↓")
    print("  PlanningProject")
    print("       ↓")
    print("  scenario.toml")

    print()
    print(f"Projeto:  {project.path}")
    print(f"Scenario: {project.scenario_path}")
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
