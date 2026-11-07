//! RBAC capability system — fine-grained permission model for tool dispatch.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Capability {
    #[serde(rename = "file:read")]
    FileRead,
    #[serde(rename = "file:write")]
    FileWrite,
    #[serde(rename = "network:fetch")]
    NetworkFetch,
    #[serde(rename = "code:execute")]
    CodeExecute,
    #[serde(rename = "memory:read")]
    MemoryRead,
    #[serde(rename = "memory:write")]
    MemoryWrite,
    #[serde(rename = "channel:send")]
    ChannelSend,
    #[serde(rename = "tool:invoke")]
    ToolInvoke,
    #[serde(rename = "schedule:create")]
    ScheduleCreate,
    #[serde(rename = "system:admin")]
    SystemAdmin,
}

impl Capability {
    pub fn as_str(&self) -> &'static str {
        match self {
            Capability::FileRead => "file:read",
            Capability::FileWrite => "file:write",
            Capability::NetworkFetch => "network:fetch",
            Capability::CodeExecute => "code:execute",
            Capability::MemoryRead => "memory:read",
            Capability::MemoryWrite => "memory:write",
            Capability::ChannelSend => "channel:send",
            Capability::ToolInvoke => "tool:invoke",
            Capability::ScheduleCreate => "schedule:create",
            Capability::SystemAdmin => "system:admin",
        }
    }
}

#[derive(Debug, Clone)]
pub struct CapabilityGrant {
    pub capability: String,
    pub pattern: String,
}

#[derive(Debug, Clone)]
struct AgentPolicy {
    grants: Vec<CapabilityGrant>,
    deny: Vec<String>,
}

/// RBAC capability policy for tool dispatch.
///
/// Default policy: if no explicit policy exists for an agent, all
/// capabilities are granted. Set `default_deny` to flip.
pub struct CapabilityPolicy {
    policies: HashMap<String, AgentPolicy>,
    default_deny: bool,
}

impl CapabilityPolicy {
    pub fn new(default_deny: bool) -> Self {
        Self {
            policies: HashMap::new(),
            default_deny,
        }
    }

    pub fn grant(&mut self, agent_id: &str, capability: &str, pattern: &str) {
        let policy = self.policies.entry(agent_id.to_string()).or_insert_with(|| {
            AgentPolicy {
                grants: Vec::new(),
                deny: Vec::new(),
            }
        });
        policy.grants.push(CapabilityGrant {
            capability: capability.to_string(),
            pattern: pattern.to_string(),
        });
    }

    pub fn deny(&mut self, agent_id: &str, capability: &str) {
        let policy = self.policies.entry(agent_id.to_string()).or_insert_with(|| {
            AgentPolicy {
                grants: Vec::new(),
                deny: Vec::new(),
            }
        });
        policy.deny.push(capability.to_string());
    }

    pub fn check(&self, agent_id: &str, capability: &str, resource: &str) -> bool {
        let policy = match self.policies.get(agent_id) {
            Some(p) => p,
            None => return !self.default_deny,
        };

        for denied in &policy.deny {
            if glob_match(denied, capability) {
                return false;
            }
        }

        for grant in &policy.grants {
            if glob_match(&grant.capability, capability) {
                if !resource.is_empty() && grant.pattern != "*" {
                    if glob_match(&grant.pattern, resource) {
                        return true;
                    }
                } else {
                    return true;
                }
            }
        }

        !self.default_deny
    }

    pub fn list_agents(&self) -> Vec<String> {
        self.policies.keys().cloned().collect()
    }

    pub fn load_json(&mut self, json_str: &str) -> Result<(), serde_json::Error> {
        let data: serde_json::Value = serde_json::from_str(json_str)?;
        if let Some(agents) = data["agents"].as_array() {
            for agent_data in agents {
                let agent_id = agent_data["agent_id"].as_str().unwrap_or("");
                if agent_id.is_empty() {
                    continue;
                }
                if let Some(grants) = agent_data["grants"].as_array() {
                    for g in grants {
                        let cap = g["capability"].as_str().unwrap_or("");
                        let pat = g["pattern"].as_str().unwrap_or("*");
                        self.grant(agent_id, cap, pat);
                    }
                }
                if let Some(deny_list) = agent_data["deny"].as_array() {
                    for d in deny_list {
                        if let Some(cap) = d.as_str() {
                            self.deny(agent_id, cap);
                        }
                    }
                }
            }
        }
        Ok(())
    }
}

impl Default for CapabilityPolicy {
    fn default() -> Self {
        Self::new(false)
    }
}

fn glob_match(pattern: &str, text: &str) -> bool {
    if pattern == "*" {
        return true;
    }
    if pattern == text {
        return true;
    }
    let parts: Vec<&str> = pattern.split('*').collect();
    if parts.len() == 1 {
        return pattern == text;
    }

    let mut pos = 0;
    for (i, part) in parts.iter().enumerate() {
        if part.is_empty() {
            continue;
        }
        if let Some(found) = text[pos..].find(part) {
            if i == 0 && found != 0 {
                return false;
            }
            pos += found + part.len();
        } else {
            return false;
        }
    }
    if let Some(last) = parts.last() {
        if !last.is_empty() && !text.ends_with(last) {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_allow() {
        let policy = CapabilityPolicy::new(false);
        assert!(policy.check("agent1", "file:read", ""));
    }

    #[test]
    fn test_default_deny() {
        let policy = CapabilityPolicy::new(true);
        assert!(!policy.check("agent1", "file:read", ""));
    }

    #[test]
    fn test_explicit_grant() {
        let mut policy = CapabilityPolicy::new(true);
        policy.grant("agent1", "file:read", "*");
        assert!(policy.check("agent1", "file:read", ""));
        assert!(!policy.check("agent1", "file:write", ""));
    }

    #[test]
    fn test_explicit_deny_overrides_grant() {
        let mut policy = CapabilityPolicy::new(false);
        policy.grant("agent1", "file:*", "*");
        policy.deny("agent1", "file:write");
        assert!(policy.check("agent1", "file:read", ""));
        assert!(!policy.check("agent1", "file:write", ""));
    }

    #[test]
    fn test_glob_match() {
        assert!(glob_match("*", "anything"));
        assert!(glob_match("file:*", "file:read"));
        assert!(!glob_match("file:read", "file:write"));
        assert!(glob_match("*.txt", "doc.txt"));
    }
}
