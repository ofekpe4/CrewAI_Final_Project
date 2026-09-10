"""
Phase 1 · Task 1.6 — Technical spike: CrewAI 1.15.20 Flow / @router / or_ / and_.

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
Sibling of task_1_1..task_1_5 spike files (all untouched).

Verifies the Flow mechanisms PROJECT_PLAN.md §H depends on:
  Flow, Flow[StateModel], @start, @listen, @router, or_, and_, kickoff(),
  and calling Crew.kickoff(inputs=...) from inside a Flow method.

No production Harbor & Vale Flow. Scripted crewai.BaseLLM, no network, no key.

Run:  python spike/task_1_6_flow_router.py
"""

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import traceback
from typing import Any

from pydantic import BaseModel

import crewai
from crewai import Agent, Crew, Process, Task
from crewai.flow.flow import Flow, and_, listen, or_, router, start
from crewai.llms.base_llm import BaseLLM


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


class ScriptedLLM(BaseLLM):
    canned: str = ""
    seen: list[str] = []

    def __init__(self, canned: str, **kw: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kw)
        self.canned = canned
        self.seen = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kw) -> str:
        blob = messages if isinstance(messages, str) else "\n".join(
            (m.get("content", "") if isinstance(m, dict) else str(m)) for m in messages
        )
        self.seen.append(blob)
        return self.canned

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


