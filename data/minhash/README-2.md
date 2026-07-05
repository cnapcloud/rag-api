# MLOps Platform

MLflow, Apache Airflow, KubeRay를 기반으로 구성한 MLOps 플랫폼입니다.
NYC Yellow Taxi 데이터셋을 활용하여 데이터 수집 → 전처리 → 학습 → 모델 등록 → 서빙까지의 End-to-End 파이프라인을 제공합니다.

파이프라인은 **로컬 실행**과 **Airflow 기반 실행** 두 가지 방식을 지원합니다.
Airflow 환경에서는 `KubernetesPodOperator`를 통해 모든 Task를 컨테이너 기반으로 오케스트레이션하며,
학습 단계는 KubeRay와 연동하여 분산 환경에서 수행되고 학습된 모델은 MLflow에 저장됩니다.

---

## 디렉토리 구성

| 경로 | 설명 |
|------|------|
| `minio/` | 모델 아티팩트 저장소 MinIO Helm 설치 예제 |
| `mlflow/` | MLflow 및 PostgreSQL PVC/Helm 설치 예제 |
| `kuberay/` | Ray 클러스터, Ray Job, Serve 예제 |
| `airflow/` | DAG 기반 오케스트레이션 예제 |
| `taxi/` | NYC Taxi 예측용 기본 MLOps 파이프라인 |
| `lora/` | LLM LoRA 파인튜닝 학습 예제 |

---

## 접속 주소

| 서비스 | URL |
|--------|-----|
| MinIO Console | http://console.cnapcloud.com |
| MinIO API | http://minio-api.cnapcloud.com |
| MLflow | http://mlflow.cnapcloud.com |
| KubeRay | http://kuberay.cnapcloud.com |
| Airflow | http://airflow.cnapcloud.com |

---

## 1. 설치

각 서비스는 해당 `helm/` 디렉토리에서 설치합니다.

### 1-1. MinIO

```bash
cd minio && make apply
```

콘솔 접속 후 MLflow 모델 저장용 버킷을 생성합니다.

| 항목 | 값 |
|------|----|
| Bucket | `mlflow` |
| AWS_ACCESS_KEY_ID | `mLuTMCv1SVSfycZgX4th` |
| AWS_SECRET_ACCESS_KEY | `pMmJbYQO4o12gFy1rsTX9mzN9ELgQplOQ1nrwHLf` |

> ⚠️ MinIO는 디스크 사용량이 **75~80%** 를 초과하면 `SlowDownWrite` 오류와 함께 쓰기를 거부합니다.
> 설치 전 `/data` 경로의 여유 공간을 확인하세요.
> ```bash
> df -h /data
> ```

---

### 1-2. MLflow

```bash
cd mlflow/helm && ./install.sh
```

### 1-3. KubeRay

```bash
cd kuberay/helm && ./install.sh
```

### 1-4. Airflow

```bash
cd airflow/helm && ./install.sh
```

---

## 2. KubeRay

Ray 클러스터를 먼저 생성한 뒤 브라우저로 LoadBalancer 주소에 접속합니다.

```bash
kubectl create -f ray-shared-pvc.yaml
kubectl create -f ray-cluster.yaml
kubectl apply -f rayjob/example-job.yaml
```

---

## 3. NYC Taxi 데모

```bash
cd taxi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python pipeline.py --input data/raw/ --mode local --mlflow-uri http://localhost:5000
```

---

## 4. Airflow 파이프라인

주요 DAG 목록입니다.

| DAG 파일 | 설명 |
|----------|------|
| `airflow/dags/pipeline/dag_lora_pipeline.py` | LoRA 학습 파이프라인 |
| `airflow/dags/pipeline/dag_lora_mlflow_pipeline.py` | LoRA + MLflow 연동 파이프라인 |
| `airflow/dags/pipeline/nyc_taxi_pipeline.py` | NYC Taxi 예측 파이프라인 |

Airflow UI에서 원하는 DAG를 trigger합니다.

> `airflow/`는 Git Sync 기반으로 DAG를 배포합니다.

---

## 참고

- `taxi/`는 로컬 실행과 MLflow 연동 예제를 함께 포함합니다.
- 학습 단계는 KubeRay 분산 환경과 연동되어 수행됩니다.
- 학습된 모델은 MLflow Model Registry에 저장 및 버전 관리됩니다.
