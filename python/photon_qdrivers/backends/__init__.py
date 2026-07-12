"""Backend implementations and extension placeholders."""

from .dynamiqs_backend import DynamiqsBackend
from .emulator_targets import (
    DynamiqsBackend,
    LightworksBackend,
    PennyLaneSFBackend,
    PercevalBackend,
    PiquassoBackend,
    QuTiPBackend,
    StrawberryFieldsBackend,
    TheWalrusBackend,
)
from .emulator_backend import LocalEmulatorBackend
from .lightworks_backend import LightworksBackend
from .mock_backend import MockPhotonicBackend
from .orca_backend import OrcaBackend
from .perceval_backend import PercevalBackend
from .piquasso_backend import PiquassoBackend
from .psiquantum_backend import PsiQuantumBackend
from .qutip_backend import QuTiPBackend
from .quandela_backend import QuandelaBackend
from .strawberryfields_backend import StrawberryFieldsBackend
from .thewalrus_backend import TheWalrusBackend
from .unavailable import (
    UnavailableBackend,
    UnavailableEmulatorBackend,
    UnavailableHardwareBackend,
)
from .xanadu_backend import XanaduBackend

__all__ = [
    "LocalEmulatorBackend",
    "MockPhotonicBackend",
    "PercevalBackend",
    "PiquassoBackend",
    "LightworksBackend",
    "StrawberryFieldsBackend",
    "PennyLaneSFBackend",
    "TheWalrusBackend",
    "QuTiPBackend",
    "DynamiqsBackend",
    "XanaduBackend",
    "QuandelaBackend",
    "OrcaBackend",
    "PsiQuantumBackend",
    "UnavailableBackend",
    "UnavailableEmulatorBackend",
    "UnavailableHardwareBackend",
]
