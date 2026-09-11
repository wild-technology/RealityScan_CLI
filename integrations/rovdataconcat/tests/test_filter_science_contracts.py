"""Synthetic production-path contracts, not field calibration or policy approval.

Run from integrations/rovdataconcat. All inputs/outputs live in pytest tmp_path.
The USBL examples deliberately characterize observed-history reacquisition; an
accepted-only history is a counterfactual, not a proposed scientific replacement.

Reference evidence (2026-09-11), not synthetic acceptance thresholds:
nav_angular_validation_20260911T222855Z_07a37ec6/usbl_history_counterfactual.json
records 17,548 H2101 observations: observed history rejects 1,044, accepted-only
rejects 17,546, and 16,502 decisions differ. Neither has external truth labels.
The integration owner also reports 54,344 updated output rows with only angular
roundoff below 3e-14 degrees and all other columns unchanged. That reference has
no >180-degree crossings, so it cannot replace the synthetic branch regressions.
These tests preserve current gating/noise behavior without approving its policy,
absolute navigation accuracy, sensor calibration, or measured DVL bottom lock.
"""

import json

import numpy as np
import pandas as pd
import pytest
from pyproj import Proj

from processors import kalman_concat, kalman_filter


PREFIX = "NA999_H9999"


def _frame(roll, pitch):
    roll, pitch = np.broadcast_arrays(np.asarray(roll, dtype=float),
                                     np.asarray(pitch, dtype=float))
    return pd.DataFrame({
        "Timestamp": pd.date_range("2025-01-02T12:00:00Z", periods=roll.size,
                                   freq="s").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Vehicle": "Hercules",
        "Herc_Depth_1": -100.0,
        "Heading": 25.0,
        "Roll": roll,
        "Pitch": pitch,
        "Lat_USBL": 9.0,
        "Long_USBL": 3.0,
        "Accuracy_USBL": 5.0,
    })


def _run_filter(root, frame):
    processed = root / "NA999" / "RUMI_processed" / "H9999"
    processed.mkdir(parents=True)
    source = processed / f"{PREFIX}_filtered_datatable.csv"
    frame.to_csv(source, index=False)
    before = source.read_bytes()
    assert kalman_filter.process_data(processed, processed) == 0
    assert source.read_bytes() == before
    output = pd.read_csv(processed / f"{PREFIX}_final_datatable.csv")
    report = json.loads((processed / "reports" / "kalman_filter.json").read_text())
    assert len(output) == len(frame)
    assert report["metrics"]["rts_smoother"] == "applied"
    return output, report


def _angle_error(actual, expected):
    """Circular comparison in degrees, independent of production helpers."""
    return (np.asarray(actual) - np.asarray(expected) + 180.0) % 360.0 - 180.0


def _posterior_angles(measurements):
    """Independent batch Gaussian posterior for the existing orientation model.

    Solve its tridiagonal precision system instead of implementing a Kalman/RTS
    pass. Q/R and the initial prior are the existing contract, not new tuning.
    Measurements must already share a continuous branch for this oracle.
    """
    z = np.deg2rad(np.asarray(measurements, dtype=float))
    q, r = 0.01 ** 2, 0.017 ** 2
    initial_variance = np.deg2rad(20.0) ** 2 + q  # first predict precedes update
    precision = np.eye(len(z)) / r
    rhs = z / r
    precision[0, 0] += 1.0 / initial_variance
    rhs[0] += z[0] / initial_variance
    for i in range(1, len(z)):
        precision[i - 1, i - 1] += 1.0 / q
        precision[i, i] += 1.0 / q
        precision[i - 1, i] -= 1.0 / q
        precision[i, i - 1] -= 1.0 / q
    return np.rad2deg(np.linalg.solve(precision, rhs))


