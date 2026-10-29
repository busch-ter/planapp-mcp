import json
import shutil
from pathlib import Path

import pytest

from cisei_planning_sdk.project import PlanningProject
from scenario_agent_openai import (
    ScenarioAgentOpenAI,
    ScenarioAgentOpenAIError,
)


PROJECT_PATH = Path(
    "/home/jovyan/work/cisei_workspace/projects/"
    "scenario_agent_openai_guards_test"
)


class FakeResponse:
    def __init__(self, payload):
        self.output_text = json.dumps(payload)


class FakeResponses:
    def __init__(self, action):
        self.action = action

    def create(self, **kwargs):
        return FakeResponse(self.action)


class FakeOpenAI:
    def __init__(self, action):
        self.responses = FakeResponses(action)


@pytest.fixture
def make_agent():
    created = []

    def factory(action):
        if PROJECT_PATH.exists():
            shutil.rmtree(PROJECT_PATH)

        # Prepara o CSV mínimo exigido pelo ScenarioSession neste teste.
        PROJECT_PATH.mkdir(parents=True, exist_ok=True)
        (PROJECT_PATH / "nodes.csv").write_text(
            "site_id,device_profile,kind,lat,lon,mount_height_m,connected,can_route\n"
            "test-site,test-profile,leaf,-25.4,-49.2,10,false,true\n",
            encoding="utf-8",
        )

        agent = ScenarioAgentOpenAI(
            PlanningProject(PROJECT_PATH),
            client=FakeOpenAI(action),
        )
        created.append(agent)
        return agent

    yield factory

    for agent in created:
        if agent.project_path.exists():
            shutil.rmtree(agent.project_path)


def test_llm_confirm_action_without_user_confirmation_is_not_trusted(
    make_agent,
):
    agent = make_agent({"action": "confirm"})

    # Mensagem ambígua: não autoriza confirmação.
    with pytest.raises(ScenarioAgentOpenAIError):
        agent.chat("ok")

    assert agent.scenario.confirmed is False


def test_finalize_before_confirmation_does_not_save(make_agent):
    agent = make_agent({"action": "finalize"})

    with pytest.raises((RuntimeError, ScenarioAgentOpenAIError)):
        agent.chat("Finalize o cenário.")

    assert agent.scenario.confirmed is False
    assert not agent.scenario_path.exists()
