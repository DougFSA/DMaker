import pytest

from dmaker.domain.presets import ALIASES, PRESETS, get_preset, list_presets


def test_presets_are_well_formed():
    ids = [p.id for p in list_presets()]
    assert len(ids) == len(set(ids))
    for p in list_presets():
        assert p.width % 2 == 0 and p.height % 2 == 0
        assert p.fps > 0 and p.crf > 0 and p.maxrate_k > 0 and p.audio_k > 0
        assert p.safe.top + p.safe.bottom < p.height
        assert p.safe.left + p.safe.right < p.width
        assert "/" in p.id


def test_platform_coverage():
    platforms = {p.platform for p in list_presets()}
    assert {"Instagram", "Facebook", "YouTube"} <= platforms
    assert "instagram/reels" in PRESETS and "instagram/stories" in PRESETS
    assert "youtube/shorts" in PRESETS and "youtube/video" in PRESETS
    assert "facebook/reels" in PRESETS and "facebook/stories" in PRESETS


def test_aliases_resolve():
    for alias, target in ALIASES.items():
        assert get_preset(alias).id == target
    assert get_preset("REELS").id == "instagram/reels"


def test_unknown_preset():
    with pytest.raises(KeyError):
        get_preset("orkut/scraps")


def test_preview_scales_dimensions_and_safe_zone():
    p = get_preset("instagram/reels")
    pv = p.preview(540)
    assert (pv.width, pv.height) == (540, 960)
    assert pv.safe.bottom == int(p.safe.bottom * 0.5)
    assert pv.crf > p.crf
    assert p.orientation == "vertical" and get_preset("youtube/video").orientation == "horizontal"


def test_list_by_platform():
    assert all(p.platform == "YouTube" for p in list_presets("youtube"))
    assert len(list_presets("instagram")) >= 5
