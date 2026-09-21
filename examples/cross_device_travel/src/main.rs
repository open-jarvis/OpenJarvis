use openjarvis_cross_device_travel::travel::{run_demo, Scenario};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() == 1 && matches!(args[0].as_str(), "--help" | "-h") {
        println!(
            "Usage: cargo run -- [scenario]\nScenarios: {}\nDefault: happy",
            Scenario::NAMES
        );
        return ExitCode::SUCCESS;
    }
    if args.len() > 1 {
        eprintln!("Expected at most one scenario. Use --help for usage.");
        return ExitCode::from(2);
    }
    let scenario = match Scenario::parse(args.first().map(String::as_str).unwrap_or("happy")) {
        Ok(scenario) => scenario,
        Err(error) => {
            eprintln!("{error}");
            return ExitCode::from(2);
        }
    };
    match run_demo(scenario) {
        Ok(value) => {
            println!(
                "{}",
                serde_json::to_string_pretty(&value).expect("JSON Value serializes")
            );
            if value["report"]["aborted"] == true {
                ExitCode::FAILURE
            } else {
                ExitCode::SUCCESS
            }
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
