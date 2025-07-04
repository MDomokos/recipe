import sys
import os
import json
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
import tempfile
import shutil
from datetime import datetime
from io import BytesIO
from PIL import Image
from bs4 import BeautifulSoup
from ebooklib import epub
import re
from recipe_scrapers import scrape_me
from recipe_scrapers._exceptions import WebsiteNotImplementedError

# ...existing RecipeExtractor and EpubGenerator classes (without PyQt6 dependencies)...

# CLI logic

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Recipe Extractor CLI Tool")
    parser.add_argument('urls', nargs='+', help='Recipe URLs to extract')
    parser.add_argument('--output', '-o', default='recipes.epub', help='Output EPUB file path')
    parser.add_argument('--title', default='Recipe Book', help='Title for the EPUB book')
    args = parser.parse_args()

    extractor = RecipeExtractor(args.urls)
    extractor.run()  # Direct call, not as a thread

    if not extractor.recipes:
        print("No recipes could be extracted.")
        sys.exit(1)

    # Categorize recipes (simple: all in one category)
    categorized = {'Recipes': extractor.recipes}
    generator = EpubGenerator(categorized, args.output, book_title=args.title)
    generator.generate_epub()  # Direct call, not as a thread
    print(f"EPUB generated: {args.output}")

if __name__ == "__main__":
    main()
