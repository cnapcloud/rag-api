---
name: reference-aiops-repo
description: aiops 저장소 위치와 rag-api 관련 인프라(CNPG, MinIO, Qdrant, rag-api 배포)가 있는 경로
metadata:
  type: reference
---

aiops 저장소는 `/Users/lemon/Devel/ai/aiops` — 이 세션의 기본 작업 디렉토리 목록엔 없지만
Read/Bash로 직접 접근 가능하다. kubectl 컨텍스트는 k3s, 관련 네임스페이스는 `infra`/`llm`.

- Postgres(CNPG): `aiops/infra/cnpg/cluster/kustomize/` — 클러스터 spec에 `enableSuperuserAccess: false`,
  `instances: 1`. `rag-api`/`dagster`/`langfuse` 롤·DB는 `postInitSQL`로 생성, `CREATEDB` 권한 없음.
- MinIO: `aiops/infra/minio/kustomize/` — standalone 단일 PVC. 버킷 초기화는
  `resources/minio-init-job.yaml`의 `mc mb` 목록.
- Qdrant: `aiops/llm/qdrant/kustomize/` — `llm` ns, 3 replica, `snapshotPersistence` 활성화.
- rag-api 배포: `aiops/llm/rag-api/kustomize/` — 실제 `rag-api` k8s Service는 `rag-ent-api`
  이미지(OIDC 인증 래퍼)를 쓴다. 순수 rag-api HTTP 서버는 별도로 떠 있지 않음 — API를
  인증 없이 테스트하려면 `kubectl exec`로 파드 안에서 직접 파이썬 호출해야 하는데, 이건
  실제 인증 경로를 검증하지 못하므로 권장하지 않음. Keycloak(`keycloak.cnapcloud.com`)에서
  ROPC 그랜트로 토큰 발급받아 API를 그대로 호출하는 쪽이 맞다.
- 각 컴포넌트 디렉토리에 `Makefile`(`preview`/`apply`/`delete`)이 있고, `apply`는
  `kustomize build --enable-alpha-plugins <overlay> | kubectl apply --force-conflicts --server-side=true -f -`.
  SOPS로 암호화된 시크릿을 생성하는 오버레이가 많아 `--enable-alpha-plugins` 없이는 빌드 안 됨.
