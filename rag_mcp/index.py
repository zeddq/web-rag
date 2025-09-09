from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ChunkMeta:
    id: str
    url: str
    title: str
    text: str
    offset: int


class SimpleIndex:
    """A minimal vector index stored on disk: NumPy + JSONL metadata.

    - embeddings.npy: float32, shape (N, D) L2-normalized
    - meta.jsonl: one json per row with id,url,title,text,offset
    - model.json: {"provider": "openai|sentence-transformers", "name": str, "dim": int}
    """

    def __init__(self, root: str) -> None:
        self.root = root
        self.emb_path = os.path.join(root, "embeddings.npy")
        self.meta_path = os.path.join(root, "meta.jsonl")
        self.model_path = os.path.join(root, "model.json")
        self._emb: Optional[np.ndarray] = None
        self._meta: List[ChunkMeta] = []
        self._dim: Optional[int] = None

    def exists(self) -> bool:
        return os.path.exists(self.emb_path) and os.path.exists(self.meta_path)

    def load(self) -> None:
        self._emb = np.load(self.emb_path)
        self._emb = self._emb.astype(np.float32)
        # Ensure normalized
        norms = np.linalg.norm(self._emb, axis=1, keepdims=True) + 1e-9
        self._emb = self._emb / norms
        self._dim = self._emb.shape[1]
        self._meta = []
        with open(self.meta_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                self._meta.append(ChunkMeta(**obj))

    def save(self, embeddings: np.ndarray, metas: List[Dict[str, Any]], model_info: Dict[str, Any]) -> None:
        arr = embeddings.astype(np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
        arr = arr / norms
        os.makedirs(self.root, exist_ok=True)
        np.save(self.emb_path, arr)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            for m in metas:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump(model_info, f)

    def search(self, query_vec: np.ndarray, k: int = 5) -> List[Tuple[ChunkMeta, float]]:
        assert self._emb is not None and self._meta, "index not loaded"
        q = query_vec.astype(np.float32)
        q = q / (np.linalg.norm(q) + 1e-9)
        scores = (self._emb @ q)
        idx = np.argpartition(-scores, kth=min(k, len(scores)-1))[:k]
        # sort top-k
        pairs = sorted(((int(i), float(scores[i])) for i in idx), key=lambda x: -x[1])
        return [(self._meta[i], s) for i, s in pairs]

