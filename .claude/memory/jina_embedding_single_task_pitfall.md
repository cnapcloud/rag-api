# JinaEmbedding은 query/passage task를 자동 분기하지 않음

`llama-index-embeddings-jinaai`(0.7.0 확인)의 `JinaEmbedding`은 생성 시 받은 `task` 하나를
query 임베딩과 passage 임베딩 양쪽에 그대로 보낸다. `encoding_queries`/`encoding_documents`는
task가 아니라 인코딩 타입(float/binary)이라 방향 분기에 못 쓴다. 또 `__init__`이
`_JinaAPICaller(model=, api_key=)`만 넘겨 `base_url` passthrough가 없다(자체 호스팅 시
`emb._api.api_url`을 직접 덮어써야 함).

US-50 backlog는 "인제스트(passage)/검색(query)에 서로 다른 task가 자동 전송된다"고 가정했으나
실제로는 아님 → `pipeline/steps/embed.py`의 `_build_jina()`에서 `_get_query_embedding` /
`_aget_query_embedding` / `_get_text_embeddings` / `_aget_text_embeddings`를 오버라이드해
`retrieval.query` / `retrieval.passage`를 강제하는 얇은 서브클래스로 처리했다.

패키지 업그레이드 시 이 서브클래스가 상위 클래스 메서드 시그니처와 여전히 맞는지 확인할 것.
설계 근거는 [[../../docs/internal/design/settings-composition.md]] §7.5.
