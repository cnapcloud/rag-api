# MLOps Platform

MLflow, Apache Airflow, KubeRay 기반으로 구성한 MLOps 플랫폼입니다. NYC Yellow Taxi 데이터셋을 활용하여 데이터 수집, 전처리, 학습, 모델 등록, 서빙까지의 End-to-End 파이프라인을 제공합니다.

파이프라인은 로컬 실행 방식과 Airflow 기반 실행 방식, 두 가지를 지원합니다. Airflow 환경에서는 KubernetesPodOperator를 통해 모든 Task가 컨테이너 기반으로 오케스트레이션되며, 학습 단계는 KubeRay와 연동하여 분산 환경에서 수행되고, 학습된 모델은 MLflow에 저장됩니다.

## 디렉토리 구성

- minio/ : 모델 아티팩트 저장소 MinIO Helm 설치 예제
- mlflow/ : MLflow 및 PostgreSQL PVC/Helm 설치 예제
- kuberay/ : Ray 클러스터, Ray Job, Serve 예제
- airflow/ : DAG 기반 오케스트레이션 예제
- taxi/ : NYC Taxi 예측용 기본 MLOps 파이프라인
- lora/ : LLM LoRA 파인튜닝 학습 예제

## 접속 주소

- MinIO Console: http://console.cnapcloud.com
- MinIO API: http://minio-api.cnapcloud.com
- MLflow: http://mlflow.cnapcloud.com
- KubeRay: http://kuberay.cnapcloud.com
- Airflow: http://airflow.cnapcloud.com

## 1. 설치

각 서비스는 helm/ 디렉토리에서 설치합니다.

### 1-1. MinIO

설치 명령:

    cd minio
    make apply

콘솔에 접속한 뒤, MLflow 모델 저장용 버킷을 생성합니다.

- Bucket 이름: mlflow
- AWS_ACCESS_KEY_ID 값: mLuTMCv1SVSfycZgX4th
- AWS_SECRET_ACCESS_KEY 값: pMmJbYQO4o12gFy1rsTX9mzN9ELgQplOQ1nrwHLf

주의: MinIO는 디스크 사용량이 75~80%를 초과하면 SlowDownWrite 오류와 함께 쓰기를 거부합니다. 설치 전에 /data 경로의 여유 공간을 꼭 확인하세요.

    df -h /data

### 1-2. MLflow

    cd mlflow/helm
    ./install.sh

### 1-3. KubeRay

    cd kuberay/helm
    ./install.sh

### 1-4. Airflow

    cd airflow/helm
    ./install.sh

## 2. KubeRay

Ray 클러스터를 먼저 만든 다음, 브라우저로 LoadBalancer 주소에 접속합니다.

    kubectl create -f ray-shared-pvc.yaml
    kubectl create -f ray-cluster.yaml
    kubectl apply -f rayjob/example-job.yaml

## 3. NYC Taxi 데모

    cd taxi
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python pipeline.py --input data/raw/ --mode local --mlflow-uri http://localhost:5000

## 4. Airflow 파이프라인

주요 DAG 목록은 다음과 같습니다.

- airflow/dags/pipeline/dag_lora_pipeline.py : LoRA 학습 파이프라인
- airflow/dags/pipeline/dag_lora_mlflow_pipeline.py : LoRA + MLflow 연동 파이프라인
- airflow/dags/pipeline/nyc_taxi_pipeline.py : NYC Taxi 예측 파이프라인

Airflow UI에서 원하는 DAG를 trigger하면 됩니다. airflow/ 디렉토리는 Git Sync 기반으로 DAG를 배포합니다.

## 참고

- taxi/ 디렉토리는 로컬 실행과 MLflow 연동 예제를 함께 포함합니다.
- 학습 단계는 KubeRay 분산 환경과 연동되어 수행됩니다.
- 학습된 모델은 MLflow Model Registry에 저장 및 버전 관리됩니다.