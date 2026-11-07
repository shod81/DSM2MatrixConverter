; DSM eScript E1 Simple MSI
ExecuteEx('msiexec.exe /i "%SRC%\Example Viewer.msi" /qn REBOOT=REALLYSUPPRESS', 'rc', '30')
If %rc% = '3010'
  Set(RebootNeeded, '1')
Else
  If %rc% != '0'
    ExitProcEx(Failed, 'MSI Installation failed')
  EndIf
EndIf
Copy('%Src%\Lizenz.txt', '%App%\Lizenz.txt')
$BeginUnInstallScript
ExecuteEx('msiexec.exe /x {D6B1AC8F-2F5C-4B7A-9C3E-0A1B00000120} /qn', 'rcu', '30')
