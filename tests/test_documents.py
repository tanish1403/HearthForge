import struct
import zipfile
import zlib

from hearthforge.documents import extract

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_text_and_binary(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n")
    assert extract(tmp_path / "a.py").text.startswith("print")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    r = extract(tmp_path / "b.bin")
    assert not r.supported and r.needs


def test_truncation_is_reported(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 5000)
    r = extract(tmp_path / "big.txt", max_chars=100)
    assert r.truncated and len(r.text) == 100


def test_csv(tmp_path):
    (tmp_path / "d.csv").write_text("name,age\nada,36\nbob,41\n")
    r = extract(tmp_path / "d.csv")
    assert r.metadata["columns"] == ["name", "age"] and "ada | 36" in r.text


def test_docx(tmp_path):
    p = tmp_path / "x.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f'<w:document {W}><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p></w:body></w:document>')
    r = extract(p)
    assert r.text == "Hello\nWorld" and r.kind == "docx"


def test_xlsx_with_shared_strings(tmp_path):
    p = tmp_path / "x.xlsx"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns}><sheets><sheet name="Data" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}><si><t>Name</t></si><si><t>Ada</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData><row><c t="s"><v>0</v></c><c><v>5</v></c></row><row><c t="s"><v>1</v></c><c><v>7</v></c></row></sheetData></worksheet>')
    r = extract(p)
    assert "Name | 5" in r.text and "Ada | 7" in r.text and r.metadata["sheets"] == ["Data"]


def test_pptx(tmp_path):
    p = tmp_path / "x.pptx"
    A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", f'<p {A}><a:p><a:r><a:t>Title slide</a:t></a:r></a:p></p>')
        z.writestr("ppt/slides/slide2.xml", f'<p {A}><a:p><a:r><a:t>Second</a:t></a:r></a:p></p>')
    r = extract(p)
    assert "--- slide 1 ---" in r.text and "Second" in r.text and r.metadata["slides"] == 2


def test_corrupt_office_file_degrades_gracefully(tmp_path):
    (tmp_path / "bad.docx").write_text("not a zip")
    r = extract(tmp_path / "bad.docx")
    assert not r.supported and r.warnings


def test_legacy_office_reports_what_is_needed(tmp_path):
    (tmp_path / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    r = extract(tmp_path / "old.doc")
    assert not r.supported and "convert" in r.needs.lower()


def test_png_metadata_and_no_false_vision_claim(tmp_path):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
    (tmp_path / "i.png").write_bytes(png)
    r = extract(tmp_path / "i.png")
    assert r.metadata["width"] == 3 and r.metadata["height"] == 2
    assert not r.supported and "vision" in r.needs


def test_blank_pdf_is_flagged_as_scanned(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(100, 100)
    with open(tmp_path / "s.pdf", "wb") as f:
        w.write(f)
    r = extract(tmp_path / "s.pdf")
    assert not r.supported and "OCR" in r.needs and r.metadata["pages"] == 1