@pytest.mark.parametrize("channel", ["Roll", "Pitch"])
@pytest.mark.parametrize("direction", [-1, 1], ids=["negative-crossing", "positive-crossing"])
def test_process_data_angles_cross_branch_and_ignore_full_turn_encoding(
        tmp_path, channel, direction):
    continuous = direction * np.r_[np.linspace(175, 179, 6), np.linspace(181, 185, 6)]
    wrapped = (continuous + 180.0) % 360.0 - 180.0
    # Includes both +/-360 equivalents, including a changed initial branch.
    alternate_encoding = wrapped + np.resize([-360.0, 0.0, 360.0], len(wrapped))
    expected = _posterior_angles(continuous)
    results = []
    output_column = f"kalman_{channel.lower()}_deg"
    for name, values in (("continuous", continuous), ("wrapped", wrapped),
                         ("equivalent", alternate_encoding)):
        frame = _frame(np.zeros(len(values)), np.zeros(len(values)))
        frame[channel] = values
        output, _ = _run_filter(tmp_path / name, frame)
        actual = output[output_column].to_numpy()
        assert np.isfinite(actual).all()
        assert ((actual >= -180) & (actual < 180)).all()
        np.testing.assert_allclose(_angle_error(actual, expected), 0, atol=1e-7)
        results.append(output)
    for output in results[1:]:
        np.testing.assert_allclose(
            _angle_error(output[output_column], results[0][output_column]), 0, atol=1e-7)
        # Every non-angular output must remain identical, not just position.
        angular_columns = ["Roll_rad", "Pitch_rad", "kalman_roll_deg", "kalman_pitch_deg"]
        pd.testing.assert_frame_equal(
            output.drop(columns=angular_columns),
            results[0].drop(columns=angular_columns), check_exact=True)


@pytest.mark.parametrize("constant", [False, True], ids=["ordinary-motion", "constant"])
def test_process_data_ordinary_angles_match_unchanged_noise_model(tmp_path, constant):
    roll = np.full(12, -4.0) if constant else np.linspace(-4.0, 3.0, 12)
    pitch = np.full(12, 6.0) if constant else np.linspace(6.0, 2.0, 12)
    output, _ = _run_filter(tmp_path, _frame(roll, pitch))
    for channel, values in (("roll", roll), ("pitch", pitch)):
        np.testing.assert_allclose(output[f"kalman_{channel}_deg"],
                                   _posterior_angles(values), rtol=0, atol=1e-7)


def _raw_gate_decisions(samples, *, accepted_only):
    """Expose the two history definitions on raw scalar observations only.

    Neither reference establishes whether a jump is real vehicle motion or a
    sensor fault. In particular, accepted-only history is not ground truth.
    """
    history, decisions = [], []
    for sample in samples:
        accept = True
        if len(history) >= 2:
            deviation = np.std(history)
            if deviation > 0:
                accept = abs(sample - np.mean(history)) <= 3 * deviation
        decisions.append(bool(accept))
        if accept or not accepted_only:
            history.append(sample)
            history = history[-20:]
    return decisions


def test_raw_observed_history_admits_repeat_but_accepted_only_freezes():
    samples = [0.0, 1.0] + [100.0] * 24
    observed = _raw_gate_decisions(samples, accepted_only=False)
    accepted_only = _raw_gate_decisions(samples, accepted_only=True)
    assert observed == [True, True, False] + [True] * 23
    assert accepted_only == [True, True] + [False] * 24
    # Same data could be a true relocation or repeated faulty fixes. These are
    # membership/reacquisition counterexamples, not a scientific classification.


