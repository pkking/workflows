# ADR-012: CI failure triage PoC

**Status**: Proposed
**Date**: 2026-11-24

## Context / 背景
CI duration reporting does not identify the failure domain or responsible team. A failed GitHub job must be investigated without executing its code or trusting its log text as instructions.

## Decision / 决策
Add an independent Python 3.10+ CLI, ci-triage, using GitHub REST metadata and job logs. Follow the existing ci-effective-report API approach; do not import its reporting or database layer. A versioned JSON rule catalog provides diagnostic signatures and candidate ownership. Rules return evidence line numbers and IDs; conflicting or unmatched rules produce UNKNOWN. Log evidence is untrusted and all suggestions are provisional, not verified root causes.

Use GitHub-hosted runners for PR regression tests and a daily bounded live sample of failed jobs in vllm-project/vllm-ascend. Manual dispatch accepts a single job URL. Public read API access is preferred; optionally configure a read-only CI_TRIAGE_TOKEN for cross-repository reads. No automatic reruns, upstream comments, or raw log persistence. Publish only structured reports, without raw log lines or uncontrolled metadata.

## Trade-offs / 权衡
Deterministic rules are cheap, testable and auditable but cannot resolve ambiguous symptoms. A daily rolling sample is not exhaustive and is not an accuracy benchmark. API availability, log retention and token scope can limit coverage. No cluster telemetry in the PoC; candidate attribution cannot establish actual responsibility.

## Alternatives Considered / 备选方案
- LLM-only classifier: weaker reproducibility and additional cost/privacy risks.
- HolmesGPT: defer until multi-source investigation is needed.
- Permanent webhook service: unnecessary operational overhead for PoC.

## Impact / 影响
New rules can be added without engine code changes; new evidence sources can implement the analyzer contract. Regression fixtures must accompany new rules. Before production, validate on independently labeled real jobs and add ARC/K8s/Prometheus correlation.
