-- KB별 설정 오버라이드 — docs/internal/design/kb-settings-override.md
-- key는 dot-notation Settings 필드 경로(예: "ingestion.max_file_size_mb"), allow-list/deny-list
-- 검증은 애플리케이션 레벨(config/settings.py: validate_override_key)에서 수행한다.
CREATE TABLE IF NOT EXISTS kb_settings_overrides (
    kb_id       TEXT        NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    key         TEXT        NOT NULL,
    value       JSONB       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (kb_id, key)
);
