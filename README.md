# Polybot v2

Modular Polymarket trading bot scaffold with:

- Generator: `gpt-4o-mini`
- Discriminator: `glm-4.7`
- News source: `Serper API`
- Hard JSON contracts
- GraphRAG-ready evidence layer
- 0.25 Kelly risk sizing
- Paper execution only

## Quick Start

1. Create environment:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure `.env`:

```bash
copy .env.example .env
```

3. Run one cycle:

```bash
python run_bot.py --limit 20
```

3b. Run fixed interval loop:

```bash
python run_bot.py --loop --interval 900 --limit 20
```

4. Start warm dashboard UI:

```bash
python run_dashboard.py
```

Then open `http://127.0.0.1:2345`.

## Notes

- If model API keys are missing, the system falls back to deterministic mock LLM adapters so you can test the full pipeline locally.
- Execution is paper-only and writes to `logs/paper_trades.jsonl`.
- Set `SERPER_API_KEY` in `.env` to enable live news retrieval for GraphRAG evidence.
- Loop cycle summaries are written to `logs/cycles.jsonl`.
