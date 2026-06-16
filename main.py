from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
import fitz
import json
import os
import uuid
import httpx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================================================================
# Translation config — set in Render Dashboard → Environment Variables
# ====================================================================
AZURE_KEY     = os.environ.get("AZURE_TRANSLATOR_KEY", "").strip()
AZURE_REGION  = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
AZURE_ENDPOINT = os.environ.get(
    "AZURE_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com"
).strip().rstrip("/")

LIBRE_ENDPOINT = os.environ.get(
    "LIBRE_TRANSLATE_URL",
    "https://libretranslate.de/translate"
).strip()

HTTP_TIMEOUT = 12.0


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/translate/health")
def translate_health():
    return {
        "azure": bool(AZURE_KEY and AZURE_REGION),
        "mymemory": True,
        "libre": True,
        "providers_order": ["azure", "mymemory", "libre"],
    }


# ====================================================================
# Provider implementations
# ====================================================================
async def _try_azure(texts, src, tgt):
    if not (AZURE_KEY and AZURE_REGION):
        return None
    url = f"{AZURE_ENDPOINT}/translate?api-version=3.0&to={tgt}"
    if src and src != "auto":
        url += f"&from={src}"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-Type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    body = [{"Text": t} for t in texts]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(url, headers=headers, json=body)
    if r.status_code != 200:
        return None
    data = r.json()
    out = []
    for entry in data:
        translations = entry.get("translations") or []
        out.append(translations[0]["text"] if translations else "")
    return out


async def _try_mymemory(texts, src, tgt):
    out = []
    src_use = src if (src and src != "auto") else "auto"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for t in texts:
            s = src_use if src_use != "auto" else "en"
            params = {"q": t, "langpair": f"{s}|{tgt}"}
            try:
                r = await c.get("https://api.mymemory.translated.net/get", params=params)
                if r.status_code != 200:
                    return None
                j = r.json()
                translated = j.get("responseData", {}).get("translatedText", "")
                if j.get("responseStatus") not in (200, "200"):
                    return None
                out.append(translated)
            except Exception:
                return None
    return out


async def _try_libre(texts, src, tgt):
    out = []
    s = src if (src and src != "auto") else "auto"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for t in texts:
            try:
                r = await c.post(LIBRE_ENDPOINT, json={
                    "q": t, "source": s, "target": tgt, "format": "text"
                })
                if r.status_code != 200:
                    return None
                j = r.json()
                out.append(j.get("translatedText", ""))
            except Exception:
                return None
    return out


# ====================================================================
# /translate — main translation endpoint
# ====================================================================
@app.post("/translate")
async def translate(
    texts: str = Form(...),
    source: str = Form("auto"),
    target: str = Form("de"),
):
    try:
        arr = json.loads(texts)
        if not isinstance(arr, list):
            raise ValueError("texts must be JSON array")
        arr = [str(x) for x in arr]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid 'texts' payload: {e}")

    if not arr:
        return {"translated": [], "provider": "none"}

    for name, fn in (("azure", _try_azure), ("mymemory", _try_mymemory), ("libre", _try_libre)):
        try:
            result = await fn(arr, source, target)
        except Exception:
            result = None
        if result is not None and len(result) == len(arr) and any(x for x in result):
            return {"translated": result, "provider": name}

    return JSONResponse(
        status_code=503,
        content={"translated": None, "provider": "exhausted",
                 "message": "All server providers unavailable — use local model"},
    )


# ====================================================================
# Existing endpoints (UNCHANGED)
# ====================================================================
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
        x = float(edit["x"])
        y = float(edit["y"])
        x1 = float(edit["x1"])
        y1 = float(edit["y1"])
        size = float(edit.get("size", 12))
        new_text = edit["newText"]

        rect = fitz.Rect(x, y, x1, y1)

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
            is_bold = bool(flags & 16) or "bold" in font_name
            is_italic = bool(flags & 2) or "italic" in font_name or "oblique" in font_name
            is_mono = bool(flags & 8) or "mono" in font_name or "courier" in font_name
            is_serif = bool(flags & 4) or "times" in font_name or "serif" in font_name or "roman" in font_name

            if is_mono:
                fontname = "cobo" if is_bold and is_italic else "cobi" if is_italic else "cob" if is_bold else "cour"
            elif is_serif:
                fontname = "tibo" if is_bold else ("tibi" if is_italic else "tiro")
            else:
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
