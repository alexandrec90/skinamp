from skinamp.system.api import Machine, Refresh, RegValue, System
from tests.fakes import FakeMachine, FakeSystem


def public_methods(cls):
    return {name for name in vars(cls) if not name.startswith("_") and callable(getattr(cls, name))}


def test_the_fake_implements_the_whole_system_boundary():
    # Otherwise a method added to `System` is exercised by no test on the Linux gate.
    assert public_methods(System) <= public_methods(FakeSystem)
    assert public_methods(Machine) <= public_methods(FakeMachine)


def test_taskbar_refreshes_after_everything_it_reads():
    assert list(Refresh)[-1] is Refresh.TASKBAR


def test_explorer_restarts_after_every_broadcast_and_before_the_taskbar_needs_it():
    # Live finding: a settings broadcast reaching a half-started Explorer crashed it.
    order = list(Refresh)
    assert order.index(Refresh.SHELL) == len(order) - 2
    assert order[-1] is Refresh.TASKBAR


def test_reg_value_compares_by_type_as_well_as_data():
    assert RegValue("sz", "1") != RegValue("expand_sz", "1")
