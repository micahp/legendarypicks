"""Snap-relative elapsed time semantics for BDB2025 tracking observations."""

TRACKING_FRAME_RATE_HZ = 10


def tracking_time(snap_frame, input_frame_ids, label_frame_ids):
    expected_inputs = list(range(snap_frame - 5, snap_frame + 1))
    expected_labels = list(range(snap_frame, snap_frame + 11))
    if input_frame_ids != expected_inputs:
        raise ValueError(f"input frames must be {expected_inputs}, got {input_frame_ids}")
    if label_frame_ids != expected_labels:
        raise ValueError(f"label frames must be {expected_labels}, got {label_frame_ids}")
    return {
        "origin": "ball_snap",
        "originFrameId": snap_frame,
        "frameRateHz": TRACKING_FRAME_RATE_HZ,
        "inputElapsedSeconds": [round((frame - snap_frame) / TRACKING_FRAME_RATE_HZ, 1)
                                for frame in input_frame_ids],
        "labelElapsedSeconds": [round((frame - snap_frame) / TRACKING_FRAME_RATE_HZ, 1)
                                for frame in label_frame_ids],
    }


TIME_SEMANTICS = {
    "trackingTime": {
        "origin": "unique ball_snap frame",
        "frameRateHz": TRACKING_FRAME_RATE_HZ,
        "formula": "(frameId - snapFrame) / 10 seconds",
        "gameClock": "metadata.gameClock is the snap value copied from source; it is not advanced or interpolated from trackingTime",
    }
}
