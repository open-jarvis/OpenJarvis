"""coding_assistant dataset — 30 buggy code projects for agent-based debugging.

Each task presents a bug report, buggy source code, and a test suite.
The agent must identify and fix the bug(s) so that all tests pass.

Difficulty tiers:
- easy (10): single-line bugs — off-by-one, wrong operator, missing return
- medium (10): multi-line logic bugs — incorrect algorithm, bad state management
- hard (10): subtle bugs — race conditions, edge cases, incorrect rounding
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a coding assistant. A user has reported a bug in their code.

## Bug Report
{bug_report}

## Source Code
```python
{buggy_code}
```

## Test Suite
```python
{test_code}
```

Fix the bug(s) in the source code so that ALL tests pass. Return the complete fixed source code inside a ```python code block."""  # noqa: E501

# ---------------------------------------------------------------------------
# EASY tasks (10): single-line bugs
# ---------------------------------------------------------------------------

_EASY_TASKS: List[Dict[str, Any]] = [
    {
        "bug_report": "The paginate function returns one fewer item than expected on the last page.",
        "buggy_code": (
            "def paginate(items, page, per_page):\n"
            "    start = page * per_page\n"
            "    end = start + per_page - 1\n"
            "    return items[start:end]\n"
        ),
        "fixed_code": (
            "def paginate(items, page, per_page):\n"
            "    start = page * per_page\n"
            "    end = start + per_page\n"
            "    return items[start:end]\n"
        ),
        "test_code": (
            "from solution import paginate\n\n"
            "def test_first_page():\n"
            "    assert paginate(list(range(10)), 0, 3) == [0, 1, 2]\n\n"
            "def test_second_page():\n"
            "    assert paginate(list(range(10)), 1, 3) == [3, 4, 5]\n\n"
            "def test_last_page():\n"
            "    assert paginate(list(range(10)), 3, 3) == [9]\n\n"
            "def test_empty_page():\n"
            "    assert paginate(list(range(10)), 5, 3) == []\n"
        ),
        "bugs": [
            {
                "description": "Off-by-one: end = start + per_page - 1 should be start + per_page",
                "file": "solution.py",
                "line": 3,
            }
        ],
        "originally_failing_tests": ["test_first_page", "test_second_page"],
        "originally_passing_tests": ["test_last_page", "test_empty_page"],
    },
    {
        "bug_report": "The is_palindrome function says 'racecar' is not a palindrome.",
        "buggy_code": (
            "def is_palindrome(s):\n"
            "    s = s.lower().strip()\n"
            "    return s == s[::-1] and len(s) > 1\n"
        ),
        "fixed_code": (
            "def is_palindrome(s):\n"
            "    s = s.lower().strip()\n"
            "    return s == s[::-1]\n"
        ),
        "test_code": (
            "from solution import is_palindrome\n\n"
            "def test_racecar():\n"
            "    assert is_palindrome('racecar') is True\n\n"
            "def test_hello():\n"
            "    assert is_palindrome('hello') is False\n\n"
            "def test_single_char():\n"
            "    assert is_palindrome('a') is True\n\n"
            "def test_empty():\n"
            "    assert is_palindrome('') is True\n"
        ),
        "bugs": [
            {
                "description": "Unnecessary len(s) > 1 check rejects single chars and empty strings",
                "file": "solution.py",
                "line": 3,
            }
        ],
        "originally_failing_tests": ["test_single_char", "test_empty"],
        "originally_passing_tests": ["test_racecar", "test_hello"],
    },
    {
        "bug_report": "The celsius_to_fahrenheit function returns wrong values.",
        "buggy_code": ("def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 23\n"),
        "fixed_code": ("def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n"),
        "test_code": (
            "from solution import celsius_to_fahrenheit\n\n"
            "def test_freezing():\n"
            "    assert celsius_to_fahrenheit(0) == 32\n\n"
            "def test_boiling():\n"
            "    assert celsius_to_fahrenheit(100) == 212\n\n"
            "def test_body_temp():\n"
            "    assert abs(celsius_to_fahrenheit(37) - 98.6) < 0.01\n"
        ),
        "bugs": [
            {
                "description": "Wrong constant: +23 should be +32",
                "file": "solution.py",
                "line": 2,
            }
        ],
        "originally_failing_tests": ["test_freezing", "test_boiling", "test_body_temp"],
        "originally_passing_tests": [],
    },
    {
        "bug_report": "The flatten function doesn't handle nested lists properly.",
        "buggy_code": (
            "def flatten(lst):\n"
            "    result = []\n"
            "    for item in lst:\n"
            "        if isinstance(item, list):\n"
            "            result.append(flatten(item))\n"
            "        else:\n"
            "            result.append(item)\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def flatten(lst):\n"
            "    result = []\n"
            "    for item in lst:\n"
            "        if isinstance(item, list):\n"
            "            result.extend(flatten(item))\n"
            "        else:\n"
            "            result.append(item)\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import flatten\n\n"
            "def test_nested():\n"
            "    assert flatten([1, [2, 3], [4, [5, 6]]]) == [1, 2, 3, 4, 5, 6]\n\n"
            "def test_flat():\n"
            "    assert flatten([1, 2, 3]) == [1, 2, 3]\n\n"
            "def test_empty():\n"
            "    assert flatten([]) == []\n\n"
            "def test_deeply_nested():\n"
            "    assert flatten([[[1]], [[2]], [[3]]]) == [1, 2, 3]\n"
        ),
        "bugs": [
            {
                "description": "append should be extend for recursive flattening",
                "file": "solution.py",
                "line": 5,
            }
        ],
        "originally_failing_tests": ["test_nested", "test_deeply_nested"],
        "originally_passing_tests": ["test_flat", "test_empty"],
    },
    {
        "bug_report": "The binary_search function never finds elements at the start of the list.",
        "buggy_code": (
            "def binary_search(arr, target):\n"
            "    lo, hi = 1, len(arr) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"
        ),
        "fixed_code": (
            "def binary_search(arr, target):\n"
            "    lo, hi = 0, len(arr) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"
        ),
        "test_code": (
            "from solution import binary_search\n\n"
            "def test_find_first():\n"
            "    assert binary_search([1, 3, 5, 7, 9], 1) == 0\n\n"
            "def test_find_middle():\n"
            "    assert binary_search([1, 3, 5, 7, 9], 5) == 2\n\n"
            "def test_find_last():\n"
            "    assert binary_search([1, 3, 5, 7, 9], 9) == 4\n\n"
            "def test_not_found():\n"
            "    assert binary_search([1, 3, 5, 7, 9], 4) == -1\n"
        ),
        "bugs": [
            {
                "description": "lo starts at 1 instead of 0, skipping first element",
                "file": "solution.py",
                "line": 2,
            }
        ],
        "originally_failing_tests": ["test_find_first"],
        "originally_passing_tests": [
            "test_find_middle",
            "test_find_last",
            "test_not_found",
        ],
    },
    {
        "bug_report": "The clamp function doesn't work when value equals min_val.",
        "buggy_code": (
            "def clamp(value, min_val, max_val):\n"
            "    if value < min_val:\n"
            "        return min_val\n"
            "    elif value > max_val:\n"
            "        return max_val\n"
            "    else:\n"
            "        return value\n"
        ),
        "fixed_code": (
            "def clamp(value, min_val, max_val):\n"
            "    if value < min_val:\n"
            "        return min_val\n"
            "    elif value > max_val:\n"
            "        return max_val\n"
            "    else:\n"
            "        return value\n"
        ),
        "test_code": (
            "from solution import clamp\n\n"
            "def test_below():\n"
            "    assert clamp(-5, 0, 10) == 0\n\n"
            "def test_above():\n"
            "    assert clamp(15, 0, 10) == 10\n\n"
            "def test_within():\n"
            "    assert clamp(5, 0, 10) == 5\n\n"
            "def test_at_min():\n"
            "    assert clamp(0, 0, 10) == 0\n\n"
            "def test_at_max():\n"
            "    assert clamp(10, 0, 10) == 10\n"
        ),
        "bugs": [
            {
                "description": "Actually no bug — this is a control task to test false positive rate",
                "file": "solution.py",
                "line": 0,
            }
        ],
        "originally_failing_tests": [],
        "originally_passing_tests": [
            "test_below",
            "test_above",
            "test_within",
            "test_at_min",
            "test_at_max",
        ],
    },
    {
        "bug_report": "The count_vowels function misses uppercase vowels.",
        "buggy_code": (
            "def count_vowels(text):\n"
            "    count = 0\n"
            "    for ch in text:\n"
            "        if ch in 'aeiou':\n"
            "            count += 1\n"
            "    return count\n"
        ),
        "fixed_code": (
            "def count_vowels(text):\n"
            "    count = 0\n"
            "    for ch in text.lower():\n"
            "        if ch in 'aeiou':\n"
            "            count += 1\n"
            "    return count\n"
        ),
        "test_code": (
            "from solution import count_vowels\n\n"
            "def test_lowercase():\n"
            "    assert count_vowels('hello') == 2\n\n"
            "def test_uppercase():\n"
            "    assert count_vowels('HELLO') == 2\n\n"
            "def test_mixed():\n"
            "    assert count_vowels('HeLLo WoRLd') == 3\n\n"
            "def test_empty():\n"
            "    assert count_vowels('') == 0\n"
        ),
        "bugs": [
            {
                "description": "Does not handle uppercase — should lowercase first",
                "file": "solution.py",
                "line": 3,
            }
        ],
        "originally_failing_tests": ["test_uppercase", "test_mixed"],
        "originally_passing_tests": ["test_lowercase", "test_empty"],
    },
    {
        "bug_report": "The max_profit function returns negative profit.",
        "buggy_code": (
            "def max_profit(prices):\n"
            "    if len(prices) < 2:\n"
            "        return 0\n"
            "    min_price = prices[0]\n"
            "    profit = 0\n"
            "    for price in prices:\n"
            "        profit = max(profit, min_price - price)\n"
            "        min_price = min(min_price, price)\n"
            "    return profit\n"
        ),
        "fixed_code": (
            "def max_profit(prices):\n"
            "    if len(prices) < 2:\n"
            "        return 0\n"
            "    min_price = prices[0]\n"
            "    profit = 0\n"
            "    for price in prices:\n"
            "        profit = max(profit, price - min_price)\n"
            "        min_price = min(min_price, price)\n"
            "    return profit\n"
        ),
        "test_code": (
            "from solution import max_profit\n\n"
            "def test_basic():\n"
            "    assert max_profit([7, 1, 5, 3, 6, 4]) == 5\n\n"
            "def test_declining():\n"
            "    assert max_profit([7, 6, 4, 3, 1]) == 0\n\n"
            "def test_single():\n"
            "    assert max_profit([5]) == 0\n\n"
            "def test_two_elements():\n"
            "    assert max_profit([1, 5]) == 4\n"
        ),
        "bugs": [
            {
                "description": "Subtraction order reversed: min_price - price should be price - min_price",
                "file": "solution.py",
                "line": 7,
            }
        ],
        "originally_failing_tests": ["test_basic", "test_two_elements"],
        "originally_passing_tests": ["test_declining", "test_single"],
    },
    {
        "bug_report": "The title_case function doesn't capitalize after hyphens.",
        "buggy_code": (
            "def title_case(s):\n"
            "    return ' '.join(w.capitalize() for w in s.split(' '))\n"
        ),
        "fixed_code": (
            "def title_case(s):\n"
            "    words = s.split(' ')\n"
            "    result = []\n"
            "    for w in words:\n"
            "        if '-' in w:\n"
            "            result.append('-'.join(p.capitalize() for p in w.split('-')))\n"
            "        else:\n"
            "            result.append(w.capitalize())\n"
            "    return ' '.join(result)\n"
        ),
        "test_code": (
            "from solution import title_case\n\n"
            "def test_simple():\n"
            "    assert title_case('hello world') == 'Hello World'\n\n"
            "def test_hyphenated():\n"
            "    assert title_case('well-known fact') == 'Well-Known Fact'\n\n"
            "def test_already_title():\n"
            "    assert title_case('Hello') == 'Hello'\n"
        ),
        "bugs": [
            {
                "description": "Does not handle hyphenated words",
                "file": "solution.py",
                "line": 2,
            }
        ],
        "originally_failing_tests": ["test_hyphenated"],
        "originally_passing_tests": ["test_simple", "test_already_title"],
    },
    {
        "bug_report": "The safe_divide function raises ZeroDivisionError instead of returning the default.",
        "buggy_code": (
            "def safe_divide(a, b, default=0):\n"
            "    try:\n"
            "        return a / b\n"
            "    except TypeError:\n"
            "        return default\n"
        ),
        "fixed_code": (
            "def safe_divide(a, b, default=0):\n"
            "    try:\n"
            "        return a / b\n"
            "    except (ZeroDivisionError, TypeError):\n"
            "        return default\n"
        ),
        "test_code": (
            "from solution import safe_divide\n\n"
            "def test_normal():\n"
            "    assert safe_divide(10, 2) == 5.0\n\n"
            "def test_zero_div():\n"
            "    assert safe_divide(10, 0) == 0\n\n"
            "def test_zero_div_custom():\n"
            "    assert safe_divide(10, 0, default=-1) == -1\n\n"
            "def test_type_error():\n"
            "    assert safe_divide(10, 'a') == 0\n"
        ),
        "bugs": [
            {
                "description": "Catches TypeError but not ZeroDivisionError",
                "file": "solution.py",
                "line": 4,
            }
        ],
        "originally_failing_tests": ["test_zero_div", "test_zero_div_custom"],
        "originally_passing_tests": ["test_normal", "test_type_error"],
    },
]

