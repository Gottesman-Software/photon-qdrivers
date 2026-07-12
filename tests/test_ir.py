import pytest

from photon_qdrivers import CircuitValidationError, IR_SCHEMA_VERSION, PhotonicCircuit


def test_circuit_ir_normalizes_operations() -> None:
    circuit = PhotonicCircuit.from_mapping(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "shots": 10,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
        }
    )

    assert circuit.schema_version == IR_SCHEMA_VERSION
    assert circuit.operation_names() == {"BS", "PS", "photon_counting"}
    assert circuit.operations[1].modes == (0,)
    assert circuit.operations[1].parameters == {"theta": 0.5}


def test_circuit_ir_requires_positive_shots() -> None:
    with pytest.raises(CircuitValidationError):
        PhotonicCircuit.from_mapping(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "shots": 0,
                "operations": [],
            }
        )


def test_circuit_ir_accepts_sequence_inputs() -> None:
    circuit = PhotonicCircuit.from_mapping(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "shots": 10,
            "operations": (
                {"gate": "BS", "modes": (0, 1)},
                {"measure": "photon_counting", "modes": (0, 1)},
            ),
        }
    )

    assert circuit.operations[0].modes == (0, 1)
