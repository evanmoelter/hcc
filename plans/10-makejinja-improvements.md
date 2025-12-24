# Plan: makejinja Improvements

## Overview

Update makejinja configuration and plugin to incorporate improvements from the template.

## Current State

Your `makejinja.toml`:
- Basic inputs/outputs configuration
- Custom delimiters
- Plugin with encrypt and nthhost filters

## Target State

Enhanced configuration with:
- `copy_metadata = true` for file timestamp preservation
- Improved plugin with more helper functions
- Better default value handling

## Implementation Steps

### Step 1: Update makejinja.toml

```toml
[makejinja]
inputs = ["./bootstrap/overrides", "./bootstrap/templates"]
output = "./"
exclude_patterns = [".mjfilter.py", "*.partial.yaml.j2"]
data = ["./config.yaml"]
import_paths = ["./bootstrap/scripts"]
loaders = ["plugin:Plugin"]
jinja_suffix = ".j2"
copy_metadata = true   # NEW: Preserve file timestamps
force = true
undefined = "chainable"

[makejinja.delimiter]
block_start = "#%"
block_end = "%#"
comment_start = "#|"
comment_end = "#|"
variable_start = "#{"
variable_end = "}#"
```

### Step 2: Update plugin.py

Add new helper functions to `bootstrap/scripts/plugin.py`:

```python
from pathlib import Path
from typing import Any
import ipaddress
import re
import makejinja

# Existing functions...

def basename(value: str) -> str:
    """Return the filename stem without extension."""
    return Path(value).stem

def nthhost(value: str, query: int) -> str:
    """Return the nth host in a CIDR range."""
    try:
        network = ipaddress.ip_network(value, strict=False)
        if 0 <= query < network.num_addresses:
            return str(network[query])
    except ValueError:
        pass
    return ""

def age_key(key_type: str, file_path: str = 'age.key') -> str:
    """Return the age public or private key from age.key."""
    try:
        with open(file_path, 'r') as file:
            content = file.read().strip()
        if key_type == 'public':
            match = re.search(r"# public key: (age1[\w]+)", content)
            if match:
                return match.group(1)
        elif key_type == 'private':
            match = re.search(r"(AGE-SECRET-KEY-[\w]+)", content)
            if match:
                return match.group(1)
    except FileNotFoundError:
        pass
    return ""

class Plugin(makejinja.plugin.Plugin):
    def __init__(self, data: dict[str, Any], config: makejinja.config.Config):
        self._data = data
        self._config = config
        # Set defaults
        self._data.setdefault('bootstrap_dns_servers', ['1.1.1.1', '1.0.0.1'])

    def filters(self) -> makejinja.plugin.Filters:
        return [basename, nthhost]

    def functions(self) -> makejinja.plugin.Functions:
        return [age_key]
```

## k3s Compatibility

✅ **Fully compatible** - Template rendering changes only.

## Benefits

- Preserved file timestamps help with git diffs
- More helper functions reduce template complexity
- Better default handling

## Estimated Effort

~30 minutes

