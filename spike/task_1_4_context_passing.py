"""
Phase 1 · Task 1.4 — Technical spike: CrewAI 1.15.20 `Task(context=[prev_task])`.

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
Sibling of task_1_1 / task_1_2 / task_1_3 spike files (all untouched).

Question: how does CrewAI pass a previous Task's output into the next Task via
`context=[t1]` — which representation (.raw / .pydantic / .json_dict / rendered),
where is it injected, and how does it compose with output_pydantic / guardrail /
callback? The Pattern A vs B decision is NOT made here.

No Harbor & Vale agents / dataset / crews / gate / Flow. Scripted crewai.BaseLLM,
no network, no API key. Temp files go to tempfile.mkdtemp(), not the repo.

Run:  python spike/task_1_4_context_passing.py
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


CAPTURES: dict[str, str] = {}   # tag -> full prompt blob seen by that agent's LLM
EVENTS: list[tuple[int, str]] = []


def mark(label: str) -> None:
    EVENTS.append((time.monotonic_ns(), label))


class ScriptedLLM(BaseLLM):
    responses: list[str] = []
    tag: str = ""
    idx: int = 0
    probe: Any = None

    def __init__(self, responses, tag: str, probe=None, **kw: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kw)
        self.responses = list(responses) if isinstance(responses, list) else [responses]
        self.tag, self.idx, self.probe = tag, 0, probe

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kw) -> str:
        blob = messages if isinstance(messages, str) else "\n".join(
            (m.get("content", "") if isinstance(m, dict) else str(m)) for m in messages
        )
        CAPTURES[self.tag] = blob
        mark(f"{self.tag}_llm_call")
        if self.probe is not None:
            self.probe(blob)
        r = self.responses[self.idx] if self.idx < len(self.responses) else self.responses[-1]
        self.idx += 1
        return r


def agent_for(responses, tag: str, probe=None) -> Agent:
    return Agent(role=f"Toy {tag}", goal="Emit a tiny note.",
                 backstory="Disposable spike agent.",
                 llm=ScriptedLLM(responses, tag, probe),
                 verbose=False, allow_delegation=False)


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def show_context_window(blob: str, marker: str, width: int = 160) -> str:
    i = blob.find(marker)
    if i < 0:
        return "<marker not found>"
    lo = max(0, i - width)
    hi = min(len(blob), i + len(marker) + width)
    return "…" + blob[lo:hi].replace("\n", "\\n") + "…"


# --------------------------------------------------------------------------- #
def main() -> None:
    hr("ENVIRONMENT / API INSPECTION")
    print("crewai.__version__     :", crewai.__version__)
    cf = Task.model_fields["context"]
    print("Task has 'context'     :", "context" in Task.model_fields)
    print("context annotation     :", cf.annotation)
    print("context default        :", repr(cf.default), "(sentinel NOT_SPECIFIED; truthy)")
    print("context description    :", cf.description)
    print("impl path (source)     : Crew._execute_tasks -> Crew._get_context(task, task_outputs)")
    print("                         -> aggregate_raw_outputs_from_tasks(task.context)")
    print("                         -> DIVIDERS.join(o.raw for o in [t.output ...]);  DIVIDERS = '\\n\\n----------\\n\\n'")
    print("                         -> task.execute_sync(agent, context=<str>, tools)")
    print("                         -> agent wraps via i18n 'task_with_context':")
    print("                            '{task}\\n\\nThis is the context you\\'re working with:\\n{context}'")

    CTX_HEADER = "This is the context you're working with:"
    DIVIDER = "\n\n----------\n\n"

    # ------------------- Experiment A — basic context ------------------- #
    hr("EXPERIMENT A — basic context passing  (context=[task1])")
    MARK_A = "ZZ_MARKER_ALPHA_7f3c9"
    a1 = agent_for(f'{{"text": "{MARK_A}", "count": 11}}', "A_t1")
    a2 = agent_for('{"text": "downstream", "count": 1}', "A_t2")
    A_t1 = Task(description="Produce note 1.", expected_output="JSON note.",
                agent=a1, output_pydantic=ToyNote)
    A_t2 = Task(description="Produce note 2.", expected_output="JSON note.",
                agent=a2, output_pydantic=ToyNote, context=[A_t1])
    Crew(agents=[a1, a2], tasks=[A_t1, A_t2], process=Process.sequential,
         verbose=False).kickoff()

    blob2 = CAPTURES["A_t2"]
    print("MARK_A present in Task 2 prompt      :", MARK_A in blob2)
    print("'context you're working with' header :", CTX_HEADER in blob2)
    print("Task 1 .raw appears verbatim         :", A_t1.output.raw in blob2)
    print("context window around the marker     :")
    print("  ", show_context_window(blob2, MARK_A))
    # is anything OTHER than task1.raw between the header and end?
    seg = blob2.split(CTX_HEADER, 1)[1] if CTX_HEADER in blob2 else ""
    print("segment after the header (repr)      :", repr(seg[:240]))

    # --------------- Experiment B — output_pydantic context ------------ #
    hr("EXPERIMENT B — what representation is passed for an output_pydantic task")
    b1 = agent_for('{"text": "beta", "count": 22}', "B_t1")
    b2 = agent_for('{"text": "downstream", "count": 1}', "B_t2")
    B_t1 = Task(description="Produce note 1.", expected_output="JSON note.",
                agent=b1, output_pydantic=ToyNote)
    B_t2 = Task(description="Produce note 2.", expected_output="JSON note.",
                agent=b2, output_pydantic=ToyNote, context=[B_t1])
    Crew(agents=[b1, b2], tasks=[B_t1, B_t2], process=Process.sequential,
         verbose=False).kickoff()

    blobB = CAPTURES["B_t2"]
    raw = B_t1.output.raw
    pyd_repr = repr(B_t1.output.pydantic)
    json_dict = B_t1.output.json_dict
    print("task1.output.raw                 :", repr(raw))
    print("task1.output.pydantic (repr)     :", pyd_repr)
    print("task1.output.json_dict           :", json_dict)
    print("--- in Task 2 prompt ---")
    print(".raw string present verbatim     :", raw in blobB)
    print("pydantic repr string present     :", pyd_repr in blobB)
    print("python-dict repr present         :", (str(json_dict) in blobB) if json_dict else "n/a")

    # ------------- Experiment C — callback + context ordering --------- #
    hr("EXPERIMENT C — callback completes before Task 2 builds/receives context")
    tmpdir = Path(tempfile.mkdtemp(prefix="spike_task_1_4_"))
    art = tmpdir / "c_callback.txt"
    C_BODY = "c-callback-body::MARK_C_5a1b"
    EVENTS.clear()

    def c_callback(to: TaskOutput):
        mark("C_callback_START")
        with open(art, "w") as fh:
            fh.write(C_BODY); fh.flush(); os.fsync(fh.fileno())
        time.sleep(0.15)
        mark("C_callback_FINISH")

    c_probe_res: dict[str, Any] = {}

    def c_probe(blob: str) -> None:
        c_probe_res["file_exists"] = art.exists()
        c_probe_res["file_body"] = art.read_text() if art.exists() else None
        c_probe_res["ctx_has_task1_raw"] = None  # filled after run (need t1.output)

    c1 = agent_for('{"text": "MARK_C_ctx_9d2e", "count": 33}', "C_t1")
    c2 = agent_for('{"text": "downstream", "count": 1}', "C_t2", probe=c_probe)
    C_t1 = Task(description="Produce note 1.", expected_output="JSON note.",
                agent=c1, output_pydantic=ToyNote, callback=c_callback)
    C_t2 = Task(description="Produce note 2.", expected_output="JSON note.",
                agent=c2, output_pydantic=ToyNote, context=[C_t1])
    Crew(agents=[c1, c2], tasks=[C_t1, C_t2], process=Process.sequential,
         verbose=False).kickoff()

    labels = [l for _, l in EVENTS]
    blobC = CAPTURES["C_t2"]
    print("event order:", labels)
    print("callback_FINISH before C_t2_llm_call :",
          labels.index("C_callback_FINISH") < labels.index("C_t2_llm_call"))
    print("callback side effect visible to T2   :", c_probe_res.get("file_exists"),
          "| body matches:", c_probe_res.get("file_body") == C_BODY)
    print("Task 1 .raw present in T2 context    :", C_t1.output.raw in blobC)

    # ------------- Experiment D — guardrail + context --------------- #
    hr("EXPERIMENT D — Task 2 must receive the FINAL (accepted) Task 1 output")

    def gd(to: TaskOutput):
        import json
        try:
            n = int(json.loads(to.raw).get("count", 0))
        except Exception:
            return (False, "not json")
        return (True, to.raw) if n >= 5 else (False, "count must be >= 5")

    d1 = agent_for(['{"text": "REJECTED_v1", "count": 1}',
                    '{"text": "ACCEPTED_v2", "count": 9}'], "D_t1")
    d2 = agent_for('{"text": "downstream", "count": 1}', "D_t2")
    D_t1 = Task(description="Produce note 1.", expected_output="JSON note.",
                agent=d1, output_pydantic=ToyNote, guardrail=gd, guardrail_max_retries=2)
    D_t2 = Task(description="Produce note 2.", expected_output="JSON note.",
                agent=d2, output_pydantic=ToyNote, context=[D_t1])
    Crew(agents=[d1, d2], tasks=[D_t1, D_t2], process=Process.sequential,
         verbose=False).kickoff()

    blobD = CAPTURES["D_t2"]
    print("D_t1.output.raw (final)          :", repr(D_t1.output.raw))
    print("'REJECTED_v1' leaked into T2 ctx :", "REJECTED_v1" in blobD)
    print("'ACCEPTED_v2' present in T2 ctx  :", "ACCEPTED_v2" in blobD)

    # ------------- Experiment E — multiple context tasks ----------- #
    hr("EXPERIMENT E — context=[t1, t2] ordering (list order vs rendered order)")

    def run_multi(order_label: str, ctx_order):
        e1 = agent_for('{"text": "E_ONE_aaa", "count": 1}', f"E_{order_label}_t1")
        e2 = agent_for('{"text": "E_TWO_bbb", "count": 2}', f"E_{order_label}_t2")
        e3 = agent_for('{"text": "downstream", "count": 3}', f"E_{order_label}_t3")
        T1 = Task(description="note1", expected_output="JSON", agent=e1, output_pydantic=ToyNote)
        T2 = Task(description="note2", expected_output="JSON", agent=e2, output_pydantic=ToyNote)
        ctx = [T1, T2] if ctx_order == "12" else [T2, T1]
        T3 = Task(description="note3", expected_output="JSON", agent=e3,
                  output_pydantic=ToyNote, context=ctx)
        Crew(agents=[e1, e2, e3], tasks=[T1, T2, T3], process=Process.sequential,
             verbose=False).kickoff()
        blob = CAPTURES[f"E_{order_label}_t3"]
        i1, i2 = blob.find("E_ONE_aaa"), blob.find("E_TWO_bbb")
        print(f"  context={ctx_order:>4}: both present={i1>=0 and i2>=0}  "
              f"pos(ONE)={i1} pos(TWO)={i2}  ONE_before_TWO={i1 < i2}")

    run_multi("12", "12")
    run_multi("21", "21")
    print("  => rendered order follows the list order passed to context=[...]")

    hr("DONE")
    try:
        art.unlink(missing_ok=True); tmpdir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
