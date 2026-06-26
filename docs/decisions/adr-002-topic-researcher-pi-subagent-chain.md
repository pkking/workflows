# ADR-002: Topic Researcher as pi Subagent Chain

**Status**: Accepted  
**Date**: 2026-06-26

## Context / 背景

We needed to build a multi-agent workflow that:
- Analyzes specific technical questions
- Prioritizes high-confidence information from authoritative sources
- Uses tech community sources (HN, LinkedIn, X, Reddit, top blogs) rather than academic papers
- Outputs structured Markdown reports with evidence citations

The existing projects (yt-obsidian, repo-distiller) are Python sub-projects with CLI entry points, orchestrator code, and business logic. The question was whether to follow the same pattern or use a different implementation approach.

## Decision / 决策

Implement topic-researcher as a **pi subagent chain** rather than a Python sub-project.

The workflow consists of:
- 3 parallel searcher agents (each with different query angle strategies)
- 1 synthesizer agent that merges results and applies confidence rubric

Agent definitions live as pi subagent configuration files. No custom Python code, no CLI wrapper, no orchestrator logic.

## Trade-offs / 权衡

**Pros:**
- Zero infrastructure: uses pi's existing `parallel` and `chain` modes
- Built-in tools: `web_search` and `fetch_content` are pi-native, no custom search logic needed
- Minimal code: 4 agent prompt files vs. a full Python project with models, orchestrator, tests
- Easy to iterate: change prompts without rebuilding/reinstalling

**Cons:**
- Less suitable for batch processing (running multiple questions in sequence)
- No persistent state or caching between runs
- Harder to add complex pre/post-processing (e.g., search result deduplication, rate limiting)
- Users need pi installed and configured

## Alternatives Considered / 备选方案

1. **Python sub-project** (like yt-obsidian): Full CLI tool with orchestrator, models, and tests. Rejected because the workflow is simple enough that pi subagents handle it natively, and there's no complex business logic (no transcription, no AST parsing) that requires custom code.

2. **Hybrid approach** (Python CLI + pi SDK): Python entry point that calls pi subagents programmatically. Rejected as over-engineering for the current scope.

3. **Single agent with iterative search**: One agent that searches, evaluates, and synthesizes in a loop. Rejected because parallel searchers provide better coverage and reduce anchoring bias.

## Impact / 影响

- Implementation is 4 agent definition files + documentation
- No new Python package, no `pyproject.toml`, no installation
- Users invoke via pi's subagent system rather than a standalone CLI
- If requirements grow (batch processing, caching, complex filtering), can migrate to Python sub-project later
