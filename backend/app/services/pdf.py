"""A tiny text-only PDF writer (A4, Helvetica), enough for a situation report
without adding a PDF library. Text is Latin-1/cp1252; anything else becomes '?'."""
from __future__ import annotations

import textwrap

W, H, MARGIN, LEAD = 595, 842, 50, 14


def _esc(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build(lines: list[tuple[str, str]]) -> bytes:
    """lines: (style, text) with style 'h1' | 'h2' | 'p' | 'small' | 'gap'."""
    pages: list[list[str]] = [[]]
    y = H - MARGIN

    def put(font: str, size: int, text: str, indent: int = 0) -> None:
        nonlocal y
        if y < MARGIN + size:
            pages.append([]); y = H - MARGIN
        pages[-1].append(f"BT /{font} {size} Tf {MARGIN + indent} {y} Td ({_esc(text)}) Tj ET")
        y -= int(size * 1.4)

    for style, text in lines:
        if style == "gap":
            y -= LEAD // 2; continue
        if style in ("h1", "h2") and y < H - MARGIN:
            y -= 8                                    # air above a heading
        font, size, width = {"h1": ("F2", 16, 60), "h2": ("F2", 11.5, 80), "p": ("F1", 10, 98),
                             "small": ("F1", 8.5, 118)}[style]
        for i, chunk in enumerate(textwrap.wrap(text, width) or [""]):
            put(font, int(size), chunk, 0 if i == 0 or style != "p" else 10)
        if style == "h2":
            y -= 2

    objs: list[bytes] = []
    def add(b: bytes) -> int:
        objs.append(b); return len(objs)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages)          # reserved after page/content pairs
    kids = []
    for content in pages:
        stream = "\n".join(content).encode("latin-1")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        p = add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_id, W, H, f1, f2, c))
        kids.append(p)
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))) == pages_id
    cat = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    return bytes(out)
