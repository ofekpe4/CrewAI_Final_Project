"""
Phase 1 · Task 1.2 — Technical spike: CrewAI 1.15.20 `guardrail` + retry behaviour.

DISPOSABLE SPIKE — delete once the conclusion is recorded in docs/architecture.md.
Sibling of spike/task_1_1_output_pydantic.py; that file is left untouched.

No Harbor & Vale agents, no dataset, no Crew 1 / Crew 2 / gate / Flow.
No real LLM, no network, no API key: a deterministic scripted `crewai.BaseLLM`
subclass returns canned strings while the *real* Task/Crew guardrail+retry code
path runs.

Run:  python spike/task_1_2_guardrail_retry.py

Answers, with runtime evidence against the pinned version:
  1. Does Task(guardrail=...) exist and work?
  2. Exact guardrail input type + return contract.
  3. Does (False, "msg") trigger a retry, and does the msg reach the retry?
  4. Authoritative retry field / default / deprecation of `max_retries`.
  5. Total attempts for a configured retry value.
  6. Guardrail eventually passes / never passes.
  7. How `guardrail` composes with `output_pydantic`, and the real ordering of
     pydantic validation vs guardrail vs retry.
"""

import os

# NOTE: deliberately NO `from __future__ import annotations` here — see Experiment E.
# With it, an annotated guardrail return type (`-> tuple[bool, Any]`) becomes the
# *string* 'tuple[bool, Any]' and CrewAI's `validate_guardrail_function` rejects it.

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import warnings
from typing import Any

from pydantic import BaseModel, ValidationError

import crewai
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM


# --------------------------------------------------------------------------- #
class ToyNote(BaseModel):
    text: str
    count: int


FEEDBACK_MARKER = "Previous attempt failed validation"


class ScriptedLLM(BaseLLM):
    """Returns canned strings in order; repeats the last once exhausted.
    Records, per call, whether the guardrail-feedback marker was in the prompt.
    """

    responses: list[str] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, responses: list[str], **kwargs: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kwargs)
        self.responses = list(responses)
        self.calls = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kwargs) -> str:
        if isinstance(messages, str):
            blob = messages
        else:
            blob = "\n".join(
                m.get("content", "") if isinstance(m, dict) else str(m)
                for m in messages
            )
        idx = len(self.calls)
        resp = self.responses[idx] if idx < len(self.responses) else self.responses[-1]
        self.calls.append({"feedback_in_prompt": FEEDBACK_MARKER in blob, "returned": resp})
        return resp

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def make_task(responses, *, guardrail=None, output_pydantic=ToyNote,
              guardrail_max_retries=None, max_retries=None):
    llm = ScriptedLLM(responses)
    agent = Agent(role="Toy Reporter", goal="Emit a tiny structured note.",
                  backstory="Disposable spike agent.", llm=llm, verbose=False,
                  allow_delegation=False)
    kw: dict[str, Any] = dict(
        description="Return a short text and an integer count.",
        expected_output="JSON object with keys 'text' (string) and 'count' (integer).",
        agent=agent,
    )
    if output_pydantic is not None:
        kw["output_pydantic"] = output_pydantic
    if guardrail is not None:
        kw["guardrail"] = guardrail
    if guardrail_max_retries is not None:
        kw["guardrail_max_retries"] = guardrail_max_retries
    if max_retries is not None:
        kw["max_retries"] = max_retries
    task = Task(**kw)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return crew, task, llm


def hr(t: str) -> None:
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


