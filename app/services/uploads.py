"""Product image upload handling. Files are validated by content (Pillow), not just by name."""
import os
import uuid

from flask import current_app
from PIL import Image, UnidentifiedImageError

SUBDIR = "products"
FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
ALLOWED_NAME_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_PIXELS = 40_000_000


class UploadError(ValueError):
    pass


def _validate(storage):
    """Return the canonical extension for a valid image, else raise UploadError."""
    name = storage.filename or "file"
    if name.rsplit(".", 1)[-1].lower() not in ALLOWED_NAME_EXT or "." not in name:
        raise UploadError(f"{name}: only JPG, PNG, WEBP or GIF images are allowed.")

    stream = storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise UploadError(f"{name}: file is empty.")
    if size > current_app.config["MAX_IMAGE_BYTES"]:
        mb = current_app.config["MAX_IMAGE_BYTES"] // (1024 * 1024)
        raise UploadError(f"{name}: larger than {mb} MB.")

    try:
        with Image.open(stream) as img:
            fmt = img.format
            width, height = img.size
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise UploadError(f"{name}: not a valid image file.")
    finally:
        stream.seek(0)

    if fmt not in FORMAT_EXT:
        raise UploadError(f"{name}: unsupported image type.")
    if width * height > MAX_PIXELS:
        raise UploadError(f"{name}: image dimensions are too large.")
    return FORMAT_EXT[fmt]


def _folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def save_images(files):
    """Validate every file first, then store them. Returns relative paths like 'products/<uuid>.jpg'.

    Names are random, so the user-supplied filename is never used on disk.
    """
    files = [f for f in files if f and f.filename]
    exts = [_validate(f) for f in files]  # all-or-nothing
    saved = []
    try:
        for f, ext in zip(files, exts):
            fname = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(_folder(), fname))
            saved.append(f"{SUBDIR}/{fname}")
    except OSError:
        delete_files(saved)
        raise UploadError("Could not store the uploaded images. Please try again.")
    return saved


def delete_files(rel_paths):
    """Best-effort removal; refuses to touch anything outside the upload folder."""
    root = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    for rel in rel_paths:
        full = os.path.realpath(os.path.join(root, rel))
        if full.startswith(root + os.sep):
            try:
                os.remove(full)
            except OSError:
                pass
