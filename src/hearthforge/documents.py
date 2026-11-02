"""Document adapters. Extraction is bounded, keeps locations, and never claims more than it did.

All extracted content is UNTRUSTED data and must be presented to models as such.
"""
from __future__ import annotations

import csv
import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_CHARS_DEFAULT = 60_000
MAX_ZIP_ENTRY = 20_000_000  # zip-bomb guard (uncompressed bytes per XML part)

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".html", ".css", ".scss", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb",
    ".php", ".sh", ".bat", ".ps1", ".sql", ".xml", ".log", ".env.example", ".gradle", ".kt", ".swift", ".lua", ".vue",
    ".svelte", ".tf", ".dockerfile", ".gitignore", ".lock",
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass
class Extracted:
    path: str
    kind: str
    text: str = ""
    supported: bool = True
    truncated: bool = False
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    needs: str = ""  # what is required when unsupported/limited
    locations: list[dict] = field(default_factory=list)  # [{"label": "page 3", "start": 120, "end": 980}]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _cap(text: str, limit: int) -> tuple[str, bool]:
    return (text[:limit], True) if len(text) > limit else (text, False)


def _zip_xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    info = z.getinfo(name)
    if info.file_size > MAX_ZIP_ENTRY:
        raise ValueError(f"{name} too large")
    return ET.fromstring(z.read(name))


def _texts(el: ET.Element, tag_suffix: str) -> list[str]:
    return [t.text or "" for t in el.iter() if t.tag.endswith(tag_suffix)]


def _para_texts(root: ET.Element) -> list[str]:
    paras = []
    for p in root.iter():
        if p.tag.endswith("}p"):
            paras.append("".join(t.text or "" for t in p.iter() if t.tag.endswith("}t")))
    return paras


def extract(path: str | Path, max_chars: int = MAX_CHARS_DEFAULT, rel: str | None = None) -> Extracted:
    p = Path(path)
    name = rel or p.name
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(p, name, max_chars)
        if ext == ".docx":
            return _docx(p, name, max_chars)
        if ext == ".xlsx":
            return _xlsx(p, name, max_chars)
        if ext == ".pptx":
            return _pptx(p, name, max_chars)
        if ext in {".csv", ".tsv"}:
            return _csv(p, name, max_chars)
        if ext in IMAGE_EXT:
            return _image(p, name)
        if ext in {".doc", ".xls", ".ppt", ".odt", ".rtf"}:
            return Extracted(name, ext[1:], supported=False,
                             needs="Legacy/other office format: convert to .docx/.xlsx/.pptx/.pdf or install an adapter.")
        return _text(p, name, max_chars)
    except zipfile.BadZipFile:
        return Extracted(name, ext[1:] or "file", supported=False, warnings=["File is not a valid Office/zip container"])
    except Exception as e:  # adapters must never crash the agent
        return Extracted(name, ext[1:] or "file", supported=False, warnings=[f"Extraction failed: {type(e).__name__}: {e}"])


def _text(p: Path, name: str, limit: int) -> Extracted:
    data = p.read_bytes()[: limit * 4 + 1]
    if b"\x00" in data[:8192]:
        return Extracted(name, "binary", supported=False, needs="Binary file type with no adapter installed.")
    text = data.decode("utf-8", errors="replace")
    text, trunc = _cap(text, limit)
    kind = "markdown" if p.suffix.lower() in {".md", ".markdown"} else "text"
    return Extracted(name, kind, text, truncated=trunc, metadata={"lines": text.count("\n") + 1, "bytes": p.stat().st_size})


def _csv(p: Path, name: str, limit: int) -> Extracted:
    raw = p.read_bytes()[: limit * 4].decode("utf-8", errors="replace")
    delim = "\t" if p.suffix.lower() == ".tsv" else (csv.Sniffer().sniff(raw[:4096], ",;\t|").delimiter if raw.strip() else ",")
    rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
    header = rows[0] if rows else []
    body = "\n".join(" | ".join(r) for r in rows[:500])
    text, trunc = _cap(body, limit)
    return Extracted(name, "csv", text, truncated=trunc or len(rows) > 500,
                     metadata={"columns": header, "rows_read": min(len(rows), 500)})


