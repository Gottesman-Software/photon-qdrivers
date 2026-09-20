"""Public convenience API for Photon-QDrivers."""

from __future__ import annotations

from typing import Any

from photon_qdrivers import (
    BackendCapabilityError,
    BackendConfig,
    BackendExecutionError,
    BackendUnavailableError,
    CircuitValidationError,
    ControlResourceError,
    ControlValidationError,
    AcquisitionKind,
    AcquisitionRecord,
    BOARD_CAPABILITIES_PROTOCOL,
    BOARD_PROGRAM_PROTOCOL,
    BOARD_REGISTER_MAP,
    BOARD_RESULT_PROTOCOL,
    PHYSICAL_EVIDENCE_PROTOCOL,
    PHYSICAL_REGISTER_MAP,
    RED_PITAYA_DEFAULT_BASE_ADDRESS,
    RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP,
    AnalyticLoopbackConfig,
    AnalyticLoopbackPlant,
    BoardCapabilities,
    BoardExecutionResult,
    BoardProgramImage,
    DevMemRegisterIO,
    ChannelRole,
    CompiledControlEvent,
    CompiledControlProgram,
    CompiledControlSweep,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    ControlSweep,
    EventKind,
    ExecutionTrace,
    DetectorResponse,
    HardwareProfile,
    LoopbackPath,
    P6BoardBridge,
    PhysicalExecutionEvidence,
    RedPitayaMMIOBoard,
    RegisterIO,
    QuantizationRule,
    RTL_INSTRUCTION_FORMAT_VERSION,
    RTL_INSTRUCTION_SCHEMA_VERSION,
    RTL_INSTRUCTION_WIDTH_BITS,
    RTLAcquisitionCode,
    RTLInstruction,
    RTLOpcode,
    RTLProgram,
    SoftwareBoard,
    SweepTargetKind,
    TraceEvent,
    TraceEventKind,
    VirtualControllerState,
    VirtualExecutionResult,
    VirtualPhotonicController,
    ZeroAcquisitionProvider,
    compile_control_program,
    decode_acquisition_payload,
    decode_control_request_frame,
    encode_control_request_frame,
    encode_control_result_frame,
    sha256_file,
    red_pitaya_physical_loopback_envelope,
    CONTROL_RESULT_PROTOCOL,
    CONTROL_TRANSPORT_PROTOCOL,
    CloudHardwareBackend,
    CloudJobClient,
    CloudJobSnapshot,
    CloudJobState,
    coerce_cloud_snapshot,
    coerce_cloud_state,
    JobStatus,
    JobTimeoutError,
    LiDMaSPlugin,
    NativeRuntime,
    PhotonDriver,
    PhotonicCircuit,
    PhotonicJob,
    PhotonicResult,
    SchroSIMPlugin,
    redact_sensitive_mapping,
)


class Driver(PhotonDriver):
    """Concise public facade for emulator and hardware adapter workflows."""

    @classmethod
    def load(
        cls,
        backend_name: str,
        config: BackendConfig | None = None,
        **options: Any,
    ) -> "Driver":
        driver = cls()
        driver.load_backend(backend_name, config=config, **options)
        return driver

    def use_plugin(self, plugin_name: str) -> Any:
        normalized_name = _normalize_plugin_name(plugin_name)
        try:
            return self.plugins.get(normalized_name)
        except KeyError:
            pass

        plugins = {
            "schrosim": SchroSIMPlugin,
            "lidmas": LiDMaSPlugin,
        }

        try:
            plugin_factory = plugins[normalized_name]
        except KeyError as exc:
            available = ", ".join(sorted(plugins))
            raise KeyError(
                f"Unknown plugin '{normalized_name}'. Available plugins: {available}."
            ) from exc

        return self.register_plugin(plugin_factory())


def _normalize_plugin_name(plugin_name: str) -> str:
    if not isinstance(plugin_name, str):
        raise TypeError("Plugin name must be a string.")

    normalized_name = plugin_name.strip().lower()
    if not normalized_name:
        raise ValueError("Plugin name must be non-empty.")
    return normalized_name


__all__ = [
    "Driver",
    "BackendConfig",
    "CloudJobSnapshot",
    "CloudJobState",
    "CloudHardwareBackend",
    "CloudJobClient",
    "coerce_cloud_snapshot",
    "coerce_cloud_state",
    "redact_sensitive_mapping",
    "PhotonicCircuit",
    "PhotonicJob",
    "PhotonicResult",
    "JobStatus",
    "NativeRuntime",
    "CircuitValidationError",
    "ControlValidationError",
    "ControlResourceError",
    "AcquisitionKind",
    "AcquisitionRecord",
    "BOARD_CAPABILITIES_PROTOCOL",
    "BOARD_PROGRAM_PROTOCOL",
    "BOARD_REGISTER_MAP",
    "BOARD_RESULT_PROTOCOL",
    "PHYSICAL_EVIDENCE_PROTOCOL",
    "PHYSICAL_REGISTER_MAP",
    "RED_PITAYA_DEFAULT_BASE_ADDRESS",
    "RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP",
    "AnalyticLoopbackConfig",
    "AnalyticLoopbackPlant",
    "BoardCapabilities",
    "BoardExecutionResult",
    "BoardProgramImage",
    "DevMemRegisterIO",
    "ChannelRole",
    "CompiledControlEvent",
    "CompiledControlProgram",
    "CompiledControlSweep",
    "ControlChannel",
    "ControlEnvelope",
    "ControlEvent",
    "ControlProgram",
    "ControlSweep",
    "EventKind",
    "ExecutionTrace",
    "DetectorResponse",
    "HardwareProfile",
    "LoopbackPath",
    "P6BoardBridge",
    "PhysicalExecutionEvidence",
    "RedPitayaMMIOBoard",
    "RegisterIO",
    "QuantizationRule",
    "RTL_INSTRUCTION_FORMAT_VERSION",
    "RTL_INSTRUCTION_SCHEMA_VERSION",
    "RTL_INSTRUCTION_WIDTH_BITS",
    "RTLAcquisitionCode",
    "RTLInstruction",
    "RTLOpcode",
    "RTLProgram",
    "SoftwareBoard",
    "SweepTargetKind",
    "TraceEvent",
    "TraceEventKind",
    "VirtualControllerState",
    "VirtualExecutionResult",
    "VirtualPhotonicController",
    "ZeroAcquisitionProvider",
    "compile_control_program",
    "decode_acquisition_payload",
    "decode_control_request_frame",
    "encode_control_request_frame",
    "encode_control_result_frame",
    "sha256_file",
    "red_pitaya_physical_loopback_envelope",
    "CONTROL_RESULT_PROTOCOL",
    "CONTROL_TRANSPORT_PROTOCOL",
    "BackendCapabilityError",
    "BackendExecutionError",
    "BackendUnavailableError",
    "JobTimeoutError",
]