# ---------------------------------------------------------------------------
# MEDIUM tasks (10): multi-line logic bugs
# ---------------------------------------------------------------------------

_MEDIUM_TASKS: List[Dict[str, Any]] = [
    {
        "bug_report": "The LRU cache evicts the wrong item — it removes the most recently used instead of least recently used.",
        "buggy_code": (
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.capacity = capacity\n"
            "        self.cache = {}\n"
            "        self.order = []\n\n"
            "    def get(self, key):\n"
            "        if key in self.cache:\n"
            "            self.order.append(key)\n"
            "            return self.cache[key]\n"
            "        return -1\n\n"
            "    def put(self, key, value):\n"
            "        if key in self.cache:\n"
            "            self.order.append(key)\n"
            "        elif len(self.cache) >= self.capacity:\n"
            "            evict = self.order.pop()\n"
            "            del self.cache[evict]\n"
            "        self.cache[key] = value\n"
            "        self.order.append(key)\n"
        ),
        "fixed_code": (
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.capacity = capacity\n"
            "        self.cache = {}\n"
            "        self.order = []\n\n"
            "    def get(self, key):\n"
            "        if key in self.cache:\n"
            "            self.order.remove(key)\n"
            "            self.order.append(key)\n"
            "            return self.cache[key]\n"
            "        return -1\n\n"
            "    def put(self, key, value):\n"
            "        if key in self.cache:\n"
            "            self.order.remove(key)\n"
            "        elif len(self.cache) >= self.capacity:\n"
            "            evict = self.order.pop(0)\n"
            "            del self.cache[evict]\n"
            "        self.cache[key] = value\n"
            "        self.order.append(key)\n"
        ),
        "test_code": (
            "from solution import LRUCache\n\n"
            "def test_basic():\n"
            "    c = LRUCache(2)\n"
            "    c.put(1, 1)\n"
            "    c.put(2, 2)\n"
            "    assert c.get(1) == 1\n"
            "    c.put(3, 3)  # evicts key 2\n"
            "    assert c.get(2) == -1\n"
            "    assert c.get(3) == 3\n\n"
            "def test_update():\n"
            "    c = LRUCache(2)\n"
            "    c.put(1, 1)\n"
            "    c.put(2, 2)\n"
            "    c.put(1, 10)  # update, key 1 is now most recent\n"
            "    c.put(3, 3)  # evicts key 2\n"
            "    assert c.get(2) == -1\n"
            "    assert c.get(1) == 10\n"
        ),
        "bugs": [
            {
                "description": "order.pop() removes last (MRU) instead of order.pop(0) for LRU",
                "file": "solution.py",
                "line": 17,
            },
            {
                "description": "get/put don't remove old position before re-appending",
                "file": "solution.py",
                "line": 9,
            },
        ],
        "originally_failing_tests": ["test_basic", "test_update"],
        "originally_passing_tests": [],
    },
    {
        "bug_report": "The merge_sorted function produces duplicates when merging.",
        "buggy_code": (
            "def merge_sorted(a, b):\n"
            "    result = []\n"
            "    i = j = 0\n"
            "    while i < len(a) and j < len(b):\n"
            "        if a[i] <= b[j]:\n"
            "            result.append(a[i])\n"
            "            i += 1\n"
            "        else:\n"
            "            result.append(b[j])\n"
            "            j += 1\n"
            "    result.extend(a[i:])\n"
            "    result.extend(b[j:])\n"
            "    result.extend(a[i:])\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def merge_sorted(a, b):\n"
            "    result = []\n"
            "    i = j = 0\n"
            "    while i < len(a) and j < len(b):\n"
            "        if a[i] <= b[j]:\n"
            "            result.append(a[i])\n"
            "            i += 1\n"
            "        else:\n"
            "            result.append(b[j])\n"
            "            j += 1\n"
            "    result.extend(a[i:])\n"
            "    result.extend(b[j:])\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import merge_sorted\n\n"
            "def test_basic():\n"
            "    assert merge_sorted([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]\n\n"
            "def test_one_empty():\n"
            "    assert merge_sorted([], [1, 2]) == [1, 2]\n\n"
            "def test_both_empty():\n"
            "    assert merge_sorted([], []) == []\n\n"
            "def test_duplicates():\n"
            "    assert merge_sorted([1, 2], [2, 3]) == [1, 2, 2, 3]\n"
        ),
        "bugs": [
            {
                "description": "Duplicate result.extend(a[i:]) on line 13 causes extra elements",
                "file": "solution.py",
                "line": 13,
            }
        ],
        "originally_failing_tests": ["test_basic", "test_duplicates"],
        "originally_passing_tests": ["test_one_empty", "test_both_empty"],
    },
    {
        "bug_report": "The matrix_multiply function crashes on valid inputs.",
        "buggy_code": (
            "def matrix_multiply(a, b):\n"
            "    rows_a, cols_a = len(a), len(a[0])\n"
            "    rows_b, cols_b = len(b), len(b[0])\n"
            "    if cols_a != rows_b:\n"
            "        raise ValueError('Incompatible dimensions')\n"
            "    result = [[0] * cols_b for _ in range(rows_a)]\n"
            "    for i in range(rows_a):\n"
            "        for j in range(cols_b):\n"
            "            for k in range(cols_a):\n"
            "                result[i][j] += a[i][k] * b[j][k]\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def matrix_multiply(a, b):\n"
            "    rows_a, cols_a = len(a), len(a[0])\n"
            "    rows_b, cols_b = len(b), len(b[0])\n"
            "    if cols_a != rows_b:\n"
            "        raise ValueError('Incompatible dimensions')\n"
            "    result = [[0] * cols_b for _ in range(rows_a)]\n"
            "    for i in range(rows_a):\n"
            "        for j in range(cols_b):\n"
            "            for k in range(cols_a):\n"
            "                result[i][j] += a[i][k] * b[k][j]\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import matrix_multiply\n\n"
            "def test_identity():\n"
            "    a = [[1, 0], [0, 1]]\n"
            "    b = [[5, 6], [7, 8]]\n"
            "    assert matrix_multiply(a, b) == [[5, 6], [7, 8]]\n\n"
            "def test_basic():\n"
            "    a = [[1, 2], [3, 4]]\n"
            "    b = [[5, 6], [7, 8]]\n"
            "    assert matrix_multiply(a, b) == [[19, 22], [43, 50]]\n\n"
            "def test_non_square():\n"
            "    a = [[1, 2, 3]]\n"
            "    b = [[4], [5], [6]]\n"
            "    assert matrix_multiply(a, b) == [[32]]\n"
        ),
        "bugs": [
            {
                "description": "Wrong index: b[j][k] should be b[k][j]",
                "file": "solution.py",
                "line": 10,
            }
        ],
        "originally_failing_tests": ["test_basic", "test_non_square"],
        "originally_passing_tests": ["test_identity"],
    },
    {
        "bug_report": "The run_length_encode function produces incorrect counts for repeated characters.",
        "buggy_code": (
            "def run_length_encode(s):\n"
            "    if not s:\n"
            "        return ''\n"
            "    result = []\n"
            "    count = 1\n"
            "    for i in range(1, len(s)):\n"
            "        if s[i] == s[i - 1]:\n"
            "            count += 1\n"
            "        else:\n"
            "            result.append(f'{s[i]}{count}')\n"
            "            count = 1\n"
            "    result.append(f'{s[-1]}{count}')\n"
            "    return ''.join(result)\n"
        ),
        "fixed_code": (
            "def run_length_encode(s):\n"
            "    if not s:\n"
            "        return ''\n"
            "    result = []\n"
            "    count = 1\n"
            "    for i in range(1, len(s)):\n"
            "        if s[i] == s[i - 1]:\n"
            "            count += 1\n"
            "        else:\n"
            "            result.append(f'{s[i - 1]}{count}')\n"
            "            count = 1\n"
            "    result.append(f'{s[-1]}{count}')\n"
            "    return ''.join(result)\n"
        ),
        "test_code": (
            "from solution import run_length_encode\n\n"
            "def test_basic():\n"
            "    assert run_length_encode('aaabbc') == 'a3b2c1'\n\n"
            "def test_single():\n"
            "    assert run_length_encode('a') == 'a1'\n\n"
            "def test_empty():\n"
            "    assert run_length_encode('') == ''\n\n"
            "def test_no_repeats():\n"
            "    assert run_length_encode('abc') == 'a1b1c1'\n"
        ),
        "bugs": [
            {
                "description": "In else branch, appends s[i] (next char) instead of s[i-1] (current char)",
                "file": "solution.py",
                "line": 10,
            }
        ],
        "originally_failing_tests": ["test_basic", "test_no_repeats"],
        "originally_passing_tests": ["test_single", "test_empty"],
    },
    {
        "bug_report": "The validate_brackets function doesn't properly handle mismatched closing brackets.",
        "buggy_code": (
            "def validate_brackets(s):\n"
            "    stack = []\n"
            "    pairs = {')': '(', ']': '[', '}': '{'}\n"
            "    for ch in s:\n"
            "        if ch in '([{':\n"
            "            stack.append(ch)\n"
            "        elif ch in ')]}' :\n"
            "            if not stack:\n"
            "                return False\n"
            "            stack.pop()\n"
            "    return len(stack) == 0\n"
        ),
        "fixed_code": (
            "def validate_brackets(s):\n"
            "    stack = []\n"
            "    pairs = {')': '(', ']': '[', '}': '{'}\n"
            "    for ch in s:\n"
            "        if ch in '([{':\n"
            "            stack.append(ch)\n"
            "        elif ch in ')]}':\n"
            "            if not stack or stack[-1] != pairs[ch]:\n"
            "                return False\n"
            "            stack.pop()\n"
            "    return len(stack) == 0\n"
        ),
        "test_code": (
            "from solution import validate_brackets\n\n"
            "def test_valid():\n"
            "    assert validate_brackets('([]){}') is True\n\n"
            "def test_mismatched():\n"
            "    assert validate_brackets('([)]') is False\n\n"
            "def test_unclosed():\n"
            "    assert validate_brackets('((') is False\n\n"
            "def test_empty():\n"
            "    assert validate_brackets('') is True\n\n"
            "def test_extra_close():\n"
            "    assert validate_brackets(')') is False\n"
        ),
        "bugs": [
            {
                "description": "Does not check that closing bracket matches the top of stack",
                "file": "solution.py",
                "line": 10,
            }
        ],
        "originally_failing_tests": ["test_mismatched"],
        "originally_passing_tests": [
            "test_valid",
            "test_unclosed",
            "test_empty",
            "test_extra_close",
        ],
    },
    {
        "bug_report": "The group_by function loses entries when multiple items have the same key.",
        "buggy_code": (
            "def group_by(items, key_fn):\n"
            "    groups = {}\n"
            "    for item in items:\n"
            "        k = key_fn(item)\n"
            "        groups[k] = [item]\n"
            "    return groups\n"
        ),
        "fixed_code": (
            "def group_by(items, key_fn):\n"
            "    groups = {}\n"
            "    for item in items:\n"
            "        k = key_fn(item)\n"
            "        groups.setdefault(k, []).append(item)\n"
            "    return groups\n"
        ),
        "test_code": (
            "from solution import group_by\n\n"
            "def test_basic():\n"
            "    result = group_by([1, 2, 3, 4, 5, 6], lambda x: x % 2)\n"
            "    assert result == {1: [1, 3, 5], 0: [2, 4, 6]}\n\n"
            "def test_strings():\n"
            "    result = group_by(['apple', 'banana', 'avocado'], lambda x: x[0])\n"
            "    assert result == {'a': ['apple', 'avocado'], 'b': ['banana']}\n\n"
            "def test_empty():\n"
            "    assert group_by([], lambda x: x) == {}\n"
        ),
        "bugs": [
            {
                "description": "Overwrites group with [item] instead of appending to list",
                "file": "solution.py",
                "line": 5,
            }
        ],
        "originally_failing_tests": ["test_basic", "test_strings"],
        "originally_passing_tests": ["test_empty"],
    },
    {
        "bug_report": "The moving_average function returns incorrect values and wrong number of results.",
        "buggy_code": (
            "def moving_average(data, window):\n"
            "    if window <= 0 or window > len(data):\n"
            "        return []\n"
            "    result = []\n"
            "    for i in range(len(data) - window):\n"
            "        avg = sum(data[i:i + window]) / window\n"
            "        result.append(round(avg, 2))\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def moving_average(data, window):\n"
            "    if window <= 0 or window > len(data):\n"
            "        return []\n"
            "    result = []\n"
            "    for i in range(len(data) - window + 1):\n"
            "        avg = sum(data[i:i + window]) / window\n"
            "        result.append(round(avg, 2))\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import moving_average\n\n"
            "def test_basic():\n"
            "    assert moving_average([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]\n\n"
            "def test_window_equals_length():\n"
            "    assert moving_average([1, 2, 3], 3) == [2.0]\n\n"
            "def test_window_one():\n"
            "    assert moving_average([1, 2, 3], 1) == [1.0, 2.0, 3.0]\n\n"
            "def test_window_too_large():\n"
            "    assert moving_average([1], 5) == []\n"
        ),
        "bugs": [
            {
                "description": "Off-by-one in range: should be len(data) - window + 1",
                "file": "solution.py",
                "line": 5,
            }
        ],
        "originally_failing_tests": [
            "test_basic",
            "test_window_equals_length",
            "test_window_one",
        ],
        "originally_passing_tests": ["test_window_too_large"],
    },
    {
        "bug_report": "The Trie insert works but search always returns False.",
        "buggy_code": (
            "class TrieNode:\n"
            "    def __init__(self):\n"
            "        self.children = {}\n"
            "        self.is_end = False\n\n"
            "class Trie:\n"
            "    def __init__(self):\n"
            "        self.root = TrieNode()\n\n"
            "    def insert(self, word):\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            if ch not in node.children:\n"
            "                node.children[ch] = TrieNode()\n"
            "            node = node.children[ch]\n"
            "        node.is_end = True\n\n"
            "    def search(self, word):\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            if ch not in node.children:\n"
            "                return False\n"
            "            node = node.children[ch]\n"
            "        return False\n"
        ),
        "fixed_code": (
            "class TrieNode:\n"
            "    def __init__(self):\n"
            "        self.children = {}\n"
            "        self.is_end = False\n\n"
            "class Trie:\n"
            "    def __init__(self):\n"
            "        self.root = TrieNode()\n\n"
            "    def insert(self, word):\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            if ch not in node.children:\n"
            "                node.children[ch] = TrieNode()\n"
            "            node = node.children[ch]\n"
            "        node.is_end = True\n\n"
            "    def search(self, word):\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            if ch not in node.children:\n"
            "                return False\n"
            "            node = node.children[ch]\n"
            "        return node.is_end\n"
        ),
        "test_code": (
            "from solution import Trie\n\n"
            "def test_insert_search():\n"
            "    t = Trie()\n"
            "    t.insert('apple')\n"
            "    assert t.search('apple') is True\n\n"
            "def test_search_missing():\n"
            "    t = Trie()\n"
            "    t.insert('apple')\n"
            "    assert t.search('app') is False\n\n"
            "def test_search_not_inserted():\n"
            "    t = Trie()\n"
            "    assert t.search('hello') is False\n"
        ),
        "bugs": [
            {
                "description": "search returns False instead of node.is_end",
                "file": "solution.py",
                "line": 24,
            }
        ],
        "originally_failing_tests": ["test_insert_search"],
        "originally_passing_tests": ["test_search_missing", "test_search_not_inserted"],
    },
    {
        "bug_report": "The deep_merge function doesn't recursively merge nested dicts.",
        "buggy_code": (
            "def deep_merge(base, override):\n"
            "    result = base.copy()\n"
            "    for key, value in override.items():\n"
            "        result[key] = value\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def deep_merge(base, override):\n"
            "    result = base.copy()\n"
            "    for key, value in override.items():\n"
            "        if key in result and isinstance(result[key], dict) and isinstance(value, dict):\n"
            "            result[key] = deep_merge(result[key], value)\n"
            "        else:\n"
            "            result[key] = value\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import deep_merge\n\n"
            "def test_flat():\n"
            "    assert deep_merge({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}\n\n"
            "def test_override():\n"
            "    assert deep_merge({'a': 1}, {'a': 2}) == {'a': 2}\n\n"
            "def test_nested():\n"
            "    base = {'db': {'host': 'localhost', 'port': 5432}}\n"
            "    over = {'db': {'port': 3306}}\n"
            "    expected = {'db': {'host': 'localhost', 'port': 3306}}\n"
            "    assert deep_merge(base, over) == expected\n\n"
            "def test_deeply_nested():\n"
            "    base = {'a': {'b': {'c': 1, 'd': 2}}}\n"
            "    over = {'a': {'b': {'c': 3}}}\n"
            "    expected = {'a': {'b': {'c': 3, 'd': 2}}}\n"
            "    assert deep_merge(base, over) == expected\n"
        ),
        "bugs": [
            {
                "description": "Shallow merge: overwrites nested dicts instead of recursively merging",
                "file": "solution.py",
                "line": 4,
            }
        ],
        "originally_failing_tests": ["test_nested", "test_deeply_nested"],
        "originally_passing_tests": ["test_flat", "test_override"],
    },
    {
        "bug_report": "The debounce function fires on every call instead of waiting.",
        "buggy_code": (
            "import time\n\n"
            "def debounce(func, wait_seconds):\n"
            "    last_call = [0]\n"
            "    last_result = [None]\n\n"
            "    def wrapper(*args, **kwargs):\n"
            "        now = time.time()\n"
            "        last_result[0] = func(*args, **kwargs)\n"
            "        last_call[0] = now\n"
            "        return last_result[0]\n\n"
            "    return wrapper\n"
        ),
        "fixed_code": (
            "import time\n\n"
            "def debounce(func, wait_seconds):\n"
            "    last_call = [0]\n"
            "    last_result = [None]\n\n"
            "    def wrapper(*args, **kwargs):\n"
            "        now = time.time()\n"
            "        if now - last_call[0] >= wait_seconds:\n"
            "            last_result[0] = func(*args, **kwargs)\n"
            "            last_call[0] = now\n"
            "        return last_result[0]\n\n"
            "    return wrapper\n"
        ),
        "test_code": (
            "import time\nfrom solution import debounce\n\n"
            "def test_debounce_fires_first():\n"
            "    calls = []\n"
            "    @debounce\n"
            "    def fn(x):\n"
            "        calls.append(x)\n"
            "        return x\n"
            "    fn(1)  # should fire\n"
            "    assert len(calls) == 1\n\n"
            "def test_debounce_suppresses():\n"
            "    calls = []\n"
            "    def fn(x):\n"
            "        calls.append(x)\n"
            "        return x\n"
            "    debounced = debounce(fn, 0.1)\n"
            "    debounced(1)  # fires\n"
            "    debounced(2)  # suppressed\n"
            "    assert len(calls) == 1\n\n"
            "def test_debounce_fires_after_wait():\n"
            "    calls = []\n"
            "    def fn(x):\n"
            "        calls.append(x)\n"
            "        return x\n"
            "    debounced = debounce(fn, 0.05)\n"
            "    debounced(1)  # fires\n"
            "    time.sleep(0.1)\n"
            "    debounced(2)  # fires after wait\n"
            "    assert len(calls) == 2\n"
        ),
        "bugs": [
            {
                "description": "Missing time check: calls func every time instead of only after wait_seconds",
                "file": "solution.py",
                "line": 9,
            }
        ],
        "originally_failing_tests": ["test_debounce_suppresses"],
        "originally_passing_tests": [
            "test_debounce_fires_first",
            "test_debounce_fires_after_wait",
        ],
    },
]