# --------------------------------------------------------------------------- #
def main() -> None:
    hr("ENVIRONMENT / API INSPECTION")
    print("crewai.__version__            :", crewai.__version__)
    f = Task.model_fields
    print("has 'guardrail' field        :", "guardrail" in f)
    print("guardrail annotation         :", f["guardrail"].annotation)
    print("guardrails (plural) present  :", "guardrails" in f)
    print("max_retries default / desc   :", f["max_retries"].default, "|", f["max_retries"].description)
    print("guardrail_max_retries def    :", f["guardrail_max_retries"].default, "|",
          f["guardrail_max_retries"].description)
    print("retry_count default          :", f["retry_count"].default)

    # ---------------- Experiment A — fail once, then pass ----------------- #
    hr("EXPERIMENT A — guardrail fails once, then passes  (guardrail_max_retries=2)")

    a_seen: list[dict[str, Any]] = []

    def guardrail_a(out) -> tuple[bool, Any]:
        a_seen.append({"type": type(out).__name__, "pydantic": repr(out.pydantic),
                       "raw": out.raw})
        try:
            data = __import__("json").loads(out.raw)
        except Exception:
            return (False, "output was not JSON")
        if int(data.get("count", 0)) < 2:
            return (False, "count must be >= 2; you returned %s" % data.get("count"))
        return (True, out.raw)

    crew_a, task_a, llm_a = make_task(
        ['{"text": "bad", "count": 1}', '{"text": "good", "count": 2}'],
        guardrail=guardrail_a, guardrail_max_retries=2,
    )
    try:
        out_a = crew_a.kickoff()
        print("kickoff completed            : YES")
        print("guardrail evaluations        :", len(a_seen))
        print("LLM calls                    :", len(llm_a.calls))
        for i, c in enumerate(llm_a.calls):
            print(f"  LLM call {i}: feedback_in_prompt={c['feedback_in_prompt']}  returned={c['returned']}")
        print("guardrail-call snapshots     :")
        for i, s in enumerate(a_seen):
            print(f"  eval {i}: {s}")
        print("final crew_output.pydantic   :", repr(out_a.pydantic))
        print("final task.output.pydantic   :", repr(task_a.output.pydantic))
        print("task.retry_count             :", task_a.retry_count)
    except Exception as e:  # noqa: BLE001
        print("A RAISED:", type(e).__module__ + "." + type(e).__name__, "->", str(e)[:400])

    # ------------------- Experiment B — never passes --------------------- #
    hr("EXPERIMENT B — guardrail always rejects  (guardrail_max_retries=2)")
    b_evals = {"n": 0}

    def guardrail_b(out) -> tuple[bool, Any]:
        b_evals["n"] += 1
        return (False, "always rejected")

    crew_b, task_b, llm_b = make_task(
        ['{"text": "x", "count": 1}'], guardrail=guardrail_b, guardrail_max_retries=2,
    )
    try:
        out_b = crew_b.kickoff()
        print("kickoff completed (no raise) : YES  <-- unexpected")
        print("crew_output.pydantic         :", repr(out_b.pydantic))
    except ValidationError as e:
        print("B RAISED pydantic.ValidationError:", e.errors())
    except Exception as e:  # noqa: BLE001
        print("B RAISED                     :", type(e).__module__ + "." + type(e).__name__)
        print("  message                    :", str(e)[:400])
    print("guardrail evaluations        :", b_evals["n"])
    print("LLM calls                    :", len(llm_b.calls))
    print("task.output (escaped?)       :", getattr(task_b, "output", None))

    # ------------- Experiment C — retry parameter authority ------------- #
    hr("EXPERIMENT C — retry configuration")

    def always_fail(out) -> tuple[bool, Any]:
        return (False, "nope")

    # C1: no retry param -> default
    c1_evals = {"n": 0}

    def gf_c1(out):
        c1_evals["n"] += 1
        return (False, "nope")

    crew_c1, task_c1, llm_c1 = make_task(['{"text": "x", "count": 1}'], guardrail=gf_c1)
    print("C1 default guardrail_max_retries on task:", task_c1.guardrail_max_retries)
    try:
        crew_c1.kickoff()
    except Exception as e:  # noqa: BLE001
        print("C1 raised:", type(e).__name__, "->", str(e)[:200])
    print("C1 guardrail evaluations     :", c1_evals["n"], " | LLM calls:", len(llm_c1.calls))

    # C2: deprecated max_retries -> warning + mapped onto guardrail_max_retries
    c2_evals = {"n": 0}

    def gf_c2(out):
        c2_evals["n"] += 1
        return (False, "nope")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        crew_c2, task_c2, llm_c2 = make_task(
            ['{"text": "x", "count": 1}'], guardrail=gf_c2, max_retries=1,
        )
    all_dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    mr_dep = [w for w in all_dep if "max_retries" in str(w.message)]
    print("C2 all DeprecationWarnings   :", [str(w.message)[:80] for w in all_dep])
    print("C2 max_retries deprecation   :", bool(mr_dep),
          "->", (str(mr_dep[0].message) if mr_dep else None))
    print("C2 task.max_retries          :", task_c2.max_retries)
    print("C2 task.guardrail_max_retries :", task_c2.guardrail_max_retries, "(mapped from max_retries)")
    try:
        crew_c2.kickoff()
    except Exception as e:  # noqa: BLE001
        print("C2 raised:", type(e).__name__, "->", str(e)[:200])
    print("C2 guardrail evaluations     :", c2_evals["n"], " | LLM calls:", len(llm_c2.calls))

    # ---------- Experiment D — guardrail + output_pydantic order -------- #
    hr("EXPERIMENT D-A — structurally VALID pydantic, guardrail rejects once then accepts")
    da_snap: list[dict[str, Any]] = []

    def guardrail_da(out) -> tuple[bool, Any]:
        da_snap.append({"type": type(out).__name__,
                        "pydantic_is_None": out.pydantic is None,
                        "pydantic": repr(out.pydantic), "raw": out.raw})
        if len(da_snap) == 1:
            return (False, "reject the first structurally-valid output on purpose")
        return (True, out.raw)

    crew_da, task_da, llm_da = make_task(
        ['{"text": "v1", "count": 5}', '{"text": "v2", "count": 9}'],
        guardrail=guardrail_da, guardrail_max_retries=2,
    )
    try:
        out_da = crew_da.kickoff()
        for i, s in enumerate(da_snap):
            print(f"  guardrail eval {i}: {s}")
        print("final .pydantic              :", repr(out_da.pydantic))
    except Exception as e:  # noqa: BLE001
        print("D-A RAISED:", type(e).__name__, "->", str(e)[:300])

    hr("EXPERIMENT D-B1 — structurally INVALID pydantic, guardrail ACCEPTS it")
    db1_snap: list[dict[str, Any]] = []

    def guardrail_db1(out) -> tuple[bool, Any]:
        db1_snap.append({"pydantic_is_None": out.pydantic is None, "raw": out.raw})
        return (True, out.raw)  # guardrail approves; schema is still broken

    crew_db1, task_db1, llm_db1 = make_task(
        ['{"text": "x", "count": "NaN"}'], guardrail=guardrail_db1, guardrail_max_retries=2,
    )
    try:
        out_db1 = crew_db1.kickoff()
        print("kickoff completed (no raise) : YES")
        print("  .pydantic                  :", repr(out_db1.pydantic))
        print("  .raw                       :", repr(out_db1.raw))
    except ValidationError as e:
        print("D-B1 RAISED pydantic.ValidationError AFTER guardrail passed:")
        print("  errors                     :", e.errors())
    except Exception as e:  # noqa: BLE001
        print("D-B1 RAISED                  :", type(e).__module__ + "." + type(e).__name__, "->", str(e)[:300])
    print("  guardrail evaluations        :", len(db1_snap), "->", db1_snap)

    hr("EXPERIMENT D-B2 — invalid first, guardrail REJECTS, retry returns valid")
    db2_snap: list[dict[str, Any]] = []

    def guardrail_db2(out) -> tuple[bool, Any]:
        db2_snap.append({"pydantic_is_None": out.pydantic is None, "raw": out.raw})
        if '"NaN"' in out.raw:
            return (False, "count is not a number")
        return (True, out.raw)

    crew_db2, task_db2, llm_db2 = make_task(
        ['{"text": "x", "count": "NaN"}', '{"text": "ok", "count": 3}'],
        guardrail=guardrail_db2, guardrail_max_retries=2,
    )
    try:
        out_db2 = crew_db2.kickoff()
        print("kickoff completed            : YES")
        for i, s in enumerate(db2_snap):
            print(f"  guardrail eval {i}: {s}")
        print("  final .pydantic            :", repr(out_db2.pydantic))
    except Exception as e:  # noqa: BLE001
        print("D-B2 RAISED                  :", type(e).__module__ + "." + type(e).__name__, "->", str(e)[:300])

    hr("EXPERIMENT D-B3 — invalid first, guardrail REJECTS, ALL retries stay invalid")
    db3_snap: list[dict[str, Any]] = []

    def guardrail_db3(out) -> tuple[bool, Any]:
        db3_snap.append({"raw": out.raw})
        return (False, "still not a number")

    crew_db3, task_db3, llm_db3 = make_task(
        ['{"text": "x", "count": "NaN"}'], guardrail=guardrail_db3, guardrail_max_retries=2,
    )
    try:
        crew_db3.kickoff()
        print("kickoff completed (no raise) : YES  <-- unexpected")
    except ValidationError as e:
        print("D-B3 RAISED pydantic.ValidationError mid-retry-loop:", e.errors())
    except Exception as e:  # noqa: BLE001
        print("D-B3 RAISED                  :", type(e).__module__ + "." + type(e).__name__, "->", str(e)[:300])
    print("  guardrail evaluations        :", len(db3_snap), " | LLM calls:", len(llm_db3.calls))

    # ---------- Experiment E — `from __future__ import annotations` gotcha ---------- #
    hr("EXPERIMENT E — annotated guardrail return type under PEP 563 (string annotations)")
    from typing import Any as _Any

    def g_plain(out) -> tuple[bool, _Any]:
        return (True, out.raw)

    # Simulate what `from __future__ import annotations` would do: a string annotation.
    def g_stringized(out):
        return (True, out.raw)
    g_stringized.__annotations__ = {"return": "tuple[bool, Any]"}

    for label, fn in [("real annotation object", g_plain), ("stringized annotation", g_stringized)]:
        try:
            _c, _t, _l = make_task(['{"text": "x", "count": 1}'], guardrail=fn)
            print(f"  {label:24}: accepted by Task(guardrail=...)")
        except Exception as e:  # noqa: BLE001
            print(f"  {label:24}: REJECTED -> {type(e).__name__}: {str(e).splitlines()[0][:120]}")

    hr("DONE")


if __name__ == "__main__":
    main()
