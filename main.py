from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import fitz

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
    doc.close()
    return {"items": items}

@app.post("/edit")
async def edit_text(
    pdf: UploadFile = File(...),
    page: int = Form(0),
    x: float = Form(...),
    y: float = Form(...),
    x1: float = Form(...),
    y1: float = Form(...),
    old_text: str = Form(...),
    new_text: str = Form(...),
    font_size: float = Form(12),
):
    data = await pdf.read()
    doc = fitz.open(stream=data, filetype="pdf")
    p = doc[page]
    rect = fitz.Rect(x - 1, y - 1, x1 + 1, y1 + 1)
    p.draw_rect(rect, color=(1,1,1), fill=(1,1,1))
    if new_text.strip():
        p.insert_text((x, y1 - 1), new_text, fontsize=font_size, color=(0,0,0))
    buf = doc.tobytes()
    doc.close()
    return Response(content=buf, media_type="application/pdf")
