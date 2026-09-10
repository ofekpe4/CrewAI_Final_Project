"""
Phase 1 · Task 1.3 — Technical spike: CrewAI 1.15.20 Task `callback` ordering.

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
Sibling of task_1_1_output_pydantic.py / task_1_2_guardrail_retry.py (both untouched).

Key question: in a Process.sequential Crew, does Task N's callback RUN AND FULLY
FINISH before Task N+1's agent begins? (This is the Pattern A vs B pivot — but the
decision is NOT made here.)

No Harbor & Vale agents / dataset / crews / gate / Flow. No real LLM, no network,
no API key: a scripted crewai.BaseLLM drives the real Task/Crew callback path.
Temp artifacts go to a throwaway dir (NOT the repo, NOT artifacts/).

Run:  python spike/task_1_3_callback_ordering.py
"""

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import crewai
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tasks.task_output import TaskOutput


class ToyNote(BaseModel):
    text: str
    count: int


# --- deterministic, monotonic event log shared by LLM calls + callbacks --------
EVENTS: list[tuple[int, str]] = []


def mark(label: str) -> None:
    EVENTS.append((time.monotonic_ns(), label))


def dump_events() -> None:
    if not EVENTS:
        print("  (no events)")
        return
    t0 = EVENTS[0][0]
    for i, (ts, label) in enumerate(EVENTS):
        print(f"  {i:2}  +{(ts - t0) / 1e6:8.2f} ms   {label}")


class ScriptedLLM(BaseLLM):
    """Returns a canned string; emits an event so we can see exactly when the
    agent for a given task is executing."""

    canned: str = ""
    tag: str = ""
    probe: Any = None

    def __init__(self, canned: str, tag: str, probe=None, **kw: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kw)
        self.canned, self.tag, self.probe = canned, tag, probe

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kw) -> str:
        mark(f"{self.tag}_agent_llm_call")
        if self.probe is not None:
            self.probe()
        return self.canned


def make_agent(canned: str, tag: str, probe=None) -> Agent:
    return Agent(role=f"Toy {tag}", goal="Emit a tiny note.",
                 backstory="Disposable spike agent.",
                 llm=ScriptedLLM(canned, tag, probe),
                 verbose=False, allow_delegation=False)


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