# --------------------------------------------------------------------------- #
def main() -> None:
    hr("ENVIRONMENT / API INSPECTION")
    print("crewai.__version__ :", crewai.__version__)
    print("imports OK         : Flow, Flow[State], @start, @listen, @router, or_, and_")
    print("Flow.kickoff sig   : kickoff(self, inputs=None, input_files=None, ...)")
    print("@router            : returns a string label; @listen('LABEL') consumes it")

    # ---------------- Experiment A — typed state model ---------------- #
    hr("EXPERIMENT A — Flow[StateModel]: typed, mutable, observable")

    class StateA(BaseModel):
        counter: int = 0
        trail: list[str] = []
        seed_value: str = ""

    class FlowA(Flow[StateA]):
        @start()
        def seed(self):
            self.state.counter += 1
            self.state.trail.append("seed")
            return "seed-return"

        @listen(seed)
        def bump(self):
            self.state.counter += 10
            self.state.trail.append("bump")
            return f"counter={self.state.counter}"

    fa = FlowA()
    resA = fa.kickoff(inputs={"seed_value": "INJECTED_A"})
    print("kickoff() return       :", repr(resA))
    print("flow.state.counter     :", fa.state.counter, "(expected 11)")
    print("flow.state.trail       :", fa.state.trail)
    print("flow.state.seed_value  :", repr(fa.state.seed_value), "(inputs merged into state)")
    print("type(flow.state)       :", type(fa.state).__name__,
          "| MRO:", [c.__name__ for c in type(fa.state).__mro__])
    print("isinstance(state, StateA):", isinstance(fa.state, StateA),
          "(Flow wraps the model as StateWithId(FlowState, StateA) + an `id` field)")

    # ---------------- Experiment B — start -> listen -> listen -------- #
    hr("EXPERIMENT B — @start -> @listen -> @listen ordering")
    EVB: list[str] = []

    class FlowB(Flow[StateA]):
        @start()
        def n1(self):
            EVB.append("n1")

        @listen(n1)
        def n2(self):
            EVB.append("n2")

        @listen(n2)
        def n3(self):
            EVB.append("n3")

    FlowB().kickoff()
    print("event order :", EVB, "| deterministic [n1,n2,n3]:", EVB == ["n1", "n2", "n3"])

    # ---------------- Experiment C — @router ------------------------- #
    hr("EXPERIMENT C — @router with two routes; only the matched listener runs")

    class StateC(BaseModel):
        which: str = "A"
        ran: list[str] = []

    class FlowC(Flow[StateC]):
        @start()
        def begin(self):
            self.state.ran.append("begin")

        @router(begin)
        def route(self):
            return "ROUTE_A" if self.state.which == "A" else "ROUTE_B"

        @listen("ROUTE_A")
        def on_a(self):
            self.state.ran.append("on_a")

        @listen("ROUTE_B")
        def on_b(self):
            self.state.ran.append("on_b")

    fc_a = FlowC()
    fc_a.kickoff(inputs={"which": "A"})
    fc_b = FlowC()
    fc_b.kickoff(inputs={"which": "B"})
    print("which=A -> ran :", fc_a.state.ran, "| only on_a:", fc_a.state.ran == ["begin", "on_a"])
    print("which=B -> ran :", fc_b.state.ran, "| only on_b:", fc_b.state.ran == ["begin", "on_b"])
    print("router return type: str label (consumed by @listen('LABEL'))")

    # ---------------- Experiment D — or_ / and_ --------------------- #
    hr("EXPERIMENT D — or_ / and_ trigger semantics")
    EVD_OR: list[str] = []

    class FlowOr(Flow[StateA]):
        @start()
        def p1(self):
            EVD_OR.append("p1")

        @start()
        def p2(self):
            EVD_OR.append("p2")

        @listen(or_(p1, p2))
        def joined_or(self):
            EVD_OR.append("joined_or")

    FlowOr().kickoff()
    print("or_  events :", EVD_OR)
    print("  -> joined_or fired", EVD_OR.count("joined_or"),
          "time(s) (fires when the FIRST trigger completes; not re-fired for the 2nd)")

    EVD_AND: list[str] = []

    class FlowAnd(Flow[StateA]):
        @start()
        def q1(self):
            EVD_AND.append("q1")

        @start()
        def q2(self):
            EVD_AND.append("q2")

        @listen(and_(q1, q2))
        def joined_and(self):
            EVD_AND.append("joined_and")

    FlowAnd().kickoff()
    print("and_ events :", EVD_AND)
    print("  -> joined_and fired", EVD_AND.count("joined_and"),
          "time(s) (only after ALL triggers)")

    # ---------------- Experiment E — Crew.kickoff from a Flow -------- #
    hr("EXPERIMENT E — Crew.kickoff(inputs=...) called inside a Flow method")

    class StateE(BaseModel):
        topic: str = ""
        crew_said: str = ""
        after: bool = False

    def build_crew():
        llm = ScriptedLLM('{"echo": "handled"}')
        ag = Agent(role="Toy", goal="Echo the topic {topic}.",
                   backstory="Disposable.", llm=llm, verbose=False,
                   allow_delegation=False)
        tk = Task(description="Work on topic: {topic}.",
                  expected_output="A short JSON object.", agent=ag)
        return Crew(agents=[ag], tasks=[tk], process=Process.sequential,
                    verbose=False), llm

    class FlowE(Flow[StateE]):
        @start()
        def run_crew(self):
            crew, llm = build_crew()
            out = crew.kickoff(inputs={"topic": self.state.topic})
            self.state.crew_said = str(out)
            # did the interpolated input reach the crew prompt?
            self._topic_in_prompt = any(self.state.topic in s for s in llm.seen)
            return "crew-done"

        @listen(run_crew)
        def after_crew(self):
            self.state.after = True
            return "flow-continued"

    fe = FlowE()
    resE = fe.kickoff(inputs={"topic": "SPIKE_TOPIC_42"})
    print("kickoff() return        :", repr(resE))
    print("crew returned to Flow    :", repr(fe.state.crew_said[:80]))
    print("inputs reached the Crew  :", getattr(fe, "_topic_in_prompt", None))
    print("Flow continued after crew:", fe.state.after)

    # ---------------- Experiment F — unknown route / raising node --- #
    hr("EXPERIMENT F — router emits an unlistened label / a node raises")

    class StateF(BaseModel):
        ran: list[str] = []

    class FlowUnknown(Flow[StateF]):
        @start()
        def begin(self):
            self.state.ran.append("begin")

        @router(begin)
        def route(self):
            return "NOBODY_LISTENS_HERE"

        @listen("SOME_OTHER_LABEL")
        def never(self):
            self.state.ran.append("never")

    try:
        fu = FlowUnknown()
        rf = fu.kickoff()
        print("unknown route: kickoff returned", repr(rf), "| state.ran:", fu.state.ran,
              "| downstream ran:", "never" in fu.state.ran)
    except Exception as e:  # noqa: BLE001
        print("unknown route: RAISED", type(e).__name__, "->", str(e)[:200])

    class FlowRaise(Flow[StateF]):
        @start()
        def boom(self):
            self.state.ran.append("boom")
            raise RuntimeError("intentional flow-node failure (spike)")

        @listen(boom)
        def after(self):
            self.state.ran.append("after")

    try:
        frr = FlowRaise()
        frr.kickoff()
        print("raising node: NO exception  <-- unexpected | state.ran:", frr.state.ran)
    except Exception as e:  # noqa: BLE001
        print("raising node: propagated", type(e).__module__ + "." + type(e).__name__,
              "->", str(e)[:160])
        print("  downstream 'after' ran:", "after" in frr.state.ran)

    hr("DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
