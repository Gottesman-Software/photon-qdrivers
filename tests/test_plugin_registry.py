import pytest

from photon_qdrivers import LiDMaSPlugin, PhotonDriver, SchroSIMPlugin


def test_register_plugins() -> None:
    driver = PhotonDriver()

    driver.register_plugin(SchroSIMPlugin())
    driver.register_plugin(LiDMaSPlugin())

    assert driver.list_plugins() == ["lidmas", "schrosim"]
    descriptions = driver.plugins.describe()
    assert {plugin["role"] for plugin in descriptions} == {"decoder", "simulator"}


def test_plugin_names_are_normalized_and_duplicates_are_explicit() -> None:
    class MixedCasePlugin:
        name = " SchroSIM "

    driver = PhotonDriver()
    driver.register_plugin(MixedCasePlugin())

    assert driver.list_plugins() == ["schrosim"]
    with pytest.raises(ValueError):
        driver.register_plugin(SchroSIMPlugin())
