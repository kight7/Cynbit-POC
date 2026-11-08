"""Hybrid retrieval over case-study chunks: dense vectors in ChromaDB + BM25, fused with RRF.

Embedding backends (chosen automatically):
  1. FastEmbed  BAAI/bge-small-en-v1.5  (ONNX, CPU, ~67 MB, no PyTorch) -- default
  2. TF-IDF     scikit-learn            -- offline fallback if the model cannot be downloaded

Why hybrid: the corpus is tiny (13 cases / 78 chunks) and inquiries often contain exact
domain words ("EHR", "ticket drop", "SEO"); BM25 catches those, dense vectors catch paraphrases.
"""
from __future__ import annotations

import logging
import re
import sys
import uuid
from collections import defaultdict

from .config import EMBED_MODEL, get_secret
from .corpus import build_chunks, case_by_id
from .schemas import Chunk, RetrievedCase

log = logging.getLogger(__name__)

# Streamlit Cloud ships an old sqlite3; swap in pysqlite3 if it is installed (Linux only).
try:  # pragma: no cover - platform specific
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import chromadb  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

STOPWORDS = set(
    """a an and are as at be but by for from has have i in is it its of on or our that the their them
    they this to was we were will with you your us me my can could would should need needs looking want
    hi hello dear regards thanks thank please also into about any some more than just like""".split()
)

RRF_K = 60
INDUSTRY_BOOST = 0.35  # multiplicative bonus when a case shares the lead's industry


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


class _FastEmbedBackend:
    name = "fastembed:" + EMBED_MODEL
    # cosine similarity thresholds for confidence labels (bge-small typical range)
    thresholds = (0.80, 0.70)

    def __init__(self):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=EMBED_MODEL)

    def embed_docs(self, texts):
        return [list(map(float, v)) for v in self.model.embed(texts)]

    def embed_query(self, text):
        # bge models recommend an instruction prefix for short queries
        q = "Represent this sentence for searching relevant passages: " + text
        return [float(x) for x in next(iter(self.model.embed([q])))]


class _TfidfBackend:
    name = "tfidf (offline fallback)"
    thresholds = (0.30, 0.15)

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")

    def embed_docs(self, texts):
        m = self.vec.fit_transform(texts)
        return m.toarray().tolist()

    def embed_query(self, text):
        return self.vec.transform([text]).toarray()[0].tolist()


def _make_backend(prefer: str | None = None):
    prefer = (prefer or get_secret("EMBED_BACKEND", "auto")).lower()
    if prefer in ("auto", "fastembed"):
        try:
            return _FastEmbedBackend()
        except Exception as e:  # model download blocked / no internet
            if prefer == "fastembed":
                raise
            log.warning("FastEmbed unavailable (%s); falling back to TF-IDF", e)
    return _TfidfBackend()


