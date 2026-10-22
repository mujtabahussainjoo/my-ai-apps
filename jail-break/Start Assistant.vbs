' One-click setup + launcher for Windows - NO console window.
' Double-click this file (or the "Visible AI Assistant" shortcut it creates).
'
'   - finds Node.js, or downloads a portable copy (no admin, no installer)
'   - installs npm dependencies, including Electron
'   - builds the app
'   - creates Desktop / Start Menu icons
'   - starts the app
'
' Pass --install to set everything up without starting the app.

Dim fso, root, shell, args, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

args = ""
Dim i
For i = 0 To WScript.Arguments.Count - 1
  args = args & " """ & WScript.Arguments(i) & """"
Next

Set shell = CreateObject("Wscript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & _
      root & "\scripts\bootstrap.ps1""" & args
shell.Run cmd, 0, False
