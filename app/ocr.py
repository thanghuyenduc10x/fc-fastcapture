"""
ocr.py — text extraction backend for Mode 7 ("Quét lấy chữ", v1.5).

Sends a captured image to a vision model via OpenRouter (one API key routes to
Gemini / GPT-4o / Claude / Qwen-VL …) and returns the recognised text. Chosen
over per-OS local OCR because it is ONE code path for macOS + Windows, has
excellent Vietnamese (the OS Windows OCR lacks a vi language pack), needs no
heavy bundle, and can also translate/format later.

Design:
  • PURE + Qt-free + no third-party deps (urllib only) → unit-testable by
    mocking urlopen, and trivial to bundle with PyInstaller.
  • The image NEVER leaves the machine except to OpenRouter → the caller must
    tell the user this (Settings note); do not use for sensitive content.
  • The API key is passed in by the caller (from config, entered by the user in
    Settings). It is NEVER hard-coded, committed, or logged.

Backend interface (strategy pattern) so a future offline Apple Vision backend
can be swapped in on macOS without touching callers.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"

# Prompt tuned for "give me exactly the text, nothing else" — no commentary,
# no markdown fences, keep line breaks. Vietnamese instruction (the user base).
DEFAULT_PROMPT = (
    "Bạn là công cụ OCR. Trích xuất CHÍNH XÁC toàn bộ văn bản xuất hiện trong "
    "ảnh, giữ nguyên thứ tự và ngắt dòng hợp lý. CHỈ trả về đúng văn bản đó — "
    "không thêm lời giải thích, không thêm dấu ``` hay định dạng markdown. Nếu "
    "ảnh không có chữ nào, trả về chuỗi rỗng."
)


class OcrError(Exception):
    """User-facing error (message is already Vietnamese, safe to show)."""


def _pil_to_data_url(pil_image):
    buf = io.BytesIO()
    img = pil_image
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/png;base64," + b64


def build_payload(pil_image, model, prompt=DEFAULT_PROMPT):
    """The JSON body sent to OpenRouter (split out so tests can assert it
    without any network)."""
    return {
        "model": model or DEFAULT_MODEL,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": _pil_to_data_url(pil_image)}},
            ],
        }],
    }


def parse_response(raw_text):
    """Extract the text from an OpenRouter chat-completion JSON string.
    Handles both `content: "..."` and `content: [{type:text,text:...}]`."""
    obj = json.loads(raw_text)
    if isinstance(obj.get("error"), dict):
        raise OcrError("OCR báo lỗi: %s"
                       % obj["error"].get("message", "không rõ"))
    msg = obj["choices"][0]["message"]["content"]
    if isinstance(msg, list):
        msg = "".join(p.get("text", "") for p in msg if isinstance(p, dict))
    return (msg or "").strip()


def _open(req, timeout):
    # Seam for tests to monkeypatch (urlopen is hard to patch cleanly).
    return urllib.request.urlopen(req, timeout=timeout)


def extract_text(pil_image, api_key, model=DEFAULT_MODEL, timeout=30,
                 prompt=DEFAULT_PROMPT):
    """Return recognised text (may be ""). Raise OcrError (Vietnamese message)
    on any failure. Runs synchronously — call from a worker thread."""
    if not api_key:
        raise OcrError("Chưa có API key OpenRouter — mở Settings để nhập.")
    body = json.dumps(build_payload(pil_image, model, prompt)).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            # OpenRouter asks apps to identify themselves (optional but polite).
            "HTTP-Referer": "https://10x-lifeos.com/fc-fastcapture/",
            "X-Title": "FC-FastCapture",
        })
    try:
        with _open(req, timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")) \
                .get("error", {}).get("message", "")
        except Exception:
            pass
        if e.code == 401:
            raise OcrError("API key sai hoặc hết hạn (401) — kiểm tra trong "
                           "Settings.")
        if e.code == 402:
            raise OcrError("Hết credit OpenRouter (402) — nạp thêm hoặc đổi "
                           "model rẻ hơn.")
        if e.code == 429:
            raise OcrError("Bị giới hạn tần suất (429) — thử lại sau giây lát.")
        raise OcrError("Lỗi máy chủ OCR (%s)%s"
                       % (e.code, (": " + detail) if detail else ""))
    except urllib.error.URLError as e:
        raise OcrError("Không kết nối được mạng — Mode 7 cần internet (%s)."
                       % getattr(e, "reason", e))
    except OcrError:
        raise
    except Exception as e:
        raise OcrError("Lỗi gọi OCR: %s" % e)
    try:
        return parse_response(raw)
    except OcrError:
        raise
    except Exception:
        raise OcrError("Không đọc được kết quả OCR (định dạng phản hồi lạ).")
