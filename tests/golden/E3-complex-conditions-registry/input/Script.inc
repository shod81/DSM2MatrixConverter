; DSM eScript E3 Complex Conditions Registry
Set(APPVERSION, '2.4.0')
Set(APPSERVER, '\\fileserver01\inst')
If DoesFileExist('%WINDIR%\appmarker.cfg') = '1'
  ExecuteEx('msiexec.exe /i "%SRC%\report.msi" REINSTALL=ALL REINSTALLMODE=vomus /qn', 'rc3', '30')
Else
  ExecuteEx('msiexec.exe /i "%SRC%\report.msi" /qn ALLUSERS=2', 'rc1', '30')
  RegLoad('%Src%\config\schema.nir')
  Copy('%Src%\config\app.ini', '%WINDIR%\app.ini')
  If RegKeyExists('HKLM\Software\ExampleApp\Report') = '1'
    ExecuteEx('"%SRC%\tools\DbCheck.exe" /srv:%APPSERVER%', 'rc2', '10')
  EndIf
EndIf
CreateLink('%Desktop%\Example Berichte', '%ProgramFiles%\Example Report\report.exe', '--config "%WINDIR%\app.ini"')
$BeginUnInstallScript
ExecuteEx('msiexec.exe /x {B3F0D9A2-77C1-4E88-9A6B-A1B2C3D40024} /qn', 'rcu', '30')
Delete('%WINDIR%\app.ini')
