"""
Phase 1 · Task 1.1 — Technical spike: how does CrewAI 1.15.20 `output_pydantic` behave?

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
No Harbor & Vale business logic. No dataset. No Crew 1 / Crew 2 / gate / Flow.
No real LLM and no network: a deterministic in-process fake LLM (a supported
`crewai.BaseLLM` subclass) drives the *real* Task/Crew structured-output code path.

Run:  python spike/task_1_1_output_pydantic.py

It answers, with evidence against the pinned version:
  1. Does Task(output_pydantic=Model) exist and work?
  2. What exact type is exposed after a successful structured task?
  3. Where is the validated Pydantic object available?
  4. What happens when the structured output is valid?
  5. What happens when the output does NOT satisfy the schema?
  6. Who enforces the schema — CrewAI, the LLM mechanism, or a later parse step?
  7. What API names/signatures are actually present in 1.15.20?
"""

from __future__ import annotations

import os

# Keep the spike fully offline and side-effect free.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import traceback
from typing import Any

from pydantic import BaseModel, ValidationError

import crewai
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM


# --------------------------------------------------------------------------- #
# Trivial toy schema — a short text field and an integer field.
# --------------------------------------------------------------------------- #
class ToyNote(BaseModel):
    text: str
    count: int


# --------------------------------------------------------------------------- #
# Deterministic fake LLM. `call()` ignores the prompt and returns a canned
# string, so every run is identical and no network/API key is involved.
# This is the officially supported extension point (crewai.BaseLLM).
# --------------------------------------------------------------------------- #
class ScriptedLLM(BaseLLM):
    canned_response: str = ""
    call_log: list[str] = []

    def __init__(self, canned_response: str, **kwargs: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kwargs)
        self.canned_response = canned_response
        self.call_log = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kwargs) -> str:
        self.call_log.append("call")
        return self.canned_response

    # No function-calling: forces the plain-text -> parser path, and avoids
    # any provider-capability probing.
    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def build_crew(canned: str, schema: type[BaseModel]) -> tuple[Crew, Task, ScriptedLLM]:
    llm = ScriptedLLM(canned)
    agent = Agent(
        role="Toy Reporter",
        goal="Emit a tiny structured note.",
        backstory="A disposable spike agent.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description="Return a short text and an integer count.",
        expected_output="A JSON object with keys 'text' (string) and 'count' (integer).",
        agent=agent,
        output_pydantic=schema,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return crew, task, llm


def hr(title: str) -> None:
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


# --------------------------------------------------------------------------- #
def main() -> None:
    hr("ENVIRONMENT")
    print("crewai.__version__       :", crewai.__version__)
    print("Task has 'output_pydantic':", "output_pydantic" in Task.model_fields)
    print("output_pydantic field    :", Task.model_fields["output_pydantic"].annotation,
          "| default:", Task.model_fields["output_pydantic"].default)
    print("TaskOutput.pydantic field:",
          __import__("crewai.tasks.task_output", fromlist=["TaskOutput"])
          .TaskOutput.model_fields["pydantic"].annotation)

    # ---------------- Experiment A — valid structured output ---------------- #
    hr("EXPERIMENT A — valid output  {\"text\": \"hello spike\", \"count\": 7}")
    crew_a, task_a, _ = build_crew('{"text": "hello spike", "count": 7}', ToyNote)
    try:
        out_a = crew_a.kickoff()
        print("crew.kickoff() completed : YES")
        print("type(crew_output)        :", type(out_a).__module__ + "." + type(out_a).__name__)
        print("crew_output.pydantic     :", repr(out_a.pydantic))
        print("type(crew_output.pydantic):", type(out_a.pydantic))
        print("isinstance(_, ToyNote)   :", isinstance(out_a.pydantic, ToyNote))
        print("  .text                  :", repr(getattr(out_a.pydantic, "text", None)))
        print("  .count                 :", repr(getattr(out_a.pydantic, "count", None)),
              "| type:", type(getattr(out_a.pydantic, "count", None)).__name__)
        print("crew_output.json_dict    :", out_a.json_dict)
        print("crew_output.raw          :", repr(out_a.raw))
        print("-- task.output (TaskOutput) --")
        print("task.output.pydantic     :", repr(task_a.output.pydantic))
        print("type(task.output.pydantic):", type(task_a.output.pydantic))
        print("task.output.output_format:", task_a.output.output_format)
        print("task.output.raw          :", repr(task_a.output.raw))
        print("task.output.json_dict    :", task_a.output.json_dict)
    except Exception as e:  # noqa: BLE001 - spike wants to see everything
        print("A raised:", type(e).__name__, "->", e)
        traceback.print_exc()

    # -------- Experiment A2 — coercible types ("count": "7" as string) ------ #
    hr('EXPERIMENT A2 — coercion probe  {"text": "n", "count": "7"}  (count is a STRING)')
    crew_a2, task_a2, _ = build_crew('{"text": "n", "count": "7"}', ToyNote)
    try:
        out_a2 = crew_a2.kickoff()
        print("completed                :", "YES")
        print("crew_output.pydantic     :", repr(out_a2.pydantic))
        print("  .count value / type    :", repr(getattr(out_a2.pydantic, "count", None)),
              "/", type(getattr(out_a2.pydantic, "count", None)).__name__)
    except Exception as e:  # noqa: BLE001
        print("A2 raised:", type(e).__name__, "->", e)

    # ---------------- Experiment B — schema-violating output --------------- #
    hr('EXPERIMENT B — invalid output  {"text": "oops", "count": "not-a-number"}')
    crew_b, task_b, llm_b = build_crew('{"text": "oops", "count": "not-a-number"}', ToyNote)
    try:
        out_b = crew_b.kickoff()
        print("crew.kickoff() completed : YES  (did NOT raise)")
        print("type(crew_output)        :", type(out_b).__name__)
        print("crew_output.pydantic     :", repr(out_b.pydantic))
        print("type(crew_output.pydantic):", type(out_b.pydantic))
        print("crew_output.raw          :", repr(out_b.raw))
        print("crew_output.json_dict    :", out_b.json_dict)
        try:
            print("task.output.pydantic     :", repr(task_b.output.pydantic))
            print("task.output.output_format:", task_b.output.output_format)
        except Exception as e:  # noqa: BLE001
            print("task.output access raised:", type(e).__name__, "->", e)
        print("fake LLM call count      :", len(llm_b.call_log),
              "(>1 => CrewAI asked the LLM to repair the output)")
    except ValidationError as e:
        print("crew.kickoff() RAISED    : pydantic.ValidationError")
        print("  error count            :", e.error_count())
        print("  errors()               :", e.errors())
    except Exception as e:  # noqa: BLE001
        print("crew.kickoff() RAISED    :", type(e).__module__ + "." + type(e).__name__)
        print("  message                :", str(e)[:600])
        print("  fake LLM call count    :", len(llm_b.call_log))

    # ------------- Experiment B2 — missing required field ----------------- #
    hr('EXPERIMENT B2 — missing required field  {"text": "only text"}')
    crew_b2, task_b2, llm_b2 = build_crew('{"text": "only text"}', ToyNote)
    try:
        out_b2 = crew_b2.kickoff()
        print("completed (no raise)     : YES")
        print("crew_output.pydantic     :", repr(out_b2.pydantic))
        print("crew_output.raw          :", repr(out_b2.raw))
        print("fake LLM call count      :", len(llm_b2.call_log))
    except Exception as e:  # noqa: BLE001
        print("RAISED                   :", type(e).__module__ + "." + type(e).__name__)
        print("  message                :", str(e)[:600])
        print("  fake LLM call count    :", len(llm_b2.call_log))

    hr("DONE")


if __name__ == "__main__":
    main()
