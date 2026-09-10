"""
Phase 1 · Task 1.5 — Technical spike: CrewAI 1.15.20 `Literal[...]` tool-arg enforcement.

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
Sibling of task_1_1..task_1_4 spike files (all untouched).

Question: is a tool parameter typed `Literal["alpha", "beta"]` mechanically
rejected BEFORE the Python tool body runs? This directly backs the future Crew 2
handoff allowlist:  HandoffName = Literal["clean_data", "dataset_contract"].

No Harbor & Vale tools / dataset / crews / gate / Flow. Scripted crewai.BaseLLM,
no network, no API key.

Run:  python spike/task_1_5_literal_tool_enforcement.py
"""

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import json
import traceback
from typing import Any, Literal

import crewai
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import BaseTool, tool

# ------------------------------------------------------------------ #
BODY_CALLS: list[str] = []          # every value that actually reached a tool body


@tool("pick_resource")
def pick_resource(resource: Literal["alpha", "beta"]) -> str:
    """Pick a resource. `resource` must be exactly 'alpha' or 'beta'."""
    BODY_CALLS.append(f"@tool:{resource}")
    return f"picked::{resource}"


class PickResourceBaseTool(BaseTool):
    name: str = "pick_resource_bt"
    description: str = "Pick a resource. `resource` must be exactly 'alpha' or 'beta'."

    def _run(self, resource: Literal["alpha", "beta"]) -> str:
        BODY_CALLS.append(f"BaseTool:{resource}")
        return f"picked::{resource}"


class ScriptedLLM(BaseLLM):
    responses: list[str] = []
    calls: list[str] = []

    def __init__(self, responses: list[str], **kw: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kw)
        self.responses = list(responses)
        self.calls = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kw) -> str:
        blob = messages if isinstance(messages, str) else "\n".join(
            (m.get("content", "") if isinstance(m, dict) else str(m)) for m in messages
        )
        i = len(self.calls)
        self.calls.append(blob)
        return self.responses[i] if i < len(self.responses) else self.responses[-1]

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


