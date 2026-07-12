---
name: pg-restore-schema-remap-pitfall
description: pg_dump/pg_restore 산출물을 같은 DB의 다른 스키마로 비파괴적 복원할 때 겪는 3가지 함정
metadata:
  type: feedback
---

**`SET search_path`는 안 통한다**: pg_dump/pg_restore가 만드는 SQL은 테이블·시퀀스를
`CREATE TABLE public.foo`처럼 항상 스키마로 명시 한정(qualify)해서 출력한다. 복원 전에
`SET search_path TO other_schema;`를 붙여도 무시되고 원래 스키마(`public`)에 그대로
생성/충돌한다.

**Why:** 백업·복구 리허설(2026-07-11, rag-ent-api 05-backup-plan.md)에서 임시 스키마
비파괴적 복원을 시도하다가 `relation "connectors" already exists` 에러로 발견. `public.X`를
쓰는 CREATE TABLE/SEQUENCE 뿐 아니라 COPY, DEFAULT nextval(), FK REFERENCES까지 전부
스키마가 박혀 있었음.

**How to apply:** 검증용으로 다른 스키마에 복원하려면, SQL 텍스트에서
`CREATE TABLE public\.X` / `CREATE SEQUENCE public\.X` 패턴으로 뽑은 객체 이름만 화이트리스트로
`public.X` → `target_schema.X` sed 치환한다. **전체를 일괄 치환하지 말 것** — pg_trgm 같은
확장이 제공하는 연산자 클래스(`public.gin_trgm_ops` 등)까지 잘못 바뀌어 "operator class ...
does not exist" 에러가 난다. 확장은 원래 설치된 스키마(보통 `public`)를 그대로 가리켜야 함.

**`--no-owner`만으로는 코멘트가 안 걸러진다**: `pg_restore --no-owner --no-privileges -f`로
평문 SQL을 뽑아도 `COMMENT ON SCHEMA public IS '';`는 그대로 남는다. 이 문장은 스키마
소유자만 실행 가능해서 소유자가 아닌 롤(예: 애플리케이션 DB 롤)로 복원하면
"must be owner of schema public" 에러가 난다. `--no-comments` 플래그를 반드시 추가하거나,
해당 라인을 grep -v로 걸러야 한다.
