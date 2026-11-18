"""The registry delete guard (clean.reg_delete_recursive / is_protected_key).

winreg.DeleteKey is replaced by a recorder for the whole test, so even a broken
guard cannot delete a real key: every check reads only what would have been
deleted.
"""

import os
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clean  # noqa: E402

deleted = []
real_delete = winreg.DeleteKey
winreg.DeleteKey = lambda hive, path: deleted.append((hive, path))
try:
    HKLM, HKCU, HKCR = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT
    SM_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    refused = [
        (HKLM, SM_ENV),
        (HKLM, SM_ENV.upper() + "\\"),                     # case and trailing slash
        (HKLM, r"SYSTEM\ControlSet001\Control\Session Manager\Environment"),
        (HKLM, r"SYSTEM\CurrentControlSet\Control\Session Manager"),   # a parent
        (HKLM, "SYSTEM"),
        (HKLM, "SOFTWARE"),
        (HKLM, ""),
        (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (HKCU, "Environment"),
        (HKCU, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (HKCU, "Software"),
        (HKCR, "CLSID"),
    ]
    for hive, path in refused:
        try:
            clean.reg_delete_recursive(hive, path)
            raise AssertionError(f"not refused: {path}")
        except PermissionError:
            pass
    assert not deleted, deleted
    print(f"refused ok: {len(refused)} protected keys and parents, nothing deleted")

    # children of protected keys stay deletable (an uninstall entry, a CLSID)
    for hive, path in ((HKCU, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\__nope__"),
                       (HKCR, r"CLSID\{00000000-0000-0000-0000-000000000000}"),
                       (HKCU, r"Software\__clean_guard_test__")):
        clean.reg_delete_recursive(hive, path)
    assert [p for _h, p in deleted] == [
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\__nope__",
        r"CLSID\{00000000-0000-0000-0000-000000000000}",
        r"Software\__clean_guard_test__"], deleted
    print("children ok: still deletable")

    # the orphan scanner no longer reads a PATH list as one missing file
    path_list = r"C:\Python\313\Scripts\;C:\Python\313\;C:\Program Files\ImageMagick-7.1.1-Q16-HDRI"
    assert clean.extract_path_candidate(path_list) == "", clean.extract_path_candidate(path_list)
    assert clean.extract_path_candidate(r'"C:\nope\app.exe" --x') == r"C:\nope\app.exe"
    assert clean.extract_path_candidate(r"C:\a;C:\nope\b.dll") == r"C:\nope\b.dll"
    assert clean.extract_path_candidate(r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI") == ""
    assert clean.extract_path_candidate(r"rundll32.exe C:\nope\x.dll,Start") == r"C:\nope\x.dll"
    assert clean.extract_path_candidate(r"C:\nope\a b\app.exe -flag") == r"C:\nope\a b\app.exe"
    print("orphan candidates ok")
finally:
    winreg.DeleteKey = real_delete

print("STATUS: SUCCESS")
