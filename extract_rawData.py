#!/usr/bin/env python3
"""
Extract the top-level `rawData` JSON object from HTML/JS input.
Usage:
  # read from stdin
  cat page.html | python3 extract_rawData.py > rawData.json
  # or pass a filename
  python3 extract_rawData.py page.html > rawData.json

The script locates the first occurrence of `var rawData` and then finds the first `{`
that follows and scans forward counting braces until the matching closing `}` for
that object. It then prints the JSON. If the JSON parses, it pretty-prints it.
"""
import sys
import json


def extract_rawdata_from_string(s: str) -> str | None:
    key = 'var rawData'
    idx = s.find(key)
    if idx == -1:
        return None
    # find first '{' after the key
    brace_start = s.find('{', idx)
    if brace_start == -1:
        return None
    i = brace_start
    depth = 0
    in_string = False
    escape = False
    while i < len(s):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return s[brace_start:i+1]
        i += 1
    return None


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            s = f.read()
    else:
        s = sys.stdin.read()

    jtext = extract_rawdata_from_string(s)
    if not jtext:
        sys.exit(2)

    # Try to parse and pretty-print; fall back to raw text if parse fails
    try:
        obj = json.loads(jtext)
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    except Exception:
        # Parsing failed, print raw capture so user can inspect
        print(jtext)


if __name__ == '__main__':
    main()
