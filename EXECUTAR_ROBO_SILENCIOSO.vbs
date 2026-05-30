Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Edson\eadriaticleague2"
WshShell.Run "C:\Users\Edson\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe C:\Users\Edson\eadriaticleague2\main.py", 0, False
Set WshShell = Nothing
