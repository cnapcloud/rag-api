"""Sparse TF encoder — pure Python, no onnxruntime.

Qdrant Modifier.IDF와 함께 사용한다.
클라이언트는 TF만 계산하고, IDF는 Qdrant 서버가 코퍼스 기반으로 자동 관리한다.
"""
from __future__ import annotations

import re
import zlib
from collections import Counter
from typing import List, Tuple

BatchSparseEncoding = Tuple[List[List[int]], List[List[float]]]


def _token_id(token: str) -> int:
    return zlib.crc32(token.encode()) & 0x7FFFFFFF


def compute_sparse_tf(texts: List[str]) -> BatchSparseEncoding:
    """
    텍스트 배치를 TF sparse 벡터로 변환한다.

    SparseEncoderCallable 시그니처: List[str] → (List[List[int]], List[List[float]])
    """
    all_indices: List[List[int]] = []
    all_values: List[List[float]] = []

    for text in texts:
        tokens = re.findall(r"\w+", text.lower())
        counts = Counter(tokens)
        all_indices.append([_token_id(t) for t in counts])
        all_values.append([float(v) for v in counts.values()])

    return all_indices, all_values
