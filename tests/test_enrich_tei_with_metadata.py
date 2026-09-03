import json
import sys
import tempfile
import unittest
from pathlib import Path

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pyscripts"))

from enrich_tei_with_metadata import enrich_tei_files
from get_images_from_3if import get_manifest_copyright_text


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


class CopyrightDisclaimerTests(unittest.TestCase):
    def test_get_manifest_copyright_text_prefers_localized_statement(self):
        manifest = {
            "rights": "https://rights.example/license",
            "requiredStatement": {
                "label": {"de": ["Bereitgestellt von"], "en": ["Attribution"]},
                "value": {
                    "de": ["Österreichische Nationalbibliothek"],
                    "en": ["Austrian National Library"],
                },
            },
        }

        self.assertEqual(
            get_manifest_copyright_text(manifest),
            "https://rights.example/license | Bereitgestellt von: Österreichische Nationalbibliothek",
        )

    def test_enrich_tei_files_writes_image_copyright_to_publication_stmt(self):
        manifest_path = REPO_ROOT / "metadata" / "iiif" / "A.json"
        tei_input = """<?xml version='1.0' encoding='UTF-8'?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>A</title></titleStmt>
      <publicationStmt><p>Publication Information</p></publicationStmt>
      <sourceDesc><p>Information about the source</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body><pb n="9r"/></body></text>
</TEI>
"""

        metadata = {
            "A": {
                "country": "Österreich",
                "city": "Wien",
                "repository": "Österreichische Nationalbibliothek",
                "signatures": ["Cod. 2742*"],
                "handschriftencensus_id": 1229,
                "handschriftencensus_url": "https://www.handschriftencensus.de/1229",
                "metadata": {},
                "IIIF_manifest": str(manifest_path),
                "first_scan": 23,
                "last_scan": 23,
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tei_dir = tmp_path / "tei"
            tei_dir.mkdir()
            tei_path = tei_dir / "A.xml"
            tei_path.write_text(tei_input, encoding="utf-8")
            metadata_path = tmp_path / "witnesses.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            processed, updated, missing = enrich_tei_files(str(metadata_path), str(tei_dir))
            processed_again, updated_again, missing_again = enrich_tei_files(
                str(metadata_path), str(tei_dir)
            )

            self.assertEqual((processed, updated, missing), (1, 1, []))
            self.assertEqual((processed_again, updated_again, missing_again), (1, 1, []))

            tree = etree.parse(str(tei_path))
            copyright_note = tree.find(
                ".//tei:publicationStmt/tei:availability/tei:p[@type='image_copyright']",
                namespaces=NS,
            )
            self.assertIsNotNone(copyright_note)
            self.assertEqual(
                copyright_note.text,
                "Bereitgestellt von: Österreichische Nationalbibliothek",
            )

            graphic = tree.find(".//tei:facsimile/tei:surface/tei:graphic", namespaces=NS)
            self.assertIsNotNone(graphic)
            self.assertEqual(len(tree.findall(".//tei:facsimile", namespaces=NS)), 1)
            self.assertEqual(
                graphic.attrib["url"],
                "https://api.onb.ac.at/iiif/image/v3/1003371B/uk4nGb4kRHdUzWvz/info.json",
            )


if __name__ == "__main__":
    unittest.main()
