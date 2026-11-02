@echo off
rem 1000Jobs ATS Lab: closes the running Lab (the program on port 8501 and the windows that started it).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$port = 8501;" ^
  "$pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object OwningProcess | Select-Object -Unique);" ^
  "if (-not $pids) { Write-Host 'The ATS Lab is not running.'; Start-Sleep -Seconds 2; exit 0 };" ^
  "$kill = New-Object System.Collections.Generic.List[int];" ^
  "foreach ($id in $pids) {" ^
  "  $cur = $id;" ^
  "  while ($cur) {" ^
  "    $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $cur) -ErrorAction SilentlyContinue;" ^
  "    if (-not $p) { break };" ^
  "    $mine = ($p.Name -in 'python.exe','pythonw.exe','py.exe') -or ($p.Name -eq 'cmd.exe' -and $p.CommandLine -match 'streamlit run (app|dashboard).py');" ^
  "    if (-not $mine) { break };" ^
  "    $kill.Add([int]$p.ProcessId); $cur = $p.ParentProcessId" ^
  "  }" ^
  "};" ^
  "foreach ($id in $kill) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue };" ^
  "Start-Sleep -Seconds 1;" ^
  "if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { Write-Host 'The ATS Lab is still running.'; Start-Sleep -Seconds 3; exit 1 };" ^
  "Write-Host 'The ATS Lab is stopped.'; Start-Sleep -Seconds 2"
