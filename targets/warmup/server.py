"""Warmup CTF target: a small site with a deliberate hole. Offline, small and fast, for live checks and beginners.

Challenge: the flag sits behind a hidden path disclosed by robots.txt. Tests basic recon.
This target ships with the project and is for authorized testing; the provisioner injects the flag per match,
so it is not a real secret.
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

    def log_message(self, *args) -> None:  # silence request logs
        pass


if __name__ == "__main__":
    # Cloud Run sets the listening port via the PORT env var; local Docker defaults to 8000.
    port = int(os.environ.get("PORT", "8000"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
