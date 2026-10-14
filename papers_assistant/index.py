"""Local search index over the papers: SQLite for storage, hybrid retrieval in memory.

Retrieval = BM25 (exact terms: gene names, markers, product codes)
          + dense embeddings (meaning / paraphrase)
          fused with reciprocal-rank fusion, then re-ranked by a cross-encoder.
Embedding and re-ranking models run locally (fastembed / ONNX), so paper text is
only sent to Claude for the passages actually retrieved for a question.
"""
import re
import sqlite3
from array import array
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np

import config

CHUNK_CHARS = 1100
CHUNK_OVERLAP = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    file_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    title       TEXT,
    folder      TEXT,
    mime        TEXT,
    modified    TEXT,
    link        TEXT,
    n_pages     INTEGER,
    n_chars     INTEGER,
    indexed_at  TEXT,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id   TEXT NOT NULL REFERENCES docs(file_id) ON DELETE CASCADE,
    page      INTEGER,
    ord       INTEGER,
    text      TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id, ord);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z0-9]")
_STOP = set("""a an and are as at be by for from has have in is it its of on or that the
this to was were which with we our these those than then also been not but can may""".split())


def drive_path(d):
    """Human-readable Drive location of a paper: 'Literature › subfolder › file.pdf'."""
    parts = [p for p in (d.get("folder") or "").split("/") if p] + [d["name"]]
    return " › ".join(parts)


def tokenize(text):
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def connect(path=None):
    path = path or config.INDEX_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    try:  # databases created before last_seen existed
        conn.execute("ALTER TABLE docs ADD COLUMN last_seen TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chunk_pages(pages):
    """[(page, text)] -> [(page, chunk_text)], packing paragraphs up to CHUNK_CHARS
    with a CHUNK_OVERLAP tail carried into the next chunk. Chunks never span pages,
    so every passage has an exact page number for citation."""
    out = []
    for page, text in pages:
        if not text.strip():
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        # break overlong paragraphs on sentence boundaries
        pieces = []
        for p in paras:
            if len(p) <= CHUNK_CHARS:
                pieces.append(p)
            else:
                pieces.extend(s for s in re.split(r"(?<=[.!?])\s+", p) if s)
        buf = ""
        for piece in pieces:
            if buf and len(buf) + len(piece) + 1 > CHUNK_CHARS:
                out.append((page, buf))
                buf = buf[-CHUNK_OVERLAP:].split(" ", 1)[-1] + " " + piece
            else:
                buf = f"{buf}\n{piece}" if buf else piece
            while len(buf) > CHUNK_CHARS * 1.5:   # a single huge sentence/table row
                out.append((page, buf[:CHUNK_CHARS]))
                buf = buf[CHUNK_CHARS - CHUNK_OVERLAP:]
        if buf.strip() and len(buf.strip()) > 40:
            out.append((page, buf))
    return out


_embedder = None
_reranker = None


def embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=config.MODEL_CACHE_DIR)
    return _embedder


def reranker():
    """Cross-encoder re-ranker; None if unavailable (search still works without it)."""
    global _reranker
    if _reranker is None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            _reranker = TextCrossEncoder(model_name=config.RERANK_MODEL, cache_dir=config.MODEL_CACHE_DIR)
        except Exception:
            _reranker = False
    return _reranker or None


def _embed_passages(texts):
    # Small batches: fastembed's default (256) makes the ONNX runtime grab ~1.8 GB on a
    # long paper, enough to crash a 2 GB server; 16 needs ~0.2 GB and gives identical vectors.
    vecs = np.array(list(embedder().passage_embed(texts, batch_size=16)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-9)


def upsert_document(conn, file, title, pages):
    """Replace a document's chunks. Returns the number of chunks written."""
    chunks = chunk_pages(pages)
    conn.execute("DELETE FROM docs WHERE file_id = ?", (file["id"],))
    conn.execute(
        "INSERT INTO docs (file_id, name, title, folder, mime, modified, link, n_pages, n_chars, indexed_at, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (file["id"], file["name"], title, file.get("folder", ""), file["mimeType"], file["modifiedTime"],
         file.get("webViewLink"), len(pages), sum(len(t) for _, t in pages), _now(), _now()),
    )
    if chunks:
        # title is embedded with each chunk so passages keep their paper's context
        vecs = _embed_passages([f"{title}\n{text}" for _, text in chunks])
        conn.executemany(
            "INSERT INTO chunks (file_id, page, ord, text, embedding) VALUES (?, ?, ?, ?, ?)",
            [(file["id"], page, i, text, vec.tobytes()) for i, ((page, text), vec) in enumerate(zip(chunks, vecs))],
        )
    conn.commit()
    return len(chunks)


