from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass

from defusedxml import ElementTree as SafeET


WATERMARK_TERMS = {
    "SPECIMEN",
    "SAMPLE",
    "PREVIEW",
    "WATERMARK",
    "DEMONSTRATION",
    "DÉMONSTRATION",
    "ÉPREUVE",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def normalized_text(value: str) -> str:
    return " ".join(value.split()).strip()


def class_tokens(element) -> tuple[str, ...]:
    return tuple(token for token in element.attrib.get("class", "").split() if token)


def is_diagonal_transform(transform: str) -> bool:
    match = re.search(r"matrix\(\s*([-+\d.eE]+)[, ]+([-+\d.eE]+)[, ]+([-+\d.eE]+)[, ]+([-+\d.eE]+)", transform)
    if not match:
        return "rotate(" in transform.lower()
    try:
        _a, b, c, _d = (float(value) for value in match.groups())
    except ValueError:
        return False
    return abs(b) > 0.05 or abs(c) > 0.05


@dataclass(frozen=True)
class WatermarkCandidate:
    text: str
    classes: tuple[str, ...]
    transform: str
    score: int
    confidence: str
    reasons: tuple[str, ...]


def score_watermark(element, class_counts: Counter[str]) -> WatermarkCandidate | None:
    text = normalized_text("".join(element.itertext()))
    if not text:
        return None
    upper = text.upper()
    score = 0
    reasons: list[str] = []
    exact_term = upper in WATERMARK_TERMS
    contained_term = any(term in upper for term in WATERMARK_TERMS)
    if exact_term:
        score += 60
        reasons.append("texte exact de filigrane")
    elif contained_term:
        score += 35
        reasons.append("mot de filigrane dans le texte")

    classes = class_tokens(element)
    if classes and all(class_counts[token] == 1 for token in classes):
        score += 10
        reasons.append("classe rare")
    transform = element.attrib.get("transform", "")
    if is_diagonal_transform(transform):
        score += 20
        reasons.append("transformation diagonale")
    try:
        if float(element.attrib.get("textLength", "0")) >= 250:
            score += 10
            reasons.append("texte très large")
    except ValueError:
        pass
    opacity = element.attrib.get("opacity")
    try:
        if opacity is not None and float(opacity) < 0.8:
            score += 5
            reasons.append("opacité réduite")
    except ValueError:
        pass

    if score < 35:
        return None
    confidence = "élevée" if score >= 75 else "moyenne"
    return WatermarkCandidate(text, classes, transform, score, confidence, tuple(reasons))


def inspect_svg(data: bytes) -> dict:
    if len(data) > 100 * 1024 * 1024:
        raise ValueError("SVG trop volumineux à analyser")
    root = SafeET.fromstring(data)
    elements = list(root.iter())
    tag_counts = Counter(local_name(element.tag) for element in elements)
    text_elements = [element for element in elements if local_name(element.tag) == "text"]
    class_counts: Counter[str] = Counter(
        token for element in text_elements for token in class_tokens(element)
    )
    candidates = [
        candidate
        for element in text_elements
        if (candidate := score_watermark(element, class_counts)) is not None
    ]
    embedded_images = 0
    for element in elements:
        if local_name(element.tag) != "image":
            continue
        href = element.attrib.get("href") or element.attrib.get("{http://www.w3.org/1999/xlink}href", "")
        if href.startswith("data:image/"):
            embedded_images += 1
    return {
        "tags": dict(tag_counts.most_common()),
        "text_count": len(text_elements),
        "class_counts": dict(class_counts.most_common()),
        "embedded_images": embedded_images,
        "watermark_candidates": [asdict(candidate) for candidate in candidates],
        "high_confidence_watermark": any(candidate.confidence == "élevée" for candidate in candidates),
    }


def remove_exact_watermarks(
    data: bytes,
    extra_terms: list[str] | tuple[str, ...] | None = None,
) -> tuple[bytes, list[dict]]:
    """Retire les éléments <text> dont le contenu correspond exactement à un terme."""
    if len(data) > 100 * 1024 * 1024:
        raise ValueError("SVG trop volumineux à traiter")
    root = SafeET.fromstring(data)
    text_elements = [element for element in root.iter() if local_name(element.tag) == "text"]
    class_counts: Counter[str] = Counter(
        token for element in text_elements for token in class_tokens(element)
    )
    requested_terms = {
        normalized_text(term).upper()
        for term in (extra_terms or [])
        if normalized_text(term)
    }
    exact_terms = WATERMARK_TERMS | requested_terms
    removed: list[dict] = []
    for parent in root.iter():
        for element in list(parent):
            if local_name(element.tag) != "text":
                continue
            text = normalized_text("".join(element.itertext()))
            if text.upper() not in exact_terms:
                continue
            candidate = score_watermark(element, class_counts)
            parent.remove(element)
            removed.append(
                asdict(candidate)
                if candidate is not None
                else {
                    "text": text,
                    "classes": class_tokens(element),
                    "transform": element.attrib.get("transform", ""),
                    "score": 0,
                    "confidence": "explicite",
                    "reasons": ("texte exact demandé",),
                }
            )

    if not removed:
        return data, []
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    processed = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    remaining = SafeET.fromstring(processed)
    remaining_terms = {
        normalized_text("".join(element.itertext())).upper()
        for element in remaining.iter()
        if local_name(element.tag) == "text"
    }
    if exact_terms & remaining_terms:
        raise RuntimeError("Validation échouée : un texte de filigrane subsiste.")
    return processed, removed
