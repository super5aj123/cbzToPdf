import re
import tempfile
import zipfile
from pathlib import Path
from tkinter import Tk, filedialog

from PIL import Image


def naturalSortKey(path: Path):
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def isImageFile(path: Path):
    return path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


root = Tk()
root.withdraw()

directoryString = filedialog.askdirectory()

if not directoryString:
    raise SystemExit("No directory selected.")

directory = Path(directoryString)

cbzFiles = [
    path for path in directory.iterdir()
    if path.is_file() and path.suffix.lower() == ".cbz"
]

for cbzFile in cbzFiles:
    try:
        pdfFile = cbzFile.with_suffix(".pdf")

        with tempfile.TemporaryDirectory() as tmpDirName:
            tmpDir = Path(tmpDirName)

            with zipfile.ZipFile(cbzFile, "r") as zipFile:
                zipFile.extractall(tmpDir)

            imageFiles = sorted(
                [
                    path for path in tmpDir.rglob("*")
                    if isImageFile(path) and not path.name.startswith(".")
                ],
                key=naturalSortKey
            )

            if not imageFiles:
                raise ValueError("No supported image files found in archive")

            pdfImages = []

            for imageFile in imageFiles:
                with Image.open(imageFile) as img:
                    pdfImages.append(img.convert("RGB"))

            firstImage = pdfImages[0]
            remainingImages = pdfImages[1:]

            firstImage.save(
                pdfFile,
                save_all=True,
                append_images=remainingImages
            )

        print(f"Converted: {cbzFile.name} -> {pdfFile.name}")

    except Exception as e:
        print(f"Failed on file {cbzFile}: {e}")