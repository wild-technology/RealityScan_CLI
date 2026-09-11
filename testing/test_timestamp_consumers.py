"""Missing capture times must stop video extraction rather than become epoch."""
import logging

import pytest

from modules.extract_images.extract_images import ExtractImages


@pytest.mark.parametrize("name", ["recording.mp4", "camupper_20251399T999999Z.mp4"])
def test_extractor_rejects_missing_or_invalid_capture_time(name):
    extractor = ExtractImages(logging.getLogger("timestamp-test"))
    with pytest.raises(ValueError, match="timestamp"):
        extractor._ExtractImages__get_video_timestamp(name)
    with pytest.raises(ValueError, match="timestamp"):
        extractor._ExtractImages__get_video_timestamp_str(name)


def test_extractor_preserves_valid_capture_time():
    extractor = ExtractImages(logging.getLogger("timestamp-test"))
    stamp = extractor._ExtractImages__get_video_timestamp("camupper_20250524T043533Z.mp4")
    assert stamp.isoformat() == "2025-05-24T04:35:33"
