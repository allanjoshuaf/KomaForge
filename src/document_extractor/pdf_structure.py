"""Inspection and explicit recovery of detached PDF page trees."""

from __future__ import annotations

import hashlib
from io import BytesIO


def _pdf_page_signature(page, pikepdf) -> tuple[str, tuple, tuple]:
    """Return a structural fingerprint suitable for comparing two /Page objects."""

    content = page.get("/Contents")
    streams = list(content) if isinstance(content, pikepdf.Array) else [content]
    digest = hashlib.sha256()
    for stream in streams:
        if stream is None:
            continue
        try:
            digest.update(stream.read_bytes())
        except Exception:
            try:
                digest.update(stream.read_raw_bytes())
            except Exception:
                digest.update(repr(stream).encode("utf-8", errors="replace"))
    media_box = tuple(float(value) for value in page.get("/MediaBox", []))
    crop_box = tuple(float(value) for value in page.get("/CropBox", []))
    return digest.hexdigest(), media_box, crop_box


def _flatten_pdf_page_tree(node, pikepdf, seen: set[tuple]) -> list:
    """Return /Page objects in the order declared by a tree's /Kids arrays."""

    try:
        reference = tuple(node.objgen)
    except Exception:
        reference = (id(node), 0)
    if reference in seen:
        raise ValueError("Cycle détecté dans une arborescence PDF /Pages.")
    seen.add(reference)

    object_type = str(node.get("/Type"))
    if object_type == "/Page":
        return [node]
    if object_type != "/Pages":
        raise ValueError(f"Enfant inattendu dans /Kids : {object_type}")

    pages = []
    for child in list(node.get("/Kids", [])):
        pages.extend(_flatten_pdf_page_tree(child, pikepdf, seen))
    return pages


def _pdf_page_tree_nodes(node, seen: set[tuple]) -> set[tuple]:
    """Inventory /Pages nodes reachable from the official page tree."""

    try:
        reference = tuple(node.objgen)
    except Exception:
        reference = (id(node), 0)
    if reference in seen:
        return set()
    seen.add(reference)
    if str(node.get("/Type")) != "/Pages":
        return set()
    nodes = {reference}
    for child in list(node.get("/Kids", [])):
        if str(child.get("/Type")) == "/Pages":
            nodes.update(_pdf_page_tree_nodes(child, seen))
    return nodes


def inspect_detached_page_trees(data: bytes) -> dict:
    """Detect, count and validate detached /Pages trees without modifying them."""

    import pikepdf

    with pikepdf.Pdf.open(BytesIO(data)) as document:
        visible_pages = [page.obj for page in document.pages]
        page_count = len(visible_pages)
        if page_count < 1:
            raise ValueError("Le PDF ne contient aucune page officielle.")

        official_page_objects = {page.objgen for page in document.pages}
        official_tree_nodes = _pdf_page_tree_nodes(document.Root.Pages, set())
        detached_page_objects = 0
        detached_tree_counts: set[int] = set()
        detached_trees: list[dict] = []

        for obj in document.objects:
            try:
                object_type = str(obj.get("/Type"))
                if object_type == "/Page":
                    if obj.objgen not in official_page_objects:
                        detached_page_objects += 1
                    continue
                if object_type != "/Pages" or tuple(obj.objgen) in official_tree_nodes:
                    continue

                declared_count = int(obj.get("/Count", 0))
                if declared_count <= page_count:
                    continue
                detached_tree_counts.add(declared_count)
                detached_pages = _flatten_pdf_page_tree(obj, pikepdf, set())
                resolved_count = len(detached_pages)
                prefix_length = min(page_count, resolved_count)
                prefix_matches = sum(
                    _pdf_page_signature(visible_pages[index], pikepdf)
                    == _pdf_page_signature(detached_pages[index], pikepdf)
                    for index in range(prefix_length)
                )
                is_visible_prefix = (
                    prefix_length == page_count and prefix_matches == page_count
                )
                continuation = detached_pages[page_count:] if is_visible_prefix else []
                with_content = sum(
                    child.get("/Contents") is not None for child in continuation
                )
                with_resources = sum(
                    child.get("/Resources") is not None for child in continuation
                )
                detached_trees.append(
                    {
                        "object_reference": f"{obj.objgen[0]} {obj.objgen[1]} R",
                        "declared_count": declared_count,
                        "resolved_page_count": resolved_count,
                        "count_matches_resolved": declared_count == resolved_count,
                        "visible_prefix_matches": prefix_matches,
                        "visible_prefix_length": prefix_length,
                        "is_visible_prefix": is_visible_prefix,
                        "continuation_count": len(continuation),
                        "continuation_with_content": with_content,
                        "continuation_with_resources": with_resources,
                        "is_structurally_complete": (
                            declared_count == resolved_count
                            and is_visible_prefix
                            and with_content == len(continuation)
                            and with_resources == len(continuation)
                        ),
                    }
                )
            except Exception:
                continue

    return {
        "visible_page_count": page_count,
        "detached_page_objects": detached_page_objects,
        "detached_page_tree_counts": sorted(detached_tree_counts),
        "detached_ordered_page_trees": detached_trees,
    }


