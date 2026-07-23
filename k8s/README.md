# rag-api Helm chart

Umbrella Helm chart for the whole stack. `rag-api`/`rag-admin` are this chart's own
templates; everything else is a dependency.

```
k8s/
  README.md
  values.yaml.example      # copy to values.yaml (gitignored) and fill in — secrets override
  helm/
    Chart.yaml              # this chart's own metadata + dependency list
    values.yaml             # the single environment currently deployed — base/parent values
    templates/               # rag-api + rag-admin resources
    charts/
      cnpg-cluster/           # local subchart — Cluster CR + backup/restore CronJobs
      minio-jobs/             # local subchart — bucket bootstrap Job + mirror CronJob
      ollama/                 # local subchart — Service + EndpointSlice to an external Ollama host
      *.tgz                   # fetched by `helm dependency update`, gitignored
```

## Dependencies

| alias | source | purpose |
|---|---|---|
| `cnpg-cluster` | local (`charts/cnpg-cluster`) | Postgres `Cluster` CR, backup/restore CronJobs |
| `minio-jobs` | local (`charts/minio-jobs`) | bucket bootstrap Job, backup-mirror CronJob |
| `ollama` | local (`charts/ollama`) | Service/EndpointSlice pointing at an external Ollama host |
| `cnpg-operator` (chart: `cloudnative-pg`) | `https://cloudnative-pg.github.io/charts` | CNPG operator — `enabled: false` always, install separately (see Prerequisites) |
| `redis-ha` | `https://dandydeveloper.github.io/charts` | ingest/delete event queue |
| `minio` | `https://charts.min.io` | S3-compatible document storage |
| `mailpit` | `https://jouve.github.io/charts` | dev SMTP catcher |
| `reloader` | `https://stakater.github.io/stakater-charts` | restarts pods on ConfigMap/Secret change |
| `qdrant` | `https://qdrant.github.io/qdrant-helm` | vector DB |
| `dagster` | `https://dagster-io.github.io/helm` | pipeline orchestration |

Toggle any of these off (`<alias>.enabled: false`) to reuse infra that's already deployed
elsewhere instead of installing it again.

Everything installs into a single namespace (`--namespace rag`).

## Platform requirements (arm64 / Apple Silicon)

1. **Image**: this chart's own images (`rag-api`, `rag-admin`) are built for arm64.

2. **Parsing**: depends on `onnxruntime` correctly detecting the host CPU's features.
   - Running the cluster on a Mac inside a VM: use **UTM** with the **Apple
     Virtualization** backend, not Multipass. UTM's Apple Virtualization framework passes
     Apple Silicon CPU capabilities through to the guest VM, letting `onnxruntime` detect
     CPU features correctly — this eliminates the `SIGILL` crash (and the related
     document-loader `SIGKILL`) seen under other virtualization backends.
   - At least one node needs the `node-role.kubernetes.io/onnx` label
     (`kubectl label node <node> node-role.kubernetes.io/onnx=`) so the ingest pipeline's
     parsing pods get scheduled there (see the `runLauncher` node affinity in
     `helm/values.yaml`).

3. **Embedding** (when using Ollama): set Ollama's address via `ollama.externalIP` in
   `helm/values.yaml`.

## Prerequisites

**`cnpg-operator` is not a dependency of this chart at all.** Install it separately, once
per cluster, before installing this chart:

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm install cnpg-operator cnpg/cloudnative-pg -n cnpg-system --create-namespace
```

If the `Cluster` CR is deployed in the same release before the operator is fully up, CR
creation fails (no webhook yet) and the whole install fails. `--atomic` tears down the
entire release on failure, including the operator Deployment itself. So the operator must
always be installed as a separate release first.

Note: `--atomic` makes Helm clean up any partially-created resources on failure, leaving a
clean state.

## Usage

```bash
cp values.yaml.example values.yaml   # fill in real credentials

helm dependency update ./helm
helm lint ./helm -f helm/values.yaml -f values.yaml
helm template rag ./helm -n rag -f helm/values.yaml -f values.yaml    # dry run
helm upgrade --install rag ./helm -n rag --create-namespace --atomic \
  -f helm/values.yaml -f values.yaml
