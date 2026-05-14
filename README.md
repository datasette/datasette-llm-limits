# datasette-llm-limits

[![PyPI](https://img.shields.io/pypi/v/datasette-llm-limits.svg)](https://pypi.org/project/datasette-llm-limits/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-llm-limits?include_prereleases&label=changelog)](https://github.com/datasette/datasette-llm-limits/releases)
[![Tests](https://github.com/datasette/datasette-llm-limits/actions/workflows/test.yml/badge.svg)](https://github.com/datasette/datasette-llm-limits/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-llm-limits/blob/main/LICENSE)

Plugin for configuring periodic limits on LLM usage in Datasette

## Installation

Install this plugin in the same environment as Datasette.
```bash
datasette install datasette-llm-limits
```
## Usage

Usage instructions go here.

## Development

To set up this plugin locally, first checkout the code. You can confirm it is available like this:
```bash
cd datasette-llm-limits
# Confirm the plugin is visible
uv run datasette plugins
```
To run the tests:
```bash
uv run pytest
```
