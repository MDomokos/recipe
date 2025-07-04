# Recipe Extraction Test Tool

This tool helps test and debug recipe extraction from various websites. It provides detailed diagnostics about the extraction process and can help identify why certain recipes aren't being extracted correctly.

## Directory Structure

```
TestExtraction/
  ├── logs/              # Log files for each test run
  ├── results/           # JSON results from test runs
  └── test_extraction.py # Main test script
```

## Usage

You can run the script in two ways:

1. Test URLs from recipe_links.md in the parent directory:
```bash
cd TestExtraction
python test_extraction.py
```

2. Test specific URLs directly:
```bash
cd TestExtraction
python test_extraction.py https://example.com/recipe1 https://example.com/recipe2
```

## Output

The script generates:
1. Console output with real-time progress and summaries
2. Detailed log file in `logs/recipe_extraction_YYYYMMDD_HHMMSS.log`
3. Full results in `results/extraction_results_YYYYMMDD_HHMMSS.json`

## Rate Limiting

The script includes measures to handle rate limiting:
- 10-second delay between requests
- Browser-like headers
- Rate limit detection and reporting

If you're getting rate limited frequently:
1. Increase the delay between requests
2. Use a VPN or proxy
3. Test fewer URLs at a time