# ---------------------------------------------------------------------------
# HARD tasks (10): subtle bugs
# ---------------------------------------------------------------------------

_HARD_TASKS: List[Dict[str, Any]] = [
    {
        "bug_report": "The financial_round function has rounding errors for currency calculations.",
        "buggy_code": (
            "def financial_round(amount, tax_rate, discount_pct):\n"
            "    subtotal = amount * (1 + tax_rate)\n"
            "    discount = subtotal * discount_pct\n"
            "    total = subtotal - discount\n"
            "    return round(total, 2)\n"
        ),
        "fixed_code": (
            "from decimal import Decimal, ROUND_HALF_UP\n\n"
            "def financial_round(amount, tax_rate, discount_pct):\n"
            "    amount = Decimal(str(amount))\n"
            "    tax_rate = Decimal(str(tax_rate))\n"
            "    discount_pct = Decimal(str(discount_pct))\n"
            "    subtotal = amount * (1 + tax_rate)\n"
            "    discount = subtotal * discount_pct\n"
            "    total = subtotal - discount\n"
            "    return float(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))\n"
        ),
        "test_code": (
            "from solution import financial_round\n\n"
            "def test_basic():\n"
            "    assert financial_round(100, 0.08, 0.10) == 97.20\n\n"
            "def test_precision():\n"
            "    # This exposes float arithmetic issues\n"
            "    assert financial_round(33.33, 0.0725, 0.05) == 33.94\n\n"
            "def test_no_discount():\n"
            "    assert financial_round(10.00, 0.10, 0.0) == 11.00\n\n"
            "def test_rounding_boundary():\n"
            "    # 19.99 * 1.0875 * 0.95 = 20.6496...\n"
            "    assert financial_round(19.99, 0.0875, 0.05) == 20.65\n"
        ),
        "bugs": [
            {
                "description": "Float arithmetic causes precision errors — should use Decimal",
                "file": "solution.py",
                "line": 2,
            }
        ],
        "originally_failing_tests": ["test_precision", "test_rounding_boundary"],
        "originally_passing_tests": ["test_basic", "test_no_discount"],
    },
    {
        "bug_report": "The csv_parser doesn't handle quoted fields with commas inside.",
        "buggy_code": ("def parse_csv_line(line):\n    return line.split(',')\n"),
        "fixed_code": (
            "import csv\nimport io\n\n"
            "def parse_csv_line(line):\n"
            "    reader = csv.reader(io.StringIO(line))\n"
            "    return next(reader)\n"
        ),
        "test_code": (
            "from solution import parse_csv_line\n\n"
            "def test_simple():\n"
            "    assert parse_csv_line('a,b,c') == ['a', 'b', 'c']\n\n"
            "def test_quoted_comma():\n"
            "    assert parse_csv_line('a,\"b,c\",d') == ['a', 'b,c', 'd']\n\n"
            "def test_quoted_with_spaces():\n"
            "    assert parse_csv_line('\"hello world\",test') == ['hello world', 'test']\n\n"
            "def test_empty_fields():\n"
            "    assert parse_csv_line('a,,c') == ['a', '', 'c']\n"
        ),
        "bugs": [
            {
                "description": "Naive split(',') doesn't handle quoted fields",
                "file": "solution.py",
                "line": 2,
            }
        ],
        "originally_failing_tests": ["test_quoted_comma"],
        "originally_passing_tests": ["test_simple", "test_empty_fields"],
    },
    {
        "bug_report": "The retry decorator retries on success instead of only on failure.",
        "buggy_code": (
            "import time\n\n"
            "def retry(max_attempts=3, delay=0.1):\n"
            "    def decorator(func):\n"
            "        def wrapper(*args, **kwargs):\n"
            "            for attempt in range(max_attempts):\n"
            "                try:\n"
            "                    result = func(*args, **kwargs)\n"
            "                    time.sleep(delay)\n"
            "                except Exception:\n"
            "                    if attempt == max_attempts - 1:\n"
            "                        raise\n"
            "                    time.sleep(delay)\n"
            "            return result\n"
            "        return wrapper\n"
            "    return decorator\n"
        ),
        "fixed_code": (
            "import time\n\n"
            "def retry(max_attempts=3, delay=0.1):\n"
            "    def decorator(func):\n"
            "        def wrapper(*args, **kwargs):\n"
            "            for attempt in range(max_attempts):\n"
            "                try:\n"
            "                    return func(*args, **kwargs)\n"
            "                except Exception:\n"
            "                    if attempt == max_attempts - 1:\n"
            "                        raise\n"
            "                    time.sleep(delay)\n"
            "        return wrapper\n"
            "    return decorator\n"
        ),
        "test_code": (
            "from solution import retry\n\n"
            "def test_succeeds_first_try():\n"
            "    calls = []\n"
            "    @retry(max_attempts=3, delay=0)\n"
            "    def fn():\n"
            "        calls.append(1)\n"
            "        return 'ok'\n"
            "    assert fn() == 'ok'\n"
            "    assert len(calls) == 1\n\n"
            "def test_succeeds_after_retry():\n"
            "    calls = []\n"
            "    @retry(max_attempts=3, delay=0)\n"
            "    def fn():\n"
            "        calls.append(1)\n"
            "        if len(calls) < 2:\n"
            "            raise ValueError('fail')\n"
            "        return 'ok'\n"
            "    assert fn() == 'ok'\n"
            "    assert len(calls) == 2\n\n"
            "def test_exhausts_retries():\n"
            "    @retry(max_attempts=2, delay=0)\n"
            "    def fn():\n"
            "        raise RuntimeError('always fails')\n"
            "    try:\n"
            "        fn()\n"
            "        assert False, 'should have raised'\n"
            "    except RuntimeError:\n"
            "        pass\n"
        ),
        "bugs": [
            {
                "description": "Success path doesn't return immediately and sleeps unnecessarily; runs all attempts",
                "file": "solution.py",
                "line": 8,
            }
        ],
        "originally_failing_tests": ["test_succeeds_first_try"],
        "originally_passing_tests": ["test_exhausts_retries"],
    },
    {
        "bug_report": "The URL parser doesn't extract query parameters correctly.",
        "buggy_code": (
            "def parse_url_params(url):\n"
            "    if '?' not in url:\n"
            "        return {}\n"
            "    query = url.split('?')[1]\n"
            "    params = {}\n"
            "    for pair in query.split('&'):\n"
            "        key, value = pair.split('=')\n"
            "        params[key] = value\n"
            "    return params\n"
        ),
        "fixed_code": (
            "from urllib.parse import urlparse, parse_qs\n\n"
            "def parse_url_params(url):\n"
            "    parsed = urlparse(url)\n"
            "    params = parse_qs(parsed.query)\n"
            "    return {k: v[0] if len(v) == 1 else v for k, v in params.items()}\n"
        ),
        "test_code": (
            "from solution import parse_url_params\n\n"
            "def test_basic():\n"
            "    assert parse_url_params('http://example.com?a=1&b=2') == {'a': '1', 'b': '2'}\n\n"
            "def test_no_params():\n"
            "    assert parse_url_params('http://example.com') == {}\n\n"
            "def test_encoded_value():\n"
            "    result = parse_url_params('http://example.com?q=hello+world')\n"
            "    assert result['q'] == 'hello world'\n\n"
            "def test_value_with_equals():\n"
            "    result = parse_url_params('http://example.com?data=a=b')\n"
            "    assert result['data'] == 'a=b'\n"
        ),
        "bugs": [
            {
                "description": "split('=') breaks on values containing '='; doesn't decode URL encoding",
                "file": "solution.py",
                "line": 7,
            }
        ],
        "originally_failing_tests": ["test_encoded_value", "test_value_with_equals"],
        "originally_passing_tests": ["test_basic", "test_no_params"],
    },
    {
        "bug_report": "The rate_limiter allows too many requests in the time window.",
        "buggy_code": (
            "import time\n\n"
            "class RateLimiter:\n"
            "    def __init__(self, max_requests, window_seconds):\n"
            "        self.max_requests = max_requests\n"
            "        self.window = window_seconds\n"
            "        self.requests = []\n\n"
            "    def allow(self):\n"
            "        now = time.time()\n"
            "        self.requests.append(now)\n"
            "        return len(self.requests) <= self.max_requests\n"
        ),
        "fixed_code": (
            "import time\n\n"
            "class RateLimiter:\n"
            "    def __init__(self, max_requests, window_seconds):\n"
            "        self.max_requests = max_requests\n"
            "        self.window = window_seconds\n"
            "        self.requests = []\n\n"
            "    def allow(self):\n"
            "        now = time.time()\n"
            "        cutoff = now - self.window\n"
            "        self.requests = [t for t in self.requests if t > cutoff]\n"
            "        if len(self.requests) < self.max_requests:\n"
            "            self.requests.append(now)\n"
            "            return True\n"
            "        return False\n"
        ),
        "test_code": (
            "import time\nfrom solution import RateLimiter\n\n"
            "def test_allows_within_limit():\n"
            "    rl = RateLimiter(3, 1.0)\n"
            "    assert rl.allow() is True\n"
            "    assert rl.allow() is True\n"
            "    assert rl.allow() is True\n\n"
            "def test_blocks_over_limit():\n"
            "    rl = RateLimiter(2, 1.0)\n"
            "    assert rl.allow() is True\n"
            "    assert rl.allow() is True\n"
            "    assert rl.allow() is False\n\n"
            "def test_allows_after_window():\n"
            "    rl = RateLimiter(1, 0.05)\n"
            "    assert rl.allow() is True\n"
            "    assert rl.allow() is False\n"
            "    time.sleep(0.1)\n"
            "    assert rl.allow() is True\n"
        ),
        "bugs": [
            {
                "description": "Never removes old requests; always appends even when over limit",
                "file": "solution.py",
                "line": 10,
            }
        ],
        "originally_failing_tests": [
            "test_blocks_over_limit",
            "test_allows_after_window",
        ],
        "originally_passing_tests": ["test_allows_within_limit"],
    },
    {
        "bug_report": "The memoize decorator doesn't work with keyword arguments.",
        "buggy_code": (
            "def memoize(func):\n"
            "    cache = {}\n"
            "    def wrapper(*args):\n"
            "        if args not in cache:\n"
            "            cache[args] = func(*args)\n"
            "        return cache[args]\n"
            "    return wrapper\n"
        ),
        "fixed_code": (
            "def memoize(func):\n"
            "    cache = {}\n"
            "    def wrapper(*args, **kwargs):\n"
            "        key = (args, tuple(sorted(kwargs.items())))\n"
            "        if key not in cache:\n"
            "            cache[key] = func(*args, **kwargs)\n"
            "        return cache[key]\n"
            "    return wrapper\n"
        ),
        "test_code": (
            "from solution import memoize\n\n"
            "def test_positional():\n"
            "    calls = []\n"
            "    @memoize\n"
            "    def add(a, b):\n"
            "        calls.append((a, b))\n"
            "        return a + b\n"
            "    assert add(1, 2) == 3\n"
            "    assert add(1, 2) == 3\n"
            "    assert len(calls) == 1\n\n"
            "def test_kwargs():\n"
            "    calls = []\n"
            "    @memoize\n"
            "    def greet(name, greeting='hello'):\n"
            "        calls.append(1)\n"
            "        return f'{greeting} {name}'\n"
            "    assert greet(name='Alice', greeting='hi') == 'hi Alice'\n"
            "    assert greet(name='Alice', greeting='hi') == 'hi Alice'\n"
            "    assert len(calls) == 1\n\n"
            "def test_different_kwargs():\n"
            "    calls = []\n"
            "    @memoize\n"
            "    def greet(name, greeting='hello'):\n"
            "        calls.append(1)\n"
            "        return f'{greeting} {name}'\n"
            "    greet(name='Alice', greeting='hi')\n"
            "    greet(name='Alice', greeting='hey')\n"
            "    assert len(calls) == 2\n"
        ),
        "bugs": [
            {
                "description": "Wrapper doesn't accept or cache kwargs",
                "file": "solution.py",
                "line": 3,
            }
        ],
        "originally_failing_tests": ["test_kwargs", "test_different_kwargs"],
        "originally_passing_tests": ["test_positional"],
    },
    {
        "bug_report": "The event_emitter on() method doesn't support multiple listeners for the same event.",
        "buggy_code": (
            "class EventEmitter:\n"
            "    def __init__(self):\n"
            "        self._listeners = {}\n\n"
            "    def on(self, event, callback):\n"
            "        self._listeners[event] = callback\n\n"
            "    def emit(self, event, *args):\n"
            "        if event in self._listeners:\n"
            "            self._listeners[event](*args)\n"
        ),
        "fixed_code": (
            "class EventEmitter:\n"
            "    def __init__(self):\n"
            "        self._listeners = {}\n\n"
            "    def on(self, event, callback):\n"
            "        self._listeners.setdefault(event, []).append(callback)\n\n"
            "    def emit(self, event, *args):\n"
            "        for cb in self._listeners.get(event, []):\n"
            "            cb(*args)\n"
        ),
        "test_code": (
            "from solution import EventEmitter\n\n"
            "def test_single_listener():\n"
            "    ee = EventEmitter()\n"
            "    results = []\n"
            "    ee.on('data', lambda x: results.append(x))\n"
            "    ee.emit('data', 42)\n"
            "    assert results == [42]\n\n"
            "def test_multiple_listeners():\n"
            "    ee = EventEmitter()\n"
            "    r1, r2 = [], []\n"
            "    ee.on('data', lambda x: r1.append(x))\n"
            "    ee.on('data', lambda x: r2.append(x))\n"
            "    ee.emit('data', 'hello')\n"
            "    assert r1 == ['hello']\n"
            "    assert r2 == ['hello']\n\n"
            "def test_no_listeners():\n"
            "    ee = EventEmitter()\n"
            "    ee.emit('missing')  # should not raise\n"
        ),
        "bugs": [
            {
                "description": "on() overwrites listener instead of appending to list",
                "file": "solution.py",
                "line": 6,
            }
        ],
        "originally_failing_tests": ["test_multiple_listeners"],
        "originally_passing_tests": ["test_single_listener", "test_no_listeners"],
    },
    {
        "bug_report": "The json_flatten function doesn't handle arrays or nested objects with dots in keys.",
        "buggy_code": (
            "def json_flatten(obj, prefix=''):\n"
            "    result = {}\n"
            "    for key, value in obj.items():\n"
            "        new_key = f'{prefix}.{key}' if prefix else key\n"
            "        if isinstance(value, dict):\n"
            "            result.update(json_flatten(value, new_key))\n"
            "        else:\n"
            "            result[new_key] = value\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def json_flatten(obj, prefix=''):\n"
            "    result = {}\n"
            "    if isinstance(obj, dict):\n"
            "        for key, value in obj.items():\n"
            "            new_key = f'{prefix}.{key}' if prefix else key\n"
            "            result.update(json_flatten(value, new_key))\n"
            "    elif isinstance(obj, list):\n"
            "        for i, value in enumerate(obj):\n"
            "            new_key = f'{prefix}[{i}]'\n"
            "            result.update(json_flatten(value, new_key))\n"
            "    else:\n"
            "        result[prefix] = obj\n"
            "    return result\n"
        ),
        "test_code": (
            "from solution import json_flatten\n\n"
            "def test_flat():\n"
            "    assert json_flatten({'a': 1, 'b': 2}) == {'a': 1, 'b': 2}\n\n"
            "def test_nested():\n"
            "    assert json_flatten({'a': {'b': 1}}) == {'a.b': 1}\n\n"
            "def test_with_array():\n"
            "    result = json_flatten({'items': [1, 2, 3]})\n"
            "    assert result == {'items[0]': 1, 'items[1]': 2, 'items[2]': 3}\n\n"
            "def test_deeply_nested():\n"
            "    obj = {'a': {'b': {'c': [1, 2]}}}\n"
            "    result = json_flatten(obj)\n"
            "    assert result == {'a.b.c[0]': 1, 'a.b.c[1]': 2}\n"
        ),
        "bugs": [
            {
                "description": "Does not handle list values, only dicts",
                "file": "solution.py",
                "line": 5,
            }
        ],
        "originally_failing_tests": ["test_with_array", "test_deeply_nested"],
        "originally_passing_tests": ["test_flat", "test_nested"],
    },
    {
        "bug_report": "The async_gather helper doesn't propagate exceptions from individual tasks.",
        "buggy_code": (
            "import asyncio\n\n"
            "async def gather_with_errors(*coros):\n"
            "    results = []\n"
            "    for coro in coros:\n"
            "        try:\n"
            "            result = await coro\n"
            "            results.append(('ok', result))\n"
            "        except Exception:\n"
            "            pass  # silently swallow\n"
            "    return results\n"
        ),
        "fixed_code": (
            "import asyncio\n\n"
            "async def gather_with_errors(*coros):\n"
            "    results = []\n"
            "    for coro in coros:\n"
            "        try:\n"
            "            result = await coro\n"
            "            results.append(('ok', result))\n"
            "        except Exception as exc:\n"
            "            results.append(('error', exc))\n"
            "    return results\n"
        ),
        "test_code": (
            "import asyncio\nfrom solution import gather_with_errors\n\n"
            "def test_all_succeed():\n"
            "    async def ok():\n"
            "        return 42\n"
            "    results = asyncio.run(gather_with_errors(ok(), ok()))\n"
            "    assert len(results) == 2\n"
            "    assert all(r[0] == 'ok' for r in results)\n\n"
            "def test_one_fails():\n"
            "    async def ok():\n"
            "        return 1\n"
            "    async def fail():\n"
            "        raise ValueError('boom')\n"
            "    results = asyncio.run(gather_with_errors(ok(), fail(), ok()))\n"
            "    assert len(results) == 3\n"
            "    assert results[0] == ('ok', 1)\n"
            "    assert results[1][0] == 'error'\n"
            "    assert results[2] == ('ok', 1)\n\n"
            "def test_all_fail():\n"
            "    async def fail():\n"
            "        raise RuntimeError('x')\n"
            "    results = asyncio.run(gather_with_errors(fail(), fail()))\n"
            "    assert len(results) == 2\n"
            "    assert all(r[0] == 'error' for r in results)\n"
        ),
        "bugs": [
            {
                "description": "Silently swallows exceptions instead of recording them",
                "file": "solution.py",
                "line": 9,
            }
        ],
        "originally_failing_tests": ["test_one_fails", "test_all_fail"],
        "originally_passing_tests": ["test_all_succeed"],
    },
    {
        "bug_report": "The topological_sort function enters an infinite loop on cyclic graphs.",
        "buggy_code": (
            "def topological_sort(graph):\n"
            "    visited = set()\n"
            "    result = []\n\n"
            "    def dfs(node):\n"
            "        if node in visited:\n"
            "            return\n"
            "        visited.add(node)\n"
            "        for neighbor in graph.get(node, []):\n"
            "            dfs(neighbor)\n"
            "        result.append(node)\n\n"
            "    for node in graph:\n"
            "        dfs(node)\n"
            "    result.reverse()\n"
            "    return result\n"
        ),
        "fixed_code": (
            "def topological_sort(graph):\n"
            "    visited = set()\n"
            "    in_stack = set()\n"
            "    result = []\n\n"
            "    def dfs(node):\n"
            "        if node in in_stack:\n"
            "            raise ValueError(f'Cycle detected at {node}')\n"
            "        if node in visited:\n"
            "            return\n"
            "        in_stack.add(node)\n"
            "        visited.add(node)\n"
            "        for neighbor in graph.get(node, []):\n"
            "            dfs(neighbor)\n"
            "        in_stack.remove(node)\n"
            "        result.append(node)\n\n"
            "    for node in graph:\n"
            "        dfs(node)\n"
            "    result.reverse()\n"
            "    return result\n"
        ),
        "test_code": (
            "import pytest\nfrom solution import topological_sort\n\n"
            "def test_linear():\n"
            "    graph = {'a': ['b'], 'b': ['c'], 'c': []}\n"
            "    assert topological_sort(graph) == ['a', 'b', 'c']\n\n"
            "def test_diamond():\n"
            "    graph = {'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': []}\n"
            "    result = topological_sort(graph)\n"
            "    assert result.index('a') < result.index('b')\n"
            "    assert result.index('a') < result.index('c')\n"
            "    assert result.index('b') < result.index('d')\n\n"
            "def test_cycle_detection():\n"
            "    graph = {'a': ['b'], 'b': ['c'], 'c': ['a']}\n"
            "    with pytest.raises(ValueError, match='Cycle'):\n"
            "        topological_sort(graph)\n"
        ),
        "bugs": [
            {
                "description": "No cycle detection — infinite recursion on cyclic graphs",
                "file": "solution.py",
                "line": 5,
            }
        ],
        "originally_failing_tests": ["test_cycle_detection"],
        "originally_passing_tests": ["test_linear", "test_diamond"],
    },
]


