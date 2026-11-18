"""Contract test for winclassic.capture: what is read, what is left out, the
JSON round trip of every registry type, and the atomic replace of capture\\.

Nothing here touches this machine: the registry is an in-memory fake, the
Windhawk data folder and the package folder are scratch folders under %TEMP%,
and every side effect (installers, PowerShell, services, fonts) is replaced by
a fake that fails the test if it is called.
"""

import inspect
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import winclassic  # noqa: E402
from winclassic_fakes import MemoryRegistry  # noqa: E402

H, L = "HKCU", "HKLM"
NT = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
EP = r"Software\ExplorerPatcher"
ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
IMM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\ImmersiveShell"
CLSID1 = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
CLSID2 = r"Software\Classes\CLSID\{1eeb5b5a-06fb-4732-96b3-975c0194eb39}\InprocServer32"
OS = r"Software\OpenShell"
TT = r"Software\7 Taskbar Tweaker"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
COL = r"Control Panel\Colors"
WM = r"Control Panel\Desktop\WindowMetrics"
APP = r"Control Panel\Appearance"
FONTS = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
WH = r"SOFTWARE\Windhawk"
MODS = WH + r"\Engine\Mods"

VERSIONS = {"explorerpatcher": "22631.5335.68.2", "openshell": "4.4.191",
            "windhawk": "1.6.1", "taskbartweaker": "5.15.4"}


def forbidden(*args, **kwargs):
    raise AssertionError(f"real side effect called: {args} {kwargs}")


