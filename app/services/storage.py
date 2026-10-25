"""Where uploaded images live: on this server's disk (STORAGE_BACKEND=local, the default) or in an S3-compatible
bucket (STORAGE_BACKEND=s3: Cloudflare R2, AWS S3, Backblaze B2 ...).

Images are stored under keys like "products/<random>.jpg" and that key is all the database keeps, so a site can move
from disk to a bucket by copying the files and changing the setting. upload_url(key) is the one place that turns a key
into an address for the browser; templates call it rather than building /static/uploads/ paths themselves.

A container's disk is lost when it is replaced, so a hosted site with more than one server should use a bucket.
"""
import os

from flask import current_app, url_for


class StorageError(Exception):
    pass


class LocalStorage:
    """Files under UPLOAD_FOLDER, served by the app as /static/uploads/<key>."""

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def _path(self, key):
        full = os.path.realpath(os.path.join(self.root, key))
        if not full.startswith(self.root + os.sep):  # a key can never reach outside the upload folder
            raise StorageError("bad key")
        return full

    def save(self, fileobj, key, content_type):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "wb") as out:
                while chunk := fileobj.read(64 * 1024):
                    out.write(chunk)
        except OSError as e:
            raise StorageError(str(e)) from e

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except (OSError, StorageError):
            pass

    def url(self, key):
        return url_for("static", filename=f"uploads/{key}")


class S3Storage:
    """An S3-compatible bucket. Reads go straight from the bucket's public address (S3_PUBLIC_BASE_URL, e.g. an R2
    public bucket URL or your own images.example.com), so image traffic never passes through the app."""

    def __init__(self, bucket, public_base_url, endpoint_url=None, access_key=None, secret_key=None, region=None):
        import boto3
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, aws_access_key_id=access_key,
                                   aws_secret_access_key=secret_key, region_name=region or "auto")

    def save(self, fileobj, key, content_type):
        try:
            self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs={
                "ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"})  # names are random: never change
        except Exception as e:  # botocore errors and connection failures alike
            raise StorageError(str(e)) from e

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            current_app.logger.exception("Could not delete %s from the image bucket", key)

    def url(self, key):
        return f"{self.public_base_url}/{key}"


def init_app(app):
    cfg = app.config
    if cfg.get("STORAGE_BACKEND", "local") == "s3":
        missing = [k for k in ("S3_BUCKET", "S3_PUBLIC_BASE_URL") if not cfg.get(k)]
        if missing:
            raise RuntimeError("STORAGE_BACKEND=s3 needs " + " and ".join(missing))
        app.extensions["storage"] = S3Storage(cfg["S3_BUCKET"], cfg["S3_PUBLIC_BASE_URL"], cfg.get("S3_ENDPOINT_URL"),
                                              cfg.get("S3_ACCESS_KEY_ID"), cfg.get("S3_SECRET_ACCESS_KEY"), cfg.get("S3_REGION"))
    else:
        app.extensions["storage"] = LocalStorage(cfg["UPLOAD_FOLDER"])


def backend():
    """The storage in use. Built lazily, so a test that points UPLOAD_FOLDER somewhere new after startup still works."""
    store = current_app.extensions.get("storage")
    if isinstance(store, LocalStorage) and store.root != os.path.realpath(current_app.config["UPLOAD_FOLDER"]):
        store = current_app.extensions["storage"] = LocalStorage(current_app.config["UPLOAD_FOLDER"])
    return store


def upload_url(key):
    """The browser address of an uploaded image (a Jinja global as well)."""
    return backend().url(key) if key else None
