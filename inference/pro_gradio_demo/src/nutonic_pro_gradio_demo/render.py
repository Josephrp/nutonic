from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from nutonic_pro_gradio_demo.models import ProVlmBoundingBox


def decode_image(image_bytes: bytes) -> Image.Image:
    img = Image.open(BytesIO(image_bytes))
    return img.convert("RGB")


def encode_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_boxes(img: Image.Image, boxes: list[ProVlmBoundingBox]) -> Image.Image:
    if not boxes:
        return img
    out = img.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    font = _default_font()
    for box in boxes:
        x1n, y1n, x2n, y2n = (box.bbox + [0.0, 0.0, 0.0, 0.0])[:4]
        x1 = max(0, min(w, int(x1n * w)))
        y1 = max(0, min(h, int(y1n * h)))
        x2 = max(0, min(w, int(x2n * w)))
        y2 = max(0, min(h, int(y2n * h)))
        if x2 <= x1 or y2 <= y1:
            continue
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=3)
        label = box.label
        if box.confidence is not None:
            label = f"{label} ({box.confidence:.2f})"
        if label:
            _draw_label(draw=draw, x=x1, y=y1, text=label, font=font)
    return out


def _draw_label(*, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont | None) -> None:
    pad = 4
    if font is None:
        tw, th = draw.textbbox((0, 0), text)[2:]
    else:
        tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    box = [x, max(0, y - th - 2 * pad), x + tw + 2 * pad, y]
    draw.rectangle(box, fill=(255, 0, 0))
    draw.text((x + pad, box[1] + pad), text, fill=(255, 255, 255), font=font)


def _default_font() -> ImageFont.ImageFont | None:
    try:
        return ImageFont.load_default()
    except Exception:
        return None