class HybridRetriever:
    def __init__(self, backend: str | None = None, persist: bool = True):
        self.chunks: list[Chunk] = build_chunks()
        self.cases = case_by_id()
        self.backend = _make_backend(backend)
        self.notice = None if isinstance(self.backend, _FastEmbedBackend) else (
            "Embedding model could not be loaded; using TF-IDF vectors (lower recall on paraphrases)."
        )

        texts = [c.text for c in self.chunks]
        embeddings = self.backend.embed_docs(texts)

        # In-memory Chroma with a unique collection per instance. The index rebuilds in about a second,
        # and this avoids stale collection handles when Streamlit restarts or reruns the app.
        client = chromadb.EphemeralClient()
        self.collection = client.create_collection(
            f"cynbit_cases_{uuid.uuid4().hex[:10]}", metadata={"hnsw:space": "cosine"}
        )
        self.collection.add(
            ids=[c.chunk_id for c in self.chunks],
            documents=texts,
            embeddings=embeddings,
            metadatas=[c.metadata for c in self.chunks],
        )
        self.bm25 = BM25Okapi([tokenize(t) for t in texts])
        self._by_id = {c.chunk_id: c for c in self.chunks}
        self._pos = {c.chunk_id: i for i, c in enumerate(self.chunks)}

    # ------------------------------------------------------------------ query
    def search(self, query: str, industry: str | None = None, top_k_cases: int = 3,
               use_dense: bool = True, use_bm25: bool = True, industry_boost: bool = True) -> list[RetrievedCase]:
        n = len(self.chunks)

        # Dense ranking (Chroma)
        res = self.collection.query(query_embeddings=[self.backend.embed_query(query)], n_results=n)
        dense_ids = res["ids"][0]
        dense_sim = {cid: 1.0 - d for cid, d in zip(dense_ids, res["distances"][0])}

        # Sparse ranking (BM25)
        bm = self.bm25.get_scores(tokenize(query))
        sparse_ids = [self.chunks[i].chunk_id for i in sorted(range(n), key=lambda i: -bm[i])]

        # Reciprocal-rank fusion at chunk level
        fused: dict[str, float] = defaultdict(float)
        for rank, cid in enumerate(dense_ids if use_dense else []):
            fused[cid] += 1.0 / (RRF_K + rank + 1)
        for rank, cid in enumerate(sparse_ids if use_bm25 else []):
            if bm[self._pos[cid]] > 0:  # only chunks sharing at least one term
                fused[cid] += 1.0 / (RRF_K + rank + 1)

        # Aggregate to case level: best chunk + half of the second best
        per_case: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for cid, s in fused.items():
            per_case[self._by_id[cid].case_id].append((s, cid))
        case_scores = {}
        for case_id, lst in per_case.items():
            lst.sort(reverse=True)
            score = lst[0][0] + (0.5 * lst[1][0] if len(lst) > 1 else 0.0)
            if industry_boost and industry and industry in self.cases[case_id].industries:
                score *= 1.0 + INDUSTRY_BOOST
            case_scores[case_id] = score

        ranked = sorted(case_scores, key=lambda k: -case_scores[k])[:top_k_cases]
        top_score = case_scores[ranked[0]] if ranked else 1.0
        out = []
        for case_id in ranked:
            cs = self.cases[case_id]
            best = sorted(per_case[case_id], reverse=True)[:3]
            chunk_dicts = [
                {
                    "chunk_id": cid,
                    "section": self._by_id[cid].section,
                    "text": self._by_id[cid].text,
                    "fused_score": round(s, 5),
                    "cosine": round(dense_sim.get(cid, 0.0), 4),
                }
                for s, cid in best
            ]
            # Always include the outcome chunk so the generator sees the citable metrics
            oid = f"{case_id}::outcome_metric"
            if oid in self._by_id and all(c["chunk_id"] != oid for c in chunk_dicts):
                chunk_dicts.append(
                    {
                        "chunk_id": oid,
                        "section": "Outcome / metric",
                        "text": self._by_id[oid].text,
                        "fused_score": 0.0,
                        "cosine": round(dense_sim.get(oid, 0.0), 4),
                    }
                )
            best_cos = max(c["cosine"] for c in chunk_dicts)
            out.append(
                RetrievedCase(
                    case_id=case_id,
                    title=cs.title,
                    client=cs.client,
                    industry=cs.industry_raw,
                    source_url=cs.source_url,
                    score=round(case_scores[case_id], 5),
                    confidence=round(best_cos, 3),
                    metrics=cs.metrics,
                    chunks=chunk_dicts,
                )
            )
        return out

    def confidence_label(self, cosine: float) -> str:
        hi, mid = self.backend.thresholds
        return "high" if cosine >= hi else "medium" if cosine >= mid else "low"


def build_query(fields, inquiry: str) -> str:
    """Query builder: structured need + industry words + the raw inquiry (truncated)."""
    parts = []
    if fields.need_summary:
        parts.append(fields.need_summary)
    if fields.industry and fields.industry != "other":
        parts.append(fields.industry.replace("_", " "))
    parts.extend(n.replace("_", " ") for n in fields.need_types)
    parts.append(inquiry[:1500])
    return " \n".join(parts)