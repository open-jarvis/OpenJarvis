//! Hardware detection and engine recommendation.
//!
//! Rust translation of the hardware detection in `src/openjarvis/core/config.py`.

use serde::{Deserialize, Serialize};
use std::process::Command;

// ---------------------------------------------------------------------------
// Hardware data types
// ---------------------------------------------------------------------------

/// Detected GPU metadata.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GpuInfo {
    #[serde(default)]
    pub vendor: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub vram_gb: f64,
    #[serde(default)]
    pub compute_capability: String,
    #[serde(default)]
    pub count: i64,
}

/// Detected system hardware.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct HardwareInfo {
    #[serde(default)]
    pub platform: String,
    #[serde(default)]
    pub cpu_brand: String,
    #[serde(default)]
    pub cpu_count: i64,
    #[serde(default)]
    pub ram_gb: f64,
    #[serde(default)]
    pub gpu: Option<GpuInfo>,
}

// ---------------------------------------------------------------------------
// Detection helpers
// ---------------------------------------------------------------------------

fn run_cmd(args: &[&str]) -> String {
    Command::new(args[0])
        .args(&args[1..])
        .output()
        .ok()
        .and_then(|out| {
            if out.status.success() {
                String::from_utf8(out.stdout).ok().map(|s| s.trim().to_string())
            } else {
                None
            }
        })
        .unwrap_or_default()
}

fn which(cmd: &str) -> bool {
    Command::new("which")
        .arg(cmd)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn detect_nvidia_gpu() -> Option<GpuInfo> {
    if !which("nvidia-smi") {
        return None;
    }
    let raw = run_cmd(&[
        "nvidia-smi",
        "--query-gpu=name,memory.total,count",
        "--format=csv,noheader,nounits",
    ]);
    if raw.is_empty() {
        return None;
    }
    let first_line = raw.lines().next()?;
    let parts: Vec<&str> = first_line.split(',').map(|s| s.trim()).collect();
    if parts.len() < 3 {
        return None;
    }
    let name = parts[0].to_string();
    let vram_mb: f64 = parts[1].parse().ok()?;
    let count: i64 = parts[2].parse().ok()?;
    Some(GpuInfo {
        vendor: "nvidia".into(),
        name,
        vram_gb: (vram_mb / 1024.0 * 10.0).round() / 10.0,
        count,
        compute_capability: String::new(),
    })
}

fn detect_amd_gpu() -> Option<GpuInfo> {
    if !which("rocm-smi") {
        return None;
    }
    let raw = run_cmd(&["rocm-smi", "--showproductname"]);
    if raw.is_empty() {
        return None;
    }
    let name = raw.lines().next().unwrap_or("AMD GPU").to_string();

    // Parse VRAM
    let mut vram_gb = 0.0;
    let vram_raw = run_cmd(&["rocm-smi", "--showmeminfo", "vram"]);
    for line in vram_raw.lines() {
        if line.contains("Total Memory (B):") {
            if let Some(val) = line.split(':').next_back() {
                if let Ok(bytes) = val.trim().parse::<f64>() {
                    vram_gb = (bytes / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0;
                }
            }
        }
    }

    // Parse GPU count
    let mut count = 1i64;
    let allinfo = run_cmd(&["rocm-smi", "--showallinfo"]);
    let re = regex::Regex::new(r"GPU\[(\d+)\]").unwrap();
    let gpu_ids: std::collections::HashSet<_> = re
        .captures_iter(&allinfo)
        .filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string()))
        .collect();
    if !gpu_ids.is_empty() {
        count = gpu_ids.len() as i64;
    }

    Some(GpuInfo {
        vendor: "amd".into(),
        name,
        vram_gb,
        count,
        compute_capability: String::new(),
    })
}

fn detect_apple_gpu() -> Option<GpuInfo> {
    if std::env::consts::OS != "macos" {
        return None;
    }
    let raw = run_cmd(&["system_profiler", "SPDisplaysDataType"]);
    if !raw.contains("Apple") {
        return None;
    }
    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.contains("Chipset Model") {
            let name = trimmed.split(':').next_back().unwrap_or("Apple Silicon").trim();
            let ram_gb = run_cmd(&["sysctl", "-n", "hw.memsize"])
                .trim()
                .parse::<u64>()
                .map(|b| b as f64 / (1024.0 * 1024.0 * 1024.0))
                .unwrap_or(0.0);
            return Some(GpuInfo {
                vendor: "apple".into(),
                name: name.to_string(),
                vram_gb: ram_gb,
                count: 1,
                compute_capability: String::new(),
            });
        }
    }
    let ram_gb = run_cmd(&["sysctl", "-n", "hw.memsize"])
        .trim()
        .parse::<u64>()
        .map(|b| b as f64 / (1024.0 * 1024.0 * 1024.0))
        .unwrap_or(0.0);
    Some(GpuInfo {
        vendor: "apple".into(),
        name: "Apple Silicon".into(),
        vram_gb: ram_gb,
        count: 1,
        compute_capability: String::new(),
    })
}

