import win32api

from app import acquire_single_instance


def test_only_one_instance_can_hold_the_lock():
    name = "ShakeChecker_pytest_singleinstance"
    h1 = acquire_single_instance(name)
    assert h1 is not None  # first acquire wins

    assert acquire_single_instance(name) is None  # second is blocked while h1 is held

    win32api.CloseHandle(h1)  # release -> the named mutex is gone
    h2 = acquire_single_instance(name)
    assert h2 is not None  # a fresh acquire succeeds again
    win32api.CloseHandle(h2)
