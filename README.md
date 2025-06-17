# Recipe EPUB Converter

A powerful tool that converts recipes from websites into beautiful, organized EPUB recipe books that you can read on your e-reader device.

## Features

- Extract recipes from supported recipe websites
- Convert recipes into EPUB format for e-readers
- User-friendly GUI interface built with PyQt6
- Supports multiple recipes in a single EPUB book
- Includes recipe images, ingredients, and instructions
- Automatic retry mechanism for reliable extraction
- Progress tracking for batch processing
- Error handling and reporting

## Requirements (Not required for .exe)

- Python 3.x
- PyQt6
- Beautiful Soup 4
- ebooklib
- recipe-scrapers
- Pillow (PIL)
- requests

## Installation (Not required for .exe)

1. Clone this repository:
```bash
git clone [repository-url]
```

2. Install the required dependencies:
```bash
pip install PyQt6 beautifulsoup4 ebooklib recipe-scrapers Pillow requests
```

## Usage

1. Run the RecipeConverter.exe

or

1. Run the main converter:
```bash
python recipe_epub_converter.py
```

2. Enter recipe URLs in the interface
3. Click "Extract Recipes" to begin the process
4. Once extraction is complete, save your recipe book as an EPUB file
5. Transfer the EPUB file to your e-reader
6. Profit 💸💸💸

## Testing

For testing recipe extraction, use the included test tool in the TestExtraction directory:

```bash
cd TestExtraction
python test_extraction.py
```

Test results and logs will be saved in the `TestExtraction/results` and `TestExtraction/logs` directories respectively.

## Troubleshooting

If a recipe fails to extract:
1. Check if the website is supported by recipe-scrapers
2. Verify your internet connection
3. Check the logs for detailed error messages
4. Try using the test tool for debugging

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

[Insert license here]