helm uninstall rag -n rag
```

`helm/values.yaml` is the base (checked in); `values.yaml` (gitignored, at `k8s/`) layers
secrets on top. Add `-f values-prod.yaml` (also at `k8s/`) once one exists, layered after
`values.yaml`, for a second environment.

## Troubleshooting

**`<resource> already exists` on install/upgrade, for a release that "does not exist"
yet.** A previous attempt failed partway through and left resources behind without a
recorded release (this is why the install command above passes `--atomic`, so a failed
attempt rolls itself back instead of leaving orphans for the next retry to collide with).
Fix: delete the conflicting objects and retry, e.g.:
```bash
kubectl delete role dagster-role -n rag
kubectl delete rolebinding dagster-rolebinding -n rag
```

## Naming

Helm subchart resource names are normally derived from the *release* name, not the
subchart alias (`<release>-<chart>` unless the release name already contains the chart
name). `fullnameOverride` is set per subchart in `helm/values.yaml` to pin `minio`, `qdrant`,
`redis-ha` (`-haproxy`), `mailpit`, `reloader` to fixed names regardless of the release
name this chart is installed under.

The one exception is the dagster subchart's webserver Service — its own template hardcodes
`<release-name>-webserver` and ignores `fullnameOverride`. `rag-api`'s `settings.yaml` is
rendered with `tpl` so `dagster.endpoint` resolves `{{ .Release.Name }}-webserver`
dynamically instead of a fixed string — this is the one config value that depends on
whatever release name you install under.

`rag-api`/`rag-admin` (this chart's own resources) use the same `fullnameOverride`/
`nameOverride` convention (see `templates/_helpers.tpl`, `helm/values.yaml`).

## Secrets

8 required Secrets: `rag-api-credentials`, `redis-auth`, `minio-root-secret`,
`mailpit-smtp-auth`, `dagster-postgresql-secret`, and the three `cnpg-cluster` role
secrets (`cnpg-rag-api-role`/`cnpg-dagster-role`/`cnpg-langfuse-role`).

- Two ways to supply each — pick freely per secret name, don't mix both for the same name.
- `rag-api-credentials` needs `S3_ACCESS_KEY`/`S3_SECRET_KEY` (rag_api's own S3 client,
  `settings.py`) set to the same values as `minio-root-secret`'s `rootUser`/`rootPassword`
  (MinIO server bootstrap). Omitting it fails uploads with `InvalidAccessKeyId` even though
  MinIO itself is up.

**Chart-managed (default)**
- Copy `values.yaml.example` to `values.yaml` (gitignored, at `k8s/`), fill in real
  values, layer it in with `-f values.yaml` (see Usage above).
- `templates/secrets.yaml` and `charts/cnpg-cluster/templates/secrets.yaml` create/update a
  `Secret` for every key present in `.Values.secrets` / `.Values.cnpg-cluster.secrets`.

**Pre-created / existing secret.** Leave the corresponding key out of those maps (or don't
layer `values.yaml` at all) and create the Secret yourself once, e.g.:

```bash
kubectl create secret generic rag-api-credentials -n rag \
  --from-literal=S3_ACCESS_KEY=... --from-literal=S3_SECRET_KEY=... \
  --from-literal=REDIS_PASSWORD=... \
  --from-literal=POSTGRES_USER=... --from-literal=POSTGRES_PASSWORD=... \
  --from-literal=OPENAI_API_KEY=... --from-literal=RERANKER_API_KEY=... \
  --from-literal=OIDC_ADMIN_CLIENT_ID=... --from-literal=OIDC_ADMIN_CLIENT_SECRET=... \
  --from-literal=SMTP_USERNAME=... --from-literal=SMTP_PASSWORD=... \
  --from-literal=TRACING_LANGFUSE_PUBLIC_KEY=... --from-literal=TRACING_LANGFUSE_SECRET_KEY=...

kubectl create secret generic redis-auth -n rag --from-literal=REDIS_PASSWORD=...       # match above
kubectl create secret generic minio-root-secret -n rag \
  --from-literal=rootUser=... --from-literal=rootPassword=...                          # match above
kubectl create secret generic mailpit-smtp-auth -n rag --from-literal=smtp.htpasswd='user:bcrypt-hash'
kubectl create secret generic dagster-postgresql-secret -n rag \
  --from-literal=postgresql-password=...   # match cnpg-dagster-role's password below

kubectl create secret generic cnpg-rag-api-role -n rag --type=kubernetes.io/basic-auth \
  --from-literal=username=rag-api --from-literal=password=...    # match rag-api-credentials' POSTGRES_PASSWORD
kubectl create secret generic cnpg-dagster-role -n rag --type=kubernetes.io/basic-auth \
  --from-literal=username=dagster --from-literal=password=...
kubectl create secret generic cnpg-langfuse-role -n rag --type=kubernetes.io/basic-auth \
  --from-literal=username=langfuse --from-literal=password=...
```

Every consumer (`envFrom`, `existingSecret`, `passwordSecret`) references these by fixed
name regardless of who created them — Helm never touches or claims ownership of Secrets
you pre-create this way.

`rag-api-credentials` is also referenced by the dagster subchart's code-server deployment
(same app, same env vars — no separate copy) via `credentialsSecretName` in
`helm/values.yaml`; change that value directly in the file if you rename it (see the
comment there for why `--set`/`-f` overrides don't fully propagate).

## Other notes

- The bucket-bootstrap `Job` (`minio-jobs`) runs as a `post-install,post-upgrade` Helm hook
  with `before-hook-creation` delete policy, so re-running `helm upgrade` doesn't hit the
  "Job spec is immutable" error a bare Job would.
- `dagster-postgresql-secret` needs a `postgresql-password` key matching the `dagster`
  postgres role's actual password — every dagster component injects `DAGSTER_PG_PASSWORD`
  from it unconditionally (not gated by `generatePostgresqlPasswordSecret`, which only
  controls whether the *dagster chart itself* creates this secret).