fn detect_cpu_brand() -> String {
    if std::env::consts::OS == "macos" {
        let brand = run_cmd(&["sysctl", "-n", "machdep.cpu.brand_string"]);
        if !brand.is_empty() {
            return brand;
        }
    }
    let cpuinfo = std::path::Path::new("/proc/cpuinfo");
    if cpuinfo.exists() {
        if let Ok(content) = std::fs::read_to_string(cpuinfo) {
            for line in content.lines() {
                if line.starts_with("model name") {
                    if let Some(val) = line.split(':').nth(1) {
                        return val.trim().to_string();
                    }
                }
            }
        }
    }
    "unknown".into()
}

fn total_ram_gb() -> f64 {
    if std::env::consts::OS == "macos" {
        let raw = run_cmd(&["sysctl", "-n", "hw.memsize"]);
        if let Ok(bytes) = raw.parse::<f64>() {
            return (bytes / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0;
        }
    }
    let meminfo = std::path::Path::new("/proc/meminfo");
    if meminfo.exists() {
        if let Ok(content) = std::fs::read_to_string(meminfo) {
            for line in content.lines() {
                if line.starts_with("MemTotal") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        if let Ok(kb) = parts[1].parse::<f64>() {
                            return (kb / (1024.0 * 1024.0) * 10.0).round() / 10.0;
                        }
                    }
                }
            }
        }
    }
    0.0
}

/// Auto-detect hardware capabilities with graceful fallbacks.
pub fn detect_hardware() -> HardwareInfo {
    let gpu = detect_nvidia_gpu()
        .or_else(detect_amd_gpu)
        .or_else(detect_apple_gpu);

    let cpu_count = std::thread::available_parallelism()
        .map(|n| n.get() as i64)
        .unwrap_or(1);

    HardwareInfo {
        platform: std::env::consts::OS.to_string(),
        cpu_brand: detect_cpu_brand(),
        cpu_count,
        ram_gb: total_ram_gb(),
        gpu,
    }
}

/// Suggest the best inference engine for the detected hardware.
pub fn recommend_engine(hw: &HardwareInfo) -> String {
    let gpu = match &hw.gpu {
        Some(g) => g,
        None => return "llamacpp".into(),
    };

    match gpu.vendor.as_str() {
        "apple" => "mlx".into(),
        "nvidia" => {
            let datacenter = ["A100", "H100", "H200", "L40", "A10", "A30"];
            if datacenter.iter().any(|kw| gpu.name.contains(kw)) {
                "vllm".into()
            } else {
                "ollama".into()
            }
        }
        "amd" => "vllm".into(),
        _ => "llamacpp".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_recommend_engine_no_gpu() {
        let hw = HardwareInfo::default();
        assert_eq!(recommend_engine(&hw), "llamacpp");
    }

    #[test]
    fn test_recommend_engine_apple() {
        let hw = HardwareInfo {
            gpu: Some(GpuInfo {
                vendor: "apple".into(),
                name: "Apple M2 Max".into(),
                ..GpuInfo::default()
            }),
            ..HardwareInfo::default()
        };
        assert_eq!(recommend_engine(&hw), "mlx");
    }

    #[test]
    fn test_recommend_engine_nvidia_consumer() {
        let hw = HardwareInfo {
            gpu: Some(GpuInfo {
                vendor: "nvidia".into(),
                name: "NVIDIA GeForce RTX 4090".into(),
                vram_gb: 24.0,
                count: 1,
                ..GpuInfo::default()
            }),
            ..HardwareInfo::default()
        };
        assert_eq!(recommend_engine(&hw), "ollama");
    }

    #[test]
    fn test_recommend_engine_nvidia_datacenter() {
        let hw = HardwareInfo {
            gpu: Some(GpuInfo {
                vendor: "nvidia".into(),
                name: "NVIDIA A100-SXM4-80GB".into(),
                vram_gb: 80.0,
                count: 4,
                ..GpuInfo::default()
            }),
            ..HardwareInfo::default()
        };
        assert_eq!(recommend_engine(&hw), "vllm");
    }

    #[test]
    fn test_recommend_engine_amd() {
        let hw = HardwareInfo {
            gpu: Some(GpuInfo {
                vendor: "amd".into(),
                name: "AMD Instinct MI250".into(),
                vram_gb: 64.0,
                count: 1,
                ..GpuInfo::default()
            }),
            ..HardwareInfo::default()
        };
        assert_eq!(recommend_engine(&hw), "vllm");
    }

    #[test]
    fn test_detect_hardware_runs() {
        // Just verify it doesn't panic
        let hw = detect_hardware();
        assert!(!hw.platform.is_empty());
        assert!(hw.cpu_count >= 1);
    }
}
