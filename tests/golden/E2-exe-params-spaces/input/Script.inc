; DSM eScript E2 EXE Params Spaces
Set(TARGETDIR, 'C:\Program Files\Example Tools')
ExecuteEx('"%SRC%\Example Setup\setup.exe" /S /TARGETDIR="%TARGETDIR%" /COMPONENTS=core,reports', 'rc', '60')
If %rc% != '0'
  ExitProcEx(Failed, 'ExampleTools Fehler')
EndIf
Copy('%Src%\readme_de.txt', '%TARGETDIR%\doc\readme_de.txt')
CreateLink('%CommonPrograms%\Example Tools', '%TARGETDIR%\ExampleTool.exe', '')
