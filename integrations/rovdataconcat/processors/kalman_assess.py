from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from .common import expedition_dive_from_processed_dir


def process_data(raw_dir, processed_dir):
    """
    Performs Kalman filter assessment on processed navigation data.
    Uses the directories (which include dive information) passed from the main script.

    Parameters
    ----------
    raw_dir : Path or str
        Directory containing raw data (including the dive folder).
    processed_dir : Path or str
        Directory where processed data is saved and where output will be written.
    """
    raw_dir = Path(raw_dir).resolve()
    processed_dir = Path(processed_dir).resolve()

    # Ensure the processed directory exists.
    processed_dir.mkdir(parents=True, exist_ok=True)

    print("Running Kalman Assessment Process...")

    expedition, dive = expedition_dive_from_processed_dir(processed_dir)

    # Match what kalman_filter writes: "{expedition}_{dive}_kalman_filtered_data.csv"
    input_file = processed_dir / f"{expedition}_{dive}_kalman_filtered_data.csv"
    output_file = processed_dir / f"{expedition}_{dive}_kalman_assessment.csv"

    if not input_file.is_file():
        # Raise instead of returning None: a silent return let the
        # orchestrator mark this stage 'ok' with no assessment produced.
        raise FileNotFoundError(
            f"kalman_assess: expected input file '{input_file}' not found -- "
            f"run kalman_filter first."
        )

    # Read CSV with low_memory set to False to avoid DtypeWarning.
    df = pd.read_csv(input_file, parse_dates=['Timestamp'], low_memory=False)

    # Define required columns for analysis.
    required_columns = [
        'Timestamp', 'Herc_Depth_1', 'Roll', 'Pitch', 'Heading', 'x_usbl', 'y_usbl',
        'kalman_depth', 'kalman_roll_deg', 'kalman_pitch_deg', 'kalman_yaw_deg',
        'kalman_x', 'kalman_y'
    ]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        print(f"Warning: Missing required columns: {missing_columns}")

    # Functions to compute smoothness and consistency.
    def calculate_smoothness(data):
        return data.diff().dropna().std() if data is not None and len(data) > 1 else np.nan

    def calculate_smoothness_circular(deg_series):
        """Smoothness for angular data: wrap step differences into (-180, 180]."""
        if deg_series is None or len(deg_series) < 2:
            return np.nan
        diffs = deg_series.diff().dropna()
        wrapped = (diffs + 180) % 360 - 180
        return wrapped.std()

    def calculate_consistency(filtered, raw):
        if filtered is None or raw is None:
            return np.nan
        min_len = min(len(filtered), len(raw))
        return np.abs(filtered[:min_len] - raw[:min_len]).mean()

    def calculate_consistency_circular(filtered_deg, raw_deg):
        """Mean absolute angular error, accounting for 0/360 wrap."""
        if filtered_deg is None or raw_deg is None:
            return np.nan
        diff = (filtered_deg - raw_deg + 180) % 360 - 180
        return np.abs(diff).mean()

    # df.get returns None for absent columns; the calculators treat None as NaN,
    # so a missing source degrades to an empty metric instead of a crash.
    smoothness_metrics = {
        'Depth': {
            'Raw': calculate_smoothness(df.get('Herc_Depth_1')),
            'Filtered': calculate_smoothness(df.get('kalman_depth'))
        },
        'Roll': {
            'Raw': calculate_smoothness(df.get('Roll')),
            'Filtered': calculate_smoothness(df.get('kalman_roll_deg'))
        },
        'Pitch': {
            'Raw': calculate_smoothness(df.get('Pitch')),
            'Filtered': calculate_smoothness(df.get('kalman_pitch_deg'))
        },
        'Yaw': {
            'Raw': calculate_smoothness_circular(df.get('Heading')),
            'Filtered': calculate_smoothness_circular(df.get('kalman_yaw_deg'))
        }
    }

    # Compute consistency metrics.
    consistency_metrics = {
        'Depth': calculate_consistency(df.get('kalman_depth'), df.get('Herc_Depth_1')),
        'Roll': calculate_consistency(df.get('kalman_roll_deg'), df.get('Roll')),
        'Pitch': calculate_consistency(df.get('kalman_pitch_deg'), df.get('Pitch')),
        'Yaw': calculate_consistency_circular(df.get('kalman_yaw_deg'), df.get('Heading')),
        'X': calculate_consistency(df.get('kalman_x'), df.get('x_usbl')),
        'Y': calculate_consistency(df.get('kalman_y'), df.get('y_usbl'))
    }

    # Prepare assessment results.
    assessment_results = []
    for param, values in smoothness_metrics.items():
        for data_type, value in values.items():
            assessment_results.append(["Smoothness", f"{param}_{data_type}", value])
    for param, value in consistency_metrics.items():
        assessment_results.append(["Consistency", param, value])

    assessment_df = pd.DataFrame(assessment_results, columns=['Metric', 'Parameter', 'Value'])
    assessment_df.to_csv(output_file, index=False)
    print(f"Kalman assessment results saved to: {output_file}")

    # Generate plots.
    fig, axes = plt.subplots(3, 2, figsize=(12, 12))
    axes = axes.ravel()
    plot_configs = [
        ('Herc_Depth_1', 'kalman_depth', 'Depth', 'Depth (m)', 0),
        ('Roll', 'kalman_roll_deg', 'Roll', 'Roll (deg)', 1),
        ('Pitch', 'kalman_pitch_deg', 'Pitch', 'Pitch (deg)', 2),
        ('Heading', 'kalman_yaw_deg', 'Heading', 'Heading (deg)', 3),
        ('x_usbl', 'kalman_x', 'X Position', 'X (m)', 4),
        ('y_usbl', 'kalman_y', 'Y Position', 'Y (m)', 5)
    ]

    for raw_col, filtered_col, label, ylabel, plot_idx in plot_configs:
        ax = axes[plot_idx]
        if raw_col in df.columns:
            ax.plot(df['Timestamp'], df[raw_col], label=f'Raw {label}')
        if filtered_col in df.columns:
            ax.plot(df['Timestamp'], df[filtered_col], label=f'Filtered {label}')
        ax.set_xlabel('Timestamp')
        ax.set_ylabel(ylabel)
        ax.legend()

    plt.tight_layout()
    plot_file = processed_dir / f"{expedition}_{dive}_kalman_assessment_plots.png"
    plt.savefig(plot_file)
    print(f"Kalman assessment plots saved to: {plot_file}")
