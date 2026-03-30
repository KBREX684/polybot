-- Postgres + pgvector schema for GraphRAG
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    chunk_text TEXT NOT NULL,
    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_market_id ON doc_chunks (market_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_published_at ON doc_chunks (published_at DESC);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    label TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edges (
    id BIGSERIAL PRIMARY KEY,
    market_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('supports','contradicts','causes','time_precedes','depends_on')),
    signed_weight DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_edges_market_id ON edges (market_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges (relation);
