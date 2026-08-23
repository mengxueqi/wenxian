Option Explicit

Dim fileSystem, shell, projectRoot, updateScript, command, exitCode

Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
updateScript = fileSystem.BuildPath(projectRoot, "run_literature_tracker_update.ps1")

If Not fileSystem.FileExists(updateScript) Then
    WScript.Quit 2
End If

command = "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden " & _
    "-ExecutionPolicy Bypass -File """ & updateScript & """"
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