def mark_seen(conn, files):
    """Record that these Drive files still exist (someone signed in could see them).
    Also refreshes name/folder/link, which can change without a content change."""
    now = _now()
    before = conn.total_changes
    conn.executemany(
        "UPDATE docs SET name = ?, folder = ?, link = ? WHERE file_id = ? "
        "AND (name IS NOT ? OR folder IS NOT ? OR link IS NOT ?)",
        [(f["name"], f.get("folder", ""), f.get("webViewLink"), f["id"],
          f["name"], f.get("folder", ""), f.get("webViewLink")) for f in files],
    )
    if conn.total_changes > before:  # renamed/moved papers: tell the app to reload the index
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('paths_changed_at', ?)", (now,))
    conn.executemany("UPDATE docs SET last_seen = ? WHERE file_id = ?", [(now, f["id"]) for f in files])
    conn.commit()


def version(conn):
    """Changes whenever the in-memory Index must be rebuilt (papers added/changed/
    removed, or papers renamed or moved in Drive)."""
    return conn.execute(
        "SELECT COUNT(*), MAX(indexed_at), (SELECT value FROM meta WHERE key = 'paths_changed_at') FROM docs"
    ).fetchone()


def purge_excluded(conn):
    """Remove indexed files that the current rules no longer cover: unsupported file
    types (e.g. .txt/.log) and anything inside an EXCLUDE_FOLDERS folder.
    Returns the number of files removed."""
    import drive

    rows = conn.execute("SELECT file_id, mime, folder FROM docs").fetchall()
    drop = [(fid,) for fid, mime, folder in rows
            if mime not in drive.SUPPORTED_MIME or drive.is_excluded_path(folder)]
    conn.executemany("DELETE FROM docs WHERE file_id = ?", drop)
    conn.commit()
    return len(drop)


def pending(conn, files):
    """Files in this Drive listing that are new or changed since they were indexed."""
    known = dict(conn.execute("SELECT file_id, modified FROM docs").fetchall())
    return [f for f in files if known.get(f["id"]) != f["modifiedTime"]]


def sync_with_drive(conn, service, files, progress=None):
    """Index new/changed files from `files` (a Drive listing made with the syncing
    user's own access).

    A file missing from one person's listing may just be one they can't see, so
    nothing is deleted on that basis. Papers no signed-in user has seen in Drive for
    PRUNE_AFTER_DAYS are removed instead; until then they're hidden from everyone
    anyway, because search only returns files in the searcher's own Drive listing.
    """
    import drive
    import extract

    excluded = purge_excluded(conn)
    mark_seen(conn, files)
    todo = pending(conn, files)
    added, failed = 0, []
    for i, f in enumerate(todo, start=1):
        if progress:
            progress(i, len(todo), f["name"])
        try:
            data = drive.download(service, f)
            title, pages = extract.extract(data, f["mimeType"], f["name"])
            upsert_document(conn, f, title, pages)
            added += 1
        except drive.SessionExpired:
            raise
        except Exception as e:  # one bad file must not stop the sync
            failed.append((f["name"], str(e)[:200]))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.PRUNE_AFTER_DAYS)).isoformat(timespec="seconds")
    removed = conn.execute("DELETE FROM docs WHERE last_seen < ?", (cutoff,)).rowcount
    conn.commit()
    return {"total": len(files), "indexed": added, "removed": removed, "excluded": excluded, "failed": failed}


class SparseBM25:
    """Okapi BM25 with the same formula and IDF floor as rank_bm25.BM25Okapi, stored as
    flat numpy posting lists instead of one Python dict per passage (~10x less memory)."""

    def __init__(self, corpus, k1=1.5, b=0.75, epsilon=0.25):
        vocab, doc_ids, term_ids, tfs = {}, array("i"), array("i"), array("f")
        doc_len = []
        for d, tokens in enumerate(corpus):
            doc_len.append(len(tokens))
            for term, n in Counter(tokens).items():
                doc_ids.append(d)
                term_ids.append(vocab.setdefault(term, len(vocab)))
                tfs.append(n)
        term_ids = np.frombuffer(term_ids, dtype=np.int32)
        order = np.argsort(term_ids, kind="stable")
        self.doc_ids = np.frombuffer(doc_ids, dtype=np.int32)[order]
        self.tfs = np.frombuffer(tfs, dtype=np.float32)[order]
        df = np.bincount(term_ids, minlength=len(vocab))
        self.starts = np.concatenate([[0], np.cumsum(df)])
        n_docs = len(doc_len)
        doc_len = np.array(doc_len, dtype=np.float32)
        idf = np.log(n_docs - df + 0.5) - np.log(df + 0.5)
        idf[idf < 0] = epsilon * idf.mean()
        self.idf = idf.astype(np.float32)
        self.norm = (k1 * (1 - b + b * doc_len / max(doc_len.mean(), 1e-9))).astype(np.float32)
        self.vocab, self.k1, self.n_docs = vocab, k1, n_docs

    def get_scores(self, query_tokens):
        scores = np.zeros(self.n_docs, dtype=np.float32)
        for term in query_tokens:
            t = self.vocab.get(term)
            if t is None:
                continue
            docs = self.doc_ids[self.starts[t]:self.starts[t + 1]]
            tf = self.tfs[self.starts[t]:self.starts[t + 1]]
            scores[docs] += self.idf[t] * tf * (self.k1 + 1) / (tf + self.norm[docs])
        return scores


