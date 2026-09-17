Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
bat = WScript.Arguments.Item(0)
' intWindowStyle=0 -> 完全隐藏；True -> 等待 bat 跑完
ws.Run """" & bat & """ silent", 0, True
On Error Resume Next
fso.DeleteFile WScript.ScriptFullName
