import pytest
from pydantic import ValidationError

from backend.app.schemas import Detection


@pytest.mark.parametrize(
    "bounds",
    [
        {"start_sec": 1},
        {"end_sec": 3},
        {"start_sec": 3, "end_sec": 1},
        {"start_sec": 2, "end_sec": 2},
        {"start_sec": -1, "end_sec": 3},
        {"start_sec": 0, "end_sec": 1},
        {"start_sec": 3, "end_sec": 4},
        {"start_sec": 0, "end_sec": float("inf")},
    ],
)
def test_invalid_detection_ranges_are_rejected(bounds):
    with pytest.raises(ValidationError):
        Detection(
            type="Test",
            timecode_sec=2,
            description="Observation",
            rule_id="R01",
            confidence=0.9,
            **bounds,
        )


def test_old_point_contract_and_new_range_contract_are_both_supported():
    fields = dict(
        type="Test", timecode_sec=2, description="Observation", rule_id="R01", confidence=0.9
    )
    assert Detection(**fields).start_sec is None
    interval = Detection(**fields, start_sec=1, end_sec=3)
    assert interval.start_sec == 1 and interval.end_sec == 3