class Index:
    """Everything needed for search, loaded into memory once per index version."""

    def __init__(self, conn):
        rows = conn.execute(
            "SELECT c.id, c.file_id, c.page, c.ord, c.text, c.embedding, d.title, d.name, d.link, d.folder "
            "FROM chunks c JOIN docs d ON d.file_id = c.file_id ORDER BY c.file_id, c.ord"
        ).fetchall()
        self.chunks = [
            {"id": r[0], "file_id": r[1], "page": r[2], "ord": r[3], "text": r[4],
             "title": r[6] or r[7], "name": r[7], "link": r[8], "folder": r[9] or ""}
            for r in rows
        ]
        self.by_id = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.file_ids = np.array([c["file_id"] for c in self.chunks], dtype=object)
        self.by_doc_ord = {(c["file_id"], c["ord"]): i for i, c in enumerate(self.chunks)}
        self.docs = [dict(zip(("file_id", "name", "title", "folder", "n_pages", "n_chars", "link", "modified"), r))
                     for r in conn.execute(
                         "SELECT file_id, name, title, folder, n_pages, n_chars, link, modified FROM docs ORDER BY title")]
        if rows:
            self.matrix = np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
            self.bm25 = SparseBM25(tokenize(f"{c['title']} {c['text']}") for c in self.chunks)
        else:
            self.matrix, self.bm25 = None, None

    def __len__(self):
        return len(self.chunks)

    def search(self, query, top_k=8, doc_filter=None, per_doc_cap=3, allowed_files=None):
        """Hybrid search. doc_filter: case-insensitive substring of title, filename or folder.
        allowed_files: if given, only passages from these Drive file IDs are returned."""
        if not self.chunks:
            return []
        allowed = None
        if allowed_files is not None:
            allowed = np.isin(self.file_ids, list(allowed_files))
        if doc_filter:
            f = doc_filter.lower()
            match = np.array([f in c["title"].lower() or f in c["name"].lower() or f in c["folder"].lower()
                              for c in self.chunks])
            allowed = match if allowed is None else allowed & match
        if allowed is not None and not allowed.any():
            return []

        n_cand = 60
        qvec = np.array(next(iter(embedder().query_embed([query]))), dtype=np.float32)
        qvec /= max(np.linalg.norm(qvec), 1e-9)
        dense = self.matrix @ qvec
        sparse = self.bm25.get_scores(tokenize(query))
        if allowed is not None:
            dense = np.where(allowed, dense, -np.inf)
            sparse = np.where(allowed, sparse, -np.inf)

        fused = {}
        for ranking in (np.argsort(-dense)[:n_cand], np.argsort(-sparse)[:n_cand]):
            for rank, idx in enumerate(ranking):
                if allowed is not None and not allowed[idx]:
                    continue
                fused[int(idx)] = fused.get(int(idx), 0.0) + 1.0 / (60 + rank)
        cands = sorted(fused, key=fused.get, reverse=True)[:40]

        rr = reranker()
        if rr and cands:
            # small batches keep the ONNX runtime's working memory low (~0.5 GB less than one batch of 40)
            scores = list(rr.rerank(query, [f"{self.chunks[i]['title']}\n{self.chunks[i]['text']}" for i in cands],
                                    batch_size=8))
            order = sorted(zip(cands, scores), key=lambda x: x[1], reverse=True)
        else:
            order = [(i, fused[i]) for i in cands]

        results, per_doc = [], {}
        for idx, score in order:
            c = self.chunks[idx]
            if per_doc.get(c["file_id"], 0) >= per_doc_cap:
                continue
            per_doc[c["file_id"]] = per_doc.get(c["file_id"], 0) + 1
            # ms-marco cross-encoder logits well below 0 mean "probably not about this"
            results.append({**c, "score": float(score), "weak": bool(rr) and score < -5})
            if len(results) >= top_k:
                break
        return results

    def neighbors(self, chunk_id, window=1):
        """The chunk plus `window` chunks before/after it in the same document."""
        i = self.by_id.get(chunk_id)
        if i is None:
            return []
        c = self.chunks[i]
        out = []
        for o in range(c["ord"] - window, c["ord"] + window + 1):
            j = self.by_doc_ord.get((c["file_id"], o))
            if j is not None:
                out.append(self.chunks[j])
        return out


class UserView:
    """The index as one user is allowed to see it: only papers in their own Drive
    listing. Exposes the same interface the assistant uses (search/neighbors/docs)."""

    def __init__(self, index, allowed_files):
        self.index = index
        self.allowed = set(allowed_files)
        self.docs = [d for d in index.docs if d["file_id"] in self.allowed]
        self.n_chunks = sum(1 for c in index.chunks if c["file_id"] in self.allowed)

    def __len__(self):
        return self.n_chunks

    def search(self, query, **kwargs):
        return self.index.search(query, allowed_files=self.allowed, **kwargs)

    def neighbors(self, chunk_id, window=1):
        return [c for c in self.index.neighbors(chunk_id, window) if c["file_id"] in self.allowed]
