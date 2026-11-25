"""What only real Windows can show (CI runs these, as administrator, on a throwaway machine): the Task Manager
redirect really set and really removed, and another tool's redirect left alone."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not os.environ.get("CI"),
                                reason="writes HKLM: Windows CI only")


def test_replace_and_restore_task_manager():
    import winreg
    from pr7sm import taskmgr
    try:
        taskmgr.replace()
        assert taskmgr.is_replaced() and taskmgr.current_debugger().endswith("/taskmgr")
        taskmgr.restore()
        assert not taskmgr.is_replaced() and taskmgr.current_debugger() == ""
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, taskmgr.IFEO, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Debugger", 0, winreg.REG_SZ, r'"C:\Tools\procexp64.exe"')
        taskmgr.restore()                                                  # someone else's: left alone
        assert taskmgr.current_debugger() == r'"C:\Tools\procexp64.exe"'
    finally:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, taskmgr.IFEO, 0, winreg.KEY_SET_VALUE | view) as k:
                    winreg.DeleteValue(k, "Debugger")
            except OSError:
                pass


def test_file_details_of_a_real_program():
    from pr7sm import winver
    d = winver.details(os.path.join(os.environ["SystemRoot"], "System32", "notepad.exe"))
    assert d.get("company") == "Microsoft Corporation" and d.get("description")
