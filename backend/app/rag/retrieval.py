"""Hybrid retrieval: authorization filter -> metadata filter -> vector + full-text -> RRF fusion -> citations.

Authorization is part of the SQL WHERE clause, so unauthorized chunks are never selected, ranked,
or handed to the model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Float, and_, bindparam, func, literal, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.config import get_settings
from app.models import Document, DocumentChunk, DocumentEmbedding
from app.rag.embeddings import cosine, get_embedder, tokenize

RRF_K = 60


def authorization_conditions(principal: Principal) -> list:
    conds = [
        Document.company_id == principal.company_id,
        DocumentChunk.company_id == principal.company_id,
        DocumentChunk.is_quarantined.is_(False),
        Document.status.in_(["indexed", "flagged"]),
    ]
    perms = principal.permissions
    if "DOCUMENTS_READ" not in perms:
        # employees may read permitted (non-confidential) policies only
        conds.append(Document.document_type == "policy") if "POLICIES_READ" in perms else conds.append(literal(False))
    if "DOCUMENTS_CONFIDENTIAL_READ" not in perms:
        conds.append(Document.classification.in_(["public", "internal"]))
    conds.append(or_(Document.required_permission.is_(None), Document.required_permission.in_(sorted(perms) or [""])))
    return conds


@dataclass
class RetrievalFilters:
    document_type: str | None = None
    framework_code: str | None = None
    document_ids: list[int] | None = None


def _metadata_conditions(f: RetrievalFilters | None) -> list:
    if not f:
        return []
    c = []
    if f.document_type:
        c.append(Document.document_type == f.document_type)
    if f.framework_code:
        c.append(Document.framework_code == f.framework_code)
    if f.document_ids:
        c.append(Document.id.in_(f.document_ids))
    return c


def _citation(chunk: DocumentChunk, doc: Document, score: float, via: list[str]) -> dict:
    return {
        "chunk_id": chunk.id, "document_id": doc.id, "document_code": doc.code, "document_name": doc.name,
        "page": chunk.page, "section": chunk.section, "classification": doc.classification,
        "version": doc.version, "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
        "document_type": doc.document_type, "content": chunk.content, "score": round(score, 4), "matched_by": via,
    }


def hybrid_search(db: Session, principal: Principal, query: str, k: int = 6,
                  filters: RetrievalFilters | None = None) -> dict:
    t0 = time.perf_counter()
    conds = authorization_conditions(principal) + _metadata_conditions(filters)
    base_join = lambda s: s.join(Document, Document.id == DocumentChunk.document_id)  # noqa: E731
    qvec = get_embedder().embed([query])[0]
    vec_rank: dict[int, int] = {}
    kw_rank: dict[int, int] = {}

    if get_settings().is_postgres:
        from pgvector.sqlalchemy import Vector

        qparam = bindparam("qvec", qvec, type_=Vector(len(qvec)))
        dist = DocumentEmbedding.embedding.op("<=>", return_type=Float)(qparam)
        rows = db.execute(
            base_join(select(DocumentChunk.id).join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id))
            .where(and_(*conds)).order_by(dist).limit(k * 4)
        ).scalars().all()
        vec_rank = {cid: i for i, cid in enumerate(rows)}
        terms = [t for t in tokenize(query) if t.isalnum()][:12]
        tsq = func.to_tsquery("english", " | ".join(terms) or "none")
        tsv = func.to_tsvector("english", DocumentChunk.content)
        rows = db.execute(
            base_join(select(DocumentChunk.id)).where(and_(*conds), tsv.op("@@")(tsq))
            .order_by(func.ts_rank_cd(tsv, tsq).desc()).limit(k * 4)
        ).scalars().all()
        kw_rank = {cid: i for i, cid in enumerate(rows)}
    else:  # portable fallback for SQLite dev/test
        rows = db.execute(
            base_join(select(DocumentChunk, DocumentEmbedding.embedding)
                      .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)).where(and_(*conds))
        ).all()
        qt = set(tokenize(query))
        sims = sorted(((cosine(qvec, emb), ch.id) for ch, emb in rows), reverse=True)[: k * 4]
        vec_rank = {cid: i for i, (_, cid) in enumerate(sims)}
        kws = sorted(((len(qt & set(tokenize(ch.content))), ch.id) for ch, _ in rows if qt & set(tokenize(ch.content))),
                     reverse=True)[: k * 4]
        kw_rank = {cid: i for i, (_, cid) in enumerate(kws)}

    fused: dict[int, float] = {}
    for ranks in (vec_rank, kw_rank):
        for cid, r in ranks.items():
            fused[cid] = fused.get(cid, 0) + 1 / (RRF_K + r + 1)
    top_ids = sorted(fused, key=fused.get, reverse=True)[:k]
    results = []
    if top_ids:
        pairs = db.execute(base_join(select(DocumentChunk, Document)).where(DocumentChunk.id.in_(top_ids), and_(*conds))).all()
        by_id = {ch.id: (ch, doc) for ch, doc in pairs}
        for cid in top_ids:
            if cid in by_id:
                ch, doc = by_id[cid]
                via = (["vector"] if cid in vec_rank else []) + (["keyword"] if cid in kw_rank else [])
                results.append(_citation(ch, doc, fused[cid], via))
    return {"query": query, "results": results, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "retrieval": "hybrid (pgvector + full-text, RRF)" if get_settings().is_postgres else "hybrid (portable)",
            "authorization": "filtered in SQL before ranking"}
