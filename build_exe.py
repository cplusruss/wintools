import subprocess
import sys
import zipfile
from pathlib import Path

PYTHON = r"C:\Python\313\python.exe"
ROOT = Path(__file__).resolve().parent
WORK = ROOT / "temp" / "pyi-build"
DIST = ROOT / "dist"
EXE = DIST / "wintools.exe"
KIT = ROOT / "resource" / "winclassic"
KIT_ZIP = DIST / "wintools-winclassic-kit.zip"


def add_data():
    # --add-data needs absolute sources: the generated spec lives in WORK.
    data = [f"{ROOT / 'wintools.ico'};."]
    data += [
        f"{ico};resource/icons"
        for ico in sorted((ROOT / "resource" / "icons").glob("*.ico"))
    ]
    return data


def build_exe():
    cmd = [
        PYTHON,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--name",
        "wintools",
        "--icon",
        str(ROOT / "wintools.ico"),
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
    ]
    # Pulled in only by win32com.client.makepy; saves 3.4 MB.
    for mod in ("pywin", "win32ui"):
        cmd += ["--exclude-module", mod]
    for item in add_data():
        cmd += ["--add-data", item]
    cmd.append(str(ROOT / "wintools.py"))
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"{EXE}  {EXE.stat().st_size / 1e6:.1f} MB")


def build_kit_zip():
    # Installers are already compressed; deflating them only costs time.
    with zipfile.ZipFile(KIT_ZIP, "w", zipfile.ZIP_STORED) as z:
        for path in sorted(KIT.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(ROOT))
    print(f"{KIT_ZIP}  {KIT_ZIP.stat().st_size / 1e6:.1f} MB")


def link_resource():
    # The frozen exe reads resource\ beside itself; this keeps dist\wintools.exe
    # working here without a second copy of the kit.
    link = DIST / "resource"
    if not link.exists():
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(ROOT / "resource")],
            check=True,
            capture_output=True,
        )


def main():
    build_exe()
    build_kit_zip()
    link_resource()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
