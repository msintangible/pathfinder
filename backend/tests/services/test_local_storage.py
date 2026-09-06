import logging
from pathlib import Path

import pytest

from services.storage import local_storage
from services.storage.local_storage import LocalResumeStorage


def test_uses_configured_path_when_it_can_be_created(tmp_path):
    target = tmp_path / "resumes"

    storage = LocalResumeStorage(base_path=str(target))

    assert storage._base_path == target
    assert target.is_dir()


def test_falls_back_when_configured_path_is_not_writable(tmp_path, monkeypatch, caplog):
    unusable = tmp_path / "var" / "data" / "resumes"
    fallback = tmp_path / "fallback" / "resumes"
    monkeypatch.setattr(local_storage, "_FALLBACK_PATH", fallback)

    real_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if self == unusable:
            raise PermissionError(13, "Permission denied")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    with caplog.at_level(logging.WARNING):
        storage = LocalResumeStorage(base_path=str(unusable))

    assert storage._base_path == fallback
    assert fallback.is_dir()
    assert "not usable" in caplog.text


def test_reraises_when_even_the_fallback_is_not_writable(tmp_path, monkeypatch):
    fallback = tmp_path / "fallback" / "resumes"
    monkeypatch.setattr(local_storage, "_FALLBACK_PATH", fallback)

    def always_fail(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", always_fail)

    with pytest.raises(PermissionError):
        LocalResumeStorage(base_path=str(fallback))
