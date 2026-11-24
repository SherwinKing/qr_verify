from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from urllib.parse import parse_qs, urlencode, urlparse

from .config import AppConfig
from .db import Database
from . import tokens


class AppHandler(BaseHTTPRequestHandler):
    server_version = "QrVerify/1"
    sys_version = ""

    def __init__(self, *args, config: AppConfig, db_factory: Database, **kwargs):
        self.config = config
        self.db_factory = db_factory
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        # Access logs would contain signed verification tokens, so they are intentionally disabled.
        return

    def log_error(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if parsed.path == "/healthz":
            self._send_html(200, "<h1>ok</h1>", "text/plain")
            return
        if len(parts) == 2 and parts[0] == "v":
            self.handle_verification(parts[1], parse_qs(parsed.query))
            return
        self._send_html(
            404,
            self.render_page("Not found", "لم يتم العثور على الصفحة", lang="en"),
            "text/html; charset=utf-8",
        )

    def handle_verification(self, token: str, query: dict[str, list[str]]) -> None:
        host = self.headers.get("Host", "").lower()
        print_host = self.config.print_host
        verify_host = urlparse(self.config.verify_base_url).netloc.lower()
        if host == print_host and host != verify_host:
            params = {key: value[0] for key, value in query.items() if value}
            location = f"{self.config.verify_base_url}/v/{token}"
            if params:
                location += "?" + urlencode(params)
            self.send_response(302)
            self.send_header("Location", location)
            self._common_headers()
            self.end_headers()
            return

        lang = self.choose_language(query.get("lang", [None])[0])
        data = tokens.verify_token(self.config.public_key, token)
        if data is None:
            self.render_result(lang, False, None, None, 0, False)
            return

        products = self.config.products()
        product = products.get(str(data.product_id))
        if not isinstance(product, dict):
            self.render_result(lang, False, None, None, 0, False)
            return

        hashed = tokens.token_hash(token)
        database = self.db_factory
        database.connect()
        try:
            database.migrate()
            if database.is_revoked(hashed):
                self.render_result(lang, False, product, data.batch_id, 0, False, revoked=True)
                return
            scan = database.record_scan(hashed, data.product_id, data.batch_id)
        except Exception:
            raise
        self.render_result(lang, True, product, data.batch_id, scan.scan_count, scan.is_first_scan)

    def choose_language(self, query_lang: str | None) -> str:
        if query_lang in {"en", "ar"}:
            return query_lang
        accept = self.headers.get("Accept-Language", "").lower()
        if accept.startswith("ar") or ",ar" in accept:
            return "ar"
        return "en"

    def render_page(self, english: str, arabic: str, lang: str, body: str = "") -> str:
        if lang == "ar":
            title, message, html_dir = arabic, arabic, ' dir="rtl"'
        else:
            title, message, html_dir = english, english, ""
        return f"""<!doctype html>
<html lang="{lang}"{html_dir}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(title)}</title>
<style>
body {{ font-family: system-ui,-apple-system,"Segoe UI",sans-serif; margin:0; background:#f4f5f7; color:#171717; }}
main {{ max-width:30rem; margin:0 auto; padding:2rem 1rem; }}
.card {{ background:white; border-radius:1rem; padding:1.25rem; box-shadow:0 2px 10px rgba(0,0,0,.08); }}
.valid {{ border-top:.4rem solid #15803d; }} .invalid {{ border-top:.4rem solid #dc2626; }}
.count {{ font-size:2rem; font-weight:700; }} .note {{ color:#525252; }}
button {{ font:inherit; padding:.7rem 1rem; border-radius:.6rem; border:0; background:#111827; color:white; }}
</style>
</head><body><main><div class="card"><p>{escape(message)}</p>{body}</div></main></body></html>"""

    def render_result(self, lang: str, valid: bool, product: dict | None, batch_id: int | None,
                      scan_count: int, first: bool, revoked: bool = False) -> None:
        if not valid:
            english = "This product code is invalid." if not revoked else "This product code has been revoked."
            arabic = "رمز المنتج غير صالح." if not revoked else "تم إلغاء هذا الرمز."
            css_class = "invalid"
            status = 404 if not revoked else 410
            body = "<p><strong>Do not trust this product.</strong></p>" if lang == "en" else "<p><strong>لا تثق بهذا المنتج.</strong></p>"
            self._send_html(status, self.render_page(english, arabic, lang, body), "text/html; charset=utf-8", css_class)
            return

        names = product or {}
        product_name = str(names.get(lang) or names.get("en") or "Product")
        if first:
            english = "First verification"
            arabic = "أول تحقق"
            risk = "No previous scans were recorded." if lang == "en" else "لا توجد عمليات تحقق سابقة."
        else:
            english = f"Scanned {scan_count} times"
            arabic = f"تم التحقق {scan_count} مرة"
            if scan_count >= self.config.strong_repeat_threshold:
                risk = "This code has been scanned repeatedly. Compare carefully and consider risk." if lang == "en" else "تم التحقق من هذا الرمز عدة مرات. يرجى توخي الحذر."
            else:
                risk = "This code has been scanned before. Keep the QR link private." if lang == "en" else "تم التحقق من هذا الرمز سابقًا. حافظ على سرية الرابط."
        body = f"""<h1>{escape(product_name)}</h1>
<p class="count">{scan_count}</p><p>{escape(risk)}</p>
<p class="note">A valid code does not prove that the physical item is genuine.</p>"""
        if lang == "ar":
            body = f"""<h1>{escape(product_name)}</h1>
<p class="count">{scan_count}</p><p>{escape(risk)}</p>
<p class="note">الرمز الصالح لا يثبت بالضرورة أن المنتج الأصلي.</p>"""
        self._send_html(200, self.render_result_page(english if lang == "en" else arabic, lang, body), "text/html; charset=utf-8", "valid")

    def render_result_page(self, title: str, lang: str, body: str) -> str:
        direction = ' dir="rtl" lang="ar"' if lang == "ar" else ' lang="en"'
        return f"""<!doctype html>
<html{direction}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;background:#f5f5f5;margin:0}}main{{max-width:30rem;margin:auto;padding:1rem}}
.card{{background:#fff;border-radius:1rem;padding:1.25rem;box-shadow:0 2px 10px rgba(0,0,0,.1)}}.valid{{border-top:.35rem solid #16a34a}}.count{{font-size:2rem;font-weight:700}}</style>
</head><body><main><div class="card">{body}</div></main></body></html>"""

    def _common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _send_html(self, status: int, content: str, content_type: str, css_class: str = "") -> None:
        if css_class:
            content = content.replace('<div class="card">', f'<div class="card {css_class}">', 1)
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._common_headers()
        self.end_headers()
        self.wfile.write(payload)


class VerificationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(config: AppConfig | None = None) -> VerificationHTTPServer:
    if config is None:
        config = AppConfig.from_env()
    database = Database(config.db_path)
    database.connect()
    database.migrate()
    handler = partial(AppHandler, config=config, db_factory=database)
    import os

    host = os.environ.get("QR_VERIFY_HOST", "127.0.0.1")
    port = int(os.environ.get("QR_VERIFY_PORT", "8000"))
    return VerificationHTTPServer((host, port), handler)


def run() -> None:
    server = make_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
