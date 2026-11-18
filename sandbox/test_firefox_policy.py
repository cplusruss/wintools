"""Contract test for the firefoxsetup tweak (Firefox enterprise policy).

Every write goes to HKCU\\Software\\wintools-selftest-firefox, which is deleted
at the end; the live HKLM\\SOFTWARE\\Policies\\Mozilla\\Firefox key is only
inspected by attribute, never read or written.
"""

import json
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tweaks  # noqa: E402
from tweaks import HKCU, HKLM, Tweak  # noqa: E402

ROOT = r"Software\wintools-selftest-firefox"
UBLOCK = "uBlock0@raymondhill.net"
UBLOCK_ENTRY = {
    "installation_mode": "normal_installed",
    "install_url": "https://addons.mozilla.org/firefox/downloads/latest/"
                   "ublock-origin/latest.xpi",
}
NEWTAB = "browser.newtabpage.activity-stream."
PREFS = {NEWTAB + name: {"Value": False, "Status": "default"}
         for name in ("showWeather", "widgets.weather.enabled",
                      "logowordmark.alwaysVisible")}
HOME_OFF = ("TopSites", "SponsoredTopSites", "Highlights", "Pocket", "Stories",
            "SponsoredPocket", "SponsoredStories", "Snippets", "Locked")


