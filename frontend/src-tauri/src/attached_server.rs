//! Opt-in desktop client for an already running, loopback-only OpenJarvis.
//! Never starts inference processes, syncs packages or changes credentials.
use crate::{SetupStatus, SharedStatus};
use std::time::Duration;

fn base_for_port(raw: &str) -> Result<String, String> {
    let port = raw
        .parse::<u16>()
        .ok()
        .filter(|port| *port > 0)
        .ok_or("Invalid local desktop server port.")?;
    Ok(format!("http://127.0.0.1:{port}"))
}

pub fn configured_base() -> Option<Result<String, String>> {
    std::env::var_os("OPENJARVIS_DESKTOP_ATTACH_PORT")
        .map(|value| base_for_port(&value.to_string_lossy()))
}

pub fn bundled_origin(url: &reqwest::Url) -> bool {
    url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
        && matches!(
            (url.scheme(), url.host_str()),
            ("tauri", Some("localhost")) | ("http" | "https", Some("tauri.localhost"))
        )
}

pub fn require_managed_mode() -> Result<(), String> {
    if configured_base().is_some() {
        return Err(
            "This window uses an existing local server. Configure it outside the desktop setup."
                .into(),
        );
    }
    Ok(())
}

pub fn starting_status() -> SetupStatus {
    SetupStatus {
        phase: "server".into(),
        detail: "Connecting to the existing local OpenJarvis...".into(),
        source: "custom".into(),
        requires_source: false,
        ..SetupStatus::default()
    }
}

async fn probe(base: &str) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .build()
        .map_err(|_| "Could not initialize the local connection.")?;
    let health = client
        .get(format!("{base}/health"))
        .send()
        .await
        .map_err(|_| "The local OpenJarvis server is unavailable.")?;
    if !health.status().is_success() {
        return Err("The local OpenJarvis server is not healthy.".into());
    }
    let response = client
        .get(format!("{base}/v1/info"))
        .send()
        .await
        .map_err(|_| "Could not identify the local OpenJarvis server.")?;
    if !response.status().is_success() {
        return Err("Could not identify the local OpenJarvis server.".into());
    }
    let info: serde_json::Value = response
        .json()
        .await
        .map_err(|_| "Invalid local OpenJarvis identity.")?;
    if !valid_identity(&info) {
        return Err("The local OpenJarvis server has no configured model or agent.".into());
    }
    Ok(())
}

fn valid_identity(info: &serde_json::Value) -> bool {
    ["model", "agent"].iter().all(|field| {
        info[*field]
            .as_str()
            .is_some_and(|value| !value.trim().is_empty())
    })
}

pub async fn connect(base: Result<String, String>, status: SharedStatus) {
    *status.lock().await = starting_status();
    let result = match base {
        Ok(base) => probe(&base).await,
        Err(error) => Err(error),
    };
    let mut state = status.lock().await;
    match result {
        Ok(()) => {
            state.phase = "ready".into();
            state.detail = "Connected to the existing local OpenJarvis.".into();
            state.server_ready = true;
            state.model_ready = true;
            state.ollama_ready = true; // setup's legacy engine-ready indicator
        }
        Err(error) => {
            state.phase = "error".into();
            state.error = Some(error);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn local_fixture(replies: Vec<&'static str>) -> (String, tokio::task::JoinHandle<()>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            for reply in replies {
                let (mut socket, _) =
                    tokio::time::timeout(Duration::from_secs(3), listener.accept())
                        .await
                        .unwrap()
                        .unwrap();
                let mut request = vec![0; 4096];
                socket.read(&mut request).await.unwrap();
                socket.write_all(reply.as_bytes()).await.unwrap();
                socket.shutdown().await.unwrap();
            }
        });
        (base, task)
    }

    #[tokio::test]
    async fn attached_server_ready_requires_health_and_identity() {
        let (base, server) = local_fixture(vec![
            "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{}",
            "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{\"model\":\"codex/test\",\"agent\":\"simple\"}",
        ]).await;
        assert!(probe(&base).await.is_ok());
        server.await.unwrap();
        let (base, server) = local_fixture(vec![
            "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{}",
            "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{}",
        ])
        .await;
        assert!(probe(&base).await.is_err());
        server.await.unwrap();
    }

    #[tokio::test]
    async fn attached_server_does_not_follow_redirects_or_ignore_failed_health() {
        for reply in [
            "HTTP/1.1 302 Found\r\nLocation: https://example.com\r\nConnection: close\r\n\r\n",
            "HTTP/1.1 503 Unavailable\r\nConnection: close\r\n\r\nprivate details",
        ] {
            let (base, server) = local_fixture(vec![reply]).await;
            let error = probe(&base).await.unwrap_err();
            assert!(!error.contains("private details"));
            server.await.unwrap();
        }
    }

    #[test]
    fn attached_server_only_accepts_loopback_port_numbers() {
        assert_eq!(base_for_port("8001").unwrap(), "http://127.0.0.1:8001");
        for bad in [
            "",
            "0",
            "65536",
            "https://example.com",
            "8001/path",
            "8001?key=x",
        ] {
            assert!(base_for_port(bad).is_err());
        }
    }

    #[test]
    fn attached_server_microphone_only_for_bundled_ui() {
        for good in [
            "tauri://localhost/",
            "http://tauri.localhost/",
            "https://tauri.localhost/",
        ] {
            assert!(bundled_origin(&reqwest::Url::parse(good).unwrap()));
        }
        for bad in [
            "https://example.com/",
            "http://127.0.0.1:8001/",
            "http://tauri.localhost:123/",
            "http://user@tauri.localhost/",
        ] {
            assert!(!bundled_origin(&reqwest::Url::parse(bad).unwrap()));
        }
    }

    #[test]
    fn attached_server_requires_model_and_agent() {
        assert!(valid_identity(
            &serde_json::json!({"model":"codex/test", "agent":"simple"})
        ));
        for bad in [
            serde_json::json!({}),
            serde_json::json!({"model":"", "agent":"simple"}),
            serde_json::json!({"model":"test"}),
        ] {
            assert!(!valid_identity(&bad));
        }
    }

    #[tokio::test]
    async fn attached_server_invalid_configuration_stays_blocked() {
        let status = std::sync::Arc::new(tokio::sync::Mutex::new(SetupStatus::default()));
        connect(base_for_port("invalid"), status.clone()).await;
        let status = status.lock().await;
        assert_eq!(status.phase, "error");
        assert!(!status.server_ready);
        assert!(!status.requires_source);
    }
}
