import json
from cisei_scenario_sdk.scenario_agent_openai import create_scenario_agent_openai
from cisei_scenario_sdk.scenario_domain.providers import CISEIPluginDomainContextProvider

DOMAIN_CONTEXT_SECTIONS = ("scenario_format", "assistant_workflow", "design_gaps_and_decisions")
INSTANCE_BINDING = {"source": "nodes.csv", "format": "csv", "profile_column": "device_profile"}


def initialize_agent(state):
    if not state.nodes_ready or not state.nodes_path.is_file():
        raise RuntimeError("Prepare e valide nodes.csv antes de inicializar o agente.")
    state.validated_rows = state.compiler.read_csv(state.nodes_path)
    provider = CISEIPluginDomainContextProvider()
    agent = create_scenario_agent_openai(
        state.project_root, domain_context_provider=provider,
        domain_context_sections=DOMAIN_CONTEXT_SECTIONS)
    session = agent.scenario_agent.conversation.session
    if callable(getattr(session, "update", None)):
        session.update({"instances": INSTANCE_BINDING})
    else:
        session.builder.update({"instances": INSTANCE_BINDING})
    current = session.builder.spec.get("instances", {})
    for key, expected in INSTANCE_BINDING.items():
        if current.get(key) != expected:
            raise RuntimeError(f"instances.{key} deveria ser {expected!r}")
    state.agent, state.conversation_session = agent, session
    print("ScenarioAgentOpenAI inicializado após validar", len(state.validated_rows), "nós.")
    print("Contexto do plugin:", ", ".join(DOMAIN_CONTEXT_SECTIONS))
    return agent


def conversation_state(state):
    if state.agent is None:
        raise RuntimeError("Agente ainda não inicializado.")
    return state.agent.scenario_agent.conversation_state()


def chat(state, message):
    message = str(message).strip()
    return state.agent.chat(message) if message else None


def response_text(response):
    if isinstance(response, dict):
        action = response.get("action")
        if action == "ask_user" and response.get("question"):
            return str(response["question"])
        messages = {"update_scenario": "Informações recebidas e encaminhadas para validação. Consulte o estado atual do cenário abaixo.",
                    "confirm": "Confirmação processada. Consulte o estado do cenário abaixo.",
                    "finalize": "Finalização processada. Verifique scenario.toml."}
        if action in messages:
            return messages[action]
    if isinstance(response, (dict, list)):
        return json.dumps(response, indent=2, ensure_ascii=False, default=str)
    return str(response) if response is not None else "O agente não retornou conteúdo."
