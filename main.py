from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import fitz
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"ok": True}

@app.post("/render")
async def render_page(
    pdf: UploadFile = File(...),
    page: int = Form(0)
):
    data = await pdf.read()
    doc = fitz.open(stream=data, filetype="pdf")
    p = doc[page]
    pix = p.get_pixmap(matrix=fitz.Matrix(2, 2))
    png = pix.tobytes("png")
    doc.close()
    return Response(content=png, media_type="image/png")

@app.post("/extract")
async def extract_text(
    pdf: UploadFile = File(...),
    page: int = Form(0)
):
    data = await pdf.read()
    doc = fitz.open(stream=data, filetype="pdf")
    p = doc[page]
    items = []
    for b in p.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                items.append({
                    "text": span["text"],
                    "x": span["bbox"][0],
                    "y": span["bbox"][1],
                    "x1": span["bbox"][2],
                    "y1": span["bbox"][3],
                    "size": span["size"],
                    "color": span.get("color", 0),
                    "font": span.get("font", ""),
                    "flags": span.get("flags", 0),
                })
    pageWidth = p.rect.width
    pageHeight = p.rect.height
    doc.close()
    return {"items": items, "pageWidth": pageWidth, "pageHeight": pageHeight}

@app.post("/edit-batch")
async def edit_batch(
    pdf: UploadFile = File(...),
    edits: str = Form(...),
):
    data = await pdf.read()
    doc = fitz.open(stream=data, filetype="pdf")
    edits_list = json.loads(edits)

    for edit in edits_list:
        page_num = edit["page"] - 1
        p = doc[page_num]
        x    = float(edit["x"])
        y    = float(edit["y"])
        x1   = float(edit["x1"])
        y1   = float(edit["y1"])
        size = float(edit.get("size", 12))
        new_text = edit["newText"]

        rect = fitz.Rect(x, y, x1, y1)

        # Löscht NUR Text-Pixel — Hintergrund, Farben, Bilder bleiben erhalten
        p.add_redact_annot(rect)
        p.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE
        )

        if new_text.strip():
            color_int = int(edit.get("color", 0))
            r = ((color_int >> 16) & 255) / 255
            g = ((color_int >> 8) & 255) / 255
            b = (color_int & 255) / 255

            flags = int(edit.get("flags", 0))
            font_name = (edit.get("font") or "").lower()
            is_bold   = bool(flags & 16) or "bold"   in font_name
            is_italic = bool(flags & 2)  or "italic" in font_name or "oblique" in font_name
            is_mono   = bool(flags & 8)  or "mono"   in font_name or "courier" in font_name
            is_serif  = bool(flags & 4)  or "times"  in font_name or "serif"   in font_name or "roman" in font_name

            if is_mono:
                fontname = "cobo" if is_bold and is_italic else "cobi" if is_italic else "cob" if is_bold else "cour"
                fontname = {"cobo":"cobo","cobi":"cobi","cob":"cob","cour":"cour"}[fontname]
            elif is_serif:
                fontname = "tibo" if is_bold and is_italic else "tibi" if is_italic else "tibo" if is_bold else "tiro"
                fontname = "tibo" if is_bold else ("tibi" if is_italic else "tiro")
            else:
                fontname = "hebo" if is_bold and is_italic else "hebi" if is_italic else "hebo" if is_bold else "helv"
                fontname = "hebo" if is_bold else ("hebi" if is_italic else "helv")

            p.insert_text(
                (x, y1 - (y1 - y) * 0.15),
                new_text,
                fontsize=size,
                fontname=fontname,
                color=(r, g, b)
            )

    buf = doc.tobytes()
    doc.close()
    return Response(content=buf, media_type="application/pdf")
