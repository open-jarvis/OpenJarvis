"""security_scanner dataset — 30 vulnerable code projects for security auditing.

Each task presents a small Python project with planted vulnerabilities.
The agent must identify vulnerabilities, classify severity, and recommend fixes.

Difficulty tiers:
- easy (10): single obvious vulnerability (hardcoded secret, SQL injection)
- medium (10): multiple vulnerabilities requiring deeper analysis
- hard (10): subtle vulnerabilities mixed with safe patterns (false positive traps)
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a security auditor. Scan the following Python project for security vulnerabilities.

## Project Files

{file_listing}

Produce a structured security report with these sections:
- **Secrets Found**: any hardcoded credentials, API keys, or tokens.
- **Vulnerabilities**: code patterns that could be exploited (include file name and line).
- **Dependency Issues**: outdated or vulnerable packages.
- **Recommendations**: prioritized list of fixes.
- **Risk Level**: CRITICAL, HIGH, MEDIUM, or LOW overall assessment."""  # noqa: E501

# ---------------------------------------------------------------------------
# EASY tasks (10): single obvious vulnerability
# ---------------------------------------------------------------------------

_EASY_TASKS: List[Dict[str, Any]] = [
    {
        "project_files": {
            "app.py": (
                "from flask import Flask, request\n"
                "import sqlite3\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/user')\n"
                "def get_user():\n"
                "    uid = request.args.get('id')\n"
                "    conn = sqlite3.connect('app.db')\n"
                "    cursor = conn.cursor()\n"
                '    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
                "    return str(cursor.fetchone())\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "app.py",
                "line": 11,
                "type": "sql_injection",
                "severity": "CRITICAL",
                "description": "f-string SQL query with unsanitized user input",
            },
        ],
        "safe_patterns": ["Flask app instantiation", "sqlite3.connect usage"],
    },
    {
        "project_files": {
            "config.py": (
                "DATABASE_URL = 'postgresql://admin:password123@db.prod.internal:5432/myapp'\n"
                "SECRET_KEY = 'super-secret-key-do-not-share'\n"
                "DEBUG = True\n"
                "API_KEY = 'sk-proj-abc123def456ghi789'\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "config.py",
                "line": 1,
                "type": "hardcoded_secret",
                "severity": "CRITICAL",
                "description": "Database password hardcoded in source",
            },
            {
                "file": "config.py",
                "line": 2,
                "type": "hardcoded_secret",
                "severity": "HIGH",
                "description": "Secret key hardcoded in source",
            },
            {
                "file": "config.py",
                "line": 4,
                "type": "hardcoded_secret",
                "severity": "CRITICAL",
                "description": "API key hardcoded in source",
            },
            {
                "file": "config.py",
                "line": 3,
                "type": "debug_enabled",
                "severity": "MEDIUM",
                "description": "Debug mode enabled in production config",
            },
        ],
        "safe_patterns": [],
    },
    {
        "project_files": {
            "utils.py": (
                "import subprocess\n\n"
                "def run_command(user_input):\n"
                "    result = subprocess.call(user_input, shell=True)\n"
                "    return result\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "utils.py",
                "line": 4,
                "type": "command_injection",
                "severity": "CRITICAL",
                "description": "subprocess.call with shell=True and unsanitized input",
            },
        ],
        "safe_patterns": [],
    },
    {
        "project_files": {
            "auth.py": (
                "import hashlib\n\n"
                "def hash_password(password):\n"
                "    return hashlib.md5(password.encode()).hexdigest()\n\n"
                "def verify_password(password, hashed):\n"
                "    return hash_password(password) == hashed\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "auth.py",
                "line": 4,
                "type": "weak_crypto",
                "severity": "HIGH",
                "description": "MD5 used for password hashing — use bcrypt or argon2",
            },
        ],
        "safe_patterns": ["verify_password comparison logic"],
    },
    {
        "project_files": {
            "api.py": (
                "import pickle\nfrom flask import Flask, request\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/load', methods=['POST'])\n"
                "def load_data():\n"
                "    data = pickle.loads(request.data)\n"
                "    return str(data)\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "api.py",
                "line": 8,
                "type": "insecure_deserialization",
                "severity": "CRITICAL",
                "description": "pickle.loads on untrusted request data allows arbitrary code execution",
            },
        ],
        "safe_patterns": ["Flask route decorator"],
    },
    {
        "project_files": {
            "server.py": (
                "from flask import Flask, request, render_template_string\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/greet')\n"
                "def greet():\n"
                "    name = request.args.get('name', 'World')\n"
                "    return render_template_string(f'<h1>Hello {name}!</h1>')\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "server.py",
                "line": 8,
                "type": "xss",
                "severity": "HIGH",
                "description": "render_template_string with unescaped user input enables XSS/SSTI",
            },
        ],
        "safe_patterns": ["Default parameter value"],
    },
    {
        "project_files": {
            "download.py": (
                "import os\nfrom flask import Flask, request, send_file\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/download')\n"
                "def download():\n"
                "    filename = request.args.get('file')\n"
                "    return send_file(os.path.join('/data', filename))\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "download.py",
                "line": 9,
                "type": "path_traversal",
                "severity": "HIGH",
                "description": "No validation on filename allows path traversal (../../etc/passwd)",
            },
        ],
        "safe_patterns": ["os.path.join usage"],
    },
    {
        "project_files": {
            "cors_app.py": (
                "from flask import Flask\nfrom flask_cors import CORS\n\n"
                "app = Flask(__name__)\n"
                "CORS(app, resources={r'/*': {'origins': '*'}})\n\n"
                "@app.route('/api/data')\n"
                "def get_data():\n"
                "    return {'secret': 'internal-data'}\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "cors_app.py",
                "line": 5,
                "type": "misconfiguration",
                "severity": "MEDIUM",
                "description": "CORS allows all origins — exposes API to any domain",
            },
        ],
        "safe_patterns": ["Flask-CORS import pattern"],
    },
    {
        "project_files": {
            "logging_app.py": (
                "import logging\n\n"
                "logger = logging.getLogger(__name__)\n\n"
                "def process_payment(card_number, amount):\n"
                "    logger.info(f'Processing payment of ${amount} with card {card_number}')\n"
                "    # ... payment logic ...\n"
                "    return True\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "logging_app.py",
                "line": 6,
                "type": "sensitive_data_exposure",
                "severity": "HIGH",
                "description": "Credit card number logged in plaintext",
            },
        ],
        "safe_patterns": ["logging.getLogger pattern"],
    },
    {
        "project_files": {
            "jwt_app.py": (
                "import jwt\n\n"
                "def create_token(user_id):\n"
                "    return jwt.encode({'user_id': user_id}, 'secret', algorithm='none')\n\n"
                "def verify_token(token):\n"
                "    return jwt.decode(token, 'secret', algorithms=['none', 'HS256'])\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "jwt_app.py",
                "line": 4,
                "type": "weak_crypto",
                "severity": "CRITICAL",
                "description": "JWT using algorithm='none' disables signature verification",
            },
            {
                "file": "jwt_app.py",
                "line": 7,
                "type": "weak_crypto",
                "severity": "CRITICAL",
                "description": "JWT decode allows 'none' algorithm — attacker can forge tokens",
            },
        ],
        "safe_patterns": [],
    },
]

