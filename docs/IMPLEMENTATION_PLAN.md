# Polymarket Bot v2 Implementation Plan

## Summary

This workspace implements a first executable version of a modular Polymarket bot with:

1. Market scout
2. Data collector
3. Hard filter
4. Generator (GPT-4o-mini)
5. Discriminator (GLM-4.7)
6. Risk engine (0.25 Kelly)
7. Paper execution
8. Decision logging

The design follows official `polymarket/agents` modular ideas while introducing stricter JSON contracts, dual-model roles, and GraphRAG-ready evidence interfaces.

## Defaults Locked

- Launch mode: paper trading only
- Holding horizon: 24h-14d
- Generator model: `gpt-4o-mini`
- Discriminator model: `glm-4.7`
- Position sizing: 0.25 Kelly
- GraphRAG storage target: Postgres + pgvector + relation tables

## First Execution Scope

- End-to-end single-cycle pipeline
- Strict output schema validation from both LLM stages
- Risk blocking before any execution
- JSONL decision audit trail
- SQL schema for GraphRAG tables