def raw(sub, name):
    path = ROOT + ("\\" + sub if sub else "")
    with winreg.OpenKey(HKCU, path, 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        return winreg.QueryValueEx(k, name)


def put(sub, name, kind, value):
    path = ROOT + ("\\" + sub if sub else "")
    with winreg.CreateKeyEx(HKCU, path, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def absent(sub, name):
    try:
        raw(sub, name)
    except FileNotFoundError:
        return True
    return False


def doc(name):
    val, kind = raw("", name)
    assert kind == winreg.REG_MULTI_SZ, (name, kind)
    assert isinstance(val, list) and len(val) == 1, (name, val)
    return json.loads(val[0])


def make():
    return Tweak("firefoxsetup", "Apps", "Apps", "Firefox Clean Setup",
                 tweaks.firefox_ops(ROOT, HKCU))


tweaks._delete_tree(HKCU, ROOT)
try:
    # ---- nothing written yet: off, and reading creates nothing ----
    tw = make()
    assert tw.state() is False, tw.state()
    try:
        winreg.OpenKey(HKCU, ROOT).Close()
        raise AssertionError("state() created the scratch key")
    except FileNotFoundError:
        pass
    print("absent reads off ok")

    # ---- apply writes every value with the right type and data ----
    tw.apply(True)
    assert tw.state() is True, tw.state()
    assert raw("SearchEngines", "Default") == ("DuckDuckGo", winreg.REG_SZ)
    assert raw("FirefoxHome", "Search") == (1, winreg.REG_DWORD)
    for name in HOME_OFF:
        assert raw("FirefoxHome", name) == (0, winreg.REG_DWORD), name
    assert doc("ExtensionSettings") == {UBLOCK: UBLOCK_ENTRY}
    assert doc("Preferences") == PREFS
    print("apply writes every value ok")

    # ---- revert from a clean slate leaves no value behind ----
    tw.apply(False)
    assert tw.state() is False, tw.state()
    for sub, name in [("SearchEngines", "Default"), ("FirefoxHome", "Search"),
                      ("", "ExtensionSettings"), ("", "Preferences"),
                      *[("FirefoxHome", n) for n in HOME_OFF]]:
        assert absent(sub, name), (sub, name)
    print("revert removes every value ok")

    # ---- foreign policy values and JSON entries survive apply and revert ----
    foreign_ext = {
        "*": {"installation_mode": "blocked",
              "blocked_install_message": "no"},
        "other@example.org": {"installation_mode": "force_installed",
                              "install_url": "https://example.org/x.xpi"},
    }
    foreign_pref = {"browser.tabs.warnOnClose": {"Value": False,
                                                 "Status": "locked"}}
    put("", "DisableTelemetry", winreg.REG_DWORD, 1)
    put("SearchEngines", "PreventInstalls", winreg.REG_DWORD, 1)
    put("FirefoxHome", "WidgetsKept", winreg.REG_DWORD, 1)
    put("", "ExtensionSettings", winreg.REG_MULTI_SZ,
        [json.dumps(foreign_ext)])
    put("", "Preferences", winreg.REG_MULTI_SZ, [json.dumps(foreign_pref)])
    tw = make()
    assert tw.state() is False, tw.state()
    tw.apply(True)
    assert tw.state() is True
    assert doc("ExtensionSettings") == {**foreign_ext, UBLOCK: UBLOCK_ENTRY}
    assert doc("Preferences") == {**foreign_pref, **PREFS}
    assert raw("", "DisableTelemetry") == (1, winreg.REG_DWORD)
    assert raw("SearchEngines", "PreventInstalls") == (1, winreg.REG_DWORD)
    tw.apply(False)
    assert tw.state() is False
    assert doc("ExtensionSettings") == foreign_ext
    assert doc("Preferences") == foreign_pref
    assert raw("", "DisableTelemetry") == (1, winreg.REG_DWORD)
    assert raw("SearchEngines", "PreventInstalls") == (1, winreg.REG_DWORD)
    assert raw("FirefoxHome", "WidgetsKept") == (1, winreg.REG_DWORD)
    assert absent("SearchEngines", "Default") and absent("FirefoxHome", "Search")
    print("foreign entries survive apply and revert ok")

    # ---- state is on only while every piece is ours ----
    tw.apply(True)
    assert tw.state() is True
    put("SearchEngines", "Default", winreg.REG_SZ, "Google")
    assert tw.state() is False, "engine changed"
    tw.apply(True)
    assert tw.state() is True
    put("FirefoxHome", "Pocket", winreg.REG_DWORD, 1)
    assert tw.state() is False, "a home section back on"
    tw.apply(True)
    ext = doc("ExtensionSettings")
    ext[UBLOCK]["installation_mode"] = "blocked"
    put("", "ExtensionSettings", winreg.REG_MULTI_SZ, [json.dumps(ext)])
    assert tw.state() is False, "uBlock entry altered"
    tw.apply(True)
    prefs = doc("Preferences")
    del prefs[NEWTAB + "showWeather"]
    put("", "Preferences", winreg.REG_MULTI_SZ, [json.dumps(prefs)])
    assert tw.state() is False, "a pref missing"
    tw.apply(True)
    assert tw.state() is True
    print("state reads true/false ok")

    # ---- a REG_SZ or multi-line value is read as the JSON it holds ----
    put("", "ExtensionSettings", winreg.REG_SZ,
        json.dumps({UBLOCK: UBLOCK_ENTRY}))
    assert tw.state() is True
    put("", "ExtensionSettings", winreg.REG_MULTI_SZ,
        json.dumps({UBLOCK: UBLOCK_ENTRY}, indent=2).split("\n"))
    assert tw.state() is True
    tw.apply(True)
    print("alternate encodings read ok")

    # ---- an unreadable JSON value is never overwritten ----
    put("", "ExtensionSettings", winreg.REG_MULTI_SZ, ["{not json"])
    assert tw.state() is None, tw.state()
    for on in (True, False):
        try:
            tw.apply(on)
            raise AssertionError(f"apply({on}) clobbered unreadable JSON")
        except OSError as e:
            assert "ExtensionSettings" in str(e), e
    assert raw("", "ExtensionSettings")[0] == ["{not json"]
    put("", "ExtensionSettings", winreg.REG_MULTI_SZ, ["[1, 2]"])
    assert tw.state() is None, tw.state()
    print("invalid JSON left alone ok")
finally:
    tweaks._delete_tree(HKCU, ROOT)

try:
    winreg.OpenKey(HKCU, ROOT).Close()
    raise AssertionError("scratch key not cleaned up")
except FileNotFoundError:
    pass
print("cleanup ok")

# ---- the live tweak: catalog slot and target key (attributes only) ----
live = next(t for t in tweaks.TWEAKS if t.key == "firefoxsetup")
assert (live.tab, live.section, live.label) == (
    "Apps", "Apps", "Firefox Clean Setup"), (live.tab, live.section, live.label)
keys = [t.key for t in tweaks.TWEAKS]
assert keys.index("firefoxsetup") == keys.index("firefoxtelemetry") + 1
assert tweaks.FIREFOX_POL == r"SOFTWARE\Policies\Mozilla\Firefox"
for op in live.ops:
    assert op.hive == HKLM, op.path
    assert op.path == tweaks.FIREFOX_POL or op.path.startswith(
        tweaks.FIREFOX_POL + "\\"), op.path
    assert op.off_key is None and op.path
    assert getattr(op, "name", None) != "DisableTelemetry"
    for attr in ("available", "read", "is_on", "write"):
        assert callable(getattr(op, attr)), (op.path, attr)
assert sum(isinstance(op, tweaks.JsonMergeOp) for op in live.ops) == 2
assert [op.name for op in live.ops if isinstance(op, tweaks.JsonMergeOp)] == [
    "ExtensionSettings", "Preferences"]
tel = next(t for t in tweaks.TWEAKS if t.key == "firefoxtelemetry")
assert [(o.path, o.name, o.on) for o in tel.ops] == [
    (tweaks.FIREFOX_POL, "DisableTelemetry", 1)]
print("live tweak targets HKLM Firefox policy ok")

print("STATUS: SUCCESS")
