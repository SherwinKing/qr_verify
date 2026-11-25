from __future__ import annotations

import hashlib
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
            self.render_result(token, lang, False, None, None, 0, False)
            return

        products = self.config.products()
        product = products.get(str(data.product_id))
        if not isinstance(product, dict):
            self.render_result(token, lang, False, None, None, 0, False)
            return

        hashed = tokens.token_hash(token)
        database = self.db_factory
        database.connect()
        try:
            database.migrate()
            if database.is_revoked(hashed):
                self.render_result(token, lang, False, product, data.batch_id, 0, False, revoked=True)
                return
            scan = database.record_scan(hashed, data.product_id, data.batch_id)
        except Exception:
            raise
        self.render_result(token, lang, True, product, data.batch_id, scan.scan_count, scan.is_first_scan)

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

    def render_result(self, token: str, lang: str, valid: bool, product: dict | None,
                      batch_id: int | None, scan_count: int, first: bool,
                      revoked: bool = False) -> None:
        del lang, product, batch_id
        current_host = escape(self.headers.get("Host", "121.43.32.57"))

        if not valid:
            reason = "Code Revoked" if revoked else "Invalid Code"
            title = "Product Authenticity Verification"
            body = f"""
            <div class="outer">
              <div class="card failed">
                <h2><span class="emoji">❌</span> Verification Failed</h2>
                <p>We cannot verify this product.</p>
                <div class="reason"><p><strong>Reason:</strong> {reason}</p></div>
              </div>
            </div>
            """
            status = 410 if revoked else 404
            self._send_html(status, self.render_result_page(title, body), "text/html; charset=utf-8")
            return

        if first:
            serial = hashlib.sha256(token.encode("ascii")).hexdigest()[:8].upper()
            title = "Product Authenticity Verification"
            body = f"""
            <div class="outer">
              <div class="card authentic">
                <h2><span class="emoji">✅</span> Product is Authentic</h2>
                <div class="status-line"><span class="strong">Scan Count:</span> 1</div>
                <div class="status-line safe">(Safe)</div>
                <div class="status-line"><span class="strong">Serial:</span> {serial}</div>
                <div class="status-line"><span class="strong">URL:</span> {current_host}</div>
              </div>
            </div>
            """
            self._send_html(200, self.render_result_page(title, body), "text/html; charset=utf-8")
            return

        title = "Product Authenticity Verification"
        body = f"""
        <div class="outer">
          <div class="card warning">
            <h2><span class="emoji">⚠️</span> Scan History Warning</h2>
            <p>This unique <span class="strong">authenticity code</span> has been scanned
               <span class="count">{scan_count}</span> times.</p>
            <div class="notice">
              <p><strong>Important:</strong> If you did <strong>not</strong> personally scan this
                 product previously, its authenticity cannot be guaranteed. This may indicate that
                 the code has been duplicated or tampered with.</p>
            </div>
            <button type="button">Report Suspicious Product</button>
            <p class="hint">If you scanned this yourself previously, no further action is required.</p>
          </div>
        </div>
        """
        self._send_html(200, self.render_result_page(title, body), "text/html; charset=utf-8")

    def render_result_page(self, title: str, body: str) -> str:
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#000">
<title>{escape(title)}</title>
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100vh; }}
body {{
  background: #f3f4f6;
  color: #111827;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}}
.outer {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 1rem;
}}
.card {{
  width: 100%;
  max-width: 28rem;
  margin: auto;
  padding: 1.5rem;
  border-radius: .5rem;
  border: 1px solid;
  text-align: center;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .05);
}}
.authentic {{ background: #f0fdf4; border-color: #bbf7d0; }}
.warning {{ background: #fff7ed; border-color: #fed7aa; }}
.failed {{ background: #fef2f2; border-color: #fecaca; }}
h2 {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: .5rem;
  margin: 0;
  font-size: 1.25rem;
  line-height: 2rem;
  font-weight: 700;
}}
.authentic h2 {{ color: #166534; }}
.warning h2 {{ color: #9a3412; }}
.failed h2 {{ color: #991b1b; }}
.authentic p, .warning p, .failed p {{ margin-top: 1rem; margin-bottom: 0; color: #7c2d12; }}
.failed p {{ color: #7f1d1d; }}
.strong {{ font-weight: 600; }}
.count {{ font-size: 1.5rem; line-height: 2rem; font-weight: 700; }}
.status-line {{ margin-top: .5rem; color: #166534; }}
.status-line.safe {{ font-weight: 700; }}
.notice {{
  margin-top: 1rem;
  padding: 1rem;
  border: 1px solid #fed7aa;
  border-radius: .25rem;
  background: rgba(255, 255, 255, .6);
  text-align: left;
}}
.notice p {{ margin: 0; font-size: .875rem; line-height: 1.625; color: #7c2d12; }}
.reason {{ margin-top: 1rem; padding: 1rem; border: 1px solid #fecaca; border-radius: .25rem; background: rgba(255,255,255,.6); text-align: left; }}
.reason p {{ margin: 0; font-size: .875rem; line-height: 1.625; color: #7f1d1d; }}
button {{
  width: 100%;
  margin-top: 1.5rem;
  padding: .5rem 1rem;
  border: 0;
  border-radius: .25rem;
  background: #ea580c;
  color: #fff;
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.5rem;
  cursor: pointer;
}}
button:hover {{ background: #c2410c; }}
.hint {{ margin-top: .75rem; font-size: .75rem; font-style: italic; color: #ea580c; }}
@media (max-width: 640px) {{
  .outer {{ padding: 1rem; }}
  h2 {{ font-size: 1.25rem; line-height: 1.75rem; }}
}}
</style>
</head><body>{body}</body></html>"""

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
