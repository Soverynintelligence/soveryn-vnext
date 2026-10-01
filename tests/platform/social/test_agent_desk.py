"""Per-agent browser desks — isolated profiles, Jon signs in."""
from __future__ import annotations

import pytest

from soveryn.platform.social.agent_desk import (
    classify_google_page,
    list_desks,
    profile_dir,
    seat_for,
)


def test_eve_google_is_not_instagram_profile():
    google = profile_dir("eve", "google")
    ig = profile_dir("eve", "instagram")
    assert google != ig
    assert google.as_posix().endswith("desks/eve/google/chrome")
    assert ig.as_posix().endswith("eve_ig_profile")


def test_kernel_and_aetheria_have_separate_desks():
    a = profile_dir("aetheria", "browser")
    k = profile_dir("kernel", "browser")
    assert a != k
    assert "aetheria" in a.as_posix()
    assert "kernel" in k.as_posix()


def test_unknown_desk_raises():
    with pytest.raises(ValueError, match="unknown desk"):
        seat_for("eve", "tiktok")


def test_classify_google_ads_home():
    assert (
        classify_google_page(url="https://ads.google.com/aw/overview?ocid=1")
        == "home"
    )


def test_classify_google_signin_is_login():
    assert (
        classify_google_page(
            url="https://accounts.google.com/v3/signin/identifier",
            has_password=False,
        )
        == "login"
    )
    assert classify_google_page(url="https://ads.google.com/", has_password=True) == "login"


def test_signed_in_from_profile_reads_preferences(tmp_path):
    from soveryn.platform.social.agent_desk import _signed_in_from_profile
    import json

    default = tmp_path / "Default"
    default.mkdir()
    (default / "Preferences").write_text(
        json.dumps(
            {
                "google": {
                    "services": {"last_signed_in_username": "cwg@example.com"}
                }
            }
        ),
        encoding="utf-8",
    )
    info = _signed_in_from_profile(tmp_path)
    assert info["email"] == "cwg@example.com"


def test_list_desks_includes_eve_google():
    rows = list_desks()
    keys = {(r["agent"], r["seat"]) for r in rows}
    assert ("eve", "google") in keys
    assert ("eve", "instagram") in keys
    assert ("aetheria", "browser") in keys
    assert ("kernel", "browser") in keys
