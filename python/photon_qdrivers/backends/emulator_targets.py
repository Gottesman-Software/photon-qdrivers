"""Known emulator backend registration points."""

from __future__ import annotations

from photon_qdrivers.backends.dynamiqs_backend import DynamiqsBackend
from photon_qdrivers.backends.lightworks_backend import LightworksBackend
from photon_qdrivers.backends.perceval_backend import PercevalBackend
from photon_qdrivers.backends.piquasso_backend import PiquassoBackend
from photon_qdrivers.backends.qutip_backend import QuTiPBackend
from photon_qdrivers.backends.strawberryfields_backend import StrawberryFieldsBackend
from photon_qdrivers.backends.thewalrus_backend import TheWalrusBackend
from photon_qdrivers.backends.unavailable import UnavailableEmulatorBackend


class PennyLaneSFBackend(UnavailableEmulatorBackend):
    """Unavailable adapter stub for PennyLane-SF legacy workflows."""

    name = "pennylane-sf"
    target_name = "PennyLane-SF"
    package_hint = "photon-qdrivers-pennylane-sf"
    docs_hint = "install the PennyLane-SF adapter for legacy compatibility workflows."
