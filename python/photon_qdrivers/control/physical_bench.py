"""Versioned control programs for physical hardware benches."""

from __future__ import annotations

import math

from .acquisition import AcquisitionKind
from .native_protocol import ControlEnvelope
from .profile import HardwareProfile
from .program import (
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    EventKind,
)
from .timing import compile_control_program


RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP = {
    "source/0": 0,
    "modulator/0": 1,
    "phase/0": 2,
    "sync/0": 3,
    "detector/0": 4,
}


def red_pitaya_physical_loopback_envelope() -> ControlEnvelope:
    """Build the P6.1 125 MHz DIO_N0-to-DIO_P4 loopback schedule."""

    roles = {
        "source/0": ChannelRole.SOURCE,
        "modulator/0": ChannelRole.MODULATOR,
        "phase/0": ChannelRole.PHASE,
        "sync/0": ChannelRole.SYNC,
        "detector/0": ChannelRole.DETECTOR,
    }
    profile = HardwareProfile(
        profile_id="p61-red-pitaya-125mhz-v1",
        clock_period_ns=8.0,
        channel_roles=roles,
        counter_bits=2,
    )
    program = ControlProgram(
        program_id="p61-red-pitaya-digital-loopback-v1",
        channels=tuple(
            ControlChannel(name=name, role=role) for name, role in roles.items()
        ),
        events=(
            ControlEvent(
                "modulator-pulse",
                EventKind.MODULATOR_PULSE,
                "modulator/0",
                start_ns=16,
                duration_ns=24,
                parameters={"amplitude": 0.5},
            ),
            ControlEvent(
                "phase-update",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=16,
                parameters={"phase": math.pi},
            ),
            ControlEvent("sync-event", EventKind.SYNC, "sync/0", start_ns=32),
            ControlEvent(
                "delay-event",
                EventKind.DELAY,
                "sync/0",
                start_ns=40,
                duration_ns=8,
            ),
            ControlEvent(
                "physical-loopback-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=56,
                duration_ns=32,
                parameters={"amplitude": 1.0},
            ),
            ControlEvent(
                "physical-loopback-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=56,
                duration_ns=32,
                acquisition_id="p61-loopback-counts",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=1,
        repetition_period_ns=96,
        provenance={
            "bench": "red-pitaya-dio-n0-to-dio-p4",
            "schema": "p61-physical-loopback-v1",
        },
    )
    return ControlEnvelope(
        job_id="p61-red-pitaya-digital-loopback-job-v1",
        program=compile_control_program(program, profile),
    )
