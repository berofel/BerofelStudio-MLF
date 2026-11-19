Option Explicit
Dim fso, shell, root, pythonw, script, env, oldPath, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\BFS\venv\Scripts\pythonw.exe"
script = root & "\scripts\abrir_com_log.py"
If Not fso.FileExists(root & "\main.py") Or Not fso.FileExists(script) Then
  MsgBox "A pasta atual não contém uma instalação completa do BerofelStudio:" & vbCrLf & root,  vbExclamation, "BerofelStudio"
  WScript.Quit 1
End If
If Not fso.FileExists(pythonw) Then
  MsgBox "Python do BerofelStudio não encontrado. Execute instalar_dependencias.bat primeiro." & vbCrLf & pythonw, vbExclamation, "BerofelStudio"
  WScript.Quit 1
End If
shell.CurrentDirectory = root
Set env = shell.Environment("PROCESS")
oldPath = env("PYTHONPATH")
If Len(oldPath) > 0 Then oldPath = ";" & oldPath
env("PYTHONPATH") = root & oldPath
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & script & Chr(34)
shell.Run command, 0, False