# ---------------------------------------------------------------------------
# MEDIUM tasks (10): multiple vulnerabilities
# ---------------------------------------------------------------------------

_MEDIUM_TASKS: List[Dict[str, Any]] = [
    {
        "project_files": {
            "app.py": (
                "from flask import Flask, request, redirect\nimport sqlite3\nimport os\n\n"
                "app = Flask(__name__)\n"
                "app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')\n\n"
                "@app.route('/login', methods=['POST'])\n"
                "def login():\n"
                "    user = request.form['username']\n"
                "    pw = request.form['password']\n"
                "    conn = sqlite3.connect('users.db')\n"
                "    row = conn.execute(\n"
                "        f\"SELECT * FROM users WHERE username='{user}' AND password='{pw}'\"\n"
                "    ).fetchone()\n"
                "    if row:\n"
                "        return redirect(request.args.get('next', '/'))\n"
                "    return 'Invalid', 401\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "app.py",
                "line": 14,
                "type": "sql_injection",
                "severity": "CRITICAL",
                "description": "f-string SQL with user-supplied username and password",
            },
            {
                "file": "app.py",
                "line": 17,
                "type": "open_redirect",
                "severity": "MEDIUM",
                "description": "Unvalidated redirect URL from request.args",
            },
            {
                "file": "app.py",
                "line": 6,
                "type": "hardcoded_secret",
                "severity": "LOW",
                "description": "Default secret key in fallback (acceptable for dev)",
            },
        ],
        "safe_patterns": ["os.environ.get for secret key (with fallback)"],
    },
    {
        "project_files": {
            "api.py": (
                "from flask import Flask, request, jsonify\nimport yaml\nimport xml.etree.ElementTree as ET\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/parse-yaml', methods=['POST'])\n"
                "def parse_yaml():\n"
                "    data = yaml.load(request.data)\n"
                "    return jsonify(data)\n\n"
                "@app.route('/parse-xml', methods=['POST'])\n"
                "def parse_xml():\n"
                "    tree = ET.fromstring(request.data)\n"
                "    return tree.text\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "api.py",
                "line": 9,
                "type": "insecure_deserialization",
                "severity": "CRITICAL",
                "description": "yaml.load without Loader allows arbitrary code execution",
            },
            {
                "file": "api.py",
                "line": 14,
                "type": "xxe",
                "severity": "HIGH",
                "description": "XML parsing without disabling external entities",
            },
        ],
        "safe_patterns": ["jsonify usage", "Flask route decorators"],
    },
    {
        "project_files": {
            "models.py": (
                "import os\nimport tempfile\n\n"
                "def save_upload(file_obj, filename):\n"
                "    path = os.path.join('/uploads', filename)\n"
                "    file_obj.save(path)\n"
                "    return path\n\n"
                "def create_temp_file(content):\n"
                "    fd, path = tempfile.mkstemp()\n"
                "    os.write(fd, content.encode())\n"
                "    return path\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "models.py",
                "line": 5,
                "type": "path_traversal",
                "severity": "HIGH",
                "description": "No sanitization of filename allows path traversal",
            },
            {
                "file": "models.py",
                "line": 10,
                "type": "resource_leak",
                "severity": "MEDIUM",
                "description": "File descriptor from mkstemp never closed",
            },
        ],
        "safe_patterns": ["tempfile.mkstemp usage pattern"],
    },
    {
        "project_files": {
            "crypto_utils.py": (
                "import base64\nfrom cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes\n\n"
                "KEY = b'0123456789abcdef'  # 16 bytes\n"
                "IV = b'0000000000000000'\n\n"
                "def encrypt(plaintext):\n"
                "    cipher = Cipher(algorithms.AES(KEY), modes.ECB())\n"
                "    encryptor = cipher.encryptor()\n"
                "    padded = plaintext.ljust(16, ' ').encode()\n"
                "    return base64.b64encode(encryptor.update(padded)).decode()\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "crypto_utils.py",
                "line": 4,
                "type": "hardcoded_secret",
                "severity": "CRITICAL",
                "description": "Encryption key hardcoded in source",
            },
            {
                "file": "crypto_utils.py",
                "line": 8,
                "type": "weak_crypto",
                "severity": "HIGH",
                "description": "AES-ECB mode is insecure — use CBC or GCM",
            },
            {
                "file": "crypto_utils.py",
                "line": 5,
                "type": "weak_crypto",
                "severity": "HIGH",
                "description": "Static IV of all zeros is insecure",
            },
        ],
        "safe_patterns": ["base64 encoding of ciphertext"],
    },
    {
        "project_files": {
            "session.py": (
                "import json\nimport base64\nfrom flask import Flask, request, make_response\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/set-prefs', methods=['POST'])\n"
                "def set_prefs():\n"
                "    prefs = request.json\n"
                "    encoded = base64.b64encode(json.dumps(prefs).encode()).decode()\n"
                "    resp = make_response('OK')\n"
                "    resp.set_cookie('prefs', encoded)\n"
                "    return resp\n\n"
                "@app.route('/get-prefs')\n"
                "def get_prefs():\n"
                "    raw = request.cookies.get('prefs', '')\n"
                "    prefs = json.loads(base64.b64decode(raw))\n"
                "    return prefs\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "session.py",
                "line": 12,
                "type": "misconfiguration",
                "severity": "MEDIUM",
                "description": "Cookie set without secure, httponly, or samesite flags",
            },
            {
                "file": "session.py",
                "line": 18,
                "type": "insecure_deserialization",
                "severity": "MEDIUM",
                "description": "Base64-encoded cookie is not signed — client can tamper with preferences",
            },
        ],
        "safe_patterns": ["json.dumps/loads for serialization (not pickle)"],
    },
    {
        "project_files": {
            "admin.py": (
                "from flask import Flask, request\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/admin/delete-user', methods=['POST'])\n"
                "def delete_user():\n"
                "    # No authentication check\n"
                "    user_id = request.form['user_id']\n"
                "    # delete_from_db(user_id)\n"
                "    return f'Deleted user {user_id}'\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "admin.py",
                "line": 6,
                "type": "broken_access_control",
                "severity": "CRITICAL",
                "description": "Admin endpoint has no authentication or authorization check",
            },
            {
                "file": "admin.py",
                "line": 10,
                "type": "xss",
                "severity": "MEDIUM",
                "description": "User ID reflected in response without escaping",
            },
        ],
        "safe_patterns": ["POST method for destructive action"],
    },
    {
        "project_files": {
            "email_sender.py": (
                "import smtplib\nfrom email.mime.text import MIMEText\n\n"
                "SMTP_HOST = 'smtp.gmail.com'\n"
                "SMTP_USER = 'bot@company.com'\n"
                "SMTP_PASS = 'Gmail2024!Secure'\n\n"
                "def send_email(to_addr, subject, body):\n"
                "    msg = MIMEText(body)\n"
                "    msg['Subject'] = subject\n"
                "    msg['From'] = SMTP_USER\n"
                "    msg['To'] = to_addr\n"
                "    with smtplib.SMTP(SMTP_HOST) as server:\n"
                "        server.login(SMTP_USER, SMTP_PASS)\n"
                "        server.send_message(msg)\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "email_sender.py",
                "line": 6,
                "type": "hardcoded_secret",
                "severity": "CRITICAL",
                "description": "SMTP password hardcoded in source",
            },
            {
                "file": "email_sender.py",
                "line": 13,
                "type": "misconfiguration",
                "severity": "HIGH",
                "description": "SMTP connection without TLS (use SMTP_SSL or starttls)",
            },
        ],
        "safe_patterns": [
            "MIMEText for email construction",
            "context manager for SMTP",
        ],
    },
    {
        "project_files": {
            "cache.py": (
                "import redis\nimport json\n\n"
                "r = redis.Redis(host='cache.internal', port=6379)\n\n"
                "def get_cached(key):\n"
                "    val = r.get(key)\n"
                "    return json.loads(val) if val else None\n\n"
                "def set_cached(key, value, ttl=3600):\n"
                "    r.set(key, json.dumps(value), ex=ttl)\n\n"
                "def flush_all():\n"
                "    r.flushall()\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "cache.py",
                "line": 4,
                "type": "misconfiguration",
                "severity": "HIGH",
                "description": "Redis connection without authentication or TLS",
            },
            {
                "file": "cache.py",
                "line": 14,
                "type": "broken_access_control",
                "severity": "MEDIUM",
                "description": "flushall exposed without access control — could wipe entire cache",
            },
        ],
        "safe_patterns": ["json serialization for cache values", "TTL on cached items"],
    },
    {
        "project_files": {
            "file_processor.py": (
                "import os\nimport subprocess\n\n"
                "def process_file(filepath):\n"
                "    if not filepath.endswith('.txt'):\n"
                "        raise ValueError('Only .txt files allowed')\n"
                "    output = subprocess.check_output(f'cat {filepath}', shell=True)\n"
                "    return output.decode()\n\n"
                "def count_lines(filepath):\n"
                "    output = subprocess.check_output(['wc', '-l', filepath])\n"
                "    return int(output.split()[0])\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "file_processor.py",
                "line": 7,
                "type": "command_injection",
                "severity": "CRITICAL",
                "description": "shell=True with f-string filepath allows command injection",
            },
            {
                "file": "file_processor.py",
                "line": 5,
                "type": "insufficient_validation",
                "severity": "MEDIUM",
                "description": "Extension check is bypassable (e.g., file.txt; rm -rf /)",
            },
        ],
        "safe_patterns": ["subprocess with list args (count_lines) is safe pattern"],
    },
    {
        "project_files": {
            "rate_limiter.py": (
                "from flask import Flask, request, g\nimport time\n\n"
                "app = Flask(__name__)\n"
                "request_counts = {}  # {ip: (count, timestamp)}\n\n"
                "@app.before_request\n"
                "def rate_limit():\n"
                "    ip = request.headers.get('X-Forwarded-For', request.remote_addr)\n"
                "    now = time.time()\n"
                "    count, ts = request_counts.get(ip, (0, now))\n"
                "    if now - ts > 60:\n"
                "        request_counts[ip] = (1, now)\n"
                "    else:\n"
                "        request_counts[ip] = (count + 1, ts)\n"
                "    if request_counts[ip][0] > 100:\n"
                "        return 'Rate limited', 429\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "rate_limiter.py",
                "line": 9,
                "type": "ip_spoofing",
                "severity": "HIGH",
                "description": "X-Forwarded-For header is client-controlled — rate limit can be bypassed",
            },
            {
                "file": "rate_limiter.py",
                "line": 5,
                "type": "resource_leak",
                "severity": "MEDIUM",
                "description": "In-memory dict grows unbounded — no cleanup of old entries",
            },
        ],
        "safe_patterns": ["Rate limiting concept", "before_request pattern"],
    },
]

