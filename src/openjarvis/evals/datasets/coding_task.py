"""Coding task benchmark dataset.

Standalone function-level coding problems with test cases for evaluating
code generation accuracy.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """Write a Python function that solves the following problem. Return ONLY the function definition, no explanations.

{spec}

Function signature: {signature}

Examples:
{examples}"""

_TASKS = [
    {
        "spec": "Given a list of integers, return a new list containing only the elements that appear exactly once, in their original order.",
        "signature": "def unique_elements(lst: list[int]) -> list[int]",
        "examples": "unique_elements([1, 2, 3, 2, 1, 4]) -> [3, 4]\nunique_elements([1, 1, 1]) -> []\nunique_elements([5]) -> [5]",
        "test_cases": "assert unique_elements([1, 2, 3, 2, 1, 4]) == [3, 4]\nassert unique_elements([1, 1, 1]) == []\nassert unique_elements([5]) == [5]\nassert unique_elements([]) == []\nassert unique_elements([1, 2, 3]) == [1, 2, 3]",
        "reference": "def unique_elements(lst):\n    from collections import Counter\n    counts = Counter(lst)\n    return [x for x in lst if counts[x] == 1]",
    },
    {
        "spec": "Flatten a nested list of arbitrary depth into a single flat list.",
        "signature": "def flatten(nested: list) -> list",
        "examples": "flatten([1, [2, [3, 4], 5]]) -> [1, 2, 3, 4, 5]\nflatten([[1, 2], [3, [4]]]) -> [1, 2, 3, 4]\nflatten([]) -> []",
        "test_cases": "assert flatten([1, [2, [3, 4], 5]]) == [1, 2, 3, 4, 5]\nassert flatten([[1, 2], [3, [4]]]) == [1, 2, 3, 4]\nassert flatten([]) == []\nassert flatten([1, 2, 3]) == [1, 2, 3]\nassert flatten([[[1]]]) == [1]",
        "reference": "def flatten(nested):\n    result = []\n    for item in nested:\n        if isinstance(item, list):\n            result.extend(flatten(item))\n        else:\n            result.append(item)\n    return result",
    },
    {
        "spec": "Given a string, return the longest substring without repeating characters.",
        "signature": "def longest_unique_substring(s: str) -> str",
        "examples": 'longest_unique_substring("abcabcbb") -> "abc"\nlongest_unique_substring("bbbbb") -> "b"\nlongest_unique_substring("pwwkew") -> "wke"',
        "test_cases": 'assert longest_unique_substring("abcabcbb") == "abc"\nassert longest_unique_substring("bbbbb") == "b"\nassert longest_unique_substring("pwwkew") == "wke"\nassert longest_unique_substring("") == ""\nassert longest_unique_substring("abcdef") == "abcdef"',
        "reference": "def longest_unique_substring(s):\n    start = 0\n    best = ''\n    seen = {}\n    for i, c in enumerate(s):\n        if c in seen and seen[c] >= start:\n            start = seen[c] + 1\n        seen[c] = i\n        if i - start + 1 > len(best):\n            best = s[start:i+1]\n    return best",
    },
    {
        "spec": "Implement a function that converts a Roman numeral string to an integer.",
        "signature": "def roman_to_int(s: str) -> int",
        "examples": 'roman_to_int("III") -> 3\nroman_to_int("IV") -> 4\nroman_to_int("MCMXCIV") -> 1994',
        "test_cases": 'assert roman_to_int("III") == 3\nassert roman_to_int("IV") == 4\nassert roman_to_int("IX") == 9\nassert roman_to_int("MCMXCIV") == 1994\nassert roman_to_int("LVIII") == 58',
        "reference": "def roman_to_int(s):\n    vals = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}\n    total = 0\n    for i in range(len(s)):\n        if i+1 < len(s) and vals[s[i]] < vals[s[i+1]]:\n            total -= vals[s[i]]\n        else:\n            total += vals[s[i]]\n    return total",
    },
    {
        "spec": "Given a list of intervals [start, end], merge all overlapping intervals and return the result sorted by start time.",
        "signature": "def merge_intervals(intervals: list[list[int]]) -> list[list[int]]",
        "examples": "merge_intervals([[1,3],[2,6],[8,10],[15,18]]) -> [[1,6],[8,10],[15,18]]\nmerge_intervals([[1,4],[4,5]]) -> [[1,5]]",
        "test_cases": "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]\nassert merge_intervals([[1,4],[4,5]]) == [[1,5]]\nassert merge_intervals([[1,4],[0,4]]) == [[0,4]]\nassert merge_intervals([]) == []\nassert merge_intervals([[1,2]]) == [[1,2]]",
        "reference": "def merge_intervals(intervals):\n    if not intervals:\n        return []\n    intervals.sort()\n    merged = [intervals[0]]\n    for s, e in intervals[1:]:\n        if s <= merged[-1][1]:\n            merged[-1][1] = max(merged[-1][1], e)\n        else:\n            merged.append([s, e])\n    return merged",
    },
    {
        "spec": "Implement a function that checks if a string of brackets is balanced. Valid brackets are (), [], {}.",
        "signature": "def is_balanced(s: str) -> bool",
        "examples": 'is_balanced("()[]{}") -> True\nis_balanced("([)]") -> False\nis_balanced("{[]}") -> True',
        "test_cases": 'assert is_balanced("()[]{}") == True\nassert is_balanced("([)]") == False\nassert is_balanced("{[]}") == True\nassert is_balanced("") == True\nassert is_balanced("(") == False\nassert is_balanced("([{}])") == True',
        "reference": "def is_balanced(s):\n    stack = []\n    pairs = {')':'(', ']':'[', '}':'{'}\n    for c in s:\n        if c in '([{':\n            stack.append(c)\n        elif c in pairs:\n            if not stack or stack[-1] != pairs[c]:\n                return False\n            stack.pop()\n    return len(stack) == 0",
    },
    {
        "spec": "Given a matrix (list of lists), rotate it 90 degrees clockwise in-place and return it.",
        "signature": "def rotate_matrix(matrix: list[list[int]]) -> list[list[int]]",
        "examples": "rotate_matrix([[1,2,3],[4,5,6],[7,8,9]]) -> [[7,4,1],[8,5,2],[9,6,3]]",
        "test_cases": "assert rotate_matrix([[1,2,3],[4,5,6],[7,8,9]]) == [[7,4,1],[8,5,2],[9,6,3]]\nassert rotate_matrix([[1]]) == [[1]]\nassert rotate_matrix([[1,2],[3,4]]) == [[3,1],[4,2]]",
        "reference": "def rotate_matrix(matrix):\n    n = len(matrix)\n    for i in range(n):\n        for j in range(i, n):\n            matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]\n    for row in matrix:\n        row.reverse()\n    return matrix",
    },
    {
        "spec": "Implement a function that computes the nth Fibonacci number using memoization. F(0)=0, F(1)=1.",
        "signature": "def fibonacci(n: int) -> int",
        "examples": "fibonacci(0) -> 0\nfibonacci(1) -> 1\nfibonacci(10) -> 55\nfibonacci(20) -> 6765",
        "test_cases": "assert fibonacci(0) == 0\nassert fibonacci(1) == 1\nassert fibonacci(10) == 55\nassert fibonacci(20) == 6765\nassert fibonacci(30) == 832040",
        "reference": "def fibonacci(n, memo={}):\n    if n in memo:\n        return memo[n]\n    if n <= 1:\n        return n\n    memo[n] = fibonacci(n-1, memo) + fibonacci(n-2, memo)\n    return memo[n]",
    },
    {
        "spec": "Given a list of words, group them by anagrams. Return a list of groups, where each group is a sorted list of words.",
        "signature": "def group_anagrams(words: list[str]) -> list[list[str]]",
        "examples": 'group_anagrams(["eat","tea","tan","ate","nat","bat"]) -> [["ate","eat","tea"],["nat","tan"],["bat"]]',
        "test_cases": 'result = group_anagrams(["eat","tea","tan","ate","nat","bat"])\nresult = [sorted(g) for g in result]\nresult.sort()\nassert result == [["bat"], ["ate","eat","tea"], ["nat","tan"]] or result == [["ate","eat","tea"], ["bat"], ["nat","tan"]]\nassert group_anagrams([""]) == [[""]]\nassert group_anagrams(["a"]) == [["a"]]',
        "reference": "def group_anagrams(words):\n    from collections import defaultdict\n    groups = defaultdict(list)\n    for w in words:\n        key = ''.join(sorted(w))\n        groups[key].append(w)\n    return [sorted(g) for g in groups.values()]",
    },
    {
        "spec": "Implement binary search on a sorted list. Return the index of the target if found, otherwise return -1.",
        "signature": "def binary_search(arr: list[int], target: int) -> int",
        "examples": "binary_search([1, 3, 5, 7, 9], 5) -> 2\nbinary_search([1, 3, 5, 7, 9], 4) -> -1\nbinary_search([], 1) -> -1",
        "test_cases": "assert binary_search([1, 3, 5, 7, 9], 5) == 2\nassert binary_search([1, 3, 5, 7, 9], 4) == -1\nassert binary_search([], 1) == -1\nassert binary_search([1], 1) == 0\nassert binary_search([1, 3, 5, 7, 9], 1) == 0\nassert binary_search([1, 3, 5, 7, 9], 9) == 4",
        "reference": "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1",
    },
    {
        "spec": "Given a string containing digits, return all possible valid IP addresses that can be formed by inserting dots.",
        "signature": "def restore_ip_addresses(s: str) -> list[str]",
        "examples": 'restore_ip_addresses("25525511135") -> ["255.255.11.135","255.255.111.35"]\nrestore_ip_addresses("0000") -> ["0.0.0.0"]',
        "test_cases": 'assert sorted(restore_ip_addresses("25525511135")) == ["255.255.11.135","255.255.111.35"]\nassert restore_ip_addresses("0000") == ["0.0.0.0"]\nassert restore_ip_addresses("1111") == ["1.1.1.1"]\nassert restore_ip_addresses("010010") == ["0.10.0.10","0.100.1.0"]',
        "reference": "def restore_ip_addresses(s):\n    result = []\n    def bt(start, parts):\n        if len(parts) == 4:\n            if start == len(s):\n                result.append('.'.join(parts))\n            return\n        for end in range(start+1, min(start+4, len(s)+1)):\n            seg = s[start:end]\n            if (seg[0] == '0' and len(seg) > 1) or int(seg) > 255:\n                continue\n            bt(end, parts + [seg])\n    bt(0, [])\n    return result",
    },
    {
        "spec": "Implement a function that computes the longest common subsequence of two strings.",
        "signature": "def lcs(s1: str, s2: str) -> str",
        "examples": 'lcs("abcde", "ace") -> "ace"\nlcs("abc", "abc") -> "abc"\nlcs("abc", "def") -> ""',
        "test_cases": 'assert lcs("abcde", "ace") == "ace"\nassert lcs("abc", "abc") == "abc"\nassert lcs("abc", "def") == ""\nassert lcs("", "abc") == ""\nassert lcs("abcd", "abdc") in ("abc", "abd")',
        "reference": "def lcs(s1, s2):\n    m, n = len(s1), len(s2)\n    dp = [[''] * (n+1) for _ in range(m+1)]\n    for i in range(1, m+1):\n        for j in range(1, n+1):\n            if s1[i-1] == s2[j-1]:\n                dp[i][j] = dp[i-1][j-1] + s1[i-1]\n            else:\n                dp[i][j] = max(dp[i-1][j], dp[i][j-1], key=len)\n    return dp[m][n]",
    },
    {
        "spec": "Given a list of integers and a target sum, return all unique pairs that sum to the target. Each pair should be sorted, and the result should contain no duplicate pairs.",
        "signature": "def two_sum_pairs(nums: list[int], target: int) -> list[list[int]]",
        "examples": "two_sum_pairs([1, 2, 3, 4, 5], 6) -> [[1, 5], [2, 4]]\ntwo_sum_pairs([1, 1, 2, 3], 4) -> [[1, 3]]",
        "test_cases": "assert two_sum_pairs([1, 2, 3, 4, 5], 6) == [[1, 5], [2, 4]]\nassert two_sum_pairs([1, 1, 2, 3], 4) == [[1, 3]]\nassert two_sum_pairs([], 5) == []\nassert two_sum_pairs([3, 3], 6) == [[3, 3]]",
        "reference": "def two_sum_pairs(nums, target):\n    nums.sort()\n    result, seen = [], set()\n    lo, hi = 0, len(nums)-1\n    while lo < hi:\n        s = nums[lo] + nums[hi]\n        if s == target:\n            pair = (nums[lo], nums[hi])\n            if pair not in seen:\n                result.append(list(pair))\n                seen.add(pair)\n            lo += 1; hi -= 1\n        elif s < target:\n            lo += 1\n        else:\n            hi -= 1\n    return result",
    },
    {
        "spec": "Implement a function that converts an integer to its English words representation.",
        "signature": "def int_to_words(num: int) -> str",
        "examples": 'int_to_words(123) -> "One Hundred Twenty Three"\nint_to_words(0) -> "Zero"\nint_to_words(1000000) -> "One Million"',
        "test_cases": 'assert int_to_words(0) == "Zero"\nassert int_to_words(123) == "One Hundred Twenty Three"\nassert int_to_words(1000) == "One Thousand"\nassert int_to_words(1000000) == "One Million"\nassert int_to_words(15) == "Fifteen"',
        "reference": "def int_to_words(num):\n    if num == 0:\n        return 'Zero'\n    ones = ['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',\n            'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',\n            'Seventeen','Eighteen','Nineteen']\n    tens = ['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']\n    scales = ['','Thousand','Million','Billion']\n    def helper(n):\n        if n == 0: return []\n        if n < 20: return [ones[n]]\n        if n < 100: return [tens[n//10]] + helper(n%10)\n        return [ones[n//100], 'Hundred'] + helper(n%100)\n    parts, i = [], 0\n    while num > 0:\n        if num % 1000 != 0:\n            chunk = helper(num % 1000)\n            if scales[i]: chunk.append(scales[i])\n            parts = chunk + parts\n        num //= 1000; i += 1\n    return ' '.join(parts)",
    },
    {
        "spec": "Implement a function that finds the kth largest element in an unsorted list without fully sorting it.",
        "signature": "def kth_largest(nums: list[int], k: int) -> int",
        "examples": "kth_largest([3, 2, 1, 5, 6, 4], 2) -> 5\nkth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4) -> 4",
        "test_cases": "assert kth_largest([3, 2, 1, 5, 6, 4], 2) == 5\nassert kth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4) == 4\nassert kth_largest([1], 1) == 1\nassert kth_largest([7, 7, 7], 1) == 7",
        "reference": "def kth_largest(nums, k):\n    import heapq\n    return heapq.nlargest(k, nums)[-1]",
    },
    {
        "spec": "Given a string, determine if it is a valid palindrome considering only alphanumeric characters and ignoring case.",
        "signature": "def is_palindrome(s: str) -> bool",
        "examples": 'is_palindrome("A man, a plan, a canal: Panama") -> True\nis_palindrome("race a car") -> False\nis_palindrome("") -> True',
        "test_cases": 'assert is_palindrome("A man, a plan, a canal: Panama") == True\nassert is_palindrome("race a car") == False\nassert is_palindrome("") == True\nassert is_palindrome(" ") == True\nassert is_palindrome("ab") == False',
        "reference": "def is_palindrome(s):\n    cleaned = ''.join(c.lower() for c in s if c.isalnum())\n    return cleaned == cleaned[::-1]",
    },
    {
        "spec": "Implement a simple LRU cache with get and put operations. The cache has a fixed capacity.",
        "signature": "class LRUCache:\n    def __init__(self, capacity: int): ...\n    def get(self, key: int) -> int: ...\n    def put(self, key: int, value: int) -> None: ...",
        "examples": "cache = LRUCache(2)\ncache.put(1, 1)\ncache.put(2, 2)\ncache.get(1) -> 1\ncache.put(3, 3)  # evicts key 2\ncache.get(2) -> -1",
        "test_cases": "cache = LRUCache(2)\ncache.put(1, 1)\ncache.put(2, 2)\nassert cache.get(1) == 1\ncache.put(3, 3)\nassert cache.get(2) == -1\ncache.put(4, 4)\nassert cache.get(1) == -1\nassert cache.get(3) == 3\nassert cache.get(4) == 4",
        "reference": "from collections import OrderedDict\nclass LRUCache:\n    def __init__(self, capacity):\n        self.cap = capacity\n        self.cache = OrderedDict()\n    def get(self, key):\n        if key not in self.cache: return -1\n        self.cache.move_to_end(key)\n        return self.cache[key]\n    def put(self, key, value):\n        if key in self.cache:\n            self.cache.move_to_end(key)\n        self.cache[key] = value\n        if len(self.cache) > self.cap:\n            self.cache.popitem(last=False)",
    },
    {
        "spec": "Given a non-negative integer represented as a list of digits, add one to the number.",
        "signature": "def plus_one(digits: list[int]) -> list[int]",
        "examples": "plus_one([1, 2, 3]) -> [1, 2, 4]\nplus_one([9, 9, 9]) -> [1, 0, 0, 0]\nplus_one([0]) -> [1]",
        "test_cases": "assert plus_one([1, 2, 3]) == [1, 2, 4]\nassert plus_one([9, 9, 9]) == [1, 0, 0, 0]\nassert plus_one([0]) == [1]\nassert plus_one([9]) == [1, 0]\nassert plus_one([1, 0, 0]) == [1, 0, 1]",
        "reference": "def plus_one(digits):\n    for i in range(len(digits)-1, -1, -1):\n        if digits[i] < 9:\n            digits[i] += 1\n            return digits\n        digits[i] = 0\n    return [1] + digits",
    },
    {
        "spec": "Implement a function that finds the maximum profit from buying and selling a stock once. You can only buy before you sell.",
        "signature": "def max_profit(prices: list[int]) -> int",
        "examples": "max_profit([7, 1, 5, 3, 6, 4]) -> 5\nmax_profit([7, 6, 4, 3, 1]) -> 0",
        "test_cases": "assert max_profit([7, 1, 5, 3, 6, 4]) == 5\nassert max_profit([7, 6, 4, 3, 1]) == 0\nassert max_profit([1, 2]) == 1\nassert max_profit([2, 1]) == 0\nassert max_profit([]) == 0",
        "reference": "def max_profit(prices):\n    if not prices: return 0\n    min_price = prices[0]\n    profit = 0\n    for p in prices[1:]:\n        profit = max(profit, p - min_price)\n        min_price = min(min_price, p)\n    return profit",
    },
    {
        "spec": "Given a string, find all starting indices of substrings that are anagrams of a given pattern.",
        "signature": "def find_anagrams(s: str, p: str) -> list[int]",
        "examples": 'find_anagrams("cbaebabacd", "abc") -> [0, 6]\nfind_anagrams("abab", "ab") -> [0, 1, 2]',
        "test_cases": 'assert find_anagrams("cbaebabacd", "abc") == [0, 6]\nassert find_anagrams("abab", "ab") == [0, 1, 2]\nassert find_anagrams("", "a") == []\nassert find_anagrams("a", "ab") == []',
        "reference": "def find_anagrams(s, p):\n    from collections import Counter\n    if len(p) > len(s): return []\n    pc = Counter(p)\n    wc = Counter(s[:len(p)])\n    result = []\n    if wc == pc: result.append(0)\n    for i in range(len(p), len(s)):\n        wc[s[i]] += 1\n        old = s[i - len(p)]\n        wc[old] -= 1\n        if wc[old] == 0: del wc[old]\n        if wc == pc: result.append(i - len(p) + 1)\n    return result",
    },
    {
        "spec": "Implement a function that evaluates a mathematical expression given as a string containing +, -, *, / and parentheses. Assume valid input with integer operands.",
        "signature": "def evaluate(expression: str) -> float",
        "examples": 'evaluate("3+2*2") -> 7.0\nevaluate("(1+2)*3") -> 9.0\nevaluate("10/3") -> 3.333...',
        "test_cases": 'assert evaluate("3+2*2") == 7.0\nassert evaluate("(1+2)*3") == 9.0\nassert abs(evaluate("10/3") - 3.333333) < 0.01\nassert evaluate("2*(3+4)") == 14.0',
        "reference": "def evaluate(expression):\n    def helper(tokens, pos):\n        def parse_num():\n            nonlocal pos\n            if tokens[pos] == '(':\n                pos += 1\n                val = parse_expr()\n                pos += 1\n                return val\n            num = 0\n            while pos < len(tokens) and tokens[pos].isdigit():\n                num = num * 10 + int(tokens[pos])\n                pos += 1\n            return float(num)\n        def parse_term():\n            val = parse_num()\n            while pos < len(tokens) and tokens[pos] in '*/':\n                op = tokens[pos]\n                nonlocal pos\n                pos += 1\n                r = parse_num()\n                val = val * r if op == '*' else val / r\n            return val\n        def parse_expr():\n            val = parse_term()\n            while pos < len(tokens) and tokens[pos] in '+-':\n                op = tokens[pos]\n                nonlocal pos\n                pos += 1\n                r = parse_term()\n                val = val + r if op == '+' else val - r\n            return val\n        return parse_expr()\n    tokens = list(expression.replace(' ', ''))\n    return helper(tokens, 0)",
    },
    {
        "spec": "Implement a trie (prefix tree) with insert, search, and startsWith methods.",
        "signature": "class Trie:\n    def __init__(self): ...\n    def insert(self, word: str) -> None: ...\n    def search(self, word: str) -> bool: ...\n    def starts_with(self, prefix: str) -> bool: ...",
        "examples": 'trie = Trie()\ntrie.insert("apple")\ntrie.search("apple") -> True\ntrie.search("app") -> False\ntrie.starts_with("app") -> True',
        "test_cases": 'trie = Trie()\ntrie.insert("apple")\nassert trie.search("apple") == True\nassert trie.search("app") == False\nassert trie.starts_with("app") == True\ntrie.insert("app")\nassert trie.search("app") == True',
        "reference": "class Trie:\n    def __init__(self):\n        self.children = {}\n        self.is_end = False\n    def insert(self, word):\n        node = self\n        for c in word:\n            if c not in node.children:\n                node.children[c] = Trie()\n            node = node.children[c]\n        node.is_end = True\n    def search(self, word):\n        node = self\n        for c in word:\n            if c not in node.children: return False\n            node = node.children[c]\n        return node.is_end\n    def starts_with(self, prefix):\n        node = self\n        for c in prefix:\n            if c not in node.children: return False\n            node = node.children[c]\n        return True",
    },
    {
        "spec": "Given a 2D grid of '1's (land) and '0's (water), count the number of islands. An island is surrounded by water and formed by connecting adjacent lands horizontally or vertically.",
        "signature": "def count_islands(grid: list[list[str]]) -> int",
        "examples": 'count_islands([["1","1","0"],["1","1","0"],["0","0","1"]]) -> 2',
        "test_cases": 'assert count_islands([["1","1","0"],["1","1","0"],["0","0","1"]]) == 2\nassert count_islands([["0","0"],["0","0"]]) == 0\nassert count_islands([["1"]]) == 1\nassert count_islands([["1","0","1"],["0","1","0"],["1","0","1"]]) == 5',
        "reference": "def count_islands(grid):\n    if not grid: return 0\n    rows, cols = len(grid), len(grid[0])\n    count = 0\n    def dfs(r, c):\n        if r < 0 or r >= rows or c < 0 or c >= cols or grid[r][c] != '1': return\n        grid[r][c] = '#'\n        dfs(r+1,c); dfs(r-1,c); dfs(r,c+1); dfs(r,c-1)\n    for r in range(rows):\n        for c in range(cols):\n            if grid[r][c] == '1':\n                count += 1\n                dfs(r, c)\n    return count",
    },
    {
        "spec": "Implement a function that generates all valid combinations of n pairs of parentheses.",
        "signature": "def generate_parentheses(n: int) -> list[str]",
        "examples": 'generate_parentheses(1) -> ["()"]\ngenerate_parentheses(2) -> ["(())", "()()"]\ngenerate_parentheses(3) -> ["((()))", "(()())", "(())()", "()(())", "()()()"]',
        "test_cases": 'assert generate_parentheses(1) == ["()"]\nassert sorted(generate_parentheses(2)) == ["(())", "()()"]\nassert len(generate_parentheses(3)) == 5\nassert len(generate_parentheses(4)) == 14',
        "reference": "def generate_parentheses(n):\n    result = []\n    def bt(s, o, c):\n        if len(s) == 2*n:\n            result.append(s)\n            return\n        if o < n: bt(s+'(', o+1, c)\n        if c < o: bt(s+')', o, c+1)\n    bt('', 0, 0)\n    return result",
    },
    {
        "spec": "Given a list of non-negative integers representing elevation heights, compute how much water can be trapped after raining.",
        "signature": "def trap_water(heights: list[int]) -> int",
        "examples": "trap_water([0,1,0,2,1,0,1,3,2,1,2,1]) -> 6\ntrap_water([4,2,0,3,2,5]) -> 9",
        "test_cases": "assert trap_water([0,1,0,2,1,0,1,3,2,1,2,1]) == 6\nassert trap_water([4,2,0,3,2,5]) == 9\nassert trap_water([]) == 0\nassert trap_water([3]) == 0\nassert trap_water([3, 0, 3]) == 3",
        "reference": "def trap_water(heights):\n    if not heights: return 0\n    l, r = 0, len(heights)-1\n    lmax = rmax = water = 0\n    while l < r:\n        if heights[l] < heights[r]:\n            if heights[l] >= lmax: lmax = heights[l]\n            else: water += lmax - heights[l]\n            l += 1\n        else:\n            if heights[r] >= rmax: rmax = heights[r]\n            else: water += rmax - heights[r]\n            r -= 1\n    return water",
    },
    {
        "spec": "Implement a function that serializes and deserializes a binary tree. The tree node has val, left, right attributes.",
        "signature": "def serialize(root) -> str\ndef deserialize(data: str) -> TreeNode",
        "examples": "serialize a tree [1,2,3,null,null,4,5] -> some string\ndeserialize that string -> same tree",
        "test_cases": "class TreeNode:\n    def __init__(self, val=0, left=None, right=None):\n        self.val, self.left, self.right = val, left, right\nroot = TreeNode(1, TreeNode(2), TreeNode(3, TreeNode(4), TreeNode(5)))\ns = serialize(root)\nnew_root = deserialize(s)\nassert new_root.val == 1\nassert new_root.left.val == 2\nassert new_root.right.val == 3\nassert new_root.right.left.val == 4",
        "reference": "class TreeNode:\n    def __init__(self, val=0, left=None, right=None):\n        self.val, self.left, self.right = val, left, right\ndef serialize(root):\n    if not root: return 'null'\n    return f'{root.val},{serialize(root.left)},{serialize(root.right)}'\ndef deserialize(data):\n    vals = iter(data.split(','))\n    def build():\n        v = next(vals)\n        if v == 'null': return None\n        node = TreeNode(int(v))\n        node.left = build()\n        node.right = build()\n        return node\n    return build()",
    },
    {
        "spec": "Implement a function that converts a number from base 10 to any base (2-36). Use lowercase letters for digits > 9.",
        "signature": "def to_base(num: int, base: int) -> str",
        "examples": 'to_base(255, 16) -> "ff"\nto_base(10, 2) -> "1010"\nto_base(0, 5) -> "0"',
        "test_cases": 'assert to_base(255, 16) == "ff"\nassert to_base(10, 2) == "1010"\nassert to_base(0, 5) == "0"\nassert to_base(100, 10) == "100"\nassert to_base(35, 36) == "z"',
        "reference": "def to_base(num, base):\n    if num == 0: return '0'\n    digits = '0123456789abcdefghijklmnopqrstuvwxyz'\n    result = []\n    neg = num < 0\n    num = abs(num)\n    while num:\n        result.append(digits[num % base])\n        num //= base\n    if neg: result.append('-')\n    return ''.join(reversed(result))",
    },
    {
        "spec": "Given a string of words, reverse the order of words while preserving whitespace normalization (single spaces, no leading/trailing).",
        "signature": "def reverse_words(s: str) -> str",
        "examples": 'reverse_words("the sky is blue") -> "blue is sky the"\nreverse_words("  hello world  ") -> "world hello"',
        "test_cases": 'assert reverse_words("the sky is blue") == "blue is sky the"\nassert reverse_words("  hello world  ") == "world hello"\nassert reverse_words("a") == "a"\nassert reverse_words("  spaces  between  ") == "between spaces"',
        "reference": "def reverse_words(s):\n    return ' '.join(s.split()[::-1])",
    },
    {
        "spec": "Implement a function that computes the power set (all subsets) of a list of unique integers.",
        "signature": "def power_set(nums: list[int]) -> list[list[int]]",
        "examples": "power_set([1, 2, 3]) -> [[], [1], [2], [1,2], [3], [1,3], [2,3], [1,2,3]]",
        "test_cases": "result = power_set([1, 2, 3])\nassert len(result) == 8\nassert [] in result\nassert [1, 2, 3] in result\nassert power_set([]) == [[]]",
        "reference": "def power_set(nums):\n    result = [[]]\n    for num in nums:\n        result += [subset + [num] for subset in result]\n    return result",
    },
]


class CodingTaskDataset(DatasetProvider):
    """Coding task benchmark: function-level code generation with test cases."""

    dataset_id = "coding_task"
    dataset_name = "Coding Task"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = list(_TASKS)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, task in enumerate(rows):
            prompt = _PROMPT_TEMPLATE.format(
                spec=task["spec"],
                signature=task["signature"],
                examples=task["examples"],
            )
            self._records.append(
                EvalRecord(
                    record_id=f"coding-task-{idx}",
                    problem=prompt,
                    reference=task["reference"],
                    category="use-case",
                    subject="coding_task",
                    metadata={
                        "test_cases": task["test_cases"],
                        "signature": task["signature"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["CodingTaskDataset"]
