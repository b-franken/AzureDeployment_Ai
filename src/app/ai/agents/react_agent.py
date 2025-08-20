from __future__ import annotations
from typing import Any
from agents.types import LLM, Tool, ExecutionPlan, PlanStep
from agents.memory import ConversationMemory


class ProvisioningAgent:
    def __init__(self, llm: LLM, tools: list[Tool]) -> None:
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.memory = ConversationMemory()

    async def plan(self, goal: str) -> ExecutionPlan:
        self.memory.add("user", goal)
        prompt = [{"role": "system", "content": "You plan infra tasks as ordered tool calls."}
                  ] + self.memory.messages()
        plan_text = await self.llm.generate(prompt)
        steps = self._parse_plan(plan_text)
        return ExecutionPlan(steps=steps)

    async def run(self, plan: ExecutionPlan) -> list[Any]:
        results: list[Any] = []
        for step in plan.steps:
            tool = self.tools[step.tool]
            out = await tool.run(**step.args)
            results.append(out)
            self.memory.add("tool", f"{step.tool}:{out}")
        return results

    def _parse_plan(self, text: str) -> list[PlanStep]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        steps: list[PlanStep] = []
        for l in lines:
            if ":" in l:
                name, argstr = l.split(":", 1)
                args = {}
                if "=" in argstr:
                    for kv in argstr.split(","):
                        k, v = kv.split("=")
                        args[k.strip()] = v.strip()
                steps.append(PlanStep(tool=name.strip(), args=args))
        return steps
