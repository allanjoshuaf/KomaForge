from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MockDocumentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/document":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur test</title></head>
<body>
  <img class="site-icon" data-src="/assets/logo-1.png" width="32" height="32" alt="Logo">
  <img class="site-icon" data-src="/assets/logo-2.png" width="32" height="32" alt="Logo">
  <label for="readingmode">Mode de lecture</label>
  <select id="readingmode">
    <option value="single">Une page</option>
    <option value="full">Toutes les pages</option>
  </select>
  <span id="page-counter">Page 1 sur 5</span>
  <main id="reader"></main>
  <script>
    const reader = document.querySelector('#reader');
    function render(count) {
      reader.innerHTML = '';
      for (let number = 1; number <= count; number++) {
        const image = document.createElement('img');
        image.className = 'ts-main-image';
        image.dataset.src = `/images/page-${String(number).padStart(3, '0')}.png`;
        image.dataset.index = String(number - 1);
        image.alt = `Document page ${number}`;
        image.width = 1000;
        image.height = 1400;
        reader.appendChild(image);
      }
    }
    render(1);
    document.querySelector('#readingmode').addEventListener('change', event => {
      render(event.target.value === 'full' ? 5 : 1);
    });
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith(("/images/page-", "/assets/logo-")):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_):
        pass
