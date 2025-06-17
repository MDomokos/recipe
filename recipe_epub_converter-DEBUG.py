import sys
import os
import json
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
import tempfile
import shutil
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                            QWidget, QPushButton, QTextEdit, QLabel, QProgressBar,
                            QMessageBox, QFileDialog, QListWidget, QSplitter,
                            QListWidgetItem, QScrollArea, QFrame)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QPixmap

from bs4 import BeautifulSoup
from ebooklib import epub
import re

class RecipeExtractor(QThread):
    progress_updated = pyqtSignal(int)
    recipe_extracted = pyqtSignal(dict)
    extraction_complete = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls
        self.recipes = []

    def run(self):
        total_urls = len(self.urls)
        for i, url in enumerate(self.urls):
            try:
                recipe = self.extract_recipe(url.strip())
                if recipe:
                    self.recipes.append(recipe)
                    self.recipe_extracted.emit(recipe)
                self.progress_updated.emit(int((i + 1) / total_urls * 100))
            except Exception as e:
                self.error_occurred.emit(f"Error extracting from {url}: {str(e)}")
        
        self.extraction_complete.emit(self.recipes)

    def extract_recipe(self, url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Try to find JSON-LD structured data first
        json_scripts = soup.find_all('script', type='application/ld+json')
        recipe_data = None
        
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get('@type') == 'Recipe' or 'Recipe' in str(data.get('@type', '')):
                    recipe_data = data
                    break
            except:
                continue
        
        if recipe_data:
            return self.parse_structured_recipe(recipe_data, url)
        else:
            return self.parse_html_recipe(soup, url)

    def parse_structured_recipe(self, data, url):
        recipe = {
            'url': url,
            'title': data.get('name', 'Untitled Recipe'),
            'description': data.get('description', ''),
            'prep_time': self.extract_time(data.get('prepTime', '')),
            'cook_time': self.extract_time(data.get('cookTime', '')),
            'total_time': self.extract_time(data.get('totalTime', '')),
            'servings': data.get('recipeYield', ''),
            'ingredients': [],
            'instructions': [],
            'image_url': None
        }
        
        # Extract ingredients
        ingredients = data.get('recipeIngredient', [])
        if isinstance(ingredients, str):
            ingredients = [ingredients]
        recipe['ingredients'] = [ing.strip() for ing in ingredients if ing.strip()]
        
        # Extract instructions
        instructions = data.get('recipeInstructions', [])
        for inst in instructions:
            if isinstance(inst, dict):
                text = inst.get('text', '')
            else:
                text = str(inst)
            if text.strip():
                recipe['instructions'].append(text.strip())
        
        # Extract image
        image = data.get('image')
        if image:
            if isinstance(image, list) and image:
                image = image[0]
            if isinstance(image, dict):
                recipe['image_url'] = image.get('url')
            else:
                recipe['image_url'] = str(image)
        
        return recipe

    def parse_html_recipe(self, soup, url):
        recipe = {
            'url': url,
            'title': 'Untitled Recipe',
            'description': '',
            'prep_time': '',
            'cook_time': '',
            'total_time': '',
            'servings': '',
            'ingredients': [],
            'instructions': [],
            'image_url': None
        }
        
        # Try to find title
        title_selectors = ['h1', '.recipe-title', '.entry-title', 'title']
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                recipe['title'] = title_elem.get_text().strip()
                break
        
        # Try to find ingredients
        ingredient_selectors = [
            '.recipe-ingredient', '.ingredient', '[class*="ingredient"]',
            'li[itemprop="recipeIngredient"]', '.recipe-ingredients li'
        ]
        for selector in ingredient_selectors:
            ingredients = soup.select(selector)
            if ingredients:
                recipe['ingredients'] = [ing.get_text().strip() for ing in ingredients]
                break
        
        # Try to find instructions
        instruction_selectors = [
            '.recipe-instruction', '.instruction', '[class*="instruction"]',
            'li[itemprop="recipeInstructions"]', '.recipe-instructions li',
            '.recipe-directions li'
        ]
        for selector in instruction_selectors:
            instructions = soup.select(selector)
            if instructions:
                recipe['instructions'] = [inst.get_text().strip() for inst in instructions]
                break
        
        # Try to find image
        img_selectors = [
            '.recipe-image img', '.recipe-photo img', '[class*="recipe"] img',
            'img[itemprop="image"]'
        ]
        for selector in img_selectors:
            img = soup.select_one(selector)
            if img and img.get('src'):
                recipe['image_url'] = urljoin(url, img['src'])
                break
        
        return recipe

    def extract_time(self, time_str):
        if not time_str:
            return ''
        # Handle ISO 8601 duration format (PT30M)
        if time_str.startswith('PT'):
            match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?', time_str)
            if match:
                hours = int(match.group(1) or 0)
                minutes = int(match.group(2) or 0)
                if hours and minutes:
                    return f"{hours}h {minutes}m"
                elif hours:
                    return f"{hours}h"
                elif minutes:
                    return f"{minutes}m"
        return str(time_str)

class EpubGenerator(QThread):
    progress_updated = pyqtSignal(int)
    generation_complete = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, recipes, output_path):
        super().__init__()
        self.recipes = recipes
        self.output_path = output_path

    def run(self):
        try:
            self.generate_epub()
        except Exception as e:
            self.error_occurred.emit(f"Error generating EPUB: {str(e)}")

    def generate_epub(self):
        book = epub.EpubBook()
        book.set_identifier('recipe-collection')
        book.set_title('Recipe Collection')
        book.set_language('en')
        book.add_author('Recipe Collector')

        chapters = []
        spine = ['nav']
        
        # Create temporary directory for images
        temp_dir = tempfile.mkdtemp()
        
        try:
            total_recipes = len(self.recipes)
            for i, recipe in enumerate(self.recipes):
                chapter_content = self.create_chapter_content(recipe, temp_dir, book)
                
                # Create chapter
                chapter_id = f'chapter_{i}'
                chapter = epub.EpubHtml(
                    title=recipe['title'],
                    content=chapter_content,
                    file_name=f'{chapter_id}.xhtml'
                )
                
                book.add_item(chapter)
                chapters.append(chapter)
                spine.append(chapter)
                
                self.progress_updated.emit(int((i + 1) / total_recipes * 100))

            # Add CSS
            css = """
            body { font-family: Arial, sans-serif; margin: 20px; }
            h1 { color: #333; border-bottom: 2px solid #333; }
            h2 { color: #666; margin-top: 30px; }
            .recipe-meta { background: #f5f5f5; padding: 10px; margin: 10px 0; }
            .ingredients { background: #f9f9f9; padding: 15px; margin: 10px 0; }
            .instructions { margin: 20px 0; }
            .instruction { margin: 10px 0; padding: 10px; background: #fafafa; }
            img { max-width: 100%; height: auto; }
            """
            
            nav_css = epub.EpubItem(
                uid="nav_css",
                file_name="style/nav.css",
                media_type="text/css",
                content=css
            )
            book.add_item(nav_css)

            # Create table of contents
            book.toc = [(epub.Link(f'{chapter_id}.xhtml', recipe['title'], f'chapter_{i}')) 
                       for i, recipe in enumerate(self.recipes)]

            # Add navigation
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())

            book.spine = spine

            # Write EPUB
            epub.write_epub(self.output_path, book)
            self.generation_complete.emit(self.output_path)
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_chapter_content(self, recipe, temp_dir, book):
        content = f'<html><head><title>{recipe["title"]}</title></head><body>'
        content += f'<h1>{recipe["title"]}</h1>'
        
        if recipe.get('description'):
            content += f'<p><em>{recipe["description"]}</em></p>'
        
        # Add image if available
        if recipe.get('image_url'):
            try:
                img_response = requests.get(recipe['image_url'], timeout=10)
                if img_response.status_code == 200:
                    # Determine image extension
                    content_type = img_response.headers.get('content-type', '')
                    if 'jpeg' in content_type or 'jpg' in content_type:
                        ext = 'jpg'
                    elif 'png' in content_type:
                        ext = 'png'
                    elif 'gif' in content_type:
                        ext = 'gif'
                    else:
                        ext = 'jpg'  # default
                    
                    img_filename = f'recipe_image_{len(book.items)}.{ext}'
                    
                    # Add image to book
                    img_item = epub.EpubItem(
                        uid=f"img_{len(book.items)}",
                        file_name=f"images/{img_filename}",
                        media_type=f"image/{ext}",
                        content=img_response.content
                    )
                    book.add_item(img_item)
                    
                    content += f'<img src="images/{img_filename}" alt="{recipe["title"]}" style="max-width: 100%; height: auto;"/><br/><br/>'
            except:
                pass  # Skip image if download fails
        
        # Recipe metadata
        meta_items = []
        if recipe.get('prep_time'):
            meta_items.append(f"Prep: {recipe['prep_time']}")
        if recipe.get('cook_time'):
            meta_items.append(f"Cook: {recipe['cook_time']}")
        if recipe.get('total_time'):
            meta_items.append(f"Total: {recipe['total_time']}")
        if recipe.get('servings'):
            meta_items.append(f"Servings: {recipe['servings']}")
        
        if meta_items:
            content += '<div class="recipe-meta">' + ' | '.join(meta_items) + '</div>'
        
        # Ingredients
        if recipe.get('ingredients'):
            content += '<h2>Ingredients</h2><div class="ingredients"><ul>'
            for ingredient in recipe['ingredients']:
                content += f'<li>{ingredient}</li>'
            content += '</ul></div>'
        
        # Instructions
        if recipe.get('instructions'):
            content += '<h2>Instructions</h2><div class="instructions"><ol>'
            for i, instruction in enumerate(recipe['instructions'], 1):
                content += f'<li class="instruction">{instruction}</li>'
            content += '</ol></div>'
        
        content += f'<br/><p><small>Source: <a href="{recipe["url"]}">{recipe["url"]}</a></small></p>'
        content += '</body></html>'
        
        return content

class RecipeConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.recipes = []
        self.md_file_path = "recipe_links.md"
        self.init_ui()
        self.load_previous_links()

    def init_ui(self):
        self.setWindowTitle("Recipe to EPUB Converter")
        self.setGeometry(100, 100, 1000, 700)
        
        # Apply flat, outline-based styling
        self.setStyleSheet("""
            QMainWindow {
                background-color: #ffffff;
                color: #333333;
            }
            QPushButton {
                background-color: transparent;
                border: 2px solid #333333;
                color: #333333;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
            QPushButton:disabled {
                color: #999999;
                border-color: #cccccc;
            }
            QTextEdit {
                border: 2px solid #333333;
                background-color: #ffffff;
                padding: 5px;
                font-family: monospace;
            }
            QListWidget {
                border: 2px solid #333333;
                background-color: #ffffff;
                alternate-background-color: #f9f9f9;
            }
            QLabel {
                color: #333333;
                font-weight: bold;
            }
            QProgressBar {
                border: 2px solid #333333;
                background-color: #ffffff;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #333333;
            }
            QSplitter::handle {
                background-color: #333333;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Title
        title_label = QLabel("RECIPE TO EPUB CONVERTER")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # URL input
        left_layout.addWidget(QLabel("RECIPE URLS (one per line):"))
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste recipe URLs here, one per line...")
        self.url_input.setMaximumHeight(150)
        left_layout.addWidget(self.url_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.load_links_btn = QPushButton("LOAD PREVIOUS")
        self.load_links_btn.clicked.connect(self.load_previous_links)
        button_layout.addWidget(self.load_links_btn)
        
        self.extract_btn = QPushButton("EXTRACT RECIPES")
        self.extract_btn.clicked.connect(self.extract_recipes)
        button_layout.addWidget(self.extract_btn)
        
        self.generate_btn = QPushButton("GENERATE EPUB")
        self.generate_btn.clicked.connect(self.generate_epub)
        self.generate_btn.setEnabled(False)
        button_layout.addWidget(self.generate_btn)
        
        left_layout.addLayout(button_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready to extract recipes...")
        left_layout.addWidget(self.status_label)
        
        splitter.addWidget(left_panel)
        
        # Right panel - Recipe preview
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        right_layout.addWidget(QLabel("EXTRACTED RECIPES:"))
        self.recipe_list = QListWidget()
        right_layout.addWidget(self.recipe_list)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([400, 600])

    def load_previous_links(self):
        if os.path.exists(self.md_file_path):
            try:
                with open(self.md_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Extract URLs from markdown
                    urls = re.findall(r'- \[.*?\]\((.*?)\)', content)
                    if urls:
                        self.url_input.setText('\n'.join(urls))
                        self.status_label.setText(f"Loaded {len(urls)} URLs from previous session")
                    else:
                        self.status_label.setText("No URLs found in previous session")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load previous links: {str(e)}")

    def extract_recipes(self):
        urls = [url.strip() for url in self.url_input.toPlainText().split('\n') if url.strip()]
        
        if not urls:
            QMessageBox.warning(self, "Warning", "Please enter at least one recipe URL")
            return
        
        self.recipes = []
        self.recipe_list.clear()
        self.extract_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Extracting recipes...")
        
        self.extractor = RecipeExtractor(urls)
        self.extractor.progress_updated.connect(self.progress_bar.setValue)
        self.extractor.recipe_extracted.connect(self.add_recipe_to_list)
        self.extractor.extraction_complete.connect(self.extraction_finished)
        self.extractor.error_occurred.connect(self.show_error)
        self.extractor.start()

    def add_recipe_to_list(self, recipe):
        self.recipes.append(recipe)
        item = QListWidgetItem(f"{recipe['title']} ({len(recipe.get('ingredients', []))} ingredients)")
        self.recipe_list.addItem(item)

    def extraction_finished(self, recipes):
        self.extract_btn.setEnabled(True)
        if recipes:
            self.generate_btn.setEnabled(True)
            self.status_label.setText(f"Extracted {len(recipes)} recipes successfully")
            self.save_links_to_md()
        else:
            self.status_label.setText("No recipes could be extracted")

    def save_links_to_md(self):
        try:
            with open(self.md_file_path, 'w', encoding='utf-8') as f:
                f.write(f"# Recipe Links - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for recipe in self.recipes:
                    f.write(f"- [{recipe['title']}]({recipe['url']})\n")
            self.status_label.setText(f"Saved {len(self.recipes)} links to {self.md_file_path}")
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not save links: {str(e)}")

    def generate_epub(self):
        if not self.recipes:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save EPUB", "recipe_collection.epub", "EPUB files (*.epub)"
        )
        
        if not file_path:
            return
        
        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Generating EPUB...")
        
        self.generator = EpubGenerator(self.recipes, file_path)
        self.generator.progress_updated.connect(self.progress_bar.setValue)
        self.generator.generation_complete.connect(self.generation_finished)
        self.generator.error_occurred.connect(self.show_error)
        self.generator.start()

    def generation_finished(self, file_path):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"EPUB generated successfully: {file_path}")
        QMessageBox.information(self, "Success", f"EPUB file created successfully!\n\n{file_path}")

    def show_error(self, error_message):
        self.extract_btn.setEnabled(True)
        self.generate_btn.setEnabled(len(self.recipes) > 0)
        self.status_label.setText("Error occurred")
        QMessageBox.critical(self, "Error", error_message)

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for better cross-platform appearance
    
    window = RecipeConverter()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
