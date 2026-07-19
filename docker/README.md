# docker 배포 (docker-compose)

단일 호스트 평가용 docker-compose 배포 구성.

```
docker-compose.yml   # 전체 서비스 정의 (rag-api, rag-admin, dagster, qdrant, postgres, redis, minio 등)
settings.yaml         # rag-api Settings (embedding/chunking/retrieval/knowledge_bases 등)
.env                  # MinIO/Redis/Postgres 자격증명 (로컬 평가용 placeholder 값)
init-db.sql           # Postgres 초기 계정/DB 생성
dagster.yaml          # Dagster 인스턴스 설정
workspace.yaml        # Dagster workspace (code location 등록)
```

기동, 설정 값 교체, 문서 인덱싱·검색 확인 절차는 저장소 루트 [README.md](../README.md)의
"시작" 절 참조.

자세한 설치 절차와 사전 준비는
[rag-docs/docs/install/02-quickstart.md](../../rag-docs/docs/install/02-quickstart.md) 참조.
