; DSM eScript P-02 EXE with parameters
Set(TargetDir, '%ProgramFiles%\Vendor Suite\App')
ExecuteEx('"%Src%\setup.exe" /DIR="%TargetDir%" /VERYSILENT', 'ExitCode', '0')
