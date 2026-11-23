import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.modules.eba_public_analysis.application import alerts as analysis


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args):
        pass

    def fetchall(self):
        return self.rows


SHA = "a" * 64
OTHER = "a" * 63 + "b"


def cursor():
    return Cursor([("eu_eba", SHA, None), ("eu_eba", OTHER, None)])


def test_profile_resolution_defaults_to_latest_name(monkeypatch):
    monkeypatch.setattr(analysis, "_profile_file", lambda _: {"version": "1.0"})
    assert analysis._resolve_profile(cursor(), None) == ("eu_eba", SHA)
    assert analysis._resolve_profile(cursor(), "eu_eba") == ("eu_eba", SHA)
    assert analysis._resolve_profile(cursor(), SHA) == ("eu_eba", SHA)


def test_profile_resolution_accepts_unique_prefix_and_rejects_ambiguous(monkeypatch):
    monkeypatch.setattr(analysis, "_profile_file", lambda _: {"version": "1.0"})
    with pytest.raises(BadRequestError):
        analysis._resolve_profile(cursor(), "aaaaaaaa")
    with pytest.raises(NotFoundError, match="eu_eba v1.0"):
        analysis._resolve_profile(cursor(), "missing")
