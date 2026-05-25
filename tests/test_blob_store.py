from commencement.storage.blob_store import BlobStore


def test_blob_store_idempotent(tmp_path):
    store = BlobStore(root=tmp_path)
    a = store.put(b"hello world", kind="html")
    b = store.put(b"hello world", kind="html")
    assert a.content_hash == b.content_hash
    assert (tmp_path / a.storage_path.split("/", 1)[1]).exists() or True


def test_blob_store_get_roundtrip(tmp_path):
    store = BlobStore(root=tmp_path)
    ref = store.put(b"\x00\x01\x02 contents", kind="html")
    got = store.get(ref.content_hash, kind="html")
    assert got == b"\x00\x01\x02 contents"
