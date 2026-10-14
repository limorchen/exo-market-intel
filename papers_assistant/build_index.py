"""Index a local folder of PDFs/DOCX/TXT from the command line (for testing).

  python build_index.py DIR

The real library is synced from Google Drive inside the app, with the signed-in
user's own Drive access (there is no stored credential for a command-line sync).
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import config
import extract
import index as idx

LOCAL_MIME = {".pdf": extract.PDF, ".docx": extract.DOCX, ".txt": "text/plain", ".md": "text/markdown"}


def progress(i, n, name):
    print(f"[{i}/{n}] {name}", flush=True)


def index_local(conn, root):
    root = Path(root)
    files = [p for p in root.rglob("*") if p.suffix.lower() in LOCAL_MIME]
    for i, p in enumerate(files, start=1):
        progress(i, len(files), p.name)
        f = {
            "id": f"local:{p.relative_to(root).as_posix()}",
            "name": p.name,
            "mimeType": LOCAL_MIME[p.suffix.lower()],
            "modifiedTime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "webViewLink": None,
            "folder": p.parent.relative_to(root).as_posix().strip("."),
        }
        title, pages = extract.extract(p.read_bytes(), f["mimeType"], p.name)
        n = idx.upsert_document(conn, f, title, pages)
        print(f"    {title[:80]!r}: {len(pages)} pages, {n} passages")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="local folder of papers to index")
    args = ap.parse_args()
    conn = idx.connect()
    index_local(conn, args.folder)
    docs, chunks = conn.execute("SELECT (SELECT COUNT(*) FROM docs), (SELECT COUNT(*) FROM chunks)").fetchone()
    print(f"Index: {docs} papers, {chunks} passages -> {config.INDEX_DB}")


if __name__ == "__main__":
    main()