# ---------------------------------------------------------------------------
# HARD tasks (10): subtle vulnerabilities with false positive traps
# ---------------------------------------------------------------------------

_HARD_TASKS: List[Dict[str, Any]] = [
    {
        "project_files": {
            "auth.py": (
                "import hmac\nimport hashlib\nimport os\nimport time\n\n"
                "def generate_token(user_id, secret):\n"
                "    timestamp = str(int(time.time()))\n"
                "    payload = f'{user_id}:{timestamp}'\n"
                "    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()\n"
                "    return f'{payload}:{sig}'\n\n"
                "def verify_token(token, secret):\n"
                "    parts = token.split(':')\n"
                "    if len(parts) != 3:\n"
                "        return False\n"
                "    user_id, timestamp, sig = parts\n"
                "    expected = hmac.new(secret.encode(), f'{user_id}:{timestamp}'.encode(), hashlib.sha256).hexdigest()\n"
                "    return sig == expected\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "auth.py",
                "line": 18,
                "type": "timing_attack",
                "severity": "MEDIUM",
                "description": "String comparison (==) instead of hmac.compare_digest for signature — vulnerable to timing attack",
            },
            {
                "file": "auth.py",
                "line": 7,
                "type": "insufficient_validation",
                "severity": "LOW",
                "description": "No token expiration check — tokens valid forever",
            },
        ],
        "safe_patterns": [
            "hmac.new with SHA-256 is correct HMAC construction",
            "Token format is reasonable",
        ],
    },
    {
        "project_files": {
            "sanitizer.py": (
                "import re\nimport html\n\n"
                "ALLOWED_TAGS = ['b', 'i', 'u', 'a', 'p', 'br']\n\n"
                "def sanitize_html(text):\n"
                "    # Remove script tags\n"
                "    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)\n"
                "    # Remove event handlers\n"
                "    text = re.sub(r'\\s+on\\w+\\s*=', ' data-removed=', text, flags=re.IGNORECASE)\n"
                "    return text\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "sanitizer.py",
                "line": 8,
                "type": "xss",
                "severity": "HIGH",
                "description": "Regex-based HTML sanitization is bypassable (e.g., <img src=x onerror=alert(1)>, <svg/onload=...>)",
            },
            {
                "file": "sanitizer.py",
                "line": 10,
                "type": "xss",
                "severity": "HIGH",
                "description": "Event handler regex can be bypassed with newlines or encoding",
            },
        ],
        "safe_patterns": [
            "html module import (though not used)",
            "ALLOWED_TAGS list (good intent)",
        ],
    },
    {
        "project_files": {
            "db.py": (
                "import sqlite3\nfrom contextlib import contextmanager\n\n"
                "@contextmanager\n"
                "def get_db():\n"
                "    conn = sqlite3.connect('app.db')\n"
                "    try:\n"
                "        yield conn\n"
                "    finally:\n"
                "        conn.close()\n\n"
                "def get_user(user_id):\n"
                "    with get_db() as conn:\n"
                "        return conn.execute(\n"
                "            'SELECT * FROM users WHERE id = ?', (user_id,)\n"
                "        ).fetchone()\n\n"
                "def search_users(query):\n"
                "    with get_db() as conn:\n"
                "        return conn.execute(\n"
                "            f\"SELECT * FROM users WHERE name LIKE '%{query}%'\"\n"
                "        ).fetchall()\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "db.py",
                "line": 21,
                "type": "sql_injection",
                "severity": "CRITICAL",
                "description": "search_users uses f-string SQL with unsanitized query parameter",
            },
        ],
        "safe_patterns": [
            "get_user uses parameterized query (?)",
            "Context manager for connection",
            "conn.close in finally",
        ],
    },
    {
        "project_files": {
            "password_reset.py": (
                "import hashlib\nimport time\nimport secrets\n\n"
                "def generate_reset_token(email):\n"
                "    token = hashlib.sha256(f'{email}:{time.time()}'.encode()).hexdigest()\n"
                "    return token\n\n"
                "def generate_api_key():\n"
                "    return secrets.token_urlsafe(32)\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "password_reset.py",
                "line": 6,
                "type": "weak_crypto",
                "severity": "HIGH",
                "description": "Reset token is predictable — based on email + timestamp, not cryptographic random",
            },
        ],
        "safe_patterns": ["secrets.token_urlsafe for API key generation is correct"],
    },
    {
        "project_files": {
            "middleware.py": (
                "from flask import Flask, request, abort\nimport re\n\n"
                "app = Flask(__name__)\n"
                "BLOCKED_IPS = ['10.0.0.1']\n\n"
                "@app.before_request\n"
                "def security_check():\n"
                "    if request.remote_addr in BLOCKED_IPS:\n"
                "        abort(403)\n"
                "    # SSRF protection\n"
                "    url = request.args.get('url', '')\n"
                "    if url and re.match(r'^https?://', url):\n"
                "        parsed = url.split('/')[2]  # hostname\n"
                "        if parsed in ('localhost', '127.0.0.1'):\n"
                "            abort(403)\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "middleware.py",
                "line": 14,
                "type": "ssrf",
                "severity": "HIGH",
                "description": "SSRF check is bypassable — doesn't handle 0.0.0.0, IPv6 ::1, or DNS rebinding",
            },
            {
                "file": "middleware.py",
                "line": 14,
                "type": "ssrf",
                "severity": "MEDIUM",
                "description": "URL parsing via split is fragile — use urllib.parse",
            },
        ],
        "safe_patterns": ["IP blocklist concept", "SSRF protection attempt"],
    },
    {
        "project_files": {
            "session_store.py": (
                "import json\nimport os\nimport hashlib\n\n"
                "SESSION_DIR = '/tmp/sessions'\n\n"
                "def create_session(user_data):\n"
                "    session_id = hashlib.sha256(os.urandom(32)).hexdigest()\n"
                "    path = os.path.join(SESSION_DIR, session_id)\n"
                "    with open(path, 'w') as f:\n"
                "        json.dump(user_data, f)\n"
                "    return session_id\n\n"
                "def load_session(session_id):\n"
                "    path = os.path.join(SESSION_DIR, session_id)\n"
                "    with open(path) as f:\n"
                "        return json.load(f)\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "session_store.py",
                "line": 15,
                "type": "path_traversal",
                "severity": "HIGH",
                "description": "session_id not validated — ../../etc/passwd traversal possible",
            },
            {
                "file": "session_store.py",
                "line": 5,
                "type": "misconfiguration",
                "severity": "MEDIUM",
                "description": "/tmp is world-readable — session files accessible to other users",
            },
        ],
        "safe_patterns": [
            "os.urandom(32) for session ID generation is cryptographically strong",
            "json serialization (not pickle)",
        ],
    },
    {
        "project_files": {
            "webhook.py": (
                "import hmac\nimport hashlib\nfrom flask import Flask, request\n\n"
                "app = Flask(__name__)\n"
                "WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', '')\n\n"
                "@app.route('/webhook', methods=['POST'])\n"
                "def handle_webhook():\n"
                "    sig = request.headers.get('X-Signature', '')\n"
                "    body = request.get_data()\n"
                "    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()\n"
                "    if not sig or sig != expected:\n"
                "        return 'Unauthorized', 401\n"
                "    # process webhook\n"
                "    return 'OK', 200\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "webhook.py",
                "line": 13,
                "type": "timing_attack",
                "severity": "MEDIUM",
                "description": "String != for HMAC comparison is vulnerable to timing attack — use hmac.compare_digest",
            },
            {
                "file": "webhook.py",
                "line": 6,
                "type": "misconfiguration",
                "severity": "LOW",
                "description": "Empty string default for WEBHOOK_SECRET — webhook verification disabled if env var missing",
            },
        ],
        "safe_patterns": [
            "HMAC-SHA256 for webhook verification",
            "os.environ.get for secrets",
        ],
    },
    {
        "project_files": {
            "upload.py": (
                "import os\nimport magic\nfrom flask import Flask, request\n\n"
                "app = Flask(__name__)\n"
                "ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif']\n\n"
                "@app.route('/upload', methods=['POST'])\n"
                "def upload():\n"
                "    f = request.files['file']\n"
                "    mime = magic.from_buffer(f.read(1024), mime=True)\n"
                "    f.seek(0)\n"
                "    if mime not in ALLOWED_TYPES:\n"
                "        return 'Invalid file type', 400\n"
                "    path = os.path.join('uploads', f.filename)\n"
                "    f.save(path)\n"
                "    return 'OK'\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "upload.py",
                "line": 15,
                "type": "path_traversal",
                "severity": "HIGH",
                "description": "f.filename not sanitized — path traversal via ../../../etc/cron.d/evil",
            },
        ],
        "safe_patterns": [
            "MIME type validation via python-magic",
            "Allowlist approach for file types",
        ],
    },
    {
        "project_files": {
            "export.py": (
                "import csv\nimport io\nfrom flask import Flask, request, Response\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/export')\n"
                "def export_data():\n"
                "    data = get_user_data(request.args.get('user_id'))\n"
                "    output = io.StringIO()\n"
                "    writer = csv.writer(output)\n"
                "    writer.writerow(['Name', 'Email', 'Phone'])\n"
                "    for row in data:\n"
                "        writer.writerow(row)\n"
                "    return Response(\n"
                "        output.getvalue(),\n"
                "        mimetype='text/csv',\n"
                "        headers={'Content-Disposition': f'attachment; filename={request.args.get(\"name\", \"export\")}.csv'}\n"
                "    )\n\n"
                "def get_user_data(user_id):\n"
                "    return []  # placeholder\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "export.py",
                "line": 9,
                "type": "broken_access_control",
                "severity": "HIGH",
                "description": "No authorization check — any user can export any other user's data via user_id parameter",
            },
            {
                "file": "export.py",
                "line": 18,
                "type": "header_injection",
                "severity": "MEDIUM",
                "description": "Unsanitized filename in Content-Disposition header allows response header injection",
            },
        ],
        "safe_patterns": [
            "csv.writer for CSV generation",
            "Content-Disposition header for download",
        ],
    },
    {
        "project_files": {
            "search.py": (
                "import re\nfrom flask import Flask, request\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/search')\n"
                "def search():\n"
                "    pattern = request.args.get('q', '')\n"
                "    try:\n"
                "        regex = re.compile(pattern)\n"
                "    except re.error:\n"
                "        return 'Invalid pattern', 400\n"
                "    results = [item for item in get_items() if regex.search(item)]\n"
                "    return str(results)\n\n"
                "def get_items():\n"
                "    return ['apple', 'banana', 'cherry']\n"
            ),
        },
        "vulnerabilities": [
            {
                "file": "search.py",
                "line": 10,
                "type": "redos",
                "severity": "HIGH",
                "description": "User-supplied regex compiled without timeout — ReDoS vulnerability (e.g., (a+)+$ on long input)",
            },
        ],
        "safe_patterns": [
            "re.error handling for invalid patterns",
            "List comprehension for filtering",
        ],
    },
]


