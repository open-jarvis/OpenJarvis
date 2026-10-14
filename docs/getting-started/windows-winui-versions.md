---
title: WinUI ARM64 version pins
description: Windows, SDK, Foundry Local, Python, and driver versions for the WinUI 3 OpenJarvis build
---

# WinUI ARM64 version pins

Record the versions this tree was written against. Bump this page when CI or the Surface checklist changes a pin.

| Component | Version | Notes |
|-----------|---------|-------|
| Windows | Windows 11 24H2, build **26100** or later | [Foundry Local get started](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started) |
| Surface Laptop Ultra OS | Windows 11 **26H1** | N1X devices do not install 26H2; they wait for a later branch |
| Architecture | ARM64 only | x64 installers are refused |
| .NET SDK | **9.0** | Target `net9.0-windows10.0.26100.0` |
| Windows App SDK | **1.7.250606001** | Self-contained with the app |
| Windows SDK build tools | **10.0.26100.1742** | From the WinUI project |
| Visual Studio | 2022, WinUI workload | Required to compile XAML |
| WiX | **5.0.2** | MSI + Burn bundle |
| CPython | **3.12.x win-arm64** | Embeddable zip; 3.14 has no numpy Windows wheels |
| Rust | stable `aarch64-pc-windows-msvc` | `uv sync --group desktop-native` builds `openjarvis_rust` |
| Foundry Local | **0.11.0** `foundry-0.11.0-win-arm64.msix` (Setup also tries `*-winml.msix`) | Installed by Setup via `Add-AppxPackage`; release tag `cli-preview-0.11.0` |
| Windows ML | Foundry Local 0.11.x / WinML 2.0 | Execution providers downloaded on first run |
| NVIDIA GPU driver | Use the Surface / NVIDIA ARM64 driver for RTX Spark N1X | Floor is whatever Windows Update ships for this SKU; record the exact version on the device in the acceptance doc |
| CUDA (if TensorRT RTX / CUDA EP) | **12.5** recommended by Foundry Local NVIDIA EPs | Confirm on-device; N1X may use a vendor stack instead of desktop CUDA |
| Default model alias | **Phi-4-mini-instruct** | Foundry catalog alias; runtime picks CUDA / TensorRT RTX / WebGPU / CPU |

## Execution providers (Foundry Local + Windows ML)

| Provider | Hardware | Expected on Surface Laptop Ultra |
|----------|----------|----------------------------------|
| `NvTensorRTRTXExecutionProvider` | NVIDIA RTX 30-series and later | Preferred if the ARM64 plugin registers |
| `CUDAExecutionProvider` | NVIDIA GPU | Alternate GPU path |
| `WebGPUExecutionProvider` | GPU fallback | Used if NVIDIA plugins are missing |
| `CPUExecutionProvider` | Any CPU | Documented fallback; the UI labels it “CPU fallback” |
| `QNNExecutionProvider` | Qualcomm NPU | Not this device (NVIDIA SoC, not Snapdragon) |

## Preview / Insider

Foundry Local with Windows ML is generally available. Surface Laptop Ultra’s 26H1 image is a device-specific Windows branch, not a Windows Insider channel. No extra Insider flight is required beyond that OEM image.

## Speech extra

`openjarvis[desktop]` pulls `faster-whisper` / `ctranslate2`, which do not have reliable Windows ARM64 wheels. The WinUI installer uses `--extra server --group desktop-native` only. Speech is omitted from this UI.
