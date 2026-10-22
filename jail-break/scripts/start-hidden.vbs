' Launch the app with no console window. Double-clickable, or via:
'   npm.cmd run start:hidden
' Kept for backwards compatibility - see "Start Assistant.vbs" in the
' project root, which also installs dependencies and rebuilds when needed.
Dim fso, root, shell
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set shell = CreateObject("Wscript.Shell")
shell.Run """" & root & "\Start Assistant.vbs""", 0, False
