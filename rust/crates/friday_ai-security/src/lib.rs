//! Security guardrails — scanners, RBAC, taint tracking, audit, SSRF protection.

pub mod audit;
pub mod capabilities;
pub mod file_policy;
pub mod guardrails;
pub mod injection;
pub mod rate_limiter;
pub mod scanner;
pub mod ssrf;
pub mod taint;
pub mod types;

pub use audit::AuditLogger;
pub use capabilities::{Capability, CapabilityPolicy};
pub use file_policy::is_sensitive_file;
pub use guardrails::GuardrailsEngine;
pub use injection::InjectionScanner;
pub use rate_limiter::{RateLimitConfig, RateLimiter};
pub use scanner::{PIIScanner, SecretScanner};
pub use ssrf::check_ssrf;
pub use taint::{TaintLabel, TaintSet, check_taint};
pub use types::{RedactionMode, ScanFinding, ScanResult, ThreatLevel};
