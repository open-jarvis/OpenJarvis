//! Optional wake-to-window only. Chat, STT and TTS remain in the native UI.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::watch;

static SPEECH_BUSY: AtomicBool = AtomicBool::new(false);
static WORKER_ACTIVE: AtomicBool = AtomicBool::new(false);

#[tauri::command]
pub async fn set_desktop_speech_busy(busy: bool) -> Result<(), String> {
    SPEECH_BUSY.store(busy, Ordering::SeqCst);
    if busy {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        while WORKER_ACTIVE.load(Ordering::SeqCst) {
            if tokio::time::Instant::now() >= deadline {
                return Err("Could not suspend wake listening for playback.".into());
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }
    Ok(())
}

struct ActiveWorker;
impl Drop for ActiveWorker {
    fn drop(&mut self) {
        WORKER_ACTIVE.store(false, Ordering::SeqCst);
    }
}

pub struct WakeLauncher {
    stop: watch::Sender<bool>,
    task: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
}

async fn stop_worker(child: &mut Child) {
    if let Some(mut input) = child.stdin.take() {
        let _ = input.write_all(b"stop\n").await;
    }
    if tokio::time::timeout(Duration::from_secs(3), child.wait())
        .await
        .is_err()
    {
        let _ = child.kill().await;
        let _ = child.wait().await;
    }
}

pub fn enabled() -> bool {
    std::env::var("OPENJARVIS_DESKTOP_WAKE").as_deref() == Ok("1")
        && crate::attached_server::configured_base().is_some()
}

pub fn start(app: &tauri::AppHandle) {
    if !enabled() {
        return;
    }
    let (stop, mut stopped) = watch::channel(false);
    let handle = app.clone();
    let task = tauri::async_runtime::spawn(async move {
        let Some(root) = crate::find_project_root() else {
            return;
        };
        let python = root.join(".venv/bin/python");
        let script = root.join("scripts/wake-desktop.py");
        // A failed worker is not retried automatically. A visible -> hidden
        // transition explicitly rearms it, preventing crash/retry loops.
        let mut blocked = false;
        loop {
            if *stopped.borrow() {
                break;
            }
            let Some(window) = handle.get_webview_window("main") else {
                break;
            };
            if window.is_visible().unwrap_or(true) {
                blocked = false;
            } else if !blocked && !SPEECH_BUSY.load(Ordering::SeqCst) {
                WORKER_ACTIVE.store(true, Ordering::SeqCst);
                let _active = ActiveWorker;
                if SPEECH_BUSY.load(Ordering::SeqCst) {
                    continue;
                }
                let child = Command::new(&python)
                    .arg(&script)
                    .stdin(std::process::Stdio::piped())
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::null())
                    .kill_on_drop(true)
                    .spawn();
                match child {
                    Ok(mut child) => {
                        let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
                        loop {
                            tokio::select! {
                                _ = stopped.changed() => { stop_worker(&mut child).await; return; }
                                line = lines.next_line() => {
                                    match line.ok().flatten().as_deref() {
                                        Some("ready") => {},
                                        Some("wake") => {
                                            stop_worker(&mut child).await;
                                            let _ = window.show();
                                            let _ = window.set_focus();
                                            break;
                                        }
                                        _ => {
                                            stop_worker(&mut child).await;
                                            blocked = true;
                                            break;
                                        }
                                    }
                                }
                                _ = tokio::time::sleep(Duration::from_millis(250)) => {
                                    if window.is_visible().unwrap_or(true) || SPEECH_BUSY.load(Ordering::SeqCst) {
                                        stop_worker(&mut child).await;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    Err(_) => {
                        blocked = true;
                    }
                }
                if blocked {
                    use tauri_plugin_dialog::DialogExt;
                    let _ = window.show();
                    handle.dialog().message("A ativação por voz está indisponível. O chat continua disponível. Verifique a instalação local do detector antes de tentar novamente.")
                        .title("OpenJarvis").show(|_| {});
                }
            }
            tokio::select! {
                _ = stopped.changed() => break,
                _ = tokio::time::sleep(Duration::from_millis(250)) => {},
            }
        }
    });
    app.manage(WakeLauncher {
        stop,
        task: Mutex::new(Some(task)),
    });
}

pub async fn shutdown(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<WakeLauncher>() {
        let _ = state.stop.send(true);
        let task = state.task.lock().unwrap().take();
        if let Some(task) = task {
            let _ = task.await;
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[tokio::test]
    async fn wake_worker_is_stopped_and_reaped_cooperatively() {
        let mut child = Command::new("/bin/sh")
            .args(["-c", "read line; test \"$line\" = stop"])
            .stdin(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        stop_worker(&mut child).await;
        assert!(child.try_wait().unwrap().unwrap().success());
    }

    #[tokio::test]
    async fn wake_worker_that_ignores_stop_is_killed_and_reaped() {
        let mut child = Command::new("/bin/sleep")
            .arg("30")
            .stdin(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        stop_worker(&mut child).await;
        assert!(child.try_wait().unwrap().is_some());
    }
}