def _pdf(p: Path, name: str, limit: int) -> Extracted:
    try:
        from pypdf import PdfReader
    except ImportError:
        return Extracted(name, "pdf", supported=False, needs="Install the 'pypdf' package (pip install hearthforge[docs]).")
    reader = PdfReader(str(p))
    if reader.is_encrypted:
        return Extracted(name, "pdf", supported=False, warnings=["PDF is encrypted"], needs="Decrypt the PDF first.")
    parts, locs, pos, empty = [], [], 0, 0
    for i, page in enumerate(reader.pages, 1):
        t = (page.extract_text() or "").strip()
        if not t:
            empty += 1
        chunk = f"\n--- page {i} ---\n{t}"
        locs.append({"label": f"page {i}", "start": pos, "end": pos + len(chunk)})
        parts.append(chunk)
        pos += len(chunk)
        if pos > limit:
            break
    text, trunc = _cap("".join(parts), limit)
    ex = Extracted(name, "pdf", text, truncated=trunc or len(parts) < len(reader.pages),
                   metadata={"pages": len(reader.pages), "pages_read": len(parts)}, locations=locs)
    if empty and empty == len(parts):
        ex.warnings.append("No extractable text: this looks like a scanned PDF.")
        ex.needs = "OCR (e.g. install Tesseract) or a vision-capable model with page images. OCR is not built in."
        ex.supported = False
    elif empty:
        ex.warnings.append(f"{empty} page(s) had no extractable text (possibly scanned).")
    return ex


def _docx(p: Path, name: str, limit: int) -> Extracted:
    with zipfile.ZipFile(p) as z:
        root = _zip_xml(z, "word/document.xml")
    paras = [t for t in _para_texts(root)]
    text, trunc = _cap("\n".join(paras), limit)
    return Extracted(name, "docx", text, truncated=trunc, metadata={"paragraphs": len(paras)},
                     warnings=["Tables/headers/comments are flattened; layout is not preserved."])


def _xlsx(p: Path, name: str, limit: int) -> Extracted:
    with zipfile.ZipFile(p) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = _zip_xml(z, "xl/sharedStrings.xml")
            shared = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in sst if si.tag.endswith("}si")]
        wb = _zip_xml(z, "xl/workbook.xml")
        sheets = [s.attrib.get("name", "?") for s in wb.iter() if s.tag.endswith("}sheet")]
        out, n = [], 0
        for idx, sname in enumerate(sheets, 1):
            part = f"xl/worksheets/sheet{idx}.xml"
            if part not in z.namelist():
                continue
            out.append(f"--- sheet: {sname} ---")
            root = _zip_xml(z, part)
            for row in (r for r in root.iter() if r.tag.endswith("}row")):
                cells = []
                for c in (c for c in row if c.tag.endswith("}c")):
                    v = next((x.text for x in c if x.tag.endswith("}v")), None)
                    isv = next((x for x in c if x.tag.endswith("}is")), None)
                    if c.attrib.get("t") == "s" and v is not None and v.isdigit() and int(v) < len(shared):
                        v = shared[int(v)]
                    elif isv is not None:
                        v = "".join(t.text or "" for t in isv.iter() if t.tag.endswith("}t"))
                    cells.append(v or "")
                out.append(" | ".join(cells))
                n += 1
                if n >= 1000:
                    break
    text, trunc = _cap("\n".join(out), limit)
    return Extracted(name, "xlsx", text, truncated=trunc or n >= 1000, metadata={"sheets": sheets},
                     warnings=["Formulas are not evaluated; cached values are shown."])


def _pptx(p: Path, name: str, limit: int) -> Extracted:
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for i, n in enumerate(slides, 1):
            out.append(f"--- slide {i} ---")
            out.extend(t for t in _para_texts(_zip_xml(z, n)) if t.strip())
    text, trunc = _cap("\n".join(out), limit)
    return Extracted(name, "pptx", text, truncated=trunc, metadata={"slides": len(slides)},
                     warnings=["Images and charts inside slides are not interpreted."])


def _image(p: Path, name: str) -> Extracted:
    head = p.read_bytes()[:32]
    w = h = None
    try:
        if head.startswith(b"\x89PNG"):
            w, h = struct.unpack(">II", head[16:24])
        elif head[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", head[6:10])
    except struct.error:
        pass
    md = {"bytes": p.stat().st_size, "width": w, "height": h}
    return Extracted(name, "image", "", supported=False, metadata=md,
                     needs="A vision-capable model (declare it in provider settings) is required to interpret image content; OCR is not built in.")


def image_data_url(path: str | Path, max_bytes: int = 4_000_000) -> str | None:
    import base64
    p = Path(path)
    if p.stat().st_size > max_bytes:
        return None
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(p.suffix.lower())
    if not mime:
        return None
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
