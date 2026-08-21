import os
import tempfile
import stat
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

import cbzToPdf


class ConvertCbzToPdfTests(unittest.TestCase):
    def test_writes_completed_pdf_without_destination_replace(self):
        with tempfile.TemporaryDirectory() as directoryString:
            directory = Path(directoryString)
            imageFile = directory / "page.png"
            cbzFile = directory / "book.cbz"
            Image.new("RGB", (2, 3), "white").save(imageFile)

            with zipfile.ZipFile(cbzFile, "w") as archive:
                archive.write(imageFile, "page.png")

            with mock.patch.object(
                Path,
                "replace",
                side_effect=OSError("replace unsupported by network drive"),
            ):
                pdfFile = cbzToPdf.convertCbzToPdf(cbzFile)

            self.assertEqual(pdfFile, directory / "book.pdf")
            self.assertTrue(pdfFile.read_bytes().startswith(b"%PDF-1.4"))
            self.assertTrue(pdfFile.read_bytes().endswith(b"%%EOF"))

    @unittest.skipUnless(hasattr(Path.stat(Path.cwd()), "st_flags"), "BSD flags")
    def test_overwriting_an_old_hidden_pdf_makes_it_visible(self):
        with tempfile.TemporaryDirectory() as directoryString:
            directory = Path(directoryString)
            sourceFile = directory / "completed.pdf"
            destinationFile = directory / "book.pdf"
            sourceFile.write_bytes(b"%PDF-1.4\n%%EOF")
            destinationFile.write_bytes(b"old")
            os.chflags(destinationFile, destinationFile.stat().st_flags | stat.UF_HIDDEN)

            cbzToPdf.copyCompletedPdf(sourceFile, destinationFile)

            self.assertFalse(destinationFile.stat().st_flags & stat.UF_HIDDEN)


if __name__ == "__main__":
    unittest.main()
