# Apple Silicon(MLX) 기준 vllm-mlx 서빙 설정
MODEL := mlx-community/Qwen3.5-9B-4bit
EMBED_MODEL := mlx-community/bge-m3-mlx-fp16
PORT := 8000
HOST := 0.0.0.0      # 클러스터(LiteLLM)에서 접근하려면 0.0.0.0 필요, 기본값 localhost는 외부 접근 불가
RERANK_MODEL := BAAI/bge-reranker-v2-m3
MAX_SEQS := 4         # 동시 처리 시퀀스 수
CONTEXT := 32768      # 시퀀스당 KV cache 한도(토큰), reasoning 모델은 32768 이상
CHUNK := 2048         # 스케줄러 step당 prefill 토큰 상한, 긴 프롬프트가 생성 중인 요청을 막지 않게
PREFILL_STEP := 4096  # prefill 청크 크기(텍스트/멀티모달 경로 공통), 클수록 빠르지만 메모리 더 사용

.PHONY: help install download run stop

help: ## 사용 가능한 타겟 목록 표시
	@echo "vllm-mlx 서빙 (macOS Apple Silicon / MLX 전용)"
	@echo ""
	@echo "사용법: make <target>"
	@echo ""
	@awk -F':.*## ' '/^[a-z]+:.*## / {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "현재 설정: MODEL=$(MODEL) HOST=$(HOST) PORT=$(PORT)"

# hf, vllm-mlx가 없을 때만 uv tool로 설치
install: ## hf, vllm-mlx 설치 (uv tool)
	@command -v uv >/dev/null || { echo "uv가 필요합니다: brew install uv"; exit 1; }
	@command -v hf >/dev/null || uv tool install huggingface-hub
	@command -v vllm-mlx >/dev/null || uv tool install vllm-mlx

download: install ## 채팅/임베딩/리랭크 모델 다운로드
	hf download $(MODEL)
	hf download $(EMBED_MODEL)
	hf download $(RERANK_MODEL)

run: install ## vllm-mlx 서버 실행
	vllm-mlx serve $(MODEL) --port $(PORT) --host $(HOST) \
		--continuous-batching --max-num-seqs $(MAX_SEQS) \
		--max-kv-size $(CONTEXT) \
		--chunked-prefill-tokens $(CHUNK) \
		--prefill-step-size $(PREFILL_STEP) --mllm-prefill-step-size $(PREFILL_STEP) \
		--reasoning-parser qwen3 \
		--embedding-model $(EMBED_MODEL) \
		--rerank-model $(RERANK_MODEL)

stop: ## vllm-mlx 서버 종료
	pkill -f "vllm-mlx serve $(MODEL) --port $(PORT)" || true