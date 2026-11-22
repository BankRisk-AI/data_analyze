"""Immutable storage of the originals: content-addressed (sha256), written once, read-only. One pass computes hash and encoding."""
import codecs, hashlib, os, tempfile
from app.modules.eba_ingest.domain import FileTooLarge

def store(src: str, storage_dir: str, max_bytes: int, detect_encoding: bool):
    size = os.path.getsize(src)
    if size > max_bytes: raise FileTooLarge(f"{os.path.basename(src)} has {size/1e6:.1f} MB; the limit is {max_bytes/1e6:.0f} MB")
    os.makedirs(os.path.join(storage_dir, "tmp"), exist_ok=True)
    h = hashlib.sha256(); dec = codecs.getincrementaldecoder("utf-8")(); utf8_ok = True
    fd, tmp = tempfile.mkstemp(dir=os.path.join(storage_dir, "tmp"))
    with os.fdopen(fd, "wb") as out, open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):          # streamed: a 65 MB file is never read whole into memory
            h.update(chunk); out.write(chunk)
            if detect_encoding and utf8_ok:
                try: dec.decode(chunk)
                except UnicodeDecodeError: utf8_ok = False
    if detect_encoding and utf8_ok:
        try: dec.decode(b"", final=True)
        except UnicodeDecodeError: utf8_ok = False
    sha = h.hexdigest(); final_dir = os.path.join(storage_dir, sha[:2]); os.makedirs(final_dir, exist_ok=True); final = os.path.join(final_dir, sha + os.path.splitext(src)[1].lower())   # the extension is kept: openpyxl decides the format by it
    created = not os.path.exists(final)
    if created: os.replace(tmp, final); os.chmod(final, 0o444)
    else: os.remove(tmp)
    encoding = ("utf-8" if utf8_ok else "cp1252") if detect_encoding else "binary"
    return sha, size, final, encoding, created
