; DSM eScript P-01 Pure MSI
ExecuteEx('msiexec.exe /i "%Src%\app.msi" TRANSFORMS="%Src%\setup.mst" /qn', 'ErrorLevel', '0')
If %ErrorLevel% != '0'
  ExitProcEx(Failed, 'MSI Installation failed')
EndIf
