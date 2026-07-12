# k8s 배포 매니페스트

Kubernetes(kustomize) 배포용 매니페스트 모음.

```
manifests/
  infra/    # 네임스페이스: infra — PostgreSQL(CNPG)/Redis/MinIO/Mailpit/Reloader
            # 기존 인프라를 재사용하면 배포하지 않아도 됨
  llm/      # 네임스페이스: llm — qdrant / dagster / rag-api(rag-admin 포함)
```

각 컴포넌트는 `kustomize/base` + `kustomize/overlays/<환경>` 구조와 자체 `Makefile`
(`preview` / `diff` / `apply` / `delete` / `namespace`)을 가진다.

자세한 설치 절차, 사전 준비, 환경 overlay 작성법, 시크릿 처리 방법은
[rag-delivery/install/03-install-k8s.md](../../rag-delivery/install/03-install-k8s.md) 참조.
