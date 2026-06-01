"""Local embedding engine via llama-server OpenAI-compatible API."""
import hashlib
import logging
import time
from collections import OrderedDict

import numpy as np
import requests

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Encapsulates llama-server /v1/embeddings endpoint."""

    def __init__(self, endpoint: str = "http://localhost:8080/v1/embeddings",
                 dim: int = 512, timeout: int = 30):
        self._endpoint = endpoint.rstrip("/")
        self._dim = dim
        self._timeout = timeout
        self._session = requests.Session()
        self._session.trust_env = False

    def encode(self, texts: list[str]) -> np.ndarray:
        """Batch encode texts -> (n, dim) float32 L2-normalized."""
        if not texts:
            return np.empty((0, self._dim), dtype=np.float32)

        t0 = time.time()
        try:
            resp = self._session.post(
                self._endpoint,
                json={"input": texts},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            vecs = np.array(
                [item["embedding"] for item in data["data"]],
                dtype=np.float32,
            )
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs /= norms
            elapsed = (time.time() - t0) * 1000
            logger.debug(f"[embed] encoded {len(texts)} texts in {elapsed:.0f}ms")
            return vecs
        except Exception as e:
            logger.error(f"[embed] encoding failed: {e}")
            raise

    def encode_single(self, text: str) -> np.ndarray:
        """Encode single text -> (dim,) float32 normalized."""
        return self.encode([text])[0]

    @staticmethod
    def similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """Cosine via dot product (vectors must be L2-normalized)."""
        return np.dot(doc_vecs, query_vec)

    @staticmethod
    def bytes_to_vec(data: bytes, dim: int = 512) -> np.ndarray:
        """Deserialize BLOB -> float32 array."""
        vec = np.frombuffer(data, dtype=np.float32)
        if len(vec) != dim:
            raise ValueError(f"Expected {dim} floats, got {len(vec)}")
        return vec

    @staticmethod
    def vec_to_bytes(vec: np.ndarray) -> bytes:
        """Serialize float32 array -> BLOB."""
        return vec.astype(np.float32).tobytes()

    def health_check(self) -> bool:
        """Check if embedding server is reachable. Compatible with llama-server
        and OpenAI-compatible APIs (text-embeddings-inference, etc.). (#139)"""
        try:
            # Try /health endpoint first (llama-server)
            health_url = self._endpoint.rsplit("/", 1)[0] + "/health"
            resp = self._session.get(health_url, timeout=3)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        # Fallback: try the embeddings endpoint directly
        try:
            resp = self._session.post(
                self._endpoint,
                json={"input": ["test"]},
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False


class EmbeddingCache:
    """LRU cache keyed by SHA-256 hash of input text."""

    def __init__(self, max_size: int = 1000):
        self._max_size = max_size
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> np.ndarray | None:
        key = self._hash(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].copy()
        return None

    def set(self, text: str, vec: np.ndarray):
        key = self._hash(text)
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = vec.copy()
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def invalidate(self, text: str):
        key = self._hash(text)
        self._cache.pop(key, None)

    def __len__(self) -> int:
        return len(self._cache)
