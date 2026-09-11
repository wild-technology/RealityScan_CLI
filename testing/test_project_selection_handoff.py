"""Actual image/mask copies and camera-log rows follow approved selection."""
import csv
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest

from modules.image_exts import associated_masks, is_geometry_image
from modules.image_batcher.batch_directory import BatchDirectory
from modules.preprocess_images.preprocess_images import PreprocessImages, _process_one
from modules.project_staging import filter_flight_log
from modules.source_inventory import SourceItem


def test_masks_never_become_batch_cameras_and_follow_each_zone(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    image = source / "camlower_20250101T000000Z.jpeg"
    image.write_bytes(b"image")
    mask = source / (image.name + ".mask.png")
    mask.write_bytes(b"mask")
    module = BatchDirectory(logging.getLogger("mask-test"))
    index = module._BatchDirectory__index_files(str(source))
    assert set(index[0]) == {image.name.lower()}
    for zone in ("zone_1", "zone_2"):
        copied, missing = module._BatchDirectory__copy_files(str(source), str(tmp_path / zone), [image.name], index)
        assert (copied, missing) == (1, 0)
        copied_image = next((tmp_path / zone).rglob(image.name))
        output = copied_image.with_name(mask.name)
        assert output.read_bytes() == b"mask"
    assert mask.read_bytes() == b"mask"


def test_enhancement_preserves_mask_pixels_and_excludes_mask_job(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "out"
    source.mkdir()
    destination.mkdir()
    image = source / "camlower_20250101T000000Z.jpeg"
    cv2.imwrite(str(image), np.full((32, 48, 3), 80, np.uint8))
    mask = source / (image.name + ".mask.png")
    cv2.imwrite(str(mask), np.vstack([np.zeros((16, 48), np.uint8), np.full((16, 48), 255, np.uint8)]))
    module = PreprocessImages(logging.getLogger("mask-test"))
    jobs, skipped = module._PreprocessImages__collect_jobs(str(source), str(destination), 2, 8, False)
    assert len(jobs) == 1 and skipped == 0
    assert _process_one(jobs[0]) is None
    assert (destination / mask.name).read_bytes() == mask.read_bytes()


def test_mask_index_refreshes_after_new_mask(tmp_path):
    image = tmp_path / "camupper_20250101T000000Z.jpeg"
    image.write_bytes(b"image")
    assert associated_masks(image) == []
    mask = tmp_path / (image.name + ".mask.png")
    mask.write_bytes(b"mask")
    assert associated_masks(image) == [mask]
    assert not is_geometry_image(mask)


def test_selected_flight_log_has_exact_retained_rows_and_crs(tmp_path):
    log = tmp_path / "flight_log_55N_UTM.txt"
    with log.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["filename", *[str(i) for i in range(13)]])
        writer.writerow(["keep.jpeg", *range(13)])
        writer.writerow(["culled.jpeg", *range(13)])
    items = [SourceItem(str(tmp_path / name), name, "image", 1, 1, included=keep)
             for name, keep in (("keep.jpeg", True), ("culled.jpeg", False))]
    selected = filter_flight_log(log, tmp_path / "selected", items, expected_epsg=32655)
    assert "keep.jpeg" in selected.read_text() and "culled.jpeg" not in selected.read_text()
    with pytest.raises(ValueError, match="CRS"):
        filter_flight_log(log, tmp_path / "wrong", items, expected_epsg=32755)
    items[1].included = True
    with pytest.raises(ValueError, match="differs"):
        filter_flight_log(log, tmp_path / "selected", items, expected_epsg=32655)
