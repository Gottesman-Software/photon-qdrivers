import pytest

from photon_qdrivers import (
    AcquisitionKind,
    AcquisitionRecord,
    ControlValidationError,
)


def test_acquisition_record_round_trip_preserves_provenance() -> None:
    record = AcquisitionRecord(
        acquisition_id="detector-window-0",
        kind=AcquisitionKind.COUNTS,
        payload={"d0": 12, "d1": 8},
        unit="counts",
        shape=(2,),
        start_tick=40,
        end_tick=72,
        overflow=True,
        dropped_events=3,
        metadata={"shot": 4, "sweep_index": 2},
    )

    restored = AcquisitionRecord.from_mapping(record.to_dict())

    assert restored == record
    assert restored.payload == {"d0": 12, "d1": 8}
    assert restored.end_tick - restored.start_tick == 32


def test_time_tags_reject_negative_ticks() -> None:
    with pytest.raises(ControlValidationError, match="Time tag"):
        AcquisitionRecord(
            acquisition_id="tags-0",
            kind=AcquisitionKind.TIME_TAGS,
            payload=[4, -1, 12],
            unit="ticks",
        )


def test_waveforms_reject_non_finite_samples() -> None:
    with pytest.raises(ControlValidationError, match="finite"):
        AcquisitionRecord(
            acquisition_id="adc-0",
            kind=AcquisitionKind.WAVEFORM,
            payload=[0.0, float("nan")],
            unit="normalized",
        )


def test_count_payload_requires_non_negative_integers() -> None:
    with pytest.raises(ControlValidationError, match="non-negative integer"):
        AcquisitionRecord(
            acquisition_id="counts-0",
            kind=AcquisitionKind.COUNTS,
            payload={"d0": 1.5},
            unit="counts",
        )