def _build_all_tasks() -> List[Dict[str, Any]]:
    tasks = []
    for task in _EASY_TASKS:
        tasks.append({**task, "difficulty": "easy"})
    for task in _MEDIUM_TASKS:
        tasks.append({**task, "difficulty": "medium"})
    for task in _HARD_TASKS:
        tasks.append({**task, "difficulty": "hard"})
    return tasks


_ALL_TASKS = _build_all_tasks()


class SecurityScannerDataset(DatasetProvider):
    """30 vulnerable code projects for security auditing evaluation."""

    dataset_id = "security_scanner"
    dataset_name = "Security Scanner"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        tasks = list(_ALL_TASKS)
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(tasks)
        if max_samples is not None:
            tasks = tasks[:max_samples]

        self._records = []
        for i, task in enumerate(tasks):
            file_listing = ""
            for fname, content in task["project_files"].items():
                file_listing += f"### {fname}\n```python\n{content}```\n\n"

            prompt = _PROMPT_TEMPLATE.format(file_listing=file_listing)

            self._records.append(
                EvalRecord(
                    record_id=f"security-scanner-{i}",
                    problem=prompt,
                    reference="",
                    category="agentic",
                    subject=task["difficulty"],
                    metadata={
                        "project_files": task["project_files"],
                        "vulnerabilities": task["vulnerabilities"],
                        "safe_patterns": task["safe_patterns"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["SecurityScannerDataset"]
