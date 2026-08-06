import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from tkinter import Tk, filedialog

from PIL import Image

try:
    import pillow_jxl  # noqa: F401
except Exception as exc:
    jxlImportError = exc
else:
    jxlImportError = None

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".jxl"}


def naturalSortKey(name):
    path = PurePosixPath(name)
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def isImageEntry(zipInfo):
    path = PurePosixPath(zipInfo.filename)
    return (
        not zipInfo.is_dir()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


def requireImageSupport(imageEntries):
    hasJxlFile = any(
        PurePosixPath(zipInfo.filename).suffix.lower() == ".jxl"
        for zipInfo in imageEntries
    )
    hasJxlSupport = ".jxl" in Image.registered_extensions()

    if hasJxlFile and not hasJxlSupport:
        raise RuntimeError(
            "JPEG XL files require pillow-jxl-plugin. "
            "Install it with: pip install pillow-jxl-plugin"
        ) from jxlImportError


class StreamingPdfWriter:
    def __init__(self, pdfFile):
        self.pdfFile = pdfFile
        self.file = None
        self.objectOffsets = [0]
        self.catalogRef = self.reserveObject()
        self.pagesRef = self.reserveObject()
        self.pageRefs = []

    def __enter__(self):
        self.file = self.pdfFile.open("wb")
        self.file.write(b"%PDF-1.4\n")
        self.file.write(b"% page-at-a-time image PDF\n")
        return self

    def __exit__(self, excType, excValue, traceback):
        try:
            if excType is None:
                self.finish()
        finally:
            if self.file is not None:
                self.file.close()

    def reserveObject(self):
        self.objectOffsets.append(None)
        return len(self.objectOffsets) - 1

    def writeObject(self, objectRef, body):
        self.objectOffsets[objectRef] = self.file.tell()
        self.file.write(f"{objectRef} 0 obj\n".encode("ascii"))
        self.file.write(body)
        self.file.write(b"\nendobj\n")

    def writeStreamObject(self, objectRef, dictionary, stream, streamLength):
        self.objectOffsets[objectRef] = self.file.tell()
        self.file.write(f"{objectRef} 0 obj\n".encode("ascii"))
        self.file.write(b"<< ")
        self.file.write(dictionary)
        self.file.write(f" /Length {streamLength} >>\nstream\n".encode("ascii"))
        shutil.copyfileobj(stream, self.file, length=1024 * 1024)
        self.file.write(b"\nendstream\nendobj\n")

    def addImagePage(self, image):
        convertedImage = None
        if image.mode != "RGB":
            convertedImage = image.convert("RGB")
            image = convertedImage

        try:
            width, height = image.size
            imageRef = self.reserveObject()
            contentRef = self.reserveObject()
            pageRef = self.reserveObject()

            with tempfile.TemporaryFile() as jpegFile:
                image.save(jpegFile, format="JPEG")
                jpegLength = jpegFile.tell()
                jpegFile.seek(0)
                self.writeStreamObject(
                    imageRef,
                    (
                        f"/Type /XObject /Subtype /Image /Width {width} "
                        f"/Height {height} /ColorSpace /DeviceRGB "
                        "/BitsPerComponent 8 /Filter /DCTDecode"
                    ).encode("ascii"),
                    jpegFile,
                    jpegLength,
                )

            pageContents = (
                f"q {width} 0 0 {height} 0 0 cm /PageImage Do Q\n"
            ).encode("ascii")
            self.writeStreamObject(
                contentRef,
                b"",
                io.BytesIO(pageContents),
                len(pageContents),
            )
            self.writeObject(
                pageRef,
                (
                    f"<< /Type /Page /Parent {self.pagesRef} 0 R "
                    f"/Resources << /ProcSet [/PDF /ImageC] "
                    f"/XObject << /PageImage {imageRef} 0 R >> >> "
                    f"/MediaBox [0 0 {width} {height}] "
                    f"/Contents {contentRef} 0 R >>"
                ).encode("ascii"),
            )
            self.pageRefs.append(pageRef)
        finally:
            if convertedImage is not None:
                convertedImage.close()

    def finish(self):
        kids = " ".join(f"{pageRef} 0 R" for pageRef in self.pageRefs)
        self.writeObject(
            self.catalogRef,
            f"<< /Type /Catalog /Pages {self.pagesRef} 0 R >>".encode("ascii"),
        )
        self.writeObject(
            self.pagesRef,
            (
                f"<< /Type /Pages /Count {len(self.pageRefs)} "
                f"/Kids [{kids}] >>"
            ).encode("ascii"),
        )

        startXref = self.file.tell()
        self.file.write(f"xref\n0 {len(self.objectOffsets)}\n".encode("ascii"))
        self.file.write(b"0000000000 65535 f \n")
        for objectOffset in self.objectOffsets[1:]:
            if objectOffset is None:
                raise ValueError("PDF object was reserved but never written")
            self.file.write(f"{objectOffset:010d} 00000 n \n".encode("ascii"))

        self.file.write(
            (
                f"trailer\n<< /Size {len(self.objectOffsets)} "
                f"/Root {self.catalogRef} 0 R >>\n"
                f"startxref\n{startXref}\n%%EOF"
            ).encode("ascii")
        )
        self.file.close()
        self.file = None


def convertImageEntry(pdfWriter, zipFile, imageEntry):
    with zipFile.open(imageEntry, "r") as imageStream:
        with Image.open(imageStream) as image:
            pdfWriter.addImagePage(image)


def convertCbzToPdf(cbzFile):
    pdfFile = cbzFile.with_suffix(".pdf")
    tempPdfFile = tempfile.NamedTemporaryFile(
        dir=pdfFile.parent,
        prefix=f".{pdfFile.stem}.",
        suffix=".pdf",
        delete=False,
    )
    tempPdfPath = Path(tempPdfFile.name)
    tempPdfFile.close()

    try:
        with zipfile.ZipFile(cbzFile, "r") as zipFile:
            imageEntries = sorted(
                [
                    zipInfo for zipInfo in zipFile.infolist()
                    if isImageEntry(zipInfo)
                ],
                key=lambda zipInfo: naturalSortKey(zipInfo.filename),
            )

            if not imageEntries:
                raise ValueError("No supported image files found in archive")

            requireImageSupport(imageEntries)

            with StreamingPdfWriter(tempPdfPath) as pdfWriter:
                for imageEntry in imageEntries:
                    convertImageEntry(pdfWriter, zipFile, imageEntry)

        tempPdfPath.replace(pdfFile)
        return pdfFile
    except Exception:
        tempPdfPath.unlink(missing_ok=True)
        raise


def main():
    root = Tk()
    root.withdraw()

    try:
        directoryString = filedialog.askdirectory()
    finally:
        root.destroy()

    if not directoryString:
        raise SystemExit("No directory selected.")

    directory = Path(directoryString)

    cbzFiles = [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".cbz"
    ]

    for cbzFile in cbzFiles:
        try:
            pdfFile = convertCbzToPdf(cbzFile)
            print(f"Converted: {cbzFile.name} -> {pdfFile.name}")

        except Exception as e:
            print(f"Failed on file {cbzFile}: {e}")


if __name__ == "__main__":
    main()
