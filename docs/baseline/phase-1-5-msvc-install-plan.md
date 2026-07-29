# Phase 1.5: MSVC Build Tools installation plan

Date: 2026-07-29

This plan was recorded before starting the Visual Studio Build Tools
installer. Its scope is limited to making the approved OpenJarvis baseline
buildable on native Windows.

## Pre-installation state

- Host: 64-bit Windows, version `10.0.26200.0`
- Process architecture: `x64`
- Current user elevated: no
- Free space on `C:`: `43.2 GiB`
- Existing Visual Studio Installer: not found
- Existing Visual Studio / Build Tools products reported by `vswhere`: none
  (`vswhere.exe` itself was not present)
- Registered Visual Studio Build Tools products: none
- `cl.exe` on the current process `PATH`: not found
- `link.exe` on the current process `PATH`: not found

These checks found no complete or partial Visual Studio Build Tools
installation to repair, resume, or remove.

## Microsoft product and channel

- Product: Microsoft Visual Studio Build Tools 2022
- Channel: Visual Studio 2022 Current channel
- Official bootstrapper URL:
  `https://aka.ms/vs/17/release/vs_BuildTools.exe`
- Bootstrapper product version: Visual Studio 2022
- Bootstrapper file version: `17.14.37516.0`
- Bootstrapper size: `4,458,504` bytes
- Bootstrapper SHA-256:
  `CE7BB977ACCAE1748191233D05EE6832A4B61A319419627BFCDBD818DE5BFD68`
- Authenticode status: valid
- Signer: Microsoft Corporation
- Planned installation path:
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`

Microsoft's current Visual Studio Build Tools workload catalog identifies
`Microsoft.VisualStudio.Workload.VCTools` as **Desktop development with C++**.
The current x64/x86 compiler component is
`Microsoft.VisualStudio.Component.VC.Tools.x86.x64` (MSVC v143). The selected
Windows SDK component is
`Microsoft.VisualStudio.Component.Windows11SDK.26100`.

## Exact selected components

The installer will receive only these explicit `--add` selections:

1. `Microsoft.VisualStudio.Workload.VCTools`
2. `Microsoft.VisualStudio.Component.VC.Tools.x86.x64`
3. `Microsoft.VisualStudio.Component.Windows11SDK.26100`

The workload's required dependencies will be installed automatically. The
command intentionally omits `--includeRecommended` and `--includeOptional`.
Therefore CMake, vcpkg, test tools, AddressSanitizer, ATL, MFC, ARM/ARM64
toolchains, gaming, mobile, Azure, .NET workloads, and the Visual Studio IDE
are not requested.

## Disk-space expectation

Microsoft documents a broad `2.3 GB` to `60 GB` range for Visual Studio Build
Tools 2022 depending on selected features. For this narrowly selected native
x64/x86 workload, the operational preflight reserves a conservative `10 GiB`
budget. The host has `43.2 GiB` free before installation. Actual disk
consumption will be measured from the `C:` drive before and after installation
and reported separately.

## Planned installer invocation

The signed bootstrapper will be launched with administrative elevation using:

```text
vs_BuildTools.exe
  --passive
  --wait
  --norestart
  --nocache
  --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
  --add Microsoft.VisualStudio.Workload.VCTools
  --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64
  --add Microsoft.VisualStudio.Component.Windows11SDK.26100
```

No credentials are supplied or requested by this workflow. Windows may show a
User Account Control consent dialog because the installation requires
administrator rights.

## Sources

- Visual Studio Build Tools component directory:
  <https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022>
- Visual Studio installer command-line parameters:
  <https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022>
- Visual Studio 2022 system requirements:
  <https://learn.microsoft.com/en-us/visualstudio/releases/2022/system-requirements>
