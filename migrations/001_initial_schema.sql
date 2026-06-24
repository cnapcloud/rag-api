CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id        TEXT PRIMARY KEY,
    kb_name      TEXT NOT NULL DEFAULT '',
    tags         TEXT[] NOT NULL DEFAULT '{}',
    description  TEXT DEFAULT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_tags ON knowledge_bases USING GIN (tags);

-- connectors must be created before documents (documents.connector_id FK)
CREATE TABLE IF NOT EXISTS connectors (
    connector_id      TEXT         PRIMARY KEY,
    kb_id             TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    name              TEXT         NOT NULL,
    source_type       TEXT         NOT NULL,
    config            JSONB        NOT NULL DEFAULT '{}',
    sync_schedule     TEXT,
    schedule_enabled  BOOLEAN      NOT NULL DEFAULT false,
    sync_status       TEXT         NOT NULL DEFAULT 'idle',
    sync_started_at   TIMESTAMPTZ,
    last_synced_at    TIMESTAMPTZ,
    status            TEXT         NOT NULL DEFAULT 'active',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- status values: uploading | fetching | pending | running | indexed | deleting | deleted | failed
CREATE TABLE IF NOT EXISTS documents (
    doc_id              TEXT         PRIMARY KEY,
    kb_id               TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    source              TEXT         NOT NULL,
    source_type         TEXT         NOT NULL,
    source_uri          TEXT         NOT NULL,
    storage_key         TEXT,
    content_version     TEXT,
    connector_id        TEXT         REFERENCES connectors(connector_id) ON DELETE SET NULL,
    status              TEXT         NOT NULL DEFAULT 'pending',
    deleted_at          TIMESTAMPTZ,
    run_id              TEXT         NOT NULL DEFAULT '',
    error               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    process_started_at  TIMESTAMPTZ,
    process_finished_at TIMESTAMPTZ,
    chunk_count         INTEGER,
    file_size           BIGINT,
    doc_type            TEXT,
    embedding_model     TEXT,
    doc_created_at      TIMESTAMPTZ,
    title_hash          TEXT,
    content_simhash     BIGINT,
    UNIQUE(kb_id, source_uri)
);

CREATE INDEX IF NOT EXISTS idx_documents_content_version
    ON documents (kb_id, content_version) WHERE content_version IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_title_hash
    ON documents (kb_id, title_hash) WHERE title_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_connector
    ON documents (connector_id) WHERE connector_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (kb_id, status);

CREATE TABLE IF NOT EXISTS simhash_bands (
    band_id     TEXT     PRIMARY KEY,
    doc_id      TEXT     NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kb_id       TEXT     NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    band_index  SMALLINT NOT NULL,
    band_value  INTEGER  NOT NULL,
    UNIQUE(doc_id, band_index, band_value)
);

CREATE INDEX IF NOT EXISTS idx_simhash_bands_lsh
    ON simhash_bands (kb_id, band_index, band_value);
