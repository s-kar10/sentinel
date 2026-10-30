"""Data-only evaluator subprocess. No target credentials, imports, or code input."""

import json
import re
import sys


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        # Linux supports this reliably; macOS address-space limits vary.
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
        task = json.loads(sys.stdin.buffer.read(1_100_000))
        if task["kind"] == "regex":
            flags = 0 if task["config"]["case_sensitive"] else re.IGNORECASE
            match = getattr(re, task["config"]["mode"])(
                task["config"]["pattern"], task["value"], flags=flags
            )
            result = {
                "passed": match is not None,
                "span": list(match.span()) if match else None,
            }
        else:
            from jsonschema import Draft202012Validator

            result = {
                "passed": Draft202012Validator(task["schema"]).is_valid(task["value"])
            }
        print(json.dumps(result))
    except Exception:
        # Never echo regex, schema, values, or exception messages.
        print('{"error":true}')


if __name__ == "__main__":
    main()
