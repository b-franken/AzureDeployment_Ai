from __future__ import annotations
from app.agents.react_agent import ProvisioningAgent
from app.tools.azure_tools import CreateResourceGroup, DeployBicep
from app.llm.adapters import CallableLLM


async def _stub_llm(messages: list[dict[str, str]]) -> str:
    return "create_resource_group: subscription_id=S, resource_group=rg-app, location=westeurope\ndeploy_bicep: resource_group=rg-app, template_path=infra/main.bicep, parameters_path=infra/params.json"


async def run_provisioning_goal(goal: str) -> list[dict]:
    agent = ProvisioningAgent(llm=CallableLLM(_stub_llm), tools=[
                              CreateResourceGroup(), DeployBicep()])
    plan = await agent.plan(goal)
    results = await agent.run(plan)
    return results
