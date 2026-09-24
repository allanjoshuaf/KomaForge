from __future__ import annotations

import base64
import gzip
import re
import zipfile
from http.server import BaseHTTPRequestHandler
from io import BytesIO


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1600">
<rect width="1200" height="1600" fill="white"/>
<text class="mark unique" transform="matrix(2 -2 2 2 140 1380)" textLength="520">SPECIMEN</text>
<text class="body" transform="matrix(1 0 0 1 80 100)">Page de test</text>
</svg>'''


def make_blank_pdf(page_count: int) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids ["
            + b" ".join(
                f"{index} 0 R".encode("ascii")
                for index in range(3, page_count + 3)
            )
            + f"] /Count {page_count} >>".encode("ascii")
        ),
    ]
    objects.extend(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 440 666] >>"
        for _ in range(page_count)
    )
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(data)


def make_detached_tree_pdf(visible_count: int, total_count: int) -> bytes:
    """PDF de test : préfixe visible et arbre complet ordonné mais détaché."""
    if not 0 < visible_count < total_count:
        raise ValueError("visible_count doit être compris entre 1 et total_count - 1")
    catalog_id = 1
    visible_tree_id = 2
    page_ids = list(range(3, total_count + 3))
    detached_tree_id = total_count + 3
    stream_ids = list(range(detached_tree_id + 1, detached_tree_id + 1 + total_count))
    objects: dict[int, bytes] = {
        catalog_id: b"<< /Type /Catalog /Pages 2 0 R >>",
        visible_tree_id: (
            b"<< /Type /Pages /Kids ["
            + b" ".join(
                f"{page_id} 0 R".encode("ascii")
                for page_id in page_ids[:visible_count]
            )
            + f"] /Count {visible_count} >>".encode("ascii")
        ),
        detached_tree_id: (
            b"<< /Type /Pages /Kids ["
            + b" ".join(
                f"{page_id} 0 R".encode("ascii") for page_id in page_ids
            )
            + f"] /Count {total_count} >>".encode("ascii")
        ),
    }
    for index, (page_id, stream_id) in enumerate(zip(page_ids, stream_ids), 1):
        parent_id = visible_tree_id if index <= visible_count else detached_tree_id
        stream = f"q % page {index}\nQ\n".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent {parent_id} 0 R "
            f"/MediaBox [0 0 440 666] /Resources << /ProcSet [/PDF] >> "
            f"/Contents {stream_id} 0 R >>"
        ).encode("ascii")
        objects[stream_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )

    maximum_id = max(objects)
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (maximum_id + 1)
    for number in range(1, maximum_id + 1):
        offsets[number] = len(data)
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(objects[number])
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {maximum_id + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        (
            f"trailer\n<< /Size {maximum_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(data)


def make_epub() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        archive.writestr(
            "OEBPS/package.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Livre EPUB test</dc:title></metadata>
  <manifest>
    <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
    <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="one"/><itemref idref="two"/></spine>
</package>""",
        )
        for number in (1, 2):
            archive.writestr(
                f"OEBPS/{'one' if number == 1 else 'two'}.xhtml",
                f"""<!doctype html><html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="utf-8"/><title>Section {number}</title></head>
<body><h1>Section {number}</h1><p>Contenu EPUB de test.</p></body></html>""",
            )
    return output.getvalue()


def make_incomplete_epub() -> bytes:
    source = make_epub()
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(source), "r") as original, zipfile.ZipFile(
        output, "w"
    ) as archive:
        for item in original.infolist():
            if item.filename == "OEBPS/package.opf":
                continue
            archive.writestr(item, original.read(item.filename))
        archive.writestr(
            "OEBPS/package.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Livre EPUB incomplet</dc:title></metadata>
  <manifest>
    <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
    <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
    <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="toc"/><itemref idref="one"/><itemref idref="two"/></spine>
</package>""",
        )
        archive.writestr(
            "OEBPS/toc.xhtml",
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Sommaire</title></head><body><nav><ol>
<li><a href="one.xhtml">Un</a></li><li><a href="two.xhtml">Deux</a></li>
<li><a href="three.xhtml">Trois absent</a></li>
</ol></nav></body></html>""",
        )
    return output.getvalue()


NETWORK_PDF = make_blank_pdf(3)
DETACHED_TREE_PDF = make_detached_tree_pdf(3, 10)
NETWORK_EPUB = make_epub()
INCOMPLETE_EPUB = make_incomplete_epub()


class MockDocumentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/assets/book.epub":
            self.send_response(200)
            self.send_header("Content-Type", "application/epub+zip")
            self.send_header("Content-Length", str(len(NETWORK_EPUB)))
            self.send_header("Content-Disposition", 'attachment; filename="book.epub"')
            self.end_headers()
            self.wfile.write(NETWORK_EPUB)
            return

        if self.path == "/assets/incomplete-book.epub":
            self.send_response(200)
            self.send_header("Content-Type", "application/epub+zip")
            self.send_header("Content-Length", str(len(INCOMPLETE_EPUB)))
            self.end_headers()
            self.wfile.write(INCOMPLETE_EPUB)
            return

        if self.path == "/assets/book.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(NETWORK_PDF)))
            self.end_headers()
            self.wfile.write(NETWORK_PDF)
            return

        if self.path == "/assets/detached-book.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(DETACHED_TREE_PDF)))
            self.end_headers()
            self.wfile.write(DETACHED_TREE_PDF)
            return

        if self.path in {"/assets/book-metadata-3.json", "/assets/book-metadata-10.json"}:
            page_count = 10 if self.path.endswith("10.json") else 3
            body = (
                '{"pageCount": '
                + str(page_count)
                + ', "labels": ['
                + ",".join(f'"{index}"' for index in range(1, page_count + 1))
                + "]}"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/network-pdf-reader":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur PDF reseau</title></head>
<body>
  <img class="landing-logo" alt="Logo" src="/assets/logo-1.png">
  <button id="load-preview">Load preview</button>
  <main id="reader"></main>
  <script>
    document.querySelector('#load-preview').addEventListener('click', async () => {
      document.querySelector('#load-preview').remove();
      await fetch('/assets/book-metadata-3.json').then(response => response.json());
      await fetch('/assets/book.pdf').then(response => response.arrayBuffer());
      const counter = document.createElement('span');
      counter.setAttribute('aria-label', 'Page 1 of 3');
      document.body.appendChild(counter);
      const canvas = document.createElement('canvas');
      canvas.width = 440;
      canvas.height = 666;
      canvas.style.width = '440px';
      canvas.style.height = '666px';
      document.querySelector('#reader').appendChild(canvas);
    });
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/network-pdf-reader-incomplete":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur PDF incomplet</title></head>
<body>
  <img class="landing-logo" alt="Logo" src="/assets/logo-1.png">
  <button id="load-preview">Load preview</button>
  <main id="reader"></main>
  <script>
    document.querySelector('#load-preview').addEventListener('click', async () => {
      document.querySelector('#load-preview').remove();
      await fetch('/assets/book-metadata-10.json').then(response => response.json());
      await fetch('/assets/detached-book.pdf').then(response => response.arrayBuffer());
      const counter = document.createElement('span');
      counter.setAttribute('aria-label', 'Page 1 of 3');
      document.body.appendChild(counter);
      const canvas = document.createElement('canvas');
      canvas.width = 440;
      canvas.height = 666;
      canvas.style.width = '440px';
      canvas.style.height = '666px';
      document.querySelector('#reader').appendChild(canvas);
    });
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/network-epub-reader":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur EPUB reseau</title></head>
<body>
  <img class="landing-logo" alt="Logo" src="/assets/logo-1.png">
  <button id="load-preview">Load preview</button>
  <main id="reader"></main>
  <script>
    document.querySelector('#load-preview').addEventListener('click', async () => {
      document.querySelector('#load-preview').remove();
      await fetch('/assets/book.epub').then(response => response.arrayBuffer());
      const iframe = document.createElement('iframe');
      iframe.src = 'about:blank';
      document.querySelector('#reader').appendChild(iframe);
    });
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/network-epub-reader-incomplete":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur EPUB incomplet</title></head>
<body><button id="load-preview">Load preview</button><main id="reader"></main>
<script>
document.querySelector('#load-preview').addEventListener('click', async () => {
  document.querySelector('#load-preview').remove();
  await fetch('/assets/incomplete-book.epub').then(response => response.arrayBuffer());
  const iframe = document.createElement('iframe'); iframe.src = 'about:blank';
  document.querySelector('#reader').appendChild(iframe);
});
</script></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/canvas-reader":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Loading...</title></head>
<body>
  <div class="page-shell">
    <img class="landing-logo" alt="Logo" src="/assets/logo-1.png">
    <img class="landing-logo" alt="Logo" src="/assets/logo-2.png">
  </div>
  <p id="loading">Preview paused</p>
  <button id="load-preview">Load preview</button>
  <main id="reader"></main>
  <script>
    document.querySelector('#load-preview').addEventListener('click', () => {
      document.querySelector('#load-preview').remove();
      document.querySelector('#loading').textContent = 'Loading...';
      window.setTimeout(() => {
        document.title = 'Lecteur PDF canvas';
        document.querySelector('#loading').remove();
        const root = document.querySelector('#reader').attachShadow({mode: 'open'});
        const input = document.createElement('input');
        input.setAttribute('aria-label', 'Printed page Cover (page 1 of 39)');
        root.appendChild(input);
        const slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = '38';
        slider.setAttribute('aria-label', 'Page slider');
        root.appendChild(slider);
        for (let index = 0; index < 3; index++) {
          const canvas = document.createElement('canvas');
          canvas.width = 382;
          canvas.height = 576;
          canvas.style.width = '382px';
          canvas.style.height = '576px';
          root.appendChild(canvas);
        }
      }, 500);
    });
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/select-work":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Collection par volumes</title></head>
<body>
  <p>Ce sont des volumes, pas des chapitres.</p>
  <select id="selectChapitres"><option>Chargement...</option></select>
  <span>Page 1 / 1</span>
  <main id="volume-reader"></main>
  <script>
    const reader = document.querySelector('#volume-reader');
    const counts = {'Volume 1': 3, 'Volume 2': 2, 'Volume 3': 4};
    function render(value) {
      reader.innerHTML = '';
      const volume = value.split(' ')[1];
      window.setTimeout(() => {
        for (let number = 1; number <= counts[value]; number++) {
          const image = document.createElement('img');
          image.className = 'volume-page';
          image.dataset.index = String(number - 1);
          image.alt = `${value} page ${number}`;
          image.width = 1000;
          image.height = 1400;
          image.src = `/volumes/${volume}/page-${number}.png`;
          reader.appendChild(image);
        }
      }, 400);
    }
    const select = document.querySelector('#selectChapitres');
    select.addEventListener('change', event => render(event.target.value));
    window.setTimeout(() => {
      select.innerHTML = ['Volume 1', 'Volume 2', 'Volume 3']
        .map(value => `<option value="${value}">${value}</option>`).join('');
      render(select.value);
    }, 500);
  </script>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/work":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Une oeuvre test</title></head>
<body><main>
  <a href="/series/demo/chapter-3">Chapitre 3</a>
  <a href="/series/demo/chapter-1">Chapitre 1</a>
  <a href="/series/demo/chapter-2">Chapitre 2</a>
  <a href="https://example.invalid/chapter-99">Chapitre externe 99</a>
</main></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        chapter_match = re.fullmatch(r"/series/demo/chapter-([1-3])", self.path)
        if chapter_match:
            chapter = chapter_match.group(1)
            body = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Chapitre {chapter}</title></head>
<body>
  <nav>
    <a href="/series/demo/chapter-1">Chapitre 1</a>
    <a href="/series/demo/chapter-2">Chapitre 2</a>
    <a href="/series/demo/chapter-3">Chapitre 3</a>
  </nav>
  <span>Page 1 sur 2</span>
  <main>
    <img class="chapter-page" data-index="0" width="1000" height="1400"
      src="/series/demo/chapter-{chapter}/page-1.png">
    <img class="chapter-page" data-index="1" width="1000" height="1400"
      src="/series/demo/chapter-{chapter}/page-2.png">
  </main>
</body></html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if re.fullmatch(
            r"/series/demo/chapter-[1-3]/page-[12]\.png",
            self.path,
        ):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
            return

        if self.path == "/delayed-image-reader":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Chapter 1 | DelayedReader</title></head>
<body><main id="shell"></main><script>
window.setTimeout(() => {
  const reader = document.createElement('section');
  reader.id = 'reader';
  const counter = document.createElement('span');
  counter.className = 'page-counter';
  counter.textContent = '1/3';
  reader.appendChild(counter);
  for (let number = 1; number <= 3; number++) {
    const wrapper = document.createElement('div');
    wrapper.className = 'reader-page';
    const image = document.createElement('img');
    image.alt = `Page ${number}`;
    image.src = `/images/page-${String(number).padStart(3, '0')}.png`;
    image.width = 900;
    image.height = 1400;
    wrapper.appendChild(image);
    reader.appendChild(wrapper);
  }
  document.querySelector('#shell').replaceWith(reader);
}, 800);
</script></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

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

        if self.path == "/svg-document":
            body = b"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Lecteur SVGZ test</title></head>
<body>
  <span id="page-counter">Page 1 sur 2</span>
  <main id="reader">
    <img class="svg-page" data-src="/svg/page-001.svgz" data-index="0" width="1200" height="1600">
    <img class="svg-page" data-src="/svg/page-002.svgz" data-index="1" width="1200" height="1600">
  </main>
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/svg/page-001.svgz":
            body = SVG
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/svg/page-002.svgz":
            body = gzip.compress(SVG)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith(("/images/page-", "/assets/logo-", "/volumes/")):
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
