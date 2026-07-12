"""Project-specific exception types."""


class PhotonQDriversError(Exception):
    """Base class for Photon-QDrivers errors."""


class CircuitValidationError(ValueError, PhotonQDriversError):
    """Raised when a symbolic circuit does not satisfy the IR schema."""


class BackendCapabilityError(ValueError, PhotonQDriversError):
    """Raised when a backend cannot accept a valid circuit."""


class BackendUnavailableError(RuntimeError, PhotonQDriversError):
    """Raised when a registered backend adapter is not installed or configured."""


class BackendExecutionError(RuntimeError, PhotonQDriversError):
    """Raised when a backend fails after accepting a job."""


class JobTimeoutError(TimeoutError, PhotonQDriversError):
    """Raised when a submitted job does not complete within the requested timeout."""
