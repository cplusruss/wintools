"""Contract test for the winclassic steps (the six Classic rows of New PC).

Nothing here touches this machine: the registry is an in-memory fake, the
package, Windhawk data and fonts folders are scratch folders under %TEMP%, and
the installer runner, PowerShell, service control, font loading and the
elevation check are fakes that record what they were asked to do. The real
run_installer is exercised against this Python interpreter (which changes
nothing) and against a fake subprocess.run.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import initcfg  # noqa: E402
import tweaks  # noqa: E402
import winclassic  # noqa: E402
from winclassic_fakes import MemoryRegistry  # noqa: E402

H, L = "HKCU", "HKLM"
NT = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
EP = r"Software\ExplorerPatcher"
IMM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\ImmersiveShell"
CLSID1 = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
OS = r"Software\OpenShell\StartMenu\Settings"
TT = r"Software\7 Taskbar Tweaker"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
COL = r"Control Panel\Colors"
WM = r"Control Panel\Desktop\WindowMetrics"
FONTS = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
WH = r"SOFTWARE\Windhawk"
MODS = WH + r"\Engine\Mods"
THEMES = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes"
DLL = r"Engine\Mods\64\local@win_2.0_222.dll"
DLL32 = r"Engine\Mods\32\local@win_2.0_222.dll"
SRC = r"ModsSource\local@win.wh.cpp"
EP_DIR = r"C:\Program Files\ExplorerPatcher"
COMPUTER = r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName"

VERSIONS = {"explorerpatcher": "22631.5335.68.2", "openshell": "4.4.191",
            "windhawk": "1.6.1", "taskbartweaker": "5.15.4"}
INSTALLS = {"ep_setup.exe": "explorerpatcher", "openshell_setup.exe": "openshell",
            "windhawk_setup_offline.exe": "windhawk", "7tt_setup.exe": "taskbartweaker"}
KEYS = ("defenderep", "explorerpatcher", "openshell", "windhawk",
        "taskbartweaker", "classicappearance")
LABELS = ("ExplorerPatcher Defender Exclusion", "ExplorerPatcher", "Open-Shell",
          "Windhawk", "7+ Taskbar Tweaker", "Classic Appearance")
OPENSHELL_OK = (0, 3010, 1641)


def rec(hive, path, name, typ, data):
    return winclassic.record(hive, path, name, typ, data)


CAPTURE = {
    "explorerpatcher.json": [
        rec(H, EP, "OldTaskbar", "DWORD", 1),
        rec(H, EP, "UpdateURL", "SZ", ""),
        rec(H, EP + r"\sws", "RowHeight", "DWORD", 230),
        rec(L, IMM, "UseWin32BatteryFlyout", "DWORD", 1),
        rec(H, CLSID1, "", "SZ", ""),
    ],
    "openshell.json": [
        rec(H, OS, "MenuStyle", "SZ", "Win7"),
        rec(H, OS, "TreeItemSpacing", "DWORD", 4294967294),
        rec(H, OS, "MenuItems7", "MULTI_SZ", ["Item1.Command=user_files", "Item2.Command=lib_documents"]),
        rec(H, OS, "StartButtonPath", "EXPAND_SZ", r"%SystemRoot%\System32\@WLOGO_96x96.png"),
        rec(H, OS, "OldItems", "BINARY", b""),
        rec(H, OS, "CSettingsDlg", "BINARY", b"\xed\xfb\xff\xff\x00\x01"),
        rec(H, OS, "LastSeen", "QWORD", 134351800836623971),
    ],
    "taskbartweaker.json": [
        rec(H, TT, "language", "DWORD", 1033),
        rec(H, TT + r"\Options", "1318069999", "DWORD", 2),
        rec(H, TT + r"\OptionsEx", "tray_icons_padding", "DWORD", 6),
        rec(H, RUN, "7 Taskbar Tweaker", "SZ",
            r'"C:\Program Files\7+ Taskbar Tweaker\7+ Taskbar Tweaker.exe" -hidewnd'),
    ],
    "appearance.json": [
        rec(H, COL, "ButtonFace", "SZ", "212 208 200"),
        rec(H, WM, "BorderWidth", "SZ", "-15"),
        rec(H, WM, "CaptionFont", "BINARY", b"\xf5\xff\xff\xff" + bytes(8)),
        rec(H, FONTS, "Marlett (TrueType)", "SZ",
            r"C:\Users\someone-else\AppData\Local\Microsoft\Windows\Fonts\marlett.ttf"),
    ],
    "windhawk/windhawk.json": [
        rec(L, WH + r"\Settings", "Language", "SZ", "en"),
        rec(L, MODS + r"\local@win", "LibraryFileName", "SZ", "local@win_2.0_222.dll"),
        rec(L, MODS + r"\local@win", "Architecture", "SZ", "x86-64|x86"),
        rec(L, MODS + r"\local@win\Settings", "style", "SZ", "vista"),
    ],
}
CAPTURE_FILES = {
    "windhawk/" + DLL.replace("\\", "/"): b"win64",
    "windhawk/" + DLL32.replace("\\", "/"): b"win32",
    "windhawk/" + SRC.replace("\\", "/"): b"// win",
}
DEFAULT_COLORS = {
    r"\Standard": [("ActiveTitle", 13743257), ("Window", 16777215)],
    r"\HighContrast": [("ActiveTitle", 7209015), ("Window", 0)],
}


def write_package(pkg, build="22631"):
    inst = pkg / "installers"
    inst.mkdir(parents=True)
    for name in (*INSTALLS, "marlett.ttf"):
        (inst / name).write_bytes(b"pkg:" + name.encode())
    cap = pkg / "capture"
    for rel, records in CAPTURE.items():
        p = cap / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(records), encoding="utf-8")
    for rel, data in CAPTURE_FILES.items():
        p = cap / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (cap / "manifest.json").write_text(json.dumps({
        "captured": "2026-10-13T12:00:00-05:00", "computer": "THISPC", "build": build,
        "ubr": 100, "dpi": 96, "versions": VERSIONS}), encoding="utf-8")


def make_machine(build="22631", default_colors=True):
    reg = MemoryRegistry()
    reg.set(L, NT, "CurrentBuild", "SZ", build)
    reg.set(L, NT, "UBR", "DWORD", 100)
    reg.set(L, COMPUTER, "ComputerName", "SZ", "ThisPC")
    reg.set(H, WM, "AppliedDPI", "DWORD", 96)
    if default_colors:
        for sub, vals in DEFAULT_COLORS.items():
            for name, val in vals:
                reg.set(L, THEMES + r"\DefaultColors" + sub, name, "DWORD", val)
    return reg


def dump(reg):
    out = {}

    def walk(hive, path):
        if not reg.exists(hive, path):
            return
        for name, typ, data in reg.values(hive, path):
            out[(hive, path, name)] = (typ, data)
        for sub in reg.subkeys(hive, path):
            walk(hive, path + "\\" + sub)
    for hive, path in ((H, "Software"), (H, "Control Panel"), (L, "SOFTWARE")):
        walk(hive, path)
    return out


def message(e):
    return e.strerror or str(e)


app = QApplication([])
STEP = {s.key: s for s in winclassic.STEPS}
real_run_installer = winclassic.run_installer
real_run_powershell = winclassic.run_powershell
real_installed_versions = winclassic.installed_versions
real_backup_root = winclassic.backup_root


def st(key):
    # what InitConfigPage.refresh_states does before it reads any row
    winclassic.clear_cache()
    return STEP[key].state()


with tempfile.TemporaryDirectory(prefix="wintools-selftest-apply-") as scratch:
    scratch = Path(scratch)
    pkg = scratch / "pkg"
    write_package(pkg)
    data_root = scratch / "ProgramData" / "Windhawk"
    fonts = scratch / "Fonts"
    ep_root = scratch / "ExplorerPatcher"
    backups = scratch / "backups"
    pc = make_machine()
    installed = {}
    exclusions = []
    events = []
    exit_codes = {}  # installer name -> (exit code, whether the program installs)
    admin = [True]
    enumerations = [0]
    exports = []  # (hive, path, events seen before the export)

    def fake_run_installer(path, args, ok=(0,)):
        path = Path(path)
        assert path.is_file(), path
        events.append(("installer", path.name, list(args), ok))
        code, installs = exit_codes.get(path.name, (0, True))
        if installs:
            comp = INSTALLS[path.name]
            installed[comp] = VERSIONS[comp]
            # what a real installer leaves behind, for the capture to overwrite
            if path.name == "ep_setup.exe":
                ep_root.mkdir(exist_ok=True)
                (ep_root / winclassic.EP_DLL).write_bytes(b"ep dll")
                pc.set(H, EP, "OldTaskbar", "DWORD", 0)
                pc.set(H, EP, "IsUpdatePending", "DWORD", 1)
            if path.name == "windhawk_setup_offline.exe":
                pc.set(L, WH + r"\Settings", "Language", "SZ", "de")
                for sub in ("32", "64"):
                    p = data_root / "Engine" / "Mods" / sub / "libc++.dll"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"runtime" + sub.encode())
        if ok is not None and code not in ok:
            raise OSError(f"{path.name} exit {code}")
        return code

    def fake_powershell(script):
        events.append(("powershell", script))
        if script == winclassic.DEFENDER_GET:
            return "\n".join(exclusions) + ("\n" if exclusions else "")
        if script == winclassic.DEFENDER_ADD:
            exclusions.append(EP_DIR)
            return ""
        raise AssertionError(f"unexpected PowerShell: {script}")

    def fake_service(name, running):
        events.append(("service", name, running,
                       (data_root / DLL).exists(), pc.exists(L, MODS + r"\local@win"),
                       pc.exists(L, WH + r"\Settings")))

    def fake_font(path):
        events.append(("font", str(path), Path(path).read_bytes()))

    def fake_export(hive, path, dest):
        # what reg export keeps: every value of the key and its subkeys
        exports.append((hive, path, len(events)))
        out = []

        def walk(key):
            out.extend([key, *v] for v in pc.values(hive, key))
            for sub in pc.subkeys(hive, key):
                walk(key + "\\" + sub)
        walk(path)
        Path(dest).write_text(json.dumps([[k, n, t, d if isinstance(d, (str, int, list)) else d.hex()]
                                          for k, n, t, d in out]), encoding="utf-8")

    def exported(key, hive, path):
        # the values of hive\path in the newest backup of the step
        folder = max(backups.glob(f"winclassic_{key}_*"))
        name = winclassic.clean._safe_filename(f"{hive}__{path.replace(chr(92), '__')}")
        if not (folder / f"{name}.reg").exists():
            return None
        return {(k, n): (t, d) for k, n, t, d in
                json.loads((folder / f"{name}.reg").read_text(encoding="utf-8"))}

    def fake_versions():
        enumerations[0] += 1
        return {k: installed.get(k) for k in VERSIONS}

    def fresh_machine():
        global pc
        pc = make_machine()
        winclassic.REG = pc
        shutil.rmtree(data_root, ignore_errors=True)
        events.clear()
        installed.clear()
        exit_codes.clear()
        exports.clear()
        shutil.rmtree(backups, ignore_errors=True)
        shutil.rmtree(ep_root, ignore_errors=True)

    patches = [
        mock.patch.object(winclassic, "REG", pc),
        mock.patch.object(winclassic, "package_dir", lambda: pkg),
        mock.patch.object(winclassic, "windhawk_data", lambda: data_root),
        mock.patch.object(winclassic, "fonts_dir", lambda: fonts),
        mock.patch.object(winclassic, "ep_dir", lambda: ep_root),
        mock.patch.object(winclassic, "backup_root", lambda: backups),
        mock.patch.object(winclassic, "export_key", fake_export),
        mock.patch.object(winclassic, "installed_versions", fake_versions),
        mock.patch.object(winclassic, "is_admin", lambda: admin[0]),
        mock.patch.object(winclassic, "run_installer", fake_run_installer),
        mock.patch.object(winclassic, "run_powershell", fake_powershell),
        mock.patch.object(winclassic, "set_service", fake_service),
        mock.patch.object(winclassic, "load_font", fake_font),
    ]
    for p in patches:
        p.start()
    assert isinstance(winclassic.REG, MemoryRegistry)
    try:
        # ---- the row objects ----
        assert tuple(s.key for s in winclassic.STEPS) == KEYS
        assert tuple(s.label for s in winclassic.STEPS) == LABELS
        assert {s.section for s in winclassic.STEPS} == {"Classic"}
        for s in winclassic.STEPS:
            try:
                s.apply(False)
                raise AssertionError(f"{s.key}.apply(False) did not raise")
            except NotImplementedError:
                pass
        assert not events
        assert sorted(winclassic.INSTALLERS.values()) == sorted([*INSTALLS, "marlett.ttf"])
        print("row objects ok")

        # ---- not elevated, a build mismatch and missing files fail the step before it does anything ----
        before = dump(pc)
        admin[0] = False
        for key in KEYS:
            try:
                STEP[key].apply(True)
                raise AssertionError(f"{key} ran without elevation")
            except OSError as e:
                assert message(e) == "not elevated", (key, message(e))
        admin[0] = True
        assert not events and dump(pc) == before, events
        print("not elevated ok")

        pc.set(L, NT, "CurrentBuild", "SZ", "22000")
        for key in KEYS:
            try:
                STEP[key].apply(True)
                raise AssertionError(f"{key} ran on the wrong build")
            except OSError as e:
                assert message(e) == "build 22000, capture is 22631", (key, message(e))
        pc.set(L, NT, "CurrentBuild", "SZ", "22631")
        assert not events and dump(pc) == before, events
        print("build mismatch ok")

        # WindowMetrics are specific to the display scaling
        pc.set(H, WM, "AppliedDPI", "DWORD", 120)
        before_dpi = dump(pc)
        try:
            STEP["classicappearance"].apply(True)
            raise AssertionError("appearance ran at another DPI")
        except OSError as e:
            assert message(e) == "DPI 120, capture is 96", message(e)
        assert not events and dump(pc) == before_dpi and not fonts.exists(), events
        pc.delete_tree(H, WM)
        try:
            STEP["classicappearance"].apply(True)
            raise AssertionError("appearance ran without a DPI")
        except OSError as e:
            assert "AppliedDPI" in message(e), message(e)
        pc.set(H, WM, "AppliedDPI", "DWORD", 96)
        assert not events and dump(pc) == before and not fonts.exists(), events
        print("DPI mismatch ok")

        inst_win = pkg / "installers" / "windhawk_setup_offline.exe"
        inst_win.rename(inst_win.with_name("hidden"))
        try:
            STEP["windhawk"].apply(True)
            raise AssertionError("missing installer did not fail")
        except OSError as e:
            assert message(e) == f"missing {inst_win}", message(e)
        inst_win.with_name("hidden").rename(inst_win)
        cap_os = pkg / "capture" / "openshell.json"
        cap_os.rename(cap_os.with_name("hidden"))
        try:
            STEP["openshell"].apply(True)
            raise AssertionError("missing capture file did not fail")
        except OSError as e:
            assert message(e) == f"missing {cap_os}", message(e)
        cap_os.with_name("hidden").rename(cap_os)
        man = pkg / "capture" / "manifest.json"
        man.rename(man.with_name("hidden"))
        try:
            STEP["explorerpatcher"].apply(True)
            raise AssertionError("missing manifest did not fail")
        except OSError as e:
            assert message(e) == f"missing {man}", message(e)
        man.with_name("hidden").rename(man)
        assert not events and dump(pc) == before, events
        print("missing installer / capture file ok")

        # ---- exit codes: ExplorerPatcher is judged by the version that got installed ----
        exit_codes["ep_setup.exe"] = (5, False)
        try:
            STEP["explorerpatcher"].apply(True)
            raise AssertionError("an install that did not happen passed")
        except OSError as e:
            assert message(e) == "ep_setup.exe exit 5", message(e)
        assert [e[0] for e in events] == ["installer"] and events[0][3] is None, events
        assert not pc.exists(H, EP), "nothing is written when the install failed"
        fresh_machine()
        exit_codes["ep_setup.exe"] = (5, True)
        assert STEP["explorerpatcher"].apply(True) == 0
        assert pc.get(H, EP, "OldTaskbar") == ("DWORD", 1)
        assert events == [("installer", "ep_setup.exe", ["/update_silent"], None)], events

        # Open-Shell: 0, 3010 and 1641 are success, anything else is not
        for code, passes in ((0, True), (3010, True), (1641, True), (1603, False), (1, False)):
            fresh_machine()
            exit_codes["openshell_setup.exe"] = (code, passes)
            try:
                STEP["openshell"].apply(True)
                assert passes, f"exit {code} passed"
            except OSError as e:
                assert not passes and message(e) == f"openshell_setup.exe exit {code}", (code, message(e))
            assert pc.exists(H, OS) == passes, code
        # the others accept 0 only
        for name, key in (("windhawk_setup_offline.exe", "windhawk"), ("7tt_setup.exe", "taskbartweaker")):
            fresh_machine()
            before = dump(pc)
            exit_codes[name] = (3010, False)
            try:
                STEP[key].apply(True)
                raise AssertionError(f"{key} passed on exit 3010")
            except OSError as e:
                assert message(e) == f"{name} exit 3010", message(e)
            assert [e[0] for e in events] == ["installer"], events
            assert dump(pc) == before, "a failed install wrote nothing"
        print("exit codes ok")

        # ---- the Windhawk service comes back whatever fails after it stopped ----
        for owner, target, label in ((winclassic.shutil, "copytree", "copy"),
                                     (winclassic, "write_records", "registry write")):
            fresh_machine()
            with mock.patch.object(owner, target,
                                   side_effect=PermissionError(5, "Access is denied")) as boom:
                try:
                    STEP["windhawk"].apply(True)
                    raise AssertionError(f"failing {label} did not fail the step")
                except OSError as e:
                    assert message(e) == "Access is denied", (label, message(e))
                assert boom.called
            assert [e[2] for e in events if e[0] == "service"] == [False, True], (label, events)
            assert events[-1][0] == "service", (label, events)
        fresh_machine()
        print("service restarted after a failure ok")

        # ---- states before anything is applied ----
        assert st("defenderep") is False
        for key in KEYS[1:]:
            assert st(key) is False, key
        events.clear()
        print("states off before apply ok")

        # ---- the whole run, in row order ----
        for s in winclassic.STEPS:
            assert s.apply(True) == 0, s.key

        assert events[0] == ("powershell", winclassic.DEFENDER_ADD)
        assert winclassic.DEFENDER_ADD == f"Add-MpPreference -ExclusionPath '{EP_DIR}'"
        rest = [e for e in events[1:] if e[0] != "powershell"]
        assert rest[0] == ("installer", "ep_setup.exe", ["/update_silent"], None)
        assert rest[1] == ("installer", "openshell_setup.exe",
                           ["/qn", "ADDLOCAL=StartMenu", "REBOOT=ReallySuppress"], OPENSHELL_OK)
        assert rest[2] == ("installer", "windhawk_setup_offline.exe", ["/S", "/STANDARD"], (0,))
        # stop sees no mod files and no mod registry yet; start sees both
        assert rest[3] == ("service", "Windhawk", False, False, False, True), rest[3]
        assert rest[4] == ("service", "Windhawk", True, True, True, True), rest[4]
        assert rest[5] == ("installer", "7tt_setup.exe", ["/S"], (0,))
        assert rest[6][0] == "font" and rest[6][2] == b"pkg:marlett.ttf", rest[6]
        assert len(rest) == 7, rest
        assert [e[1] for e in events if e[0] == "installer"] == list(INSTALLS)
        print("order, installer paths and switches ok")

        # ---- registry writes land exactly as captured ----
        marlett = fonts / "marlett.ttf"
        for name, records in CAPTURE.items():
            for r in records:
                want = (r["type"], winclassic.decode_value(r["type"], r["data"]))
                if r["name"] == "Marlett (TrueType)":
                    want = ("SZ", str(marlett))
                assert pc.get(r["hive"], r["path"], r["name"]) == want, (name, r)
        assert pc.get(H, EP, "OldTaskbar") == ("DWORD", 1), "capture must overwrite the installer default"
        assert pc.get(L, WH + r"\Settings", "Language") == ("SZ", "en")
        assert pc.get(H, EP, "IsUpdatePending") == ("DWORD", 1), "values outside the capture stay"
        assert pc.get(H, OS, "OldItems") == ("BINARY", b"")
        print("registry writes ok")

        # ---- Windhawk files ----
        assert (data_root / DLL).read_bytes() == b"win64"
        assert (data_root / DLL32).read_bytes() == b"win32"
        assert (data_root / SRC).read_bytes() == b"// win"
        assert (data_root / r"Engine\Mods\64\libc++.dll").read_bytes() == b"runtime64"
        print("windhawk files ok")

        # ---- Marlett and DefaultColors ----
        assert marlett.read_bytes() == b"pkg:marlett.ttf"
        assert [e for e in events if e[0] == "font"] == [("font", str(marlett), b"pkg:marlett.ttf")]
        assert not pc.exists(L, THEMES + r"\DefaultColors")
        for sub, vals in DEFAULT_COLORS.items():
            assert pc.values(L, THEMES + r"\DefaultColors.bak" + sub) == [
                (n, "DWORD", v) for n, v in vals], sub
        print("marlett and DefaultColors rename ok")

        # ---- all six rows are on ----
        for key in KEYS:
            assert st(key) is True, key
        print("states on after apply ok")

        # ---- running the appearance step again: already renamed counts as done ----
        events.clear()
        bak_before = dump(pc)
        assert STEP["classicappearance"].apply(True) == 0
        assert dump(pc) == bak_before
        assert st("classicappearance") is True
        print("rename twice ok")

        # ---- Windows brought DefaultColors back: the backup is replaced by it ----
        pc.set(L, THEMES + r"\DefaultColors\Standard", "ActiveTitle", "DWORD", 1)
        pc.set(L, THEMES + r"\DefaultColors\Extra", "Window", "DWORD", 2)
        assert st("classicappearance") is False
        assert STEP["classicappearance"].apply(True) == 0
        assert not pc.exists(L, THEMES + r"\DefaultColors")
        assert pc.get(L, THEMES + r"\DefaultColors.bak\Standard", "ActiveTitle") == ("DWORD", 1)
        assert pc.get(L, THEMES + r"\DefaultColors.bak\Extra", "Window") == ("DWORD", 2)
        assert pc.values(L, THEMES + r"\DefaultColors.bak\Standard") == [
            ("ActiveTitle", "DWORD", 1)], pc.values(L, THEMES + r"\DefaultColors.bak\Standard")
        assert st("classicappearance") is True
        print("rename with a stale backup ok")

        # ---- one changed value turns exactly its row off ----
        def flips(key, mutate, restore):
            mutate()
            assert st(key) is False, key
            assert [k for k in KEYS if st(k) is False] == [key], key
            restore()
            assert st(key) is True, key

        flips("explorerpatcher",
              lambda: pc.set(H, EP + r"\sws", "RowHeight", "DWORD", 231),
              lambda: pc.set(H, EP + r"\sws", "RowHeight", "DWORD", 230))
        flips("explorerpatcher",
              lambda: pc.set(H, CLSID1, "", "SZ", "x"),
              lambda: pc.set(H, CLSID1, "", "SZ", ""))
        flips("openshell",
              lambda: pc.set(H, OS, "OldItems", "BINARY", b"\x00"),
              lambda: pc.set(H, OS, "OldItems", "BINARY", b""))
        flips("openshell",
              lambda: pc.set(H, OS, "TreeItemSpacing", "QWORD", 4294967294),
              lambda: pc.set(H, OS, "TreeItemSpacing", "DWORD", 4294967294))
        flips("taskbartweaker",
              lambda: pc.set(H, RUN, "7 Taskbar Tweaker", "SZ", "x"),
              lambda: pc.set(H, RUN, "7 Taskbar Tweaker", "SZ", CAPTURE["taskbartweaker.json"][3]["data"]))
        flips("windhawk",
              lambda: pc.set(L, MODS + r"\local@win\Settings", "style", "SZ", "classic"),
              lambda: pc.set(L, MODS + r"\local@win\Settings", "style", "SZ", "vista"))
        flips("classicappearance",
              lambda: pc.set(H, COL, "ButtonFace", "SZ", "1 2 3"),
              lambda: pc.set(H, COL, "ButtonFace", "SZ", "212 208 200"))
        saved_dll = (data_root / DLL).read_bytes()
        # a DLL that is here is this PC's own build; one that is gone is not
        flips("windhawk", lambda: (data_root / DLL).unlink(),
              lambda: (data_root / DLL).write_bytes(saved_dll))
        (data_root / DLL).write_bytes(b"rebuilt here")
        assert st("windhawk") is True
        (data_root / DLL).write_bytes(saved_dll)
        flips("windhawk", lambda: (data_root / SRC).unlink(),
              lambda: (data_root / SRC).write_bytes(b"// win"))
        flips("classicappearance", lambda: marlett.unlink(),
              lambda: marlett.write_bytes(b"pkg:marlett.ttf"))
        flips("classicappearance",
              lambda: pc.create_key(L, THEMES + r"\DefaultColors"),
              lambda: pc.delete_tree(L, THEMES + r"\DefaultColors"))
        assert st("classicappearance") is True
        for key, comp in (("explorerpatcher", "explorerpatcher"), ("openshell", "openshell"),
                          ("windhawk", "windhawk"), ("taskbartweaker", "taskbartweaker")):
            old = installed[comp]
            installed[comp] = "0.0.1"
            assert st(key) is False, key
            installed[comp] = None
            assert st(key) is False, key
            installed[comp] = old
            assert st(key) is True, key
        print("single changes flip exactly one row ok")

        # ---- one refresh of the page: one uninstall enumeration, one Get-MpPreference ----
        events.clear()
        with mock.patch.object(initcfg, "STEPS", KEYS), mock.patch.object(tweaks, "TWEAKS", []):
            enumerations[0] = 0
            page = initcfg.InitConfigPage(lambda text: None, lambda: None, lambda: None)
            assert enumerations[0] == 1, enumerations
            assert [e[1] for e in events if e[0] == "powershell"] == [winclassic.DEFENDER_GET]
            assert [page.grid.item(r, 2).text() for r in range(6)] == ["on"] * 6
            events.clear()
            enumerations[0] = 0
            page.refresh_states()
            assert enumerations[0] == 1, enumerations
            assert [e[1] for e in events if e[0] == "powershell"] == [winclassic.DEFENDER_GET]
            # the cache is cleared at the start of each refresh, so changes show
            installed["openshell"] = None
            exclusions[:] = []
            page.refresh_states()
            assert [page.grid.item(r, 2).text() for r in range(6)] == [
                "off", "on", "off", "on", "on", "on"], [
                    page.grid.item(r, 2).text() for r in range(6)]
            installed["openshell"] = VERSIONS["openshell"]
            exclusions[:] = [EP_DIR]
            # rows read outside a refresh share the cached answers
            enumerations[0] = 0
            winclassic.clear_cache()
            for key in KEYS:
                STEP[key].state()
            assert enumerations[0] == 1, enumerations
            events.clear()
            STEP["defenderep"].state()
            assert [e[1] for e in events if e[0] == "powershell"] == [], events
            winclassic.clear_cache()
            STEP["defenderep"].state()
            STEP["defenderep"].state()
            assert [e[1] for e in events if e[0] == "powershell"] == [winclassic.DEFENDER_GET], events
            page.shutdown()
        print("one enumeration and one PowerShell per refresh ok")

        # ---- defender state ----
        assert st("defenderep") is True
        exclusions[:] = [EP_DIR.lower() + "\\", r"C:\Other"]
        assert st("defenderep") is True
        exclusions[:] = [r"C:\Program Files\ExplorerPatcher2", r"C:\Other"]
        assert st("defenderep") is False
        exclusions[:] = []
        assert st("defenderep") is False
        exclusions[:] = ["N/A: Must be an administrator to view exclusions"]
        assert st("defenderep") is None
        exclusions[:] = [EP_DIR]
        with mock.patch.object(winclassic, "run_powershell",
                               mock.Mock(side_effect=OSError("powershell exit 1"))):
            assert st("defenderep") is None
            try:
                STEP["defenderep"].apply(True)
                raise AssertionError("PowerShell failure did not fail the step")
            except OSError as e:
                assert message(e) == "powershell exit 1"
        assert winclassic.DEFENDER_GET == "(Get-MpPreference).ExclusionPath"
        print("defender state ok")

        # ---- a missing capture: the five captured rows read n/a ----
        (pkg / "capture").rename(pkg / "capture.hidden")
        assert [st(k) for k in KEYS] == [True, None, None, None, None, None]
        (pkg / "capture.hidden").rename(pkg / "capture")
        (pkg / "capture" / "windhawk" / "windhawk.json").write_text("{not json", encoding="utf-8")
        assert st("windhawk") is None
        (pkg / "capture" / "windhawk" / "windhawk.json").write_text(
            json.dumps(CAPTURE["windhawk/windhawk.json"]), encoding="utf-8")
        assert st("windhawk") is True
        print("missing capture reads n/a ok")

        # ---- the user name differs on the new PC: the Fonts value points at this user's folder ----
        assert pc.get(H, FONTS, "Marlett (TrueType)") == ("SZ", str(marlett))

        # ---- a capture from another PC or another update is refused until confirmed ----
        fresh_machine()
        man_path = pkg / "capture" / "manifest.json"
        man_text = man_path.read_text(encoding="utf-8")
        pc.set(L, NT, "UBR", "DWORD", 3958)
        before = dump(pc)
        assert winclassic.capture_mismatch() == ["UBR 3958, capture is 100"]
        for key in KEYS:
            try:
                STEP[key].apply(True)
                raise AssertionError(f"{key} ran on another UBR")
            except OSError as e:
                assert message(e) == "UBR 3958, capture is 100 (not confirmed)", (key, message(e))
        pc.set(L, COMPUTER, "ComputerName", "SZ", "OTHERPC")
        assert winclassic.capture_mismatch() == [
            "captured on THISPC, this is OTHERPC", "UBR 3958, capture is 100"]
        try:
            STEP["windhawk"].apply(True)
            raise AssertionError("windhawk ran on another PC")
        except OSError as e:
            assert message(e).startswith("captured on THISPC, this is OTHERPC; UBR"), message(e)
        assert not events and dump(pc) == before, events
        pc.set(L, NT, "UBR", "DWORD", 100)
        pc.set(L, COMPUTER, "ComputerName", "SZ", "ThisPC")
        assert winclassic.capture_mismatch() == [], "computer names compare without case"
        # a capture taken before the manifest named its PC
        old = json.loads(man_text)
        del old["computer"]
        man_path.write_text(json.dumps(old), encoding="utf-8")
        assert winclassic.capture_mismatch() == ["capture does not name its PC"]
        try:
            STEP["openshell"].apply(True)
            raise AssertionError("openshell ran on an unnamed capture")
        except OSError as e:
            assert message(e) == "capture does not name its PC (not confirmed)", message(e)
        assert not events and not exports and not backups.exists(), events
        pc.set(L, NT, "UBR", "DWORD", 3958)
        # confirmed: the run goes ahead, for exactly those reasons and that capture
        reasons = winclassic.capture_mismatch()
        winclassic.accept_mismatch(reasons)
        assert STEP["defenderep"].apply(True) == 0
        assert events == [("powershell", winclassic.DEFENDER_ADD)], events
        pc.set(L, NT, "UBR", "DWORD", 3959)
        try:
            STEP["defenderep"].apply(True)
            raise AssertionError("a confirmation carried over to another UBR")
        except OSError as e:
            assert message(e).endswith("UBR 3959, capture is 100 (not confirmed)"), message(e)
        pc.set(L, NT, "UBR", "DWORD", 3958)
        old["captured"] = "2026-10-14T09:00:00-05:00"
        man_path.write_text(json.dumps(old), encoding="utf-8")
        try:
            STEP["defenderep"].apply(True)
            raise AssertionError("a confirmation carried over to another capture")
        except OSError as e:
            assert message(e).endswith("(not confirmed)"), message(e)
        winclassic.accept_mismatch(None)
        man_path.write_text(man_text, encoding="utf-8")
        pc.set(L, NT, "UBR", "DWORD", 100)
        assert winclassic._accepted == [None]
        print("UBR and computer mismatch ok")

        # ---- installers never run over the captured version or a newer one ----
        fresh_machine()
        installed.update(VERSIONS, windhawk="1.7.0", openshell="4.4.191",
                         explorerpatcher="22631.5335.68.2", taskbartweaker="5.15.10")
        for key in KEYS[1:5]:
            assert STEP[key].apply(True) == 0, key
        assert not [e for e in events if e[0] == "installer"], events
        assert pc.get(H, EP, "OldTaskbar") == ("DWORD", 1), "the settings are still written"
        assert pc.get(H, OS, "MenuStyle") == ("SZ", "Win7")
        assert (data_root / DLL).read_bytes() == b"win64"
        assert not ep_root.exists(), "no ExplorerPatcher folder backup without an install"
        for key in KEYS[1:5]:
            assert st(key) is True, key
        # an older one is replaced
        installed.update(windhawk="1.5.1", explorerpatcher="22621.3880.66.6",
                         openshell="4.4.190", taskbartweaker="5.15.3")
        for key in KEYS[1:5]:
            assert st(key) is False, key
        events.clear()
        for key in KEYS[1:5]:
            assert STEP[key].apply(True) == 0, key
        assert [e[1] for e in events if e[0] == "installer"] == list(INSTALLS), events
        assert winclassic.at_least("22631.5335.68.2", "22631.5335.68.2")
        assert winclassic.at_least("22631.5335.68.10", "22631.5335.68.2")
        assert not winclassic.at_least("22621.3880.66.6", "22631.5335.68.2")
        assert not winclassic.at_least("1.5.1", "1.6.1") and winclassic.at_least("1.10", "1.6.1")
        assert not winclassic.at_least(None, "1.6.1")
        print("installer skipped when current ok")

        # ---- ExplorerPatcher is judged by the installed DLL's version ----
        fake_entries = [mock.Mock(display_name="ExplorerPatcher", display_version="22621.3880.66.6"),
                        mock.Mock(display_name="Windhawk v1.5.1", display_version="1.5.1")]
        with mock.patch.object(winclassic.clean, "enumerate_uninstall_entries",
                               lambda: fake_entries), \
                mock.patch.object(winclassic, "file_version",
                                  lambda p: "22631.5335.68.2" if Path(p) == ep_root / winclassic.EP_DLL
                                  else None):
            got = real_installed_versions()
        assert got == {"explorerpatcher": "22631.5335.68.2", "openshell": None,
                       "windhawk": "1.5.1", "taskbartweaker": None}, got
        with mock.patch.object(winclassic.clean, "enumerate_uninstall_entries", lambda: fake_entries):
            shutil.rmtree(ep_root, ignore_errors=True)
            assert real_installed_versions()["explorerpatcher"] is None, "no DLL, not installed"
            ep_root.mkdir()
            shutil.copy2(sys.executable, ep_root / winclassic.EP_DLL)
            v = real_installed_versions()["explorerpatcher"]
        assert v == winclassic.file_version(sys.executable), v
        assert v.startswith(f"{sys.version_info.major}.{sys.version_info.minor}."), v
        assert winclassic.file_version(scratch / "absent.dll") is None
        print("ExplorerPatcher file version ok:", v)

        # ---- every step backs up what it will change, before it changes anything ----
        fresh_machine()
        pc.set(H, EP, "OldTaskbar", "DWORD", 7)
        pc.set(H, EP + r"\sws", "RowHeight", "DWORD", 99)
        pc.set(H, OS, "MenuStyle", "SZ", "Classic")
        pc.set(L, WH + r"\Settings", "Language", "SZ", "fr")
        pc.set(H, COL, "ButtonFace", "SZ", "1 1 1")
        ep_root.mkdir()
        (ep_root / winclassic.EP_DLL).write_bytes(b"old ep")
        (data_root / "ModsSource").mkdir(parents=True)
        (data_root / "ModsSource" / "other.wh.cpp").write_bytes(b"// other")
        fonts.mkdir(exist_ok=True)
        marlett.write_bytes(b"old marlett")
        for s in winclassic.STEPS:
            assert s.apply(True) == 0, s.key
        assert exported("explorerpatcher", H, EP) == {
            (EP, "OldTaskbar"): ("DWORD", 7), (EP + r"\sws", "RowHeight"): ("DWORD", 99)}
        assert exported("explorerpatcher", L, IMM) is None, "keys that did not exist are skipped"
        assert exported("openshell", H, OS) == {(OS, "MenuStyle"): ("SZ", "Classic")}
        assert exported("windhawk", L, WH) == {(WH + r"\Settings", "Language"): ("SZ", "fr")}
        assert exported("classicappearance", H, COL) == {(COL, "ButtonFace"): ("SZ", "1 1 1")}
        assert exported("classicappearance", L, THEMES + r"\DefaultColors")[
            (THEMES + r"\DefaultColors\Standard", "ActiveTitle")] == ("DWORD", 13743257)
        folder = {k: max(backups.glob(f"winclassic_{k}_*")) for k in KEYS[1:]}
        assert (folder["explorerpatcher"] / "files" / "ExplorerPatcher" / winclassic.EP_DLL
                ).read_bytes() == b"old ep"
        assert (folder["windhawk"] / "files" / "ModsSource" / "other.wh.cpp").read_bytes() == b"// other"
        assert (folder["classicappearance"] / "files" / "marlett.ttf").read_bytes() == b"old marlett"
        assert [(h, p) for h, p, _n in exports] == [
            (H, EP), (H, OS), (L, WH), (H, COL), (H, WM), (L, THEMES + r"\DefaultColors")], exports
        # the keys each step would export; one inside another is not exported twice
        assert winclassic.top_keys(CAPTURE["explorerpatcher.json"]) == [
            (H, CLSID1), (H, EP), (L, IMM)]
        assert winclassic.top_keys(CAPTURE["taskbartweaker.json"]) == [(H, TT), (H, RUN)]
        assert winclassic.top_keys(CAPTURE["appearance.json"]) == [(H, COL), (H, WM), (H, FONTS)]
        # each export came before its step's installer: the n events seen then are the earlier steps'
        installer_at = {e[1]: i for i, e in enumerate(events) if e[0] == "installer"}
        assert all(n <= installer_at["ep_setup.exe"] for h, p, n in exports if p == EP), exports
        assert all(n <= installer_at["windhawk_setup_offline.exe"] for h, p, n in exports if p == WH)
        # a backup that fails stops the step before it changes anything
        fresh_machine()
        with mock.patch.object(winclassic, "export_key",
                               side_effect=OSError(r"backup of HKCU\x failed: denied")):
            pc.set(H, OS, "MenuStyle", "SZ", "Classic")
            before = dump(pc)
            try:
                STEP["openshell"].apply(True)
                raise AssertionError("a failed backup did not stop the step")
            except OSError as e:
                assert message(e) == r"backup of HKCU\x failed: denied", message(e)
        assert not events and dump(pc) == before, events
        assert real_backup_root() == winclassic.clean.REG_BACKUP_DIR
        print("backups ok")

        # ---- Windhawk keeps a mod this PC built itself ----
        LOCAL64 = r"Engine\Mods\64\local@win_1.0_111.dll"
        LOCAL32 = r"Engine\Mods\32\local@win_1.0_111.dll"

        def local_build(source=b"// win"):
            fresh_machine()
            installed["windhawk"] = VERSIONS["windhawk"]
            pc.set(L, MODS + r"\local@win", "LibraryFileName", "SZ", "local@win_1.0_111.dll")
            pc.set(L, MODS + r"\local@win", "Architecture", "SZ", "x86-64|x86")
            pc.set(L, MODS + r"\local@win\Settings", "style", "SZ", "classic")
            for rel, data in ((LOCAL64, b"here64"), (LOCAL32, b"here32"), (SRC, source)):
                (data_root / rel).parent.mkdir(parents=True, exist_ok=True)
                (data_root / rel).write_bytes(data)

        local_build()
        assert st("windhawk") is False
        assert STEP["windhawk"].apply(True) == 0
        assert pc.get(L, MODS + r"\local@win", "LibraryFileName") == ("SZ", "local@win_1.0_111.dll")
        assert pc.get(L, MODS + r"\local@win\Settings", "style") == ("SZ", "vista"), "settings still applied"
        assert (data_root / LOCAL64).read_bytes() == b"here64"
        assert (data_root / LOCAL32).read_bytes() == b"here32"
        assert not (data_root / DLL).exists() and not (data_root / DLL32).exists(), \
            "the capture's build is not copied next to this PC's"
        assert not [e for e in events if e[0] == "installer"], "1.6.1 is installed already"
        assert st("windhawk") is True
        assert exported("windhawk", L, WH)[(MODS + r"\local@win", "LibraryFileName")] == (
            "SZ", "local@win_1.0_111.dll")
        print("windhawk keeps this PC's build ok")

        # a build here from another source: refused, nothing changed
        local_build(source=b"// win, edited here")
        before = dump(pc)
        try:
            STEP["windhawk"].apply(True)
            raise AssertionError("a mod built from another source was replaced")
        except OSError as e:
            assert message(e) == "local@win is built here from another source than the capture's", message(e)
        assert not events and not exports and dump(pc) == before, events
        assert (data_root / SRC).read_bytes() == b"// win, edited here"
        assert st("windhawk") is False
        print("windhawk refuses a mod built from another source ok")

        # a LibraryFileName whose DLL is gone: the capture's build is used
        local_build()
        (data_root / LOCAL32).unlink()
        assert STEP["windhawk"].apply(True) == 0
        assert pc.get(L, MODS + r"\local@win", "LibraryFileName") == ("SZ", "local@win_2.0_222.dll")
        assert (data_root / DLL).read_bytes() == b"win64"
        assert st("windhawk") is True
        print("windhawk falls back to the captured build ok")
    finally:
        for p in patches:
            p.stop()

# ---- run_installer against this interpreter: waits, and the accepted exit codes ----
with tempfile.TemporaryDirectory(prefix="wintools-selftest-apply-") as scratch:
    marker = Path(scratch) / "done.txt"
    code = ("import sys, time; time.sleep(0.3); "
            f"open({str(marker)!r}, 'w').write('x'); sys.exit(int(sys.argv[1]))")
    assert real_run_installer(sys.executable, ["-c", code, "0"]) == 0
    assert marker.exists(), "run_installer returned before the program finished"
    marker.unlink()
    try:
        real_run_installer(sys.executable, ["-c", code, "3"])
        raise AssertionError("non-zero exit did not raise")
    except OSError as e:
        assert marker.exists()
        assert message(e) == f"{Path(sys.executable).name} exit 3", message(e)
    assert real_run_installer(sys.executable, ["-c", code, "3010"], OPENSHELL_OK) == 3010
    assert real_run_installer(sys.executable, ["-c", code, "5"], None) == 5
    try:
        real_run_installer(sys.executable, ["-c", code, "5"], OPENSHELL_OK)
        raise AssertionError("an exit code outside ok did not raise")
    except OSError as e:
        assert message(e).endswith("exit 5"), message(e)
    try:
        real_run_installer(str(Path(scratch) / "absent.exe"), [])
        raise AssertionError("missing program did not raise")
    except OSError:
        pass
print("run_installer exit codes ok")

# ---- timeouts: 15 minutes for an installer, 60 seconds for PowerShell ----
seen = []


def slow(args, **kwargs):
    seen.append((args, kwargs))
    raise subprocess.TimeoutExpired(args, kwargs["timeout"])


with mock.patch.object(winclassic.subprocess, "run", slow):
    try:
        real_run_installer(Path(r"C:\x\y\setup.exe"), ["/S"])
        raise AssertionError("an installer timeout did not raise")
    except OSError as e:
        assert message(e) == "setup.exe timed out", message(e)
    try:
        real_run_powershell("Get-Date")
        raise AssertionError("a PowerShell timeout did not raise")
    except OSError as e:
        assert message(e) == "powershell timed out", message(e)
assert [kw["timeout"] for _a, kw in seen] == [15 * 60, 60], seen
assert seen[0][0][0] == r"C:\x\y\setup.exe" and seen[0][0][1:] == ["/S"], seen[0]


def failing(args, **kwargs):
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="\nboom one\nboom two\n")


with mock.patch.object(winclassic.subprocess, "run", failing):
    try:
        real_run_powershell("Get-Date")
        raise AssertionError("a PowerShell failure did not raise")
    except OSError as e:
        assert message(e) == "boom one", message(e)
print("timeouts ok")
print("STATUS: SUCCESS")
