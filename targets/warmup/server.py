"""暖身 CTF 靶機：一個故意留洞的小網站。offline、小、快，供活體驗證與入門。

挑戰：flag 藏在 robots.txt 揭露的隱藏路徑後面。考驗基本偵察（recon）。
這是本專案自帶、授權測試用的靶機；flag 由配置器每局注入，非真實機密。
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

FLAG = os.environ.get("FLAG", "FLAG{warmup_recon_ok}")
HIDDEN = "/s3cr3t-admin"

PAGES = {
    "/": b"<h1>Acme Admin Portal</h1><p>Authorized testing target.</p>",
    "/robots.txt": ("User-agent: *\nDisallow: %s\n" % HIDDEN).encode(),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == HIDDEN:
            body = ("Access granted. flag: " + FLAG).encode()
            code = 200
        elif path in PAGES:
            body = PAGES[path]
            code = 200
        else:
            body = b"404 not found"
            code = 404
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 靜音
        pass


if __name__ == "__main__":
    # Cloud Run 會以 PORT 環境變數指定容器監聽埠；本機 Docker 預設 8000。
    port = int(os.environ.get("PORT", "8000"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
