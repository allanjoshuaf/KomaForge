from __future__ import annotations

import importlib.util
import unittest
from io import BytesIO

from document_extractor.pdf_structure import (
    inspect_detached_page_trees,
    recover_detached_page_tree,
)
from tests.mock_site import DETACHED_TREE_PDF


@unittest.skipUnless(importlib.util.find_spec("pikepdf"), "pikepdf absent")
class PdfStructureTests(unittest.TestCase):
    def test_detached_page_tree_inspector_is_independent_and_read_only(self):
        diagnostics = inspect_detached_page_trees(DETACHED_TREE_PDF)

        self.assertEqual(diagnostics["visible_page_count"], 3)
        trees = diagnostics["detached_ordered_page_trees"]
        self.assertEqual(len(trees), 1)
        self.assertEqual(trees[0]["declared_count"], 10)
        self.assertEqual(trees[0]["resolved_page_count"], 10)
        self.assertTrue(trees[0]["count_matches_resolved"])
        self.assertEqual(trees[0]["visible_prefix_matches"], 3)
        self.assertEqual(trees[0]["continuation_count"], 7)
        self.assertTrue(trees[0]["is_structurally_complete"])

    def test_detached_page_tree_recovery_creates_a_valid_complete_pdf(self):
        import pikepdf

        recovered, details = recover_detached_page_tree(DETACHED_TREE_PDF, 10)

        self.assertEqual(details["source_visible_page_count"], 3)
        self.assertEqual(details["recovered_page_count"], 10)
        self.assertEqual(details["continuation_page_count"], 7)
        with pikepdf.Pdf.open(BytesIO(recovered)) as document:
            self.assertEqual(len(document.pages), 10)
            self.assertEqual(document.Root.Pages.get("/Count"), 10)


if __name__ == "__main__":
    unittest.main()