def recover_detached_page_tree(data: bytes, expected_count: int) -> tuple[bytes, dict]:
    """Rebuild a PDF from one structurally complete detached page tree."""

    if expected_count < 1:
        raise ValueError("Le nombre de pages attendu doit être positif.")

    import pikepdf

    with pikepdf.Pdf.open(BytesIO(data)) as source:
        visible_pages = [page.obj for page in source.pages]
        visible_count = len(visible_pages)
        official_tree_nodes = _pdf_page_tree_nodes(source.Root.Pages, set())
        candidates: list[tuple[object, list]] = []

        for obj in source.objects:
            try:
                if (
                    str(obj.get("/Type")) != "/Pages"
                    or tuple(obj.objgen) in official_tree_nodes
                    or int(obj.get("/Count", 0)) != expected_count
                ):
                    continue
                pages = _flatten_pdf_page_tree(obj, pikepdf, set())
                if len(pages) != expected_count or visible_count > len(pages):
                    continue
                if any(
                    _pdf_page_signature(visible_pages[index], pikepdf)
                    != _pdf_page_signature(pages[index], pikepdf)
                    for index in range(visible_count)
                ):
                    continue
                continuation = pages[visible_count:]
                if any(page.get("/Contents") is None for page in continuation):
                    continue
                if any(page.get("/Resources") is None for page in continuation):
                    continue
                candidates.append((obj, pages))
            except Exception:
                continue

        if not candidates:
            raise RuntimeError(
                "Aucun arbre PDF détaché ne satisfait toutes les vérifications "
                "structurelles."
            )
        if len(candidates) > 1:
            raise RuntimeError(
                "Plusieurs arbres PDF détachés valides ont été trouvés; "
                "la récupération est ambiguë."
            )

        tree, pages = candidates[0]
        recovered = pikepdf.Pdf.new()
        for page in pages:
            recovered.pages.append(pikepdf.Page(page))
        output = BytesIO()
        recovered.save(output)
        recovered_data = output.getvalue()
        tree_reference = f"{tree.objgen[0]} {tree.objgen[1]} R"

    with pikepdf.Pdf.open(BytesIO(recovered_data)) as checked:
        recovered_count = len(checked.pages)
        if recovered_count != expected_count:
            raise RuntimeError(
                "Le PDF reconstruit a échoué à la validation : "
                f"{recovered_count}/{expected_count} pages."
            )

    return recovered_data, {
        "authorized": True,
        "tree_object_reference": tree_reference,
        "source_visible_page_count": visible_count,
        "recovered_page_count": recovered_count,
        "continuation_page_count": recovered_count - visible_count,
        "method": "ordered detached /Pages tree",
    }
