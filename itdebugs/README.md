# ItDebugs

> Agentic debugging assistant for automatically investigating failing tests, tracing evidence, identifying root causes, and suggesting fixes.

## Problem

Debugging a failing test usually requires developers to manually:

1. Read the failure.
2. Find the relevant source files.
3. Trace the failing behavior.
4. Compare expected and actual behavior.
5. Identify the root cause.
6. Decide what code should change.
7. Re-run tests to verify the fix.

This becomes slower when a repository contains multiple related failures.

## Solution

**ItDebugs** automates this investigation workflow using an agentic pipeline.

ItDebugs:

- Runs the repository test suite.
- Detects failing tests.
- Groups related failures.
- Analyzes repository structure.
- Identifies relevant source files.
- Collects prioritized evidence.
- Determines the likely root cause.
- Uses IBM Granite for LLM-assisted reasoning.
- Validates the LLM result against deterministic repository evidence.
- Reports the exact source location and suggested fix.

## Architecture

```text
                ┌─────────────────────┐
                │      Developer      │
                │   / Investigate     │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │    Test Runner      │
                │ pytest / failures   │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  Failure Grouping   │
                │   Multi-bug mode    │
                └──────────┬──────────┘
                           │
                           ▼
             ┌────────────────────────────┐
             │     Agentic Pipeline       │
             │                            │
             │ Repository Analyst         │
             │ Test Analyst               │
             │ Code Analyst               │
             │ Evidence Agent             │
             │ Root Cause Agent            │
             │ Verification Agent         │
             └─────────────┬──────────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  Root Cause Report  │
                │ file + line + fix   │
                └─────────────────────┘