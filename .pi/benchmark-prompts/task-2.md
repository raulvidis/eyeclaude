Task 2: Verify MediaPipe model integrity

Problem: `eye_tracker.py:ensure_model()` downloads the FaceLandmarker model with no checksum check. Pin a SHA-256, verify after download, delete + raise on mismatch.

Files:
- Modify: src/eyeclaude/eye_tracker.py (around lines 42-54)
- Test: tests/test_eye_tracker.py (APPEND a new test)

Use this canonical SHA-256 for the float16 model: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`. Do not run `eyeclaude calibrate` — the model file may not be present locally and that command opens an intrusive fullscreen overlay. Trust the canonical value.

Step 1 — Append this test to `tests/test_eye_tracker.py`:

```python
def test_ensure_model_rejects_wrong_sha(tmp_path, mocker):
    """A model file whose SHA-256 doesn't match the pinned value must be
    deleted and ensure_model() must raise."""
    import eyeclaude.eye_tracker as et

    bogus_path = tmp_path / "face_landmarker.task"
    mocker.patch.object(et, "MODEL_DIR", tmp_path)
    mocker.patch.object(et, "MODEL_PATH", bogus_path)

    def fake_download(_url, dest):
        with open(dest, "wb") as f:
            f.write(b"not-the-real-model-bytes")

    mocker.patch("urllib.request.urlretrieve", side_effect=fake_download)

    import pytest
    with pytest.raises(RuntimeError, match="checksum"):
        et.ensure_model()

    assert not bogus_path.exists(), "Bad-checksum file must be deleted"
```

Step 2 — Run `pytest tests/test_eye_tracker.py::test_ensure_model_rejects_wrong_sha -v`. Expected: FAIL.

Step 3 — Replace lines 42-54 of `src/eyeclaude/eye_tracker.py` (the `MODEL_URL`/`MODEL_DIR`/`MODEL_PATH` constants and the `ensure_model` function) with:

```python
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
MODEL_DIR = Path.home() / ".eyeclaude"
MODEL_PATH = MODEL_DIR / "face_landmarker.task"
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model() -> str:
    """Download the FaceLandmarker model if not present and verify its SHA-256."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.exists():
        logger.info("Downloading FaceLandmarker model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        logger.info("Model saved to %s", MODEL_PATH)

    actual = _sha256(MODEL_PATH)
    if actual != MODEL_SHA256:
        MODEL_PATH.unlink(missing_ok=True)
        raise RuntimeError(
            f"FaceLandmarker model checksum mismatch: "
            f"expected {MODEL_SHA256}, got {actual}. Deleted; retry."
        )
    return str(MODEL_PATH)
```

Step 4 — Run `pytest tests/test_eye_tracker.py -v`. All tests must pass.

Step 5 — Commit:
```
git add src/eyeclaude/eye_tracker.py tests/test_eye_tracker.py
git commit -m "fix: verify MediaPipe model SHA-256 before use"
```

Then reply "Task 2 done." and stop.
