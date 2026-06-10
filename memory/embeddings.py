"""Local embedding engine via llama-server OpenAI-compatible API."""
import hashlib
import logging
import threading
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
        self._cache = EmbeddingCache()  # #196: integrated cache

    def encode(self, texts: list[str]) -> np.ndarray:
        """Batch encode texts -> (n, dim) float32 L2-normalized.
        Uses cache to skip API calls for known texts. (#196)"""
        if not texts:
            return np.empty((0, self._dim), dtype=np.float32)

        # #196: check cache first
        vecs = []
        uncached = []
        for i, text in enumerate(texts):
            cached = self._cache.get(text, expected_dim=self._dim)
            if cached is not None:
                vecs.append((i, cached))
            else:
                uncached.append((i, text))

        t0 = time.time()
        try:
            if uncached:
                idxs, new_texts = zip(*uncached)
                resp = self._session.post(
                    self._endpoint,
                    json={"input": list(new_texts)},
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                api_dim = len(data["data"][0]["embedding"])
                if api_dim != self._dim:
                    logger.warning(
                        f"[embed] API returned dim={api_dim}, expected {self._dim}; "
                        f"resetting cache and discarding old-dimension vectors"
                    )
                    self._cache.clear()
                    self._dim = api_dim
                    # P0: drop old-dimension cached vectors to avoid np.stack crash
                    vecs = [(i, v) for i, v in vecs if len(v) == api_dim]
                new_vecs = np.array(
                    [item["embedding"] for item in data["data"]],
                    dtype=np.float32,
                )
                norms = np.linalg.norm(new_vecs, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1.0, norms)
                new_vecs /= norms
                for j, idx in enumerate(idxs):
                    self._cache.set(new_texts[j], new_vecs[j])
                    vecs.append((idx, new_vecs[j]))
                elapsed = (time.time() - t0) * 1000
                logger.debug(f"[embed] encoded {len(uncached)} texts in {elapsed:.0f}ms")
        except Exception as e:
            # P0: API failed — skip uncached texts, use only cached results
            logger.warning(f"[embed] API failed: {e}, using {len(vecs)}/{len(texts)} cached")
            if not vecs:
                raise  # nothing cached, must fail

        if not vecs:
            return np.empty((0, self._dim), dtype=np.float32)
        vecs.sort(key=lambda x: x[0])
        return np.stack([v for _, v in vecs])

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
            if 200 <= resp.status_code < 300:  # #198: accept any 2xx
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
    """LRU cache keyed by SHA-256 hash of input text. Thread-safe."""

    def __init__(self, max_size: int = 1000):
        self._max_size = max_size
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str, expected_dim: int | None = None) -> np.ndarray | None:
        key = self._hash(text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                vec = self._cache[key]
                if expected_dim is not None and len(vec) != expected_dim:
                    logger.warning(
                        f"[embed_cache] dimension mismatch: cached={len(vec)}, expected={expected_dim}; "
                        f"evicting stale entry"
                    )
                    del self._cache[key]
                    return None
                return vec.copy()
            return None

    def set(self, text: str, vec: np.ndarray):
        key = self._hash(text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = vec.copy()
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, text: str):
        key = self._hash(text)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
