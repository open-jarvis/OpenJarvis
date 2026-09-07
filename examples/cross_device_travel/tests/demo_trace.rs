//! Keep the handoff trace executable: reviewers can trust it matches the CLI.
#[test]
fn documented_trace_matches_the_executable() {
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_openjarvis-cross-device-travel"))
        .arg("happy")
        .output()
        .expect("run demo binary");
    assert!(output.status.success());
    let actual: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let documented: serde_json::Value =
        serde_json::from_str(include_str!("../traces/happy.json")).unwrap();
    assert_eq!(
        actual, documented,
        "Regenerate traces/happy.json after intentional demo changes"
    );
}