# ------------------------------------------------------------------ #
def main() -> None:
    hr("ENVIRONMENT / API INSPECTION")
    print("crewai.__version__ :", crewai.__version__)
    print("@tool -> type      :", type(pick_resource).__module__ + "." + type(pick_resource).__name__)
    print("BaseTool subclass  :", PickResourceBaseTool.__mro__[1].__name__, "-> BaseModel(ABC)")
    print("enforcement path (source):")
    print("  @tool  Tool.invoke -> _parse_args -> args_schema.model_validate(raw) -> THEN func(**parsed)")
    print("  BaseTool.run -> _validate_kwargs -> args_schema.model_validate(kwargs) -> THEN _run(**kwargs)")
    print("  both raise ValueError('... arguments validation failed: <pydantic>') before the body")

    # -------------------- D — tool schema -------------------- #
    hr("EXPERIMENT D — generated args schema (mechanical enum?)")
    sch = pick_resource.args_schema.model_json_schema()
    print("@tool  args_schema JSON schema:")
    print(json.dumps(sch, indent=2))
    bt = PickResourceBaseTool()
    sch_bt = bt.args_schema.model_json_schema()
    print("\nBaseTool args_schema JSON schema:")
    print(json.dumps(sch_bt, indent=2))
    enum_tool = sch.get("$defs", {}).get("resource", {})
    # resolve the enum wherever pydantic put it
    def find_enum(s: dict) -> Any:
        if "enum" in s:
            return s["enum"]
        for v in s.get("properties", {}).values():
            if "enum" in v:
                return v["enum"]
            if "allOf" in v and v["allOf"] and "$ref" in v["allOf"][0]:
                ref = v["allOf"][0]["$ref"].split("/")[-1]
                return s.get("$defs", {}).get(ref, {}).get("enum")
        for d in s.get("$defs", {}).values():
            if "enum" in d:
                return d["enum"]
        return None
    print("\n@tool   allowed values (enum) :", find_enum(sch))
    print("BaseTool allowed values (enum) :", find_enum(sch_bt))

    # -------------------- A — valid call -------------------- #
    hr("EXPERIMENT A — VALID call  resource='alpha'  (direct .run, the real enforcement path)")
    BODY_CALLS.clear()
    r = pick_resource.run(resource="alpha")
    print("result returned        :", repr(r))
    print("body call log          :", BODY_CALLS)
    print("body executed exactly 1:", BODY_CALLS == ["@tool:alpha"])

    # -------------------- B — invalid call -------------------- #
    hr("EXPERIMENT B — INVALID call  resource='gamma'  (@tool and BaseTool)")
    BODY_CALLS.clear()
    for label, fn in [("@tool", lambda: pick_resource.run(resource="gamma")),
                      ("BaseTool", lambda: bt.run(resource="gamma"))]:
        try:
            out = fn()
            print(f"{label:9}: NO exception (returned {out!r})  <-- unexpected")
        except Exception as e:  # noqa: BLE001
            print(f"{label:9}: raised {type(e).__module__}.{type(e).__name__}")
            print(f"           message: {str(e)[:300]}")
    print("body call log (must be empty):", BODY_CALLS)
    print("ASSERT invalid Literal rejected BEFORE body:", BODY_CALLS == [])

    # -------------------- C — agent correction via a Crew -------------------- #
    hr("EXPERIMENT C — agent calls 'gamma', gets feedback, corrects to 'beta'")
    BODY_CALLS.clear()
    react = [
        # attempt 1 — invalid Literal
        "Thought: I will pick a resource.\n"
        "Action: pick_resource\n"
        'Action Input: {"resource": "gamma"}',
        # attempt 2 — corrected
        "Thought: gamma is not allowed, use beta.\n"
        "Action: pick_resource\n"
        'Action Input: {"resource": "beta"}',
        # finish
        "Thought: I now can give a great answer\n"
        "Final Answer: done with beta",
    ]
    llm = ScriptedLLM(react)
    agent = Agent(role="Picker", goal="Pick a valid resource.",
                  backstory="Disposable spike agent.", llm=llm, tools=[pick_resource],
                  verbose=False, allow_delegation=False, max_iter=6)
    task = Task(description="Pick a resource using the tool.",
                expected_output="A short confirmation string.", agent=agent)
    try:
        out = Crew(agents=[agent], tasks=[task], process=Process.sequential,
                   verbose=False).kickoff()
        print("crew completed         :", True)
        print("final output           :", repr(str(out)[:120]))
    except Exception as e:  # noqa: BLE001
        print("crew RAISED            :", type(e).__name__, "->", str(e)[:300])
    print("tool body call log     :", BODY_CALLS)
    print("invalid 'gamma' ran body:", any("gamma" in c for c in BODY_CALLS))
    print("corrected 'beta' ran body:", any("beta" in c for c in BODY_CALLS))
    if len(llm.calls) >= 2:
        fb = llm.calls[1]
        marker = ("validation failed" in fb) or ("not allowed" in fb) or \
                 ("accepts these inputs" in fb) or ("Literal" in fb) or ("gamma" in fb)
        print("2nd LLM prompt carried tool-error feedback:", marker)
        idx = fb.find("arguments validation failed")
        if idx < 0:
            idx = fb.find("accepts these inputs")
        if idx >= 0:
            print("  feedback excerpt:", repr(fb[max(0, idx - 40):idx + 220]))

    # -------------------- Handoff-allowlist question -------------------- #
    hr("HANDOFF ALLOWLIST QUESTION")
    HandoffName = Literal["clean_data", "dataset_contract"]

    @tool("read_handoff_probe")
    def read_handoff_probe(name: HandoffName) -> str:  # NO path parameter exists
        """Toy stand-in — does NOT read anything. Proves Literal rejection only."""
        BODY_CALLS.append(f"handoff:{name}")
        return f"would-read::{name}"

    BODY_CALLS.clear()
    ok = read_handoff_probe.run(name="clean_data")
    print("valid  name='clean_data'  -> body ran:", BODY_CALLS == ["handoff:clean_data"], "| result:", repr(ok))
    BODY_CALLS.clear()
    try:
        read_handoff_probe.run(name="raw_data")
        print("invalid name='raw_data'   -> NO exception  <-- unexpected")
    except Exception as e:  # noqa: BLE001
        print("invalid name='raw_data'   -> rejected:", type(e).__name__)
        print("   ", str(e)[:220])
    print("body ran for 'raw_data'   :", BODY_CALLS != [])
    print("\n=> read_handoff('raw_data') WOULD be rejected before the read body: ",
          BODY_CALLS == [])

    hr("DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