@pytest.mark.parametrize("repeat_count", [2, 24], ids=["repeated-jump", "sustained-jump"])
def test_process_data_usbl_gate_characterizes_recent_observed_history(tmp_path, repeat_count):
    offsets = np.array([0.0, 1.0] + [100.0] * repeat_count)
    frame = _frame(np.zeros(len(offsets)), np.zeros(len(offsets)))
    # Real inverse projection supplies synthetic geographic observations. The
    # central meridian fixes easting; northing alone exercises the history gate.
    projection = Proj(proj="utm", zone=31, datum="WGS84")
    _, latitudes = projection(np.full(len(offsets), 500_000.0),
                              1_000_000.0 + offsets, inverse=True)
    frame["Lat_USBL"] = latitudes
    frame["Long_USBL"] = 3.0
    output, report = _run_filter(tmp_path, frame)
    expected = _raw_gate_decisions(offsets, accepted_only=False)
    assert report["metrics"]["usbl_fixes_gated_out"] == expected.count(False) == 1
    # Every row supplies depth+roll+pitch; each accepted USBL fix adds x+y.
    assert report["metrics"]["measurement_updates"] == 3 * len(frame) + 2 * sum(expected)
    assert report["metrics"]["dvl_position_updates"] == 0
    # Reacquisition means measurements resume entering this filter. It does not
    # impose an accuracy/convergence bound on its existing velocity/noise model.
    assert np.isfinite(output["kalman_y"]).all()
    assert _raw_gate_decisions(offsets, accepted_only=True).count(False) == repeat_count


def test_concat_nulls_only_offending_channel_and_retains_other_evidence(tmp_path):
    processed = tmp_path / "NA999" / "RUMI_processed" / "H9999"
    processed.mkdir(parents=True)
    timestamps = pd.date_range("2025-01-02T12:00:00Z", periods=40, freq="s")
    octans = pd.DataFrame({"Timestamp": timestamps, "Heading": 25.0,
                           "Pitch": 0.0, "Roll": 0.0})
    octans.loc[10, "Pitch"] = 90.0
    octans.loc[25, "Roll"] = -60.0
    sensors = pd.DataFrame({"Timestamp": timestamps, "Herc_Depth_1": -100.0,
                            "Temperature": np.linspace(2, 3, 40),
                            "event_value": [f"event-{i}" for i in range(40)]})
    usbl = pd.DataFrame({"Timestamp": timestamps, "Latitude": 9.0,
                         "Longitude": 3.0, "Accuracy": 5.0})
    sources = {}
    for suffix, frame in (("pitch_roll_heading_octans", octans),
                          ("sealog_sensors_merged", sensors), ("USBL_Hercules", usbl)):
        path = processed / f"{PREFIX}_{suffix}.csv"
        frame.to_csv(path, index=False)
        sources[path] = path.read_bytes()
    kalman_concat.process_data(processed, processed)
    output = pd.read_csv(processed / f"{PREFIX}_filtered_datatable.csv")
    assert len(output) == 40
    assert pd.to_datetime(output["Timestamp"], utc=True).tolist() == list(timestamps)
    assert output["Pitch"].isna().sum() == output["Roll"].isna().sum() == 1
    assert pd.isna(output.loc[10, "Pitch"]) and output.loc[10, "Roll"] == 0
    assert pd.isna(output.loc[25, "Roll"]) and output.loc[25, "Pitch"] == 0
    np.testing.assert_allclose(output["Herc_Depth_1"], sensors["Herc_Depth_1"])
    np.testing.assert_allclose(output["Temperature"], sensors["Temperature"])
    np.testing.assert_allclose(output["Lat_USBL"], usbl["Latitude"])
    np.testing.assert_allclose(output["Long_USBL"], usbl["Longitude"])
    np.testing.assert_allclose(output["Accuracy_USBL"], usbl["Accuracy"])
    assert output["event_value"].tolist() == sensors["event_value"].tolist()
    report = json.loads((processed / "reports" / "kalman_concat.json").read_text())
    notices = [event for event in report["events"] if event["category"] == "orientation-outliers"]
    assert len(notices) == 1
    assert "1 pitch / 1 roll" in notices[0]["message"]
    assert "2 rows affected, kept" in notices[0]["message"]
    assert report["metrics"]["rows_out"] == 40
    assert all(path.read_bytes() == before for path, before in sources.items())
