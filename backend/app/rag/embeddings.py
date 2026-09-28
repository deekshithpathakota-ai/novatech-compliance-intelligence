"""Embedding providers behind one interface.

* `hash`  — deterministic feature-hashing embedder (offline, instant; used for demo pre-indexing).
* `openai` — OpenAI embeddings API; model from OPENAI_EMBEDDING_MODEL. Dimension must match EMBEDDING_DIM.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings

TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")
STOP = set("the a an and or of to in for on with by is are be as at this that from it its was were will shall "
           "must should may can our we you your their any all each per not no".split())


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall((text or "").lower()) if t not in STOP]


class HashEmbedder:
    name = "hash-embedder-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign * (1.0 if "_" not in f else 0.5)
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbedder:
    def __init__(self, model: str, dim: int):
        from openai import OpenAI

        self.client = OpenAI()
        self.name = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.name, input=texts, dimensions=self.dim)
        return [d.embedding for d in resp.data]


_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        s = get_settings()
        if s.embedding_provider == "openai" and s.openai_api_key and s.openai_embedding_model:
            _embedder = OpenAIEmbedder(s.openai_embedding_model, s.embedding_dim)
        else:
            _embedder = HashEmbedder(s.embedding_dim)
    return _embedder


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
