' Launch the app with no console window. Double-clickable, or via:
'   npm.cmd run start:hidden
Dim fso, root
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
CreateObject("Wscript.Shell").Run """" & root & "\node_modules\electron\dist\electron.exe"" ""dist/main.js""", 0, False
