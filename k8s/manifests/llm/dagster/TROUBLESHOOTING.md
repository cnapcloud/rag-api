# Dagster Troubleshooting

## daemon CrashLoopBackOff — 고아 run으로 인한 반복 크래시

### 증상
```
dagster-daemon   0/1   CrashLoopBackOff   N (Xs ago)
```
daemon 로그에서 매 재시작마다 동일한 run_id를 체크하다가 종료:
```
MonitoringDaemon - Checking run <run_id>
SensorDaemon     - Sensor event_queue_sensor skipped: ...
(crash)
```

### 원인
K8s Job 없이 `STARTING` 상태로 남은 고아 run이 있을 때, `MonitoringDaemon`이
`K8sRunLauncher`로 Job 상태를 조회하다가 예외 발생 → daemon 프로세스 종료 반복.

주로 다음 상황에서 발생:
- 배포 중 run이 트리거되고 daemon이 재시작된 경우
- K8sRunLauncher 설정 오류로 Job 생성에 실패한 경우

### 해결

stuck run_id 확인:
```bash
kubectl -n llm logs deploy/dagster-daemon | grep "Checking run"
```

webserver pod에서 해당 run 삭제:
```bash
kubectl -n llm exec deploy/dagster-dagster-webserver -- \
  sh -c 'echo "DELETE" | dagster run delete <run_id>'
```

삭제 후 daemon이 자동 복구되는지 확인:
```bash
kubectl -n llm get pods -w
```

### 예방
- `runMonitoring.maxResumeRunAttempts: 0` 유지 (재시도 없이 빠른 실패 처리)
- ArgoCD 사용 시 배포 중 run 트리거 방지 (sync wave 활용)
