' Launches wintools.py through pythonw with no console window at any point.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run _
    """C:\Python\313\pythonw.exe"" """ & here & "\wintools.py""", 0, False
