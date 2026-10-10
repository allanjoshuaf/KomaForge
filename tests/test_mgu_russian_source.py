from __future__ import annotations

import unittest

from document_extractor.application import load_source_publication, resolve_source
from document_extractor.sources import SourceReference, SourceSession


PRODUCT_URL = (
    "https://book.mgu-russian.com/tproduct/"
    "615364877-472366607661-komplekt-uchebnik-tetrad"
)


class FakePage:
    def title(self):
        return "Комплект: учебник + тетрадь"


class MguRussianStoreSourceTests(unittest.TestCase):
    def test_product_page_is_recognized_without_generic_fallback(self):
        route = resolve_source(PRODUCT_URL)

        self.assertTrue(route.specialized)
        self.assertEqual(route.adapter.id, "mgu-russian-store")

    def test_product_is_normalized_but_purchase_delivery_is_not_faked(self):
        route = resolve_source(PRODUCT_URL)
        session = SourceSession(page=FakePage())
        publication = load_source_publication(
            route,
            SourceReference(route.adapter.id, PRODUCT_URL, PRODUCT_URL),
            session,
        )

        self.assertEqual(publication.title, "Комплект: учебник + тетрадь")
        self.assertEqual(publication.metadata["access"], "purchase_delivery")
        self.assertEqual(len(publication.parts), 1)
        with self.assertRaisesRegex(RuntimeError, "page d'achat, pas un lecteur"):
            route.adapter.get_resources(publication.parts[0], session)


if __name__ == "__main__":
    unittest.main()
