#!/usr/bin/env python3
"""
API Caller Script
This script calls the API endpoint defined in config.json
"""

import json
import requests
import time
from typing import Optional

def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)

def call_api(
    endpoint: str,
    api_key: str,
    timeout: int = 30,
    retries: int = 3
) -> Optional[dict]:
    """
    Call the API endpoint with retry logic.
    
    Args:
        endpoint: The API endpoint URL
        api_key: The API key for authentication
        timeout: Request timeout in seconds
        retries: Number of retry attempts on failure
    
    Returns:
        Response data as dictionary, or None if all retries fail
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    for attempt in range(retries + 1):
        try:
            print(f"Attempt {attempt + 1}/{retries + 1}: Calling {endpoint}")
            response = requests.get(
                endpoint,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < retries:
                print(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(1)  # Wait before retry
            else:
                print(f"All {retries + 1} attempts failed: {e}")
                return None

def main():
    """Main function to execute the API call."""
    # Load configuration
    config = load_config()
    
    # Extract API parameters
    endpoint = config.get("api_endpoint")
    api_key = config.get("api_key")
    timeout = config.get("timeout", 30)
    retries = config.get("retries", 3)
    
    # Validate configuration
    if not endpoint:
        print("Error: api_endpoint not found in config.json")
        return
    
    if not api_key:
        print("Warning: api_key not found in config.json")
    
    # Call the API
    result = call_api(endpoint, api_key, timeout, retries)
    
    # Handle response
    if result:
        print("\nAPI Response:")
        print(json.dumps(result, indent=2))
    else:
        print("\nFailed to retrieve data from API")

if __name__ == "__main__":
    main()