def make_pc():
    reg = MemoryRegistry()
    put = reg.set
    put(L, NT, "CurrentBuild", "SZ", "22631")
    put(L, NT, "UBR", "DWORD", 4249)
    put(L, r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName",
        "ComputerName", "SZ", "CAPTUREPC")
    # ExplorerPatcher
    put(H, EP, "OldTaskbar", "DWORD", 1)
    put(H, EP, "UpdateURL", "SZ", "")
    put(H, EP, "CrashCounter", "DWORD", 0)
    put(H, EP, "LastSectionInProperties", "DWORD", 0)
    put(H, EP, "SymbolsLastNotifiedOSBuild", "SZ", "10.0.22631.4249")
    put(H, EP + r"\sws", "RowHeight", "DWORD", 230)
    put(H, EP + r"\sws", "Theme", "DWORD", 0)
    put(H, EP + r"\explorer", "Hash", "SZ", "52ba8b5b8b9338c434f0702258273aba")
    put(H, EP + r"\explorer", "Version", "DWORD", 3)
    put(H, EP + r"\twinui.pcshell", "Version", "DWORD", 2)
    for name, val in (("TaskbarAl", 0), ("TaskbarSmallIcons", 1), ("TaskbarSD", 0),
                      ("TaskbarGlomLevel", 0), ("MMTaskbarGlomLevel", 0),
                      ("Start_ShowClassicMode", 1), ("Hidden", 1), ("TaskbarDa", 0)):
        put(H, ADV, name, "DWORD", val)
    put(L, IMM, "UseWin32BatteryFlyout", "DWORD", 1)
    put(L, IMM, "Other", "DWORD", 7)
    put(H, CLSID1, "", "SZ", "")
    put(H, CLSID1, "ThreadingModel", "SZ", "Both")
    put(H, CLSID2, "", "SZ", "")
    # Open-Shell
    s = OS + r"\StartMenu\Settings"
    put(H, s, "MenuStyle", "SZ", "Win7")
    put(H, s, "TreeItemSpacing", "DWORD", 4294967294)
    put(H, s, "LastSeen", "QWORD", 134351800836623971)
    put(H, s, "StartButtonPath", "EXPAND_SZ", r"%SystemRoot%\System32\@WLOGO_96x96.png")
    put(H, s, "MenuItems7", "MULTI_SZ", ["Item1.Command=user_files", "Item1.Settings=NOEXPAND"])
    put(H, s, "CSettingsDlg", "BINARY", b"\xed\xfb\xff\xff\x00\x01")
    put(H, s, "OldItems", "BINARY", b"")
    put(H, s, "Marker", "NONE", b"\x01\x02")
    put(H, s, "EmptyMarker", "NONE", b"")
    put(H, s, "Tahoma", "SZ", "Tahoma \u00b5 \u2126")
    put(H, s + r"\Nested", "Deep", "DWORD", 5)
    put(H, OS + r"\ClassicExplorer\Settings", "ShowStatusBar", "DWORD", 1)
    reg.create_key(H, OS + r"\OpenShell\Settings")
    put(H, OS + r"\OpenShell", "LastUpdateTime", "DWORD", 373221163)
    put(H, OS + r"\StartMenu", "LastProgramsTime", "QWORD", 134351800836623971)
    put(H, OS + r"\StartMenu", "ShowedStyle2", "DWORD", 1)
    put(H, OS + r"\StartMenu\MRU", "0", "SZ", r"C:\ProgramData\x.lnk")
    put(H, OS + r"\StartMenu\Order", "F7C85F56", "BINARY", b"\x01\x02")
    # 7+ Taskbar Tweaker
    for name, typ, val in (("language", "DWORD", 1033), ("hidetray", "DWORD", 0),
                           ("lefttrayfunc", "DWORD", 1), ("updcheck", "DWORD", 0),
                           ("updcheckauto", "DWORD", 0),
                           ("nounsupportedwarning_w11", "DWORD", 1),
                           ("install_dir", "SZ", r"C:\Program Files\7+ Taskbar Tweaker"),
                           ("MementoSection_StartMenuLnk", "DWORD", 1),
                           ("MementoSection_DesktopLnk", "DWORD", 0),
                           ("updchecktime", "DWORD", 0), ("inspector_w", "DWORD", 661),
                           ("inspector_h", "DWORD", 739)):
        put(H, TT, name, typ, val)
    put(H, TT + r"\Options", "1318069356", "DWORD", 1)
    put(H, TT + r"\Options", "1318069999", "DWORD", 2)
    put(H, TT + r"\OptionsEx", "tray_icons_padding", "DWORD", 6)
    reg.create_key(H, TT + r"\Combining")
    put(H, TT + r"\Keyboard Shortcuts", "x", "DWORD", 1)
    put(H, RUN, "7 Taskbar Tweaker", "SZ",
        r'"C:\Program Files\7+ Taskbar Tweaker\7+ Taskbar Tweaker.exe" -hidewnd')
    put(H, RUN, "AltSnap", "SZ", r"C:\AltSnap.exe")
    # classic appearance
    put(H, COL, "ButtonFace", "SZ", "212 208 200")
    put(H, COL, "Hilight", "SZ", "10 36 106")
    put(H, WM, "BorderWidth", "SZ", "-15")
    put(H, WM, "CaptionFont", "BINARY", b"\xf5\xff\xff\xff" + bytes(8) + b"T\x00a\x00")
    put(H, WM, "AppliedDPI", "DWORD", 96)
    put(H, APP, "SchemeLangID", "BINARY", b"\x09\x04")
    put(H, APP + r"\ClassicSchemes", "SelectedScheme", "SZ", "cplusruss")
    put(H, APP + r"\ClassicSchemes\cplusruss", "Color0", "DWORD", 13160660)
    put(H, APP + r"\ClassicSchemes\cplusruss\Normal", "Size0", "DWORD", 1)
    put(H, FONTS, "Marlett (TrueType)", "SZ",
        r"C:\Users\cplusruss\AppData\Local\Microsoft\Windows\Fonts\marlett.ttf")
    put(H, FONTS, "Charter (TrueType)", "SZ", r"C:\Fonts\Charter.ttf")
    # Windhawk
    put(L, WH + r"\Engine", "Warning", "SZ", "Don't delete this key, even if it's empty")
    put(L, WH + r"\Engine\Settings", "InjectIntoGames", "DWORD", 0)
    put(L, WH + r"\Settings", "Language", "SZ", "en")
    for mod, arch, dll, ver in (("local@both", "x86-64|x86", "local@both_1.0.0_111.dll", "1.0.0"),
                                ("local@win", "x86-64", "local@win_2.0_222.dll", "2.0"),
                                ("local@any", "", "local@any_1.0_333.dll", "1.0")):
        put(L, f"{MODS}\\{mod}", "LibraryFileName", "SZ", dll)
        put(L, f"{MODS}\\{mod}", "Architecture", "SZ", arch)
        put(L, f"{MODS}\\{mod}", "Version", "SZ", ver)
        put(L, f"{MODS}\\{mod}", "SettingsChangeTime", "DWORD", 1781472325)
        put(L, f"{MODS}\\{mod}\\Settings", "style", "SZ", "vista")
    put(L, WH + r"\Engine\ModsWritable", "Warning", "SZ", "Don't delete this key")
    put(L, WH + r"\Engine\ModsWritable\local@both\SymbolCache", "pdb_1", "SZ", "1#x")
    put(L, WH + r"\Engine\ModsWritable\local@both\LocalStorage", "last-path", "SZ", "C:\\WinSxS")
    return reg


def make_windhawk_data(root):
    files = {
        r"Engine\Mods\32\local@both_1.0.0_111.dll": b"both32",
        r"Engine\Mods\64\local@both_1.0.0_111.dll": b"both64",
        r"Engine\Mods\64\local@win_2.0_222.dll": b"win64",
        r"Engine\Mods\32\local@any_1.0_333.dll": b"any32",
        r"Engine\Mods\64\local@any_1.0_333.dll": b"any64",
        r"Engine\Mods\32\libc++.dll": b"runtime32",
        r"Engine\Mods\64\libc++.dll": b"runtime64",
        r"Engine\Mods\64\local@both_0.9_000.dll": b"stale",
        r"Engine\Mods\64\local@gone_1.0_999.dll": b"unregistered",
        r"ModsSource\local@both.wh.cpp": b"// both",
        r"ModsSource\local@win.wh.cpp": b"// win",
        r"ModsSource\local@any.wh.cpp": b"// any",
        r"ModsSource\local@gone.wh.cpp": b"// gone",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def load_json(cap, name):
    return json.loads((cap / name).read_text(encoding="utf-8"))


def keys_of(records):
    return {(r["hive"], r["path"], r["name"]) for r in records}


def tree_of(reg, hive, path):
    out = {}
    for name, typ, data in reg.values(hive, path):
        out[(path, name)] = (typ, data)
    for sub in reg.subkeys(hive, path):
        out.update(tree_of(reg, hive, path + "\\" + sub))
    return out


# ---- the registry interface: the fake and the winreg one stay in step ----
for meth in ("values", "subkeys", "get", "set", "create_key", "delete_tree", "exists"):
    a = inspect.signature(getattr(winclassic.WinReg, meth))
    b = inspect.signature(getattr(MemoryRegistry, meth))
    assert list(a.parameters) == list(b.parameters), (meth, a, b)
print("registry interface ok: WinReg and MemoryRegistry match")

# ---- the winreg implementation, read-only against a key every PC has ----
real = winclassic.WinReg()
vals = real.values(H, COL)
assert vals and all(t in winclassic.TYPE_NAMES.values() for _n, t, _d in vals), vals[:3]
assert all(isinstance(n, str) for n, _t, _d in vals)
build_type, build = real.get(L, NT, "CurrentBuild")
assert build_type == "SZ" and build.isdigit(), (build_type, build)
assert real.exists(H, COL) and not real.exists(H, r"Software\wintools-selftest-absent")
try:
    real.get(H, COL, "wintools-selftest-absent")
    raise AssertionError("missing value did not raise")
except FileNotFoundError:
    pass
try:
    real.values(H, r"Software\wintools-selftest-absent")
    raise AssertionError("missing key did not raise")
except FileNotFoundError:
    pass
assert "Marlett" not in real.subkeys(H, COL)
print("WinReg read-only ok")

# ---- every winreg type round trips through the JSON form ----
samples = [("DWORD", 0), ("DWORD", 4294967295), ("QWORD", 134351800836623971),
           ("QWORD", 0), ("SZ", ""), ("SZ", "Tahoma \u00b5 \u2126"),
           ("EXPAND_SZ", r"%SystemRoot%\x.png"), ("MULTI_SZ", ["a", "b c"]),
           ("MULTI_SZ", []), ("BINARY", b"\x00\xff\x10"), ("BINARY", b""),
           ("NONE", b"\x01"), ("NONE", b"")]
for typ, data in samples:
    text = json.dumps(winclassic.record(H, "k", "n", typ, data))
    back = json.loads(text)
    assert back["type"] == typ and back["hive"] == H and back["path"] == "k", back
    assert winclassic.decode_value(back["type"], back["data"]) == data, (typ, data)
    assert type(winclassic.decode_value(back["type"], back["data"])) is type(data)
assert winclassic.record(H, "k", "n", "BINARY", b"\x0a\xff")["data"] == "0aff"
assert winclassic.record(H, "k", "n", "NONE", b"")["data"] == ""
for bad in ("LINK", "DWORD_BE", "RESOURCE_LIST"):
    try:
        winclassic.record(H, "k", "n", bad, b"")
        raise AssertionError(f"{bad} was accepted")
    except ValueError as e:
        assert bad in str(e), e
print("value round trip ok:", len(samples), "samples")

# ---- capture against the fake PC ----
with tempfile.TemporaryDirectory(prefix="wintools-selftest-capture-") as scratch:
    scratch = Path(scratch)
    pkg = scratch / "pkg"
    (pkg / "installers").mkdir(parents=True)
    data_root = scratch / "ProgramData" / "Windhawk"
    make_windhawk_data(data_root)
    pc = make_pc()
    versions = dict(VERSIONS)

    patches = [
        mock.patch.object(winclassic, "REG", pc),
        mock.patch.object(winclassic, "package_dir", lambda: pkg),
        mock.patch.object(winclassic, "windhawk_data", lambda: data_root),
        mock.patch.object(winclassic, "installed_versions", lambda: dict(versions)),
        mock.patch.object(winclassic, "run_installer", forbidden),
        mock.patch.object(winclassic, "run_powershell", forbidden),
        mock.patch.object(winclassic, "set_service", forbidden),
        mock.patch.object(winclassic, "load_font", forbidden),
    ]
    for p in patches:
        p.start()
    assert isinstance(winclassic.REG, MemoryRegistry)
    try:
        cap = pkg / "capture"
        before = datetime.now().astimezone().replace(microsecond=0)
        n = winclassic.capture()
        after = datetime.now().astimezone()
        assert n == 6, n
        assert sorted(p.name for p in cap.iterdir()) == [
            "appearance.json", "explorerpatcher.json", "manifest.json",
            "openshell.json", "taskbartweaker.json", "windhawk"], list(cap.iterdir())
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())

        # ExplorerPatcher: the tree minus caches, plus the named loose values
        ep = load_json(cap, "explorerpatcher.json")
        assert keys_of(ep) == {
            (H, EP, "OldTaskbar"), (H, EP, "UpdateURL"),
            (H, EP + r"\sws", "RowHeight"), (H, EP + r"\sws", "Theme"),
            *((H, ADV, n) for n in ("TaskbarAl", "TaskbarSmallIcons", "TaskbarSD",
                                    "TaskbarGlomLevel", "MMTaskbarGlomLevel",
                                    "Start_ShowClassicMode")),
            (L, IMM, "UseWin32BatteryFlyout"),
            (H, CLSID1, ""), (H, CLSID2, ""),
        }, sorted(keys_of(ep))
        by = {(r["hive"], r["path"], r["name"]): r for r in ep}
        assert by[(H, CLSID1, "")]["type"] == "SZ" and by[(H, CLSID1, "")]["data"] == ""
        assert by[(H, EP + r"\sws", "RowHeight")] == {
            "hive": H, "path": EP + r"\sws", "name": "RowHeight", "type": "DWORD", "data": 230}
        print("explorerpatcher.json ok:", len(ep), "values")

        # Open-Shell: only the Settings subkeys, at any depth below them
        osr = load_json(cap, "openshell.json")
        assert keys_of(osr) == {
            (H, OS + r"\StartMenu\Settings", n)
            for n in ("MenuStyle", "TreeItemSpacing", "LastSeen", "StartButtonPath",
                      "MenuItems7", "CSettingsDlg", "OldItems", "Marker",
                      "EmptyMarker", "Tahoma")
        } | {(H, OS + r"\StartMenu\Settings\Nested", "Deep"),
             (H, OS + r"\ClassicExplorer\Settings", "ShowStatusBar")}, sorted(keys_of(osr))
        print("openshell.json ok:", len(osr), "values")

        # 7+ Taskbar Tweaker: settings subkeys, setting-like root values, the Run value
        tt = load_json(cap, "taskbartweaker.json")
        assert keys_of(tt) == {
            (H, TT, n) for n in ("language", "hidetray", "lefttrayfunc", "updcheck",
                                 "updcheckauto", "nounsupportedwarning_w11")
        } | {(H, TT + r"\Options", "1318069356"), (H, TT + r"\Options", "1318069999"),
             (H, TT + r"\OptionsEx", "tray_icons_padding"),
             (H, TT + r"\Keyboard Shortcuts", "x"),
             (H, RUN, "7 Taskbar Tweaker")}, sorted(keys_of(tt))
        print("taskbartweaker.json ok:", len(tt), "values")

        # classic appearance
        ap = load_json(cap, "appearance.json")
        assert keys_of(ap) == {
            (H, COL, "ButtonFace"), (H, COL, "Hilight"),
            (H, WM, "BorderWidth"), (H, WM, "CaptionFont"),
            (H, APP, "SchemeLangID"),
            (H, APP + r"\ClassicSchemes", "SelectedScheme"),
            (H, APP + r"\ClassicSchemes\cplusruss", "Color0"),
            (H, APP + r"\ClassicSchemes\cplusruss\Normal", "Size0"),
            (H, FONTS, "Marlett (TrueType)"),
        }, sorted(keys_of(ap))
        print("appearance.json ok:", len(ap), "values")

        # every captured value is the live value, exactly, in every type
        restored = MemoryRegistry()
        for name in ("explorerpatcher", "openshell", "taskbartweaker", "appearance"):
            for r in load_json(cap, name + ".json"):
                restored.set(r["hive"], r["path"], r["name"], r["type"],
                             winclassic.decode_value(r["type"], r["data"]))
                live = pc.get(r["hive"], r["path"], r["name"])
                assert (r["type"], winclassic.decode_value(r["type"], r["data"])) == live, r
        s = OS + r"\StartMenu\Settings"
        assert restored.get(H, s, "OldItems") == ("BINARY", b"")
        assert restored.get(H, s, "Marker") == ("NONE", b"\x01\x02")
        assert restored.get(H, s, "EmptyMarker") == ("NONE", b"")
        assert restored.get(H, s, "TreeItemSpacing") == ("DWORD", 4294967294)
        assert restored.get(H, s, "LastSeen") == ("QWORD", 134351800836623971)
        assert restored.get(H, s, "Tahoma") == ("SZ", "Tahoma \u00b5 \u2126")
        assert restored.get(H, s, "MenuItems7") == (
            "MULTI_SZ", ["Item1.Command=user_files", "Item1.Settings=NOEXPAND"])

        # Windhawk: registry minus the runtime caches, registered mods' files only
        wh = cap / "windhawk"
        assert sorted(p.name for p in wh.iterdir()) == ["Engine", "ModsSource", "windhawk.json"]
        whr = load_json(wh, "windhawk.json")
        paths = {r["path"] for r in whr}
        assert not [p for p in paths if "ModsWritable" in p], paths
        assert (L, WH + r"\Engine", "Warning") in keys_of(whr)
        assert (L, WH + r"\Settings", "Language") in keys_of(whr)
        assert (L, WH + r"\Engine\Settings", "InjectIntoGames") in keys_of(whr)
        assert (L, MODS + r"\local@both\Settings", "style") in keys_of(whr)
        assert (L, MODS + r"\local@win", "LibraryFileName") in keys_of(whr)
        assert len(whr) == 3 + 3 * 5, len(whr)
        files = sorted(str(p.relative_to(wh)) for p in wh.rglob("*") if p.is_file())
        assert files == sorted([
            r"Engine\Mods\32\local@any_1.0_333.dll",
            r"Engine\Mods\32\local@both_1.0.0_111.dll",
            r"Engine\Mods\64\local@any_1.0_333.dll",
            r"Engine\Mods\64\local@both_1.0.0_111.dll",
            r"Engine\Mods\64\local@win_2.0_222.dll",
            r"ModsSource\local@any.wh.cpp",
            r"ModsSource\local@both.wh.cpp",
            r"ModsSource\local@win.wh.cpp",
            "windhawk.json"]), files
        assert (wh / "Engine/Mods/64/local@win_2.0_222.dll").read_bytes() == b"win64"
        assert (wh / "Engine/Mods/32/local@both_1.0.0_111.dll").read_bytes() == b"both32"
        assert (wh / "ModsSource/local@any.wh.cpp").read_bytes() == b"// any"
        print("windhawk ok:", len(whr), "values,", len(files) - 1, "files")

        # manifest
        man = load_json(cap, "manifest.json")
        assert set(man) == {"captured", "computer", "build", "ubr", "dpi", "versions"}, man
        assert man["computer"] == "CAPTUREPC", man
        stamp = datetime.fromisoformat(man["captured"])
        assert before <= stamp <= after, (before, stamp, after)
        assert man["build"] == "22631" and man["ubr"] == 4249, man
        assert man["dpi"] == 96 and isinstance(man["dpi"], int), man
        assert man["versions"] == VERSIONS, man
        print("manifest ok:", man)

        # a failure midway leaves the previous capture exactly as it was
        (cap / "sentinel.txt").write_text("previous", encoding="utf-8")
        snapshot = {str(p.relative_to(cap)): p.read_bytes()
                    for p in cap.rglob("*") if p.is_file()}
        mod_dll = data_root / "Engine/Mods/64/local@win_2.0_222.dll"
        mod_dll.rename(mod_dll.with_name("hidden.dll"))
        try:
            winclassic.capture()
            raise AssertionError("missing mod dll did not fail the capture")
        except OSError as e:
            assert "local@win_2.0_222.dll" in str(e), e
        mod_dll.with_name("hidden.dll").rename(mod_dll)
        assert snapshot == {str(p.relative_to(cap)): p.read_bytes()
                            for p in cap.rglob("*") if p.is_file()}
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())

        # a missing tree is a genuine error naming it
        saved = tree_of(pc, H, OS)
        pc.delete_tree(H, OS)
        try:
            winclassic.capture()
            raise AssertionError("missing Open-Shell tree did not fail the capture")
        except OSError as e:
            assert r"HKCU\Software\OpenShell" in str(e), e
        assert (cap / "sentinel.txt").read_text(encoding="utf-8") == "previous"
        for (path, name), (typ, val) in saved.items():
            pc.set(H, path, name, typ, val)
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"]

        # a component that is not installed is a genuine error too
        versions["windhawk"] = None
        try:
            winclassic.capture()
            raise AssertionError("uninstalled Windhawk did not fail the capture")
        except OSError as e:
            assert "Windhawk" in str(e), e
        versions["windhawk"] = "1.6.1"
        assert (cap / "sentinel.txt").read_text(encoding="utf-8") == "previous"

        # an unreadable value type is a genuine error
        pc.set(H, OS + r"\StartMenu\Settings", "Odd", "LINK", b"\x00")
        try:
            winclassic.capture()
            raise AssertionError("unsupported type did not fail the capture")
        except ValueError as e:
            assert "LINK" in str(e) and "Odd" in str(e), e
        pc.delete_tree(H, OS + r"\StartMenu\Settings")
        for (path, name), (typ, val) in saved.items():
            pc.set(H, path, name, typ, val)

        def fails(kind, *needles):
            try:
                winclassic.capture()
            except kind as e:
                for needle in needles:
                    assert needle in str(e), (needle, str(e))
            else:
                raise AssertionError(f"capture did not fail with {kind.__name__}")
            assert (cap / "sentinel.txt").read_text(encoding="utf-8") == "previous"
            assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"]

        # Windhawk architectures: an unknown one, or a DLL missing for a required
        # one, fails with the mod id; none at all means x86 and x86-64
        any_key = f"{MODS}\\local@any"
        pc.set(L, any_key, "Architecture", "SZ", "x86-64|bogus")
        fails(ValueError, "local@any", "bogus")
        pc.set(L, any_key, "Architecture", "SZ", "")
        any32 = data_root / "Engine/Mods/32/local@any_1.0_333.dll"
        any32.rename(any32.with_name("hidden.dll"))
        fails(OSError, "local@any", str(any32))
        any32.with_name("hidden.dll").rename(any32)
        pc.set(L, f"{MODS}\\local@odd", "LibraryFileName", "SZ", "renamed.dll")
        pc.set(L, f"{MODS}\\local@odd", "Architecture", "SZ", "x86-64")
        fails(OSError, "local@odd", "renamed.dll")
        pc.delete_tree(L, f"{MODS}\\local@odd")
        any_src = data_root / "ModsSource/local@any.wh.cpp"
        any_src.rename(any_src.with_name("hidden.cpp"))
        fails(OSError, "local@any", str(any_src))
        any_src.with_name("hidden.cpp").rename(any_src)

        # the display scaling of the capturing PC is part of the manifest
        saved_wm = tree_of(pc, H, WM)
        pc.delete_tree(H, WM)
        for (path, name), (typ, val) in saved_wm.items():
            if name != "AppliedDPI":
                pc.set(H, path, name, typ, val)
        fails(OSError, "AppliedDPI")
        pc.set(H, WM, "AppliedDPI", "DWORD", 96)
        print("failed captures leave the previous one intact ok")

        # success replaces the previous capture as a whole
        winclassic.capture()
        assert not (cap / "sentinel.txt").exists()
        assert sorted(p.name for p in cap.iterdir()) == [
            "appearance.json", "explorerpatcher.json", "manifest.json",
            "openshell.json", "taskbartweaker.json", "windhawk"]
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"]
        print("successful capture replaces the previous one ok")

        # a stale temp folder from a crashed capture does not block the next one
        (pkg / "capture.new").mkdir()
        (pkg / "capture.new" / "junk").write_text("x")
        assert winclassic.capture() == 6
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"]

        # Dropbox or a scanner can hold the new folder for a moment: the swap retries
        real_rename = os.rename
        denied = []

        def flaky(src, dst, *args, **kwargs):
            if Path(src).name == "capture.new" and len(denied) < 2:
                denied.append(src)
                raise PermissionError(5, "Access is denied", str(src))
            return real_rename(src, dst, *args, **kwargs)

        (cap / "sentinel.txt").write_text("previous", encoding="utf-8")
        with mock.patch.object(os, "rename", flaky), \
                mock.patch.object(winclassic.time, "sleep") as nap:
            assert winclassic.capture() == 6
        assert len(denied) == 2 and nap.call_count == 2, (denied, nap.call_args_list)
        assert not (cap / "sentinel.txt").exists()
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"]

        # a folder that stays locked fails the capture and keeps the previous one
        (cap / "sentinel.txt").write_text("previous", encoding="utf-8")
        snapshot = {str(p.relative_to(cap)): p.read_bytes()
                    for p in cap.rglob("*") if p.is_file()}

        def locked(src, dst, *args, **kwargs):
            if Path(src).name == "capture.new":
                raise PermissionError(5, "Access is denied", str(src))
            return real_rename(src, dst, *args, **kwargs)

        with mock.patch.object(os, "rename", locked), \
                mock.patch.object(winclassic.time, "sleep"):
            try:
                winclassic.capture()
                raise AssertionError("a locked folder did not fail the capture")
            except PermissionError:
                pass
        assert snapshot == {str(p.relative_to(cap)): p.read_bytes()
                            for p in cap.rglob("*") if p.is_file()}
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())
        print("locked folder retries and fails cleanly ok")

        # the previous capture is removed even when Dropbox holds its folder for a moment
        real_rmtree = shutil.rmtree
        held = []

        def stubborn(path, *args, **kwargs):
            if Path(path).name == "capture.old" and len(held) < 2:
                held.append(path)  # the folder stays, as it does while it is held
                return None
            return real_rmtree(path, *args, **kwargs)

        with mock.patch.object(shutil, "rmtree", stubborn), \
                mock.patch.object(winclassic.time, "sleep") as nap:
            assert winclassic.capture() == 6
        assert len(held) == 2 and nap.call_count == 2, (held, nap.call_args_list)
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())

        # a swap that died half way: the old capture comes back if the new one fails,
        # and a leftover old folder next to a good capture is cleared
        (cap / "sentinel.txt").write_text("previous", encoding="utf-8")
        cap.rename(pkg / "capture.old")
        mod_dll.rename(mod_dll.with_name("hidden.dll"))
        try:
            winclassic.capture()
            raise AssertionError("missing mod dll did not fail the capture")
        except OSError:
            pass
        mod_dll.with_name("hidden.dll").rename(mod_dll)
        assert (cap / "sentinel.txt").read_text(encoding="utf-8") == "previous"
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())
        (pkg / "capture.old").mkdir()
        (pkg / "capture.old" / "junk").write_text("x")
        assert winclassic.capture() == 6
        assert sorted(p.name for p in pkg.iterdir()) == ["capture", "installers"], list(pkg.iterdir())
        print("half-finished swaps ok")
    finally:
        for p in patches:
            p.stop()

# the package folder itself must exist
with tempfile.TemporaryDirectory(prefix="wintools-selftest-capture-") as scratch:
    gone = Path(scratch) / "resource" / "winclassic"
    with mock.patch.object(winclassic, "package_dir", mock.Mock(side_effect=FileNotFoundError(f"missing {gone}"))), \
            mock.patch.object(winclassic, "REG", make_pc()):
        try:
            winclassic.capture()
            raise AssertionError("missing package folder did not fail the capture")
        except FileNotFoundError as e:
            assert str(gone) in str(e), e
print("missing package folder ok")
assert os.path.isabs(str(Path(__file__)))
print("STATUS: SUCCESS")
