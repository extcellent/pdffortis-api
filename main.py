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
                    "x":    span["bbox"][0],
                    "y":    span["bbox"][1],
                    "x1":   span["bbox"][2],
                    "y1":   span["bbox"][3],
                    "size": span["size"],
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
            p.insert_text(
                (x, y1 - (y1 - y) * 0.15),
                new_text,
                fontsize=size,
                color=(0, 0, 0)
            )

    buf = doc.tobytes()
    doc.close()
    return Response(content=buf, media_type="application/pdf")
