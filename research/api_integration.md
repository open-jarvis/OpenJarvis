# API Integration Overview

This document outlines the process for creating a Python script (`api_caller.py`) to call an API using a configuration file (`config.json`).

## Configuration (`config.json`)
*   **Required:** `api_endpoint` (string), `api_key` (string).
*   **Optional:** `timeout` (integer, default 30s), `retries` (integer, default 3).

## Python Script (`api_caller.py`)
*   **Features:** Automatic config loading, Bearer token authentication, exponential backoff retry logic, error handling, and timeout control.
*   **Structure:** `load_config()`, `call_api()`, `main()`.
*   **Dependencies:** `requests`, `json`, `time`, `typing`.
*   **Installation:** `pip install requests`.
*   **Usage:** `python api_caller.py` or `python api_caller.py --config custom_config.json`.

## Security & Troubleshooting
*   **Security:** Replace placeholder `your_api_key_here` before deployment; use environment variables for production credentials.
*   **Troubleshooting:** Increase timeout for connection issues, verify API key for auth failures, add delays for rate limits.

## Future Enhancements
Support for POST/PUT/DELETE methods, file logging, unit tests, multiple endpoints, and environment variable support.