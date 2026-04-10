#!/usr/bin/env python3
"""
API Client Script
Calls the API endpoint defined in config.json
"""

import json
import requests
from requests.exceptions import RequestException, Timeout, RetryError

# Load configuration from config.json
with open('config.json', 'r') as f:
    config = json.load(f)

# Extract configuration values
API_ENDPOINT = config['api_endpoint']
API_KEY = config['api_key']
TIMEOUT = config['timeout']
RETRIES = config['retries']

def call_api():
    """
    Call the API endpoint with retry logic and timeout handling.
    """
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    }
    
    for attempt in range(1, RETRIES + 1):
        try:
            print(f"Attempt {attempt}/{RETRIES}: Calling API...")
            response = requests.get(
                API_ENDPOINT,
                headers=headers,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            
            print(f"Success! Status code: {response.status_code}")
            print(f"Response: {response.json()}")
            return response.json()
            
        except Timeout:
            print(f"Attempt {attempt} timed out after {TIMEOUT} seconds")
        except RequestException as e:
            print(f"Attempt {attempt} failed: {str(e)}")
        except RetryError as e:
            print(f"Attempt {attempt} failed after retries: {str(e)}")
    
    print("All retry attempts exhausted.")
    return None

if __name__ == "__main__":
    result = call_api()
    if result:
        print("\nAPI call completed successfully.")
    else:
        print("\nAPI call failed.")
