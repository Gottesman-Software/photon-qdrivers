"""ctypes binding for the Photon-QDrivers C++ runtime."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .errors import BackendExecutionError, BackendUnavailableError
from .job import PhotonicJob


class NativeRuntime:
    """Thin Python wrapper around the C ABI exported by `photon_qdrivers_capi`."""

    def __init__(
        self,
        library_path: str | os.PathLike[str] | None = None,
        *,
        transport: str = "in_memory",
        command_path: str | os.PathLike[str] | None = None,
        result_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.library_path = _resolve_library_path(library_path)
        try:
            self._lib = ctypes.CDLL(str(self.library_path))
        except OSError as exc:
            raise BackendUnavailableError(
                "Native C++ runtime library is not available. Build it with "
                "`cmake -S . -B build && cmake --build build`, or set "
                "PHOTON_QDRIVERS_NATIVE_LIBRARY."
            ) from exc

        _configure_signatures(self._lib)
        self.transport = _normalize_transport(transport)
        self._handle = self._create_handle(
            command_path=command_path,
            result_path=result_path,
        )
        if not self._handle:
            raise BackendUnavailableError("Native C++ runtime could not be created.")
        self._closed = False

    @classmethod
    def available(cls, library_path: str | os.PathLike[str] | None = None) -> bool:
        try:
            cls(library_path).close()
        except BackendUnavailableError:
            return False
        return True

    @classmethod
    def candidate_library_paths(cls) -> list[Path]:
        return _candidate_library_paths()

    def initialize(self) -> None:
        self._check(self._lib.pqdr_runtime_initialize(self._handle))

    def shutdown(self) -> None:
        if not self._closed and self._handle:
            self._check(self._lib.pqdr_runtime_shutdown(self._handle))

    def close(self) -> None:
        if self._closed:
            return
        if self._handle:
            self._lib.pqdr_runtime_destroy(self._handle)
            self._handle = None
        self._closed = True

    def capabilities(self) -> dict[str, Any]:
        return self._read_json(self._lib.pqdr_runtime_capabilities(self._handle))

    def submit_job(self, job: PhotonicJob) -> None:
        circuit_ir = json.dumps(job.circuit.to_dict(), sort_keys=True, separators=(",", ":"))
        operations = ",".join(operation.name for operation in job.circuit.operations)
        status = self._lib.pqdr_runtime_submit_job(
            self._handle,
            _bytes(job.job_id),
            _bytes(circuit_ir),
            ctypes.c_uint32(job.circuit.modes),
            ctypes.c_uint64(job.shots),
            _bytes(operations),
        )
        self._check(status)

    def read_result(self, job_id: str) -> dict[str, Any]:
        return self._read_json(self._lib.pqdr_runtime_read_result(self._handle, _bytes(job_id)))

    def run_job(self, job: PhotonicJob) -> dict[str, Any]:
        self.submit_job(job)
        return self.read_result(job.job_id)

    def last_error(self) -> str:
        return _decode(self._lib.pqdr_runtime_last_error(self._handle))

    def _check(self, status: int) -> None:
        if int(status) != 0:
            message = self.last_error() or "Native C++ runtime call failed."
            raise BackendExecutionError(message)

    def _read_json(self, raw_value: bytes | str | None) -> dict[str, Any]:
        decoded = _decode(raw_value)
        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise BackendExecutionError(
                f"Native C++ runtime returned invalid JSON: {decoded!r}"
            ) from exc
        if not isinstance(value, Mapping):
            raise BackendExecutionError("Native C++ runtime JSON result must be an object.")
        return dict(value)

    def __enter__(self) -> "NativeRuntime":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.shutdown()
        finally:
            self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _create_handle(
        self,
        *,
        command_path: str | os.PathLike[str] | None,
        result_path: str | os.PathLike[str] | None,
    ) -> int:
        if self.transport == "in_memory":
            return self._lib.pqdr_runtime_create()

        if self.transport == "fpga_mailbox":
            if command_path is None or result_path is None:
                raise BackendUnavailableError(
                    "Native fpga_mailbox transport requires command_path and result_path."
                )
            if not hasattr(self._lib, "pqdr_runtime_create_fpga_mailbox"):
                raise BackendUnavailableError(
                    "Native C++ runtime library does not expose fpga_mailbox transport. "
                    "Rebuild with `cmake --build build`."
                )
            return self._lib.pqdr_runtime_create_fpga_mailbox(
                _bytes(str(command_path)),
                _bytes(str(result_path)),
            )

        if self.transport == "red_pitaya":
            if command_path is None or result_path is None:
                raise BackendUnavailableError(
                    "Native red_pitaya transport requires command_path and result_path."
                )
            if not hasattr(self._lib, "pqdr_runtime_create_red_pitaya"):
                raise BackendUnavailableError(
                    "Native C++ runtime library does not expose Red Pitaya transport. "
                    "Rebuild with `cmake --build build`."
                )
            return self._lib.pqdr_runtime_create_red_pitaya(
                _bytes(str(command_path)),
                _bytes(str(result_path)),
            )

        raise BackendUnavailableError(f"Unknown native runtime transport '{self.transport}'.")


def _configure_signatures(library: ctypes.CDLL) -> None:
    library.pqdr_runtime_create.argtypes = []
    library.pqdr_runtime_create.restype = ctypes.c_void_p

    if hasattr(library, "pqdr_runtime_create_fpga_mailbox"):
        library.pqdr_runtime_create_fpga_mailbox.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        library.pqdr_runtime_create_fpga_mailbox.restype = ctypes.c_void_p

    if hasattr(library, "pqdr_runtime_create_red_pitaya"):
        library.pqdr_runtime_create_red_pitaya.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        library.pqdr_runtime_create_red_pitaya.restype = ctypes.c_void_p

    library.pqdr_runtime_destroy.argtypes = [ctypes.c_void_p]
    library.pqdr_runtime_destroy.restype = None

    library.pqdr_runtime_initialize.argtypes = [ctypes.c_void_p]
    library.pqdr_runtime_initialize.restype = ctypes.c_int

    library.pqdr_runtime_shutdown.argtypes = [ctypes.c_void_p]
    library.pqdr_runtime_shutdown.restype = ctypes.c_int

    library.pqdr_runtime_submit_job.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_uint64,
        ctypes.c_char_p,
    ]
    library.pqdr_runtime_submit_job.restype = ctypes.c_int

    library.pqdr_runtime_read_result.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    library.pqdr_runtime_read_result.restype = ctypes.c_char_p

    library.pqdr_runtime_capabilities.argtypes = [ctypes.c_void_p]
    library.pqdr_runtime_capabilities.restype = ctypes.c_char_p

    library.pqdr_runtime_last_error.argtypes = [ctypes.c_void_p]
    library.pqdr_runtime_last_error.restype = ctypes.c_char_p

    library.pqdr_runtime_version.argtypes = []
    library.pqdr_runtime_version.restype = ctypes.c_char_p


def _resolve_library_path(library_path: str | os.PathLike[str] | None) -> Path:
    if library_path is not None:
        path = Path(library_path).expanduser()
        if path.exists():
            return path
        raise BackendUnavailableError(f"Native C++ runtime library was not found: {path}")

    configured = os.environ.get("PHOTON_QDRIVERS_NATIVE_LIBRARY")
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
        raise BackendUnavailableError(
            f"PHOTON_QDRIVERS_NATIVE_LIBRARY does not exist: {path}"
        )

    for path in _candidate_library_paths():
        if path.exists():
            return path

    candidates = ", ".join(str(path) for path in _candidate_library_paths())
    raise BackendUnavailableError(
        "Native C++ runtime library was not found. Checked: " + candidates
    )


def _candidate_library_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    build_dir = repo_root / "build"
    names = _library_names()
    candidates: list[Path] = []
    for directory in (
        build_dir,
        build_dir / "Debug",
        build_dir / "Release",
        repo_root,
    ):
        candidates.extend(directory / name for name in names)
    return candidates


def _library_names() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("libphoton_qdrivers_capi.dylib", "libphoton_qdrivers_capi.so")
    if os.name == "nt":
        return ("photon_qdrivers_capi.dll",)
    return ("libphoton_qdrivers_capi.so",)


def _normalize_transport(value: str) -> str:
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"memory", "inmemory", "in_memory"}:
        return "in_memory"
    if normalized in {"fpga", "fpga_mailbox", "mailbox"}:
        return "fpga_mailbox"
    if normalized in {"red_pitaya", "redpitaya", "rp", "stemlab", "stemlab_125_14"}:
        return "red_pitaya"
    return normalized


def _bytes(value: str) -> bytes:
    return value.encode("utf-8")


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
