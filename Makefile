# Harbor & Vale — Makefile (PROJECT_PLAN.md §T Phase 8 Internal Gate 8.12).
#
# Assumes a project-local .venv already exists with dependencies installed
# (python -m venv .venv && source .venv/bin/activate && pip install -r
# requirements.txt) — this Makefile never creates or modifies the
# environment, and never installs into Conda/Anaconda base or a global
# Python (.claude/rules/project-safety.md).
#
# PYTHONHASHSEED is exported here, not inside the Python scripts themselves
# — Python only honours it if it is set BEFORE the interpreter starts
# (config/settings.yaml's seeds.python_hash policy; §R.1).

PYTHON := .venv/bin/python
export PYTHONHASHSEED := 0

.PHONY: run validate replay demo-fail flow-diagram

run:            ## Normal end-to-end pipeline: raw data -> Crew 1 -> gate -> Crew 2 -> summary.
	$(PYTHON) scripts/run_pipeline.py

validate:       ## Gate-only: validate the existing on-disk artifacts/crew1/* without running either crew.
	$(PYTHON) scripts/run_pipeline.py --validate-only

replay:         ## Deterministic replay of stored, guardrail-accepted agent plans — zero LLM calls.
	$(PYTHON) scripts/run_pipeline.py --replay-plans

demo-fail:      ## Failure demo: inject the mandatory scale_change fault; the gate blocks Crew 2.
	$(PYTHON) scripts/run_pipeline.py --inject-failure scale_change

flow-diagram:   ## Regenerate docs/flow_diagram.html via the real flow.plot() API.
	$(PYTHON) scripts/generate_flow_diagram.py