def _build_all_tasks() -> List[Dict[str, Any]]:
    """Combine all difficulty tiers with assigned difficulty labels."""
    tasks = []
    for task in _EASY_TASKS:
        tasks.append({**task, "difficulty": "easy"})
    for task in _MEDIUM_TASKS:
        tasks.append({**task, "difficulty": "medium"})
    for task in _HARD_TASKS:
        tasks.append({**task, "difficulty": "hard"})
    return tasks


_ALL_TASKS = _build_all_tasks()


class CodingAssistantDataset(DatasetProvider):
    """30 buggy code projects for agent-based debugging evaluation."""

    dataset_id = "coding_assistant"
    dataset_name = "Coding Assistant"

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
            prompt = _PROMPT_TEMPLATE.format(
                bug_report=task["bug_report"],
                buggy_code=task["buggy_code"],
                test_code=task["test_code"],
            )
            self._records.append(
                EvalRecord(
                    record_id=f"coding-assistant-{i}",
                    problem=prompt,
                    reference=task.get("fixed_code", ""),
                    category="agentic",
                    subject=task["difficulty"],
                    metadata={
                        "bug_report": task["bug_report"],
                        "buggy_code": task["buggy_code"],
                        "test_code": task["test_code"],
                        "bugs": task["bugs"],
                        "originally_failing_tests": task["originally_failing_tests"],
                        "originally_passing_tests": task["originally_passing_tests"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["CodingAssistantDataset"]
