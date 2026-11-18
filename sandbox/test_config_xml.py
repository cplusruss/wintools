#!/usr/bin/env python3
"""Contract test: tweaks XML config round-trips without touching the registry."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tweaks


def test_roundtrip():
    items = [("perf", True), ("menudelay", False), ("smb1", True)]
    xml = tweaks.config_to_xml(items)
    assert xml.startswith(b"<?xml"), xml[:20]
    assert b"<wintools" in xml
    assert tweaks.xml_to_config(xml) == items


def test_order_and_flags_preserved():
    items = [("a", False), ("b", True), ("c", False)]
    assert tweaks.xml_to_config(tweaks.config_to_xml(items)) == items


def test_real_key_exists():
    assert any(t.key == "legacyprintdlg" for t in tweaks.TWEAKS)


def test_folded_debloat_tweaks_present():
    keys = {t.key for t in tweaks.TWEAKS}
    assert "openthispc" in keys


def test_copilot_appx_action():
    assert callable(tweaks.remove_copilot_appx)
    assert len(tweaks.COPILOT_APPX) == 3


if __name__ == "__main__":
    test_roundtrip()
    test_order_and_flags_preserved()
    test_real_key_exists()
    test_folded_debloat_tweaks_present()
    test_copilot_appx_action()
    print("STATUS: SUCCESS")
