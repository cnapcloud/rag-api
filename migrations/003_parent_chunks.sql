-- Parent-child chunking ancestor storage — docs/internal/design/parent-child-chunking.md §4.1
-- Self-referencing tree: chunk_id = "{doc_id}:{idx}" (idx = global counter across the whole
-- document, pipeline/steps/chunk.py _make_id_func). child_count=0 ancestors are never inserted
-- (filtered out before save_parent_chunks is called) — always >= 1, no ZeroDivisionError risk
-- in rag/retriever.py's auto-merge ratio calculation.
CREATE TABLE IF NOT EXISTS parent_chunks (
    chunk_id     TEXT         PRIMARY KEY,
    doc_id       TEXT         NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kb_id        TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    level        SMALLINT     NOT NULL,
    parent_id    TEXT         REFERENCES parent_chunks(chunk_id) ON DELETE CASCADE,
    chunk_index  INTEGER      NOT NULL,
    text         TEXT         NOT NULL,
    child_count  INTEGER      NOT NULL,
    page_num     INTEGER,
    page_label   TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parent_chunks_doc ON parent_chunks (doc_id);
CREATE INDEX IF NOT EXISTS idx_parent_chunks_parent ON parent_chunks (parent_id);
