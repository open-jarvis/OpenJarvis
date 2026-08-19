; NSIS installer hooks for OpenJarvis desktop build.
; Called by tauri-bundler via bundle.windows.nsis.installerHooks.
;
; NSIS_HOOK_POSTINSTALL runs after files are copied, registry keys are set,
; and the default Start Menu shortcut is created. We use it to ALSO drop a
; desktop shortcut automatically (the default Tauri finish-page checkbox is
; opt-in; we want it on by default).
;
; CreateOrUpdateDesktopShortcut is defined in Tauri's generated installer.nsi
; (creates $DESKTOP\${PRODUCTNAME}.lnk -> $INSTDIR\${MAINBINARYNAME}.exe) and is
; already in scope, so we just invoke it.

!macro NSIS_HOOK_POSTINSTALL
  Call CreateOrUpdateDesktopShortcut
!macroend
