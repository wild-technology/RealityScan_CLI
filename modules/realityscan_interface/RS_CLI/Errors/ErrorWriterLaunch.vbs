' Hidden launcher for ErrorWriter.bat (2026-07-23; quoting FIXED
' 2026-07-24 after review finding: the original composition produced a
' malformed command line and ErrorWriter never ran - the errors-marker
' system was inert for every run between the shim's introduction and
' this fix; see FINDINGS.md).
'
' RealityScan's appProcessExecCmd hook fires for EVERY completed process
' (including internal heartbeats). Invoking "cmd /c ErrorWriter.bat"
' directly pops a visible console window each time - hundreds of
' flashing terminal windows over a long run (owner report). wscript is a
' GUI-subsystem host, so this shim runs without any console and shells
' the real ErrorWriter.bat hidden and synchronously (True) to preserve
' marker-file write ordering.
'
' Args are passed UNQUOTED: they are process result codes, ids,
' durations, and the instance name - never spaces. ErrorWriter.bat uses
' %~N regardless, so either style works.
' Quote composition via Chr(34) - literal escaped quotes in VBS string
' constants caused the original malformed command line. Final shape:
'   cmd /c ""<bat>" <args>"
' (outer pair wraps everything after /c; the bat path keeps its own
' quotes for spaces - the standard cmd /c double-quoting idiom).
Dim shell, bat, args, i, q
q = Chr(34)
Set shell = CreateObject("WScript.Shell")
bat = Replace(WScript.ScriptFullName, "ErrorWriterLaunch.vbs", "ErrorWriter.bat")
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next
shell.Run "cmd /c " & q & q & bat & q & args & q, 0, True
