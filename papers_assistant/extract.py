"""Turn downloaded files into page-numbered text plus a best-guess title."""
import io
import re

from drive import GDOC_MIME

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _clean(text):
    text = text.replace("\x00", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(data, mime, filename):
    """Returns (title, [(page_number, text), ...]). Non-PDF formats are one 'page'."""
    if mime == PDF:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                pages.append((i, _clean(page.extract_text() or "")))
            except Exception:
                pages.append((i, ""))
        title = None
        try:
            meta_title = (reader.metadata or {}).get("/Title")
            if meta_title and len(str(meta_title).strip()) > 8:
                title = str(meta_title).strip()
        except Exception:
            pass
        return title or _guess_title(pages, filename), pages

    if mime == DOCX:
        import docx
        doc = docx.Document(io.BytesIO(data))
        text = _clean("\n".join(p.text for p in doc.paragraphs))
        title = (doc.core_properties.title or "").strip() or None
        pages = [(1, text)]
        return title or _guess_title(pages, filename), pages

    # Google Doc export / plain text / markdown
    text = _clean(data.decode("utf-8", errors="replace"))
    pages = [(1, text)]
    return _guess_title(pages, filename), pages


def _guess_title(pages, filename):
    """First substantial line of the first page, else the filename."""
    for _, text in pages[:1]:
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if 20 <= len(line) <= 250 and not re.match(r"^(doi|http|www\.|©|received|journal)", line, re.I):
                return line
    return re.sub(r"\.(pdf|docx|txt|md)$", "", filename, flags=re.I)
