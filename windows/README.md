# OpenJarvis WinUI 3 (ARM64)

Unpackaged WinUI 3 shell for Windows ARM64. See:

- [Build and install](../docs/getting-started/windows-winui.md)
- [Version pins](../docs/getting-started/windows-winui-versions.md)
- [Acceptance checklist](../docs/getting-started/windows-winui-acceptance.md)
- [Known issues](../docs/getting-started/windows-winui-known-issues.md)

```powershell
$env:NUGET_PACKAGES = "$env:USERPROFILE\.nuget\packages"
.\windows\scripts\publish-arm64.ps1
```

Artifacts land in `dist/` (`OpenJarvis-win-arm64/`, `OpenJarvis-1.0.0-arm64.msi`, `OpenJarvis-1.0.0-arm64.exe`).
