CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id        TEXT PRIMARY KEY,
    kb_name      TEXT NOT NULL DEFAULT '',
    tags         TEXT[] NOT NULL DEFAULT '{}',
    description  TEXT DEFAULT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_tags ON knowledge_bases USING GIN (tags);

CREATE TABLE IF NOT EXISTS documents (
    kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    doc_source       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'running',
    etag             TEXT,
    run_id           TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chunk_count      INTEGER,
    file_size        BIGINT,
    doc_type         TEXT,
    embedding_model  TEXT,
    error            TEXT,
    doc_created_at   TIMESTAMPTZ,
    title_hash       TEXT,
    content_simhash  BIGINT,
    PRIMARY KEY (kb_id, doc_source)
);

CREATE INDEX IF NOT EXISTS idx_documents_etag
    ON documents (kb_id, etag) WHERE etag IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_documents_title_hash
    ON documents (kb_id, title_hash) WHERE title_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS simhash_bands (
    kb_id        TEXT     NOT NULL,
    band_index   SMALLINT NOT NULL,
    band_value   INTEGER  NOT NULL,
    doc_source   TEXT     NOT NULL,
    PRIMARY KEY (kb_id, band_index, band_value, doc_source),
    FOREIGN KEY (kb_id, doc_source)
        REFERENCES documents(kb_id, doc_source) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_simhash_bands
    ON simhash_bands (kb_id, band_index, band_value);
