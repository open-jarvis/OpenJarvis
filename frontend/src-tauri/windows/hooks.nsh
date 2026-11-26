; Stop the app-owned Ollama before files are replaced or removed. Installed
; ollama.exe and its lib\ollama runners stay locked while running, and app
; versions released before the full runtime was bundled do not stop them
; before launching the updater. Only processes started from $INSTDIR are
; touched, never a separate Ollama installation.
!macro OPENJARVIS_STOP_BUNDLED_OLLAMA
  nsExec::Exec `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$$d = '$INSTDIR\'; Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -ieq ($$d + 'ollama.exe') -or $$_.ExecutablePath -like ($$d + 'lib\ollama\*') } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue; Wait-Process -Id $$_.ProcessId -Timeout 10 -ErrorAction SilentlyContinue }"`
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro OPENJARVIS_STOP_BUNDLED_OLLAMA
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro OPENJARVIS_STOP_BUNDLED_OLLAMA
!macroend