# --------------------------------------------------------------------------- #
def main() -> None:
    hr("ENVIRONMENT / API INSPECTION")
    print("crewai.__version__        :", crewai.__version__)
    cbf = Task.model_fields["callback"]
    print("Task has 'callback'       :", "callback" in Task.model_fields)
    print("callback default          :", cbf.default)
    print("callback description      :", cbf.description)
    print("callback invoked in Task._execute_core AFTER: guardrail loop + "
          "self.output assignment; BEFORE: output_file save, TaskCompletedEvent, return")
    print("Crew._execute_tasks: non-async tasks run via a synchronous "
          "`task.execute_sync(...)` inside a plain for-loop (source-confirmed)")

    tmpdir = Path(tempfile.mkdtemp(prefix="spike_task_1_3_"))
    artifact = tmpdir / "task1_callback_artifact.txt"
    ARTIFACT_BODY = "written-by-task1-callback::42"
    print("temp dir                  :", tmpdir)

    # ---- captured facts -------------------------------------------------- #
    cb_input: dict[str, Any] = {}
    task2_probe_result: dict[str, Any] = {}
    SLEEP_S = 0.30

    def task1_callback(task_output) -> str:
        mark("task1_callback_START")
        # (D) exact input object + attributes
        cb_input["type"] = type(task_output).__name__
        cb_input["is_TaskOutput"] = isinstance(task_output, TaskOutput)
        cb_input["attrs"] = sorted(
            a for a in ("raw", "pydantic", "json_dict", "output_format", "name",
                        "description", "agent", "summary")
            if hasattr(task_output, a)
        )
        cb_input["raw"] = task_output.raw
        cb_input["pydantic_repr"] = repr(task_output.pydantic)
        cb_input["output_format"] = str(task_output.output_format)
        # (B) filesystem side effect — write, flush, fsync, close
        with open(artifact, "w") as fh:
            fh.write(ARTIFACT_BODY)
            fh.flush()
            os.fsync(fh.fileno())
        mark("task1_callback_file_written")
        # (C) deliberate bounded block
        time.sleep(SLEEP_S)
        mark("task1_callback_FINISH")
        return "CALLBACK_RETURN_SENTINEL"  # (D) is this used?

    def task2_agent_probe() -> None:
        # runs at the very start of Task 2's agent LLM call
        task2_probe_result["file_exists"] = artifact.exists()
        task2_probe_result["content"] = artifact.read_text() if artifact.exists() else None

    hr("EXPERIMENT A/B/C/D — sequential crew, Task 1 has the instrumented callback")

    a1 = make_agent('{"text": "one", "count": 1}', "task1")
    a2 = make_agent('{"text": "two", "count": 2}', "task2", probe=task2_agent_probe)
    t1 = Task(description="Produce note 1.", expected_output="JSON note.",
              agent=a1, output_pydantic=ToyNote, callback=task1_callback)
    t2 = Task(description="Produce note 2.", expected_output="JSON note.",
              agent=a2, output_pydantic=ToyNote)
    crew = Crew(agents=[a1, a2], tasks=[t1, t2], process=Process.sequential, verbose=False)

    EVENTS.clear()
    out = crew.kickoff()

    print("\n-- event log (monotonic) --")
    dump_events()
    labels = [l for _, l in EVENTS]

    def idx(l: str) -> int:
        return labels.index(l) if l in labels else -1

    i_cb_finish = idx("task1_callback_FINISH")
    i_t2_start = idx("task2_agent_llm_call")
    print("\n-- Experiment A: ordering --")
    print("callback_finish event index :", i_cb_finish)
    print("task2_agent_start event idx :", i_t2_start)
    print("ASSERT callback_finish < task2_agent_start :",
          i_cb_finish != -1 and i_t2_start != -1 and i_cb_finish < i_t2_start)

    print("\n-- Experiment B: filesystem artifact --")
    print("artifact written by callback:", artifact.exists())
    print("Task 2 agent saw file       :", task2_probe_result.get("file_exists"))
    print("content Task 2 read         :", repr(task2_probe_result.get("content")))
    print("content matches exactly     :",
          task2_probe_result.get("content") == ARTIFACT_BODY)

    print("\n-- Experiment C: blocking --")
    ts = {l: t for t, l in EVENTS}
    if "task1_callback_START" in ts and "task2_agent_llm_call" in ts:
        gap_ms = (ts["task2_agent_llm_call"] - ts["task1_callback_START"]) / 1e6
        cb_span_ms = (ts["task1_callback_FINISH"] - ts["task1_callback_START"]) / 1e6
        print(f"callback span               : {cb_span_ms:.1f} ms (deliberate sleep {SLEEP_S*1000:.0f} ms)")
        print(f"callback_START -> task2 start: {gap_ms:.1f} ms")
        print("task2 started DURING callback:", gap_ms < SLEEP_S * 1000 * 0.9)
        print("callback fully completed 1st :",
              idx("task1_callback_FINISH") < idx("task2_agent_llm_call"))

    print("\n-- Experiment D: callback input / return --")
    for k, v in cb_input.items():
        print(f"  {k:14}: {v}")
    print("  crew_output.pydantic (unaffected by return):", repr(out.pydantic))
    print("  t1.output.raw (unaffected by return)       :", repr(t1.output.raw))
    print("  => callback return value used by CrewAI?    : NO (discarded unless a coroutine)")

    # ---------------------- Experiment E — callback raises ---------------- #
    hr("EXPERIMENT E — Task 1 callback raises an exception")
    EVENTS.clear()
    e_seen: dict[str, Any] = {}

    def failing_callback(task_output):
        mark("E_task1_callback_START")
        raise RuntimeError("intentional callback failure (spike)")

    ea1 = make_agent('{"text": "one", "count": 1}', "E_task1")
    ea2 = make_agent('{"text": "two", "count": 2}', "E_task2")
    et1 = Task(description="Produce note 1.", expected_output="JSON note.",
               agent=ea1, output_pydantic=ToyNote, callback=failing_callback)
    et2 = Task(description="Produce note 2.", expected_output="JSON note.",
               agent=ea2, output_pydantic=ToyNote)
    ecrew = Crew(agents=[ea1, ea2], tasks=[et1, et2], process=Process.sequential,
                 verbose=False)
    try:
        ecrew.kickoff()
        e_seen["raised"] = False
    except Exception as exc:  # noqa: BLE001
        e_seen["raised"] = True
        e_seen["type"] = type(exc).__module__ + "." + type(exc).__name__
        e_seen["msg"] = str(exc)
    labels_e = [l for _, l in EVENTS]
    print("event log (E):")
    dump_events()
    print("exception propagated to kickoff():", e_seen.get("raised"))
    print("  type                           :", e_seen.get("type"))
    print("  message                        :", e_seen.get("msg"))
    print("Task 2 agent ran after failure   :", "E_task2_agent_llm_call" in labels_e)
    print("Crew halted at Task 1            :",
          "E_task1_agent_llm_call" in labels_e and "E_task2_agent_llm_call" not in labels_e)

    hr("DONE")
    # best-effort cleanup of the throwaway temp dir
    try:
        artifact.unlink(missing_ok=True)
        tmpdir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
