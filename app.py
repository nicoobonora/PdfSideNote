import os
import io
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from flask import Flask, request, send_file, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB limit

# Output page is A4 landscape: slide on left, grid notes on right
PAGE_W, PAGE_H = A4[1], A4[0]  # landscape A4
MARGIN = 10 * mm


def parse_grid_style(style_str):
    """Parse 'grid-5', 'lines-7', or 'blank' into (mode, spacing_mm)."""
    if style_str == "blank":
        return "blank", 0
    parts = style_str.split("-", 1)
    mode = parts[0]  # "grid" or "lines"
    spacing = int(parts[1]) if len(parts) > 1 else 5
    return mode, spacing


def build_grid_pdf(grid_x, grid_y, grid_w, grid_h, mode="grid", spacing_mm=5):
    """Return a single-page PDF (as bytes) with the chosen ruling style."""
    if mode == "blank":
        # empty page, no lines at all
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
        c.showPage()
        c.save()
        buf.seek(0)
        return buf.read()

    spacing = spacing_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setStrokeColorRGB(0.75, 0.82, 0.92)  # light blue
    c.setLineWidth(0.3)

    if mode == "grid":
        # vertical lines
        x = grid_x
        while x <= grid_x + grid_w + 0.1:
            c.line(x, grid_y, x, grid_y + grid_h)
            x += spacing
        # horizontal lines
        y = grid_y
        while y <= grid_y + grid_h + 0.1:
            c.line(grid_x, y, grid_x + grid_w, y)
            y += spacing
    elif mode == "lines":
        # horizontal lines only
        y = grid_y
        while y <= grid_y + grid_h + 0.1:
            c.line(grid_x, y, grid_x + grid_w, y)
            y += spacing

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def process_pdf(input_bytes, grid_style="grid-5"):
    mode, spacing_mm = parse_grid_style(grid_style)

    src = fitz.open(stream=input_bytes, filetype="pdf")
    out = fitz.open()  # new blank PDF

    half_w = PAGE_W / 2
    slide_area_w = half_w - MARGIN * 1.5  # left margin + center gap
    slide_area_h = PAGE_H - MARGIN * 2

    # grid occupies the right half
    grid_x = half_w + MARGIN * 0.5
    grid_y = MARGIN
    grid_w = half_w - MARGIN * 1.5
    grid_h = PAGE_H - MARGIN * 2

    # pre-build a one-page grid PDF to reuse
    grid_pdf_bytes = build_grid_pdf(grid_x, grid_y, grid_w, grid_h, mode, spacing_mm)
    grid_doc = fitz.open(stream=grid_pdf_bytes, filetype="pdf")

    for page_num in range(len(src)):
        src_page = src[page_num]
        src_rect = src_page.rect  # original page dimensions

        # calculate scale to fit slide into left half
        scale_x = slide_area_w / src_rect.width
        scale_y = slide_area_h / src_rect.height
        scale = min(scale_x, scale_y)

        rendered_w = src_rect.width * scale
        rendered_h = src_rect.height * scale

        # center the slide vertically in the left half
        x0 = MARGIN
        y0 = MARGIN + (slide_area_h - rendered_h) / 2
        dest_rect = fitz.Rect(x0, y0, x0 + rendered_w, y0 + rendered_h)

        # create new landscape A4 page
        new_page = out.new_page(width=PAGE_W, height=PAGE_H)

        # draw a subtle border around the slide
        shape = new_page.new_shape()
        shape.draw_rect(dest_rect)
        shape.finish(color=(0.8, 0.8, 0.8), width=0.5)
        shape.commit()

        # place the original slide
        new_page.show_pdf_page(dest_rect, src, page_num)

        # overlay the grid from our pre-built PDF
        new_page.show_pdf_page(
            fitz.Rect(0, 0, PAGE_W, PAGE_H), grid_doc, 0
        )

    result_bytes = out.tobytes(deflate=True, garbage=4)
    src.close()
    out.close()
    grid_doc.close()
    return result_bytes


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    if "pdf" not in request.files:
        return "No file uploaded", 400
    f = request.files["pdf"]
    if not f.filename.lower().endswith(".pdf"):
        return "Please upload a PDF file", 400

    grid_style = request.form.get("grid_style", "grid-5")
    input_bytes = f.read()
    result = process_pdf(input_bytes, grid_style)

    base = os.path.splitext(f.filename)[0]
    return send_file(
        io.BytesIO(result),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{base}_notes.pdf",
    )


if __name__ == "__main__":
    import sys
    debug = "--debug" in sys.argv
    print("Starting PdfSideNote on http://localhost:5050")
    app.run(debug=debug, host="0.0.0.0", port=5050)
