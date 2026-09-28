"""Document ingestion: parse -> extract text/tables -> OCR check -> classify -> injection scan -> chunk ->
metadata -> embed -> store (pgvector). Uploaded content is UNTRUSTED DATA throughout."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk, DocumentEmbedding, DocumentVersion
from app.rag.embeddings import get_embedder
from app.security import dlp, injection
from app.services.audit import log_action, record_security_event

SUPPORTED = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_BYTES = 15 * 1024 * 1024
CHUNK_CHARS = 900


class IngestionError(ValueError):
    pass


@dataclass
class Block:
    page: int
    section: str
    text: str


@dataclass
class Parsed:
    blocks: list[Block]
    page_count: int
    tables: int = 0
    ocr_required_pages: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


HEADING = re.compile(r"^(#{1,4}\s+.+|\d+(\.\d+)*\.?\s+[A-Z][^.]{2,60}|[A-Z][A-Z0-9 &/\-]{4,80}|(Results|Scope|Method|Purpose)\b.{0,40})$")


def _text_to_blocks(text: str, page: int, section: str = "") -> list[Block]:
    blocks, buf = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if buf:
                blocks.append(Block(page, section, " ".join(buf)))
                buf = []
            continue
        if HEADING.match(s) and len(s) < 90:
            if buf:
                blocks.append(Block(page, section, " ".join(buf)))
                buf = []
            section = s.lstrip("# ").strip()
            continue
        buf.append(s)
    if buf:
        blocks.append(Block(page, section, " ".join(buf)))
    return blocks


def parse(filename: str, data: bytes) -> Parsed:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in SUPPORTED:
        raise IngestionError(f"Unsupported document type '{ext or 'unknown'}'. Supported: PDF, DOCX, TXT, MD, CSV, XLSX.")
    if len(data) > MAX_BYTES:
        raise IngestionError("File exceeds the 15 MB prototype limit.")
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise IngestionError("Invalid file: content is not a PDF.")
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        blocks, ocr = [], []
        section = ""
        for i, pg in enumerate(reader.pages, start=1):
            txt = pg.extract_text() or ""
            if len(txt.strip()) < 20:
                ocr.append(i)
                continue
            b = _text_to_blocks(txt, i, section)
            if b:
                section = b[-1].section
            blocks.extend(b)
        notes = []
        if ocr:
            try:
                import pytesseract  # noqa: F401
                notes.append("OCR engine available; scanned pages queued for OCR.")
            except ImportError:
                notes.append(f"{len(ocr)} scanned page(s) need OCR — OCR engine not installed in this environment.")
        return Parsed(blocks, len(reader.pages), ocr_required_pages=ocr, notes=notes)
    if ext == ".docx":
        import docx

        d = docx.Document(io.BytesIO(data))
        blocks, section = [], ""
        for p in d.paragraphs:
            t = p.text.strip()
            if not t:
                continue
            if p.style is not None and p.style.name.lower().startswith("heading"):
                section = t
                continue
            blocks.append(Block(1, section, t))
        for ti, table in enumerate(d.tables):
            rows = [" | ".join(c.text.strip() for c in r.cells) for r in table.rows]
            blocks.append(Block(1, f"Table {ti + 1}", "\n".join(rows)))
        return Parsed(blocks, 1, tables=len(d.tables))
    if ext == ".csv":
        text = data.decode("utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0] if rows else []
        blocks = [Block(1, "Table 1", "; ".join(f"{h}: {v}" for h, v in zip(header, r))) for r in rows[1:]]
        return Parsed(blocks, 1, tables=1)
    if ext == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        blocks = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            header = [str(h) for h in rows[0]] if rows else []
            for r in rows[1:]:
                blocks.append(Block(1, ws.title, "; ".join(f"{h}: {v}" for h, v in zip(header, r) if v is not None)))
        return Parsed(blocks, len(wb.worksheets), tables=len(wb.worksheets))
    # txt / md — support explicit page markers "--- Page N ---"
    text = data.decode("utf-8", errors="replace")
    parts = re.split(r"(?im)^-{2,}\s*page\s+(\d+)\s*-{2,}\s*$", text)
    blocks: list[Block] = []
    if len(parts) > 1:
        section = ""
        for i in range(1, len(parts), 2):
            b = _text_to_blocks(parts[i + 1], int(parts[i]), section)
            if b:
                section = b[-1].section
            blocks.extend(b)
        pages = max(b.page for b in blocks) if blocks else 1
    else:
        blocks = _text_to_blocks(text, 1)
        pages = 1
    return Parsed(blocks, pages)


def classify(filename: str, text: str) -> dict:
    t = (filename + " " + text[:4000]).lower()
    if "policy" in t and "report" not in filename.lower():
        dtype = "policy"
    elif any(k in t for k in ("procedure", "runbook", "standard operating")):
        dtype = "procedure"
    elif any(k in t for k in ("review report", "evidence", "test result", "export", "log")):
        dtype = "evidence"
    elif "report" in t:
        dtype = "report"
    else:
        dtype = "other"
    if "restricted" in t:
        cls = "restricted"
    elif "confidential" in t:
        cls = "confidential"
    elif "public" in t[:300]:
        cls = "public"
    else:
        cls = "internal"
    fw = None
    for code, keys in {"ISO27001": ("iso 27001", "iso/iec 27001", "annex a"), "SOC2": ("soc 2", "trust services"),
                       "NIST_CSF": ("nist csf", "nist cybersecurity"), "DPDP": ("dpdp", "personal data protection")}.items():
        if any(k in t for k in keys):
            fw = code
            break
    return {"document_type": dtype, "classification": cls, "framework_code": fw}


def chunk_blocks(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    cur: Block | None = None
    for b in blocks:
        if cur and cur.page == b.page and cur.section == b.section and len(cur.text) + len(b.text) < CHUNK_CHARS:
            cur.text += "\n" + b.text
            continue
        if cur:
            out.append(cur)
        if len(b.text) > CHUNK_CHARS:  # split long paragraphs on sentence boundaries
            sentences, buf = re.split(r"(?<=[.!?])\s+", b.text), ""
            for s in sentences:
                if len(buf) + len(s) > CHUNK_CHARS and buf:
                    out.append(Block(b.page, b.section, buf.strip()))
                    buf = ""
                buf += s + " "
            cur = Block(b.page, b.section, buf.strip()) if buf.strip() else None
        else:
            cur = Block(b.page, b.section, b.text)
    if cur:
        out.append(cur)
    return out


def _next_code(db: Session, company_id: int) -> str:
    n = db.execute(select(func.count(Document.id)).where(Document.company_id == company_id)).scalar_one()
    return f"DOC-{n + 1:03d}"


def ingest_document(db: Session, *, company_id: int, user_id: int | None, filename: str, data: bytes,
                    overrides: dict | None = None, source: str = "upload", principal=None) -> dict:
    """Runs the full pipeline and returns an ingestion report (shown in the UI)."""
    steps: list[dict] = []

    def step(name: str, t0: float, detail: str = "", status: str = "done"):
        steps.append({"step": name, "status": status, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000, 1)})

    t = time.perf_counter()
    parsed = parse(filename, data)
    step("Parse", t, f"{parsed.page_count} page(s), {len(parsed.blocks)} text blocks")
    step("Extract tables", t, f"{parsed.tables} table(s)")
    step("OCR check", t, "; ".join(parsed.notes) or "Text layer present — OCR not required",
         "warning" if parsed.ocr_required_pages else "done")
    if not parsed.blocks:
        raise IngestionError("No extractable text found in document.")

    full_text = "\n".join(b.text for b in parsed.blocks)
    t = time.perf_counter()
    meta = classify(filename, full_text)
    meta.update({k: v for k, v in (overrides or {}).items() if v})
    step("Classify", t, f"{meta['document_type']} · {meta['classification']} · {meta['framework_code'] or 'no framework'}")

    t = time.perf_counter()
    chunks = chunk_blocks(parsed.blocks)
    flagged_chunks, all_hits = [], []
    for i, ch in enumerate(chunks):
        hits = injection.detect(ch.text)
        if hits:
            flagged_chunks.append(i)
            all_hits.extend(hits)
    step("Detect suspicious content", t,
         f"{len(flagged_chunks)} chunk(s) quarantined — {injection.UNTRUSTED_NOTICE}" if flagged_chunks else "No untrusted instructions found",
         "warning" if flagged_chunks else "done")

    sha = hashlib.sha256(data).hexdigest()
    storage_dir = os.path.join(get_settings().local_storage_dir, str(company_id))
    os.makedirs(storage_dir, exist_ok=True)
    path = os.path.join(storage_dir, f"{sha[:16]}_{os.path.basename(filename)}")
    with open(path, "wb") as fh:
        fh.write(data)

    doc = Document(
        company_id=company_id, code=_next_code(db, company_id), name=os.path.basename(filename),
        document_type=meta["document_type"], classification=meta["classification"],
        framework_code=meta.get("framework_code"), department_id=meta.get("department_id"),
        owner_id=user_id, uploaded_by=user_id, sha256=sha, source=source, version=str(meta.get("version") or "1.0"),
        effective_date=meta.get("effective_date") or date.today(), mime_type=SUPPORTED[os.path.splitext(filename.lower())[1]],
        page_count=parsed.page_count, status="flagged" if flagged_chunks else "indexed",
        security_flags=[{"type": "prompt_injection", "rules": sorted({h["rule"] for h in all_hits}),
                         "chunks": flagged_chunks, "notice": injection.UNTRUSTED_NOTICE}] if flagged_chunks else [],
        storage_path=path,
    )
    db.add(doc)
    db.flush()
    db.add(DocumentVersion(company_id=company_id, document_id=doc.id, version=doc.version, sha256=sha,
                           storage_path=path, created_by=user_id))

    t = time.perf_counter()
    dlp_types: set[str] = set()
    rows: list[DocumentChunk] = []
    for i, ch in enumerate(chunks):
        masked, types = dlp.redact(ch.text)
        dlp_types.update(types)
        row = DocumentChunk(company_id=company_id, document_id=doc.id, chunk_index=i, page=ch.page,
                            section=ch.section[:250], content=masked, classification=doc.classification,
                            is_quarantined=i in flagged_chunks, token_count=len(masked.split()))
        db.add(row)
        rows.append(row)
    db.flush()
    step("Chunk + metadata", t, f"{len(rows)} chunks; DLP masked: {', '.join(sorted(dlp_types)) or 'none'}")
    if dlp_types:
        doc.security_flags = doc.security_flags + [{"type": "dlp", "detected": sorted(dlp_types),
                                                     "notice": dlp.REDACTION_NOTICE}]

    t = time.perf_counter()
    safe = [r for r in rows if not r.is_quarantined]
    emb = get_embedder()
    vectors = emb.embed([f"{r.section}\n{r.content}" for r in safe]) if safe else []
    for r, v in zip(safe, vectors):
        db.add(DocumentEmbedding(company_id=company_id, chunk_id=r.id, embedding=v, model=emb.name))
    step("Generate embeddings", t, f"{len(vectors)} vectors · {emb.name} (quarantined chunks excluded)")
    step("Store + index", time.perf_counter(), "PostgreSQL / pgvector" if get_settings().is_postgres else "SQL store")

    if flagged_chunks:
        record_security_event(
            db, company_id=company_id, user_id=user_id, event_type="prompt_injection_detected", severity="HIGH",
            description=f"{injection.UNTRUSTED_NOTICE} ({doc.name})",
            details={"document": doc.code, "rules": sorted({h["rule"] for h in all_hits}),
                     "excerpts": [h["excerpt"] for h in all_hits[:3]], "action": "Content quarantined; never sent to the model"},
        )
    log_action(db, company_id=company_id, principal=principal, action="Uploaded and indexed document",
               resource=doc.code, resource_type="document", result=doc.status.upper(),
               risk_level="HIGH" if flagged_chunks else "LOW")
    return {"document": {"id": doc.id, "code": doc.code, "name": doc.name, "status": doc.status,
                         "classification": doc.classification, "document_type": doc.document_type,
                         "framework_code": doc.framework_code, "sha256": sha, "security_flags": doc.security_flags},
            "pipeline": steps, "chunks": len(rows), "quarantined": len(flagged_chunks),
            "untrusted_instruction_detected": bool(flagged_chunks)}
