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

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                            QWidget, QPushButton, QTextEdit, QLabel, QProgressBar,
                            QMessageBox, QFileDialog, QListWidget, QSplitter,
                            QListWidgetItem, QScrollArea, QFrame, QLineEdit, QStyle, 
                            QStyledItemDelegate, QInputDialog, QSizePolicy, QDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QModelIndex
from PyQt6.QtGui import QFont, QPixmap, QIcon

from bs4 import BeautifulSoup
from ebooklib import epub
import re
from recipe_scrapers import scrape_me
from recipe_scrapers._exceptions import WebsiteNotImplementedError

class RecipeExtractor(QThread):
    progress_updated = pyqtSignal(int)
    recipe_extracted = pyqtSignal(dict)
    extraction_complete = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    status_updated = pyqtSignal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls
        self.recipes = []

    def run(self):
        total_urls = len(self.urls)
        processed_urls = []
        retry_delay = 3  # Initial delay between retries in seconds
        max_retries = 2  # Maximum number of retries per URL
        
        for i, url in enumerate(self.urls):
            url = url.strip()
            if not url or url in processed_urls:
                continue
                
            retries = 0
            while retries <= max_retries:
                try:
                    self.status_updated.emit(f"Processing recipe {i+1} of {total_urls} (attempt {retries + 1})...")
                    recipe = self.extract_recipe(url)
                    if recipe and recipe.get('ingredients') and recipe.get('instructions'):
                        self.recipes.append(recipe)
                        self.recipe_extracted.emit(recipe)
                        processed_urls.append(url)
                        # Add delay before next URL to avoid rate limiting
                        if i < total_urls - 1:  # If not the last URL
                            import time
                            time.sleep(3)  # 3 second delay between successful extractions
                        break  # Success, exit retry loop
                    else:
                        if retries < max_retries:
                            self.status_updated.emit(f"Retrying {url} in {retry_delay} seconds...")
                            import time
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            retries += 1
                        else:
                            self.error_occurred.emit(f"Couldn't extract complete recipe from {url} after {max_retries + 1} attempts")
                            break
                except Exception as e:
                    if retries < max_retries:
                        self.status_updated.emit(f"Error occurred, retrying {url} in {retry_delay} seconds...")
                        import time
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        retries += 1
                    else:
                        self.error_occurred.emit(f"Error extracting from {url} after {max_retries + 1} attempts: {str(e)}")
                        break
            
            self.progress_updated.emit(int((i + 1) / total_urls * 100))
        
        if self.recipes:
            self.status_updated.emit(f"Successfully extracted {len(self.recipes)} recipes")
        else:
            self.status_updated.emit("No recipes could be extracted")
        
        self.extraction_complete.emit(self.recipes)

    def extract_recipe(self, url):
        print(f"\nAttempting to extract recipe from: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Referer': 'https://www.google.com/'
        }

        try:
            print("Attempting recipe-scrapers...")
            # First try using recipe-scrapers without wild mode
            scraper = scrape_me(url)
            recipe_data = {
                'url': url,
                'title': scraper.title(),
                'description': '',
                'prep_time': '',
                'cook_time': '',
                'total_time': '',
                'servings': '',
                'ingredients': [],
                'instructions': [],
                'image_url': None
            }
            
            try: recipe_data['description'] = scraper.description()
            except: pass
            try: recipe_data['prep_time'] = str(scraper.prep_time())
            except: pass
            try: recipe_data['cook_time'] = str(scraper.cook_time())
            except: pass
            try: recipe_data['total_time'] = str(scraper.total_time())
            except: pass
            try: recipe_data['servings'] = str(scraper.yields())
            except: pass
            try:
                ingredients = scraper.ingredients()
                print(f"Found {len(ingredients)} ingredients")
                recipe_data['ingredients'] = ingredients
            except Exception as e:
                print(f"Failed to get ingredients: {str(e)}")
                pass
            try: 
                print("Trying to get instructions...")
                if hasattr(scraper, 'instructions_list'):
                    instructions = scraper.instructions_list()
                    print(f"Found {len(instructions)} instructions from list")
                    recipe_data['instructions'] = instructions
                else:
                    instructions = scraper.instructions()
                    print(f"Got instructions string: {instructions[:100]}...")
                    if isinstance(instructions, str):
                        # Split by newlines or numbers at start of line
                        steps = [s.strip() for s in re.split(r'\n+|\d+\.|^\d+\)', instructions, flags=re.MULTILINE)]
                        recipe_data['instructions'] = [s for s in steps if s]
                        print(f"Split into {len(recipe_data['instructions'])} steps")
                    else:
                        recipe_data['instructions'] = instructions
                        print(f"Using instructions as-is, type: {type(instructions)}")
            except Exception as e:
                print(f"Failed to get instructions: {str(e)}")
                pass
            try: recipe_data['image_url'] = scraper.image()
            except: pass

            # If we got the crucial data, return it
            if recipe_data['title'] and (recipe_data['ingredients'] or recipe_data['instructions']):
                return recipe_data

        except Exception as e:
            print(f"Recipe-scraper failed: {str(e)}")
            
        # Fallback to our custom parser for unsupported sites
        print("Trying custom parser...")
        try:
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            print("Looking for JSON-LD recipe data...")
            # Try to find JSON-LD structured data first
            json_scripts = soup.find_all('script', type='application/ld+json') + soup.find_all('script', type='application/json')
            print(f"Found {len(json_scripts)} JSON-LD scripts")
            recipe_data = None
            
            for script in json_scripts:
                try:
                    # Clean the JSON string - some sites have invalid characters
                    json_str = re.sub(r'[\x00-\x1F\x7F]', '', script.string)
                    data = json.loads(json_str)
                    
                    # Handle different JSON-LD structures
                    if isinstance(data, list):
                        # Find first recipe in array
                        for item in data:
                            if isinstance(item, dict) and (item.get('@type') == 'Recipe' or 'Recipe' in str(item.get('@type', ''))):
                                recipe_data = item
                                break
                    elif isinstance(data, dict):
                        if data.get('@type') == 'Recipe' or 'Recipe' in str(data.get('@type', '')):
                            recipe_data = data
                        elif '@graph' in data:
                            # Handle nested @graph structure
                            for item in data['@graph']:
                                if isinstance(item, dict) and (item.get('@type') == 'Recipe' or 'Recipe' in str(item.get('@type', ''))):
                                    recipe_data = item
                                    break
                    
                    if recipe_data:
                        break
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error parsing JSON-LD: {str(e)}")
            
            if recipe_data:
                return self.parse_structured_recipe(recipe_data, url)
            else:
                return self.parse_html_recipe(soup, url)
        except Exception as e:
            raise Exception(f"Failed to extract recipe: {str(e)}")

    def parse_structured_recipe(self, data, url):
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
        
        # Handle nested @graph structure and find Recipe schema
        recipe_data = None
        
        def find_recipe_data(obj):
            if isinstance(obj, dict):
                # Check if this object is a Recipe
                if obj.get('@type') == 'Recipe' or (isinstance(obj.get('@type'), list) and 'Recipe' in obj['@type']):
                    return obj
                # Check @graph
                if '@graph' in obj:
                    for item in obj['@graph']:
                        found = find_recipe_data(item)
                        if found:
                            return found
                # Check each value
                for value in obj.values():
                    found = find_recipe_data(value)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = find_recipe_data(item)
                    if found:
                        return found
            return None
        
        recipe_data = find_recipe_data(data)
        if recipe_data:
            data = recipe_data
        
        # Basic recipe metadata
        recipe['title'] = data.get('name', data.get('headline', 'Untitled Recipe'))
        recipe['description'] = data.get('description', '')
        recipe['servings'] = str(data.get('recipeYield', data.get('yield', '')))
        
        # Time information
        recipe['prep_time'] = self.extract_time(data.get('prepTime', ''))
        recipe['cook_time'] = self.extract_time(data.get('cookTime', ''))
        recipe['total_time'] = self.extract_time(data.get('totalTime', ''))
        
        # Handle ingredients - multiple possible property names
        raw_ingredients = []
        for key in ['recipeIngredient', 'ingredients', 'recipeIngredients']:
            if key in data:
                raw_ingredients = data[key]
                break
        
        if isinstance(raw_ingredients, str):
            # Split by newlines if it's a single string
            raw_ingredients = [ing.strip() for ing in raw_ingredients.split('\n')]
        elif isinstance(raw_ingredients, dict):
            # Some sites nest ingredients in an object
            raw_ingredients = [str(ing) for ing in raw_ingredients.values()]
            
        recipe['ingredients'] = [ing.strip() for ing in raw_ingredients if ing and ing.strip()]
        
        # Handle instructions - multiple possible formats
        raw_instructions = data.get('recipeInstructions', data.get('instructions', []))
        instructions = []
        
        def extract_instruction_text(inst):
            if isinstance(inst, dict):
                # HowToStep format
                if 'text' in inst:
                    return inst['text']
                # HowToSection format
                elif 'itemListElement' in inst:
                    steps = []
                    if isinstance(inst.get('name'), str):
                        steps.append(f"== {inst['name']} ==")
                    items = inst['itemListElement']
                    if isinstance(items, list):
                        for item in items:
                            extracted = extract_instruction_text(item)
                            if isinstance(extracted, list):
                                steps.extend(extracted)
                            elif extracted:
                                steps.append(extracted)
                    return steps
                # Some sites use 'step' instead of 'text'
                elif 'step' in inst:
                    return inst['step']
            elif isinstance(inst, str):
                return inst
            return None
        
        if isinstance(raw_instructions, str):
            # Split by newlines or numbers if it's a single string
            steps = re.split(r'\n+|\d+\.\s*|\d+\)\s*', raw_instructions)
            instructions = [step.strip() for step in steps if step.strip()]
        else:
            for inst in raw_instructions:
                extracted = extract_instruction_text(inst)
                if isinstance(extracted, list):
                    instructions.extend([text.strip() for text in extracted if text and text.strip()])
                elif extracted:
                    instructions.append(extracted.strip())
        
        recipe['instructions'] = instructions
        
        # Extract image - handle multiple formats
        image = data.get('image', data.get('images', data.get('thumbnailUrl')))
        if image:
            if isinstance(image, list):
                # Get the first image
                image = image[0]
            if isinstance(image, dict):
                # Prefer full-size image if available
                recipe['image_url'] = image.get('url', image.get('contentUrl'))
            elif isinstance(image, str):
                recipe['image_url'] = image
        
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
            'ul.ingredients li', '.recipe-ingredients li', '.ingredients li',
            '[itemprop="recipeIngredient"]', '.ingredient-list li',
            '.wprm-recipe-ingredient', '.ingredient', '[class*="ingredient"]',
            '.tasty-recipes-ingredients li', '.recipe-ingred_str', '.ERSIngredients li',
            '.wpurp-recipe-ingredient', '[class*="ingredient-list"] li'
        ]
        
        for selector in ingredient_selectors:
            ingredients = soup.select(selector)
            if ingredients:
                recipe['ingredients'] = [ing.get_text().strip() for ing in ingredients if ing.get_text().strip()]
                if recipe['ingredients']:  # If we found valid ingredients, break
                    break
        
        # If no ingredients found, try finding a container and get text or lists within
        if not recipe['ingredients']:
            container_selectors = ['.ingredients', '.recipe-ingredients', '[itemprop="recipeIngredient"]']
            for selector in container_selectors:
                container = soup.select_one(selector)
                if container:
                    # Try to find lists within container
                    lists = container.find_all(['ul', 'ol'])
                    if lists:
                        for list_elem in lists:
                            items = list_elem.find_all('li')
                            if items:
                                recipe['ingredients'].extend([item.get_text().strip() for item in items if item.get_text().strip()])
                    # If no lists found, try to split text by newlines
                    elif container.get_text().strip():
                        text = container.get_text().strip()
                        items = [line.strip() for line in text.split('\n') if line.strip()]
                        recipe['ingredients'].extend(items)
                    if recipe['ingredients']:
                        break
        
        # Try to find instructions
        instruction_selectors = [
            'ol.instructions li', '.recipe-instructions li', '.recipe-directions li',
            '[itemprop="recipeInstructions"] li', '.instruction-list li',
            '.wprm-recipe-instruction', '.preparation-step', '.recipe-method-step',
            '.tasty-recipes-instructions li', '.ERSInstructions li', '.recipe-steps li',
            '.wpurp-recipe-instruction', '[class*="instruction-list"] li'
        ]
        
        for selector in instruction_selectors:
            instructions = soup.select(selector)
            if instructions:
                recipe['instructions'] = [inst.get_text().strip() for inst in instructions if inst.get_text().strip()]
                break
        
        # If no structured instructions found, try finding paragraphs within instruction containers
        if not recipe['instructions']:
            container_selectors = [
                '.recipe-instructions', '.recipe-directions', '.instructions',
                '[itemprop="recipeInstructions"]', '.method-steps', '.recipe-method',
                '.wprm-recipe-instructions', '.tasty-recipes-instructions',
                '.ERSInstructions', '.wpurp-recipe-instructions', '.recipe__method-steps',
                '.RecipeInstructions', '[class*="recipe-steps"]', '[class*="cooking-steps"]',
                '[class*="method-steps"]'
            ]
            for selector in container_selectors:
                container = soup.select_one(selector)
                if container:
                    paragraphs = container.find_all(['p', 'li'])
                    if paragraphs:
                        recipe['instructions'] = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
                        break
        
        # Try to find image
        img_selectors = [
            '.recipe-image img', '.recipe-photo img', '[class*="recipe"] img',
            'img[itemprop="image"]', '.hero-photo img'
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

    def __init__(self, categorized_recipes, output_path, book_title="Recipe Book"):
        super().__init__()
        self.categorized_recipes = categorized_recipes
        self.output_path = output_path
        self.book_title = book_title

    def run(self):
        try:
            self.generate_epub()
        except Exception as e:
            self.error_occurred.emit(f"Error generating EPUB: {str(e)}")

    def generate_epub(self):
        book = epub.EpubBook()
        book.set_identifier('recipe-collection')
        book.set_title(self.book_title)
        book.set_language('en')
        book.add_author('Recipe Collector')

        chapters = []
        spine = ['nav']
        toc = []

        # Initialize all recipes list
        all_recipes = [recipe for recipes in self.categorized_recipes.values() for recipe in recipes]

        # Create temporary directory for images
        temp_dir = tempfile.mkdtemp()
        try:
            chapter_num = 0
            total_recipes = sum(len(recipes) for recipes in self.categorized_recipes.values())
            recipes_processed = 0

            # Create category sections
            for category, recipes in self.categorized_recipes.items():
                # Category section
                cat_id = f'category_{category.lower().replace(" ", "_")}'
                category_content = f'<h1>{category}</h1>'
                category_chapter = epub.EpubHtml(
                    title=category,
                    file_name=f'{cat_id}.xhtml',
                    content=category_content
                )
                book.add_item(category_chapter)
                chapters.append(category_chapter)
                spine.append(category_chapter)

                # Category recipes
                category_chapters = []
                for recipe in recipes:
                    chapter_content = self.create_chapter_content(recipe, temp_dir, book)
                    chapter_id = f'chapter_{chapter_num}'
                    
                    chapter = epub.EpubHtml(
                        title=recipe['title'],
                        content=chapter_content,
                        file_name=f'{chapter_id}.xhtml'
                    )
                    
                    book.add_item(chapter)
                    chapters.append(chapter)
                    category_chapters.append((epub.Link(f'{chapter_id}.xhtml', recipe['title'], chapter_id)))
                    spine.append(chapter)
                    
                    chapter_num += 1
                    recipes_processed += 1
                    self.progress_updated.emit(int(recipes_processed / total_recipes * 100))

                # Add category to table of contents
                toc.append((category_chapter, category_chapters))

            # Add CSS
            css = """
            @page {
                margin: 30px;
            }
            body { 
                font-family: "Bookerly", "Georgia", serif; 
                margin: 0 auto;
                line-height: 1.7;
                max-width: 800px;
                padding: 20px;
                color: #2c3338;
            }
            h1 { 
                color: #1a1d1e;
                border-bottom: 2px solid #7ed957;
                font-size: 28px;
                margin: 40px 0 30px;
                padding-bottom: 10px;
                text-align: center;
                font-weight: 700;
                letter-spacing: -0.02em;
            }
            h2 { 
                color: #2c3338;
                margin: 35px 0 20px;
                font-size: 22px;
                font-weight: 600;
                letter-spacing: -0.01em;
            }
            p {
                margin: 1.2em 0;
            }
            .recipe-meta { 
                background: #f8faf7;
                padding: 20px;
                margin: 25px 0;
                border-radius: 12px;
                border: 1px solid #e8f3e5;
                font-size: 0.95em;
                color: #4a5056;
                text-align: center;
                font-family: "Segoe UI", sans-serif;
            }
            .ingredients { 
                background: #f8faf7;
                padding: 25px 35px;
                margin: 25px 0;
                border-radius: 12px;
                border: 1px solid #e8f3e5;
            }
            .ingredients ul {
                margin: 0;
                padding: 0;
                list-style-position: inside;
            }
            .ingredients li {
                margin: 10px 0;
                line-height: 1.5;
            }
            .instructions { 
                margin: 30px 0;
            }
            .instructions ol {
                margin: 0;
                padding: 0;
                list-style-position: inside;
                counter-reset: recipe-steps;
            }
            .instruction { 
                margin: 20px 0;
                padding: 20px 25px;
                background: #f8faf7;
                border-radius: 12px;
                border: 1px solid #e8f3e5;
                position: relative;
            }
            img { 
                display: block;
                max-width: 100%;
                height: auto;
                border-radius: 12px;
                margin: 30px auto;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            }
            a {
                color: #2d7d1e;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            """
            
            nav_css = epub.EpubItem(
                uid="nav_css",
                file_name="style/nav.css",
                media_type="text/css",
                content=css
            )
            book.add_item(nav_css)

            # Set table of contents
            book.toc = toc

            # Add navigation files
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

    def create_cover_collage(self, image_urls):
        """Create an attractive collage for the book cover"""
        try:
            # Download and verify images
            images = []
            for url in image_urls:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content)).convert("RGB")
                        images.append(img)
                except Exception as e:
                    print(f"Failed to load image {url}: {e}")
                    continue

            if not images:
                return None

            # Calculate optimal layout
            n = len(images)
            if n > 6:  # Limit to 6 images for better appearance
                images = images[:6]
                n = 6

            # Determine grid dimensions
            if n <= 2:
                cols, rows = 1, n
            elif n <= 6:
                cols = 2
                rows = (n + 1) // 2

            # Target size for cover (portrait orientation)
            target_width = 1200
            target_height = 1600
            thumb_width = target_width // cols
            thumb_height = target_height // rows

            # Create blank canvas with white background
            collage = Image.new('RGB', (target_width, target_height), 'white')

            # Place images in grid
            for idx, img in enumerate(images):
                # Calculate target size maintaining aspect ratio
                aspect = img.width / img.height
                if aspect > 1:  # landscape
                    new_width = thumb_width
                    new_height = int(thumb_width / aspect)
                else:  # portrait
                    new_height = thumb_height
                    new_width = int(thumb_height * aspect)

                # Resize image
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Calculate position (centered in grid cell)
                row = idx // cols
                col = idx % cols
                x = col * thumb_width + (thumb_width - new_width) // 2
                y = row * thumb_height + (thumb_height - new_height) // 2

                # Paste image
                collage.paste(img, (x, y))

            # Save collage with good quality
            with BytesIO() as output:
                collage.save(output, format="JPEG", quality=85)
                return output.getvalue()

        except Exception as e:
            print(f"Failed to create cover collage: {e}")
            return None

class InlineEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return QLineEdit(parent)
    def setEditorData(self, editor, index):
        editor.setText(index.data())
    def setModelData(self, editor, model, index):
        model.setData(index, editor.text())

class RecipeConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.recipes = []
        self.md_file_path = "recipe_links.md"
        self.recipe_edits = {}  # {index: {'title': ..., 'category': ...}}
        self.recipe_rows = []
        self.selected_row = None
        self.init_ui()
        self.load_previous_links()

    def init_ui(self):
        self.setWindowTitle("Recipe to EPUB Converter")
        self.setGeometry(100, 100, 1000, 700)

        # Fluent 2/Windows 11 dark theme
        accent = "#7ed957"  # Light green accent
        bg_main = "#1b1b1b"  # Windows 11 dark
        bg_surface = "#23272e"
        font = '"Segoe UI Variable", "Segoe UI", Arial, sans-serif'
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg_main};
                color: #f3f6fa;
                font-family: {font};
            }}
            QPushButton {{
                background-color: {bg_surface};
                border: none;
                color: {accent};
                padding: 10px 20px;
                font-size: 15px;
                font-weight: 600;
                margin: 2px;
                border-radius: 8px;
                font-family: {font};
            }}
            QPushButton[flat=true] {{
                padding: 4px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }}
            QPushButton:hover {{
                background-color: {accent};
                color: {bg_main};
            }}
            QPushButton:pressed {{
                background-color: #222;
            }}
            QPushButton:disabled {{
                color: #888;
            }}
            QTextEdit, QLineEdit {{
                border: none;
                background-color: {bg_surface};
                color: #f3f6fa;
                padding: 7px;
                border-radius: 8px;
                font-family: {font};
                font-size: 15px;
            }}
            QListWidget {{
                border: none;
                background-color: {bg_surface};
                color: #f3f6fa;
                alternate-background-color: {bg_main};
                border-radius: 8px;
                font-family: {font};
            }}
            QLabel {{
                color: #b6b9be;
                font-weight: 500;
                font-family: {font};
                font-size: 13px;
            }}
            QProgressBar {{
                border: none;
                background-color: {bg_surface};
                text-align: center;
                color: #000000;  /* Dark text for better contrast */
                border-radius: 8px;
                font-family: {font};
                font-weight: 600;  /* Make text bolder */
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 8px;
            }}
            QSplitter::handle {{
                background-color: {accent};
            }}
            QFrame, QWidget {{
                border-radius: 8px;
            }}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)

        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # URL input with better sizing
        url_section = QWidget()
        url_layout = QVBoxLayout(url_section)
        url_layout.setContentsMargins(0, 0, 0, 0)
        
        url_header = QLabel("RECIPE URLS (one per line):")
        url_header.setStyleSheet("font-size: 13px; font-weight: 600; margin-bottom: 4px;")
        url_layout.addWidget(url_header)
        
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste recipe URLs here, one per line...")
        self.url_input.setMinimumHeight(400)  # Make input taller
        url_layout.addWidget(self.url_input)
        
        left_layout.addWidget(url_section, 1)  # Give URL section more space
        
        # Button section
        button_section = QWidget()
        button_layout = QVBoxLayout(button_section)
        button_layout.setSpacing(8)
        
        self.load_links_btn = QPushButton("LOAD PREVIOUS LINKS")
        self.load_links_btn.clicked.connect(self.load_previous_links)
        button_layout.addWidget(self.load_links_btn)
        
        self.extract_btn = QPushButton("EXTRACT RECIPES")
        self.extract_btn.clicked.connect(self.extract_recipes)
        button_layout.addWidget(self.extract_btn)
        
        self.generate_btn = QPushButton("GENERATE EPUB")
        self.generate_btn.clicked.connect(self.generate_epub)
        self.generate_btn.setEnabled(False)
        button_layout.addWidget(self.generate_btn)
        
        left_layout.addWidget(button_section)
        
        # Progress section
        progress_section = QWidget()
        progress_layout = QVBoxLayout(progress_section)
        progress_layout.setContentsMargins(0, 8, 0, 0)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready to extract recipes...")
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)
        
        left_layout.addWidget(progress_section)
        
        splitter.addWidget(left_panel)
        
        # Right panel - Recipe preview
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Book name input at the top of right panel
        bookname_row = QHBoxLayout()
        bookname_label = QLabel("RECIPE BOOK NAME:")
        bookname_label.setStyleSheet("font-size: 13px; font-weight: 600; margin-bottom: 4px;")
        self.bookname_input = QLineEdit()
        self.bookname_input.setPlaceholderText("Recipe Book")
        bookname_row.addWidget(bookname_label)
        bookname_row.addWidget(self.bookname_input)
        right_layout.addLayout(bookname_row)
        
        # Add some space between book name and recipes list
        right_layout.addSpacing(16)
        
        right_layout.addWidget(QLabel("EXTRACTED RECIPES:"))
        
        # Create a scroll area for recipes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Container for recipes
        self.recipe_list_widget = QWidget()
        self.recipe_list_layout = QVBoxLayout(self.recipe_list_widget)
        self.recipe_list_layout.setSpacing(4)
        self.recipe_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.recipe_list_widget.setLayout(self.recipe_list_layout)
        
        # Add recipe container to scroll area
        scroll_area.setWidget(self.recipe_list_widget)
        right_layout.addWidget(scroll_area)
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
        
        # Clear previous recipes
        self.recipes = []
        for row in self.recipe_rows:
            row.setParent(None)
        self.recipe_rows = []
        self.recipe_edits = {}
        
        self.extract_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Extracting recipes...")
        
        self.extractor = RecipeExtractor(urls)
        self.extractor.progress_updated.connect(self.progress_bar.setValue)
        self.extractor.recipe_extracted.connect(self.add_recipe_to_list)
        self.extractor.extraction_complete.connect(self.extraction_finished)
        self.extractor.error_occurred.connect(self.show_error)
        self.extractor.status_updated.connect(self.status_label.setText)
        self.extractor.start()

    def detect_category(self, recipe):
        """Automatically detect recipe category based on title and ingredients"""
        title = recipe['title'].lower()
        ingredients = [ing.lower() for ing in recipe.get('ingredients', [])]
        
        # Define category patterns
        patterns = {
            'Dessert': ['cake', 'cookie', 'pie', 'dessert', 'sweet', 'chocolate', 'ice cream', 'pudding'],
            'Breakfast': ['breakfast', 'pancake', 'waffle', 'eggs', 'omelette', 'oatmeal', 'cereal'],
            'Appetizer': ['appetizer', 'snack', 'dip', 'starter'],
            'Soup': ['soup', 'stew', 'broth', 'chowder'],
            'Salad': ['salad', 'slaw'],
            'Main Course': ['chicken', 'beef', 'pork', 'fish', 'salmon', 'pasta', 'rice'],
            'Vegetarian': ['tofu', 'vegetarian', 'vegan'],
            'Side Dish': ['side', 'vegetable', 'potato', 'rice'],
            'Bread': ['bread', 'roll', 'bun', 'muffin'],
            'Beverage': ['drink', 'cocktail', 'smoothie', 'juice']
        }
        
        # Check title and ingredients against patterns
        for category, keywords in patterns.items():
            if any(kw in title for kw in keywords):
                return category
            if any(any(kw in ing for kw in keywords) for ing in ingredients):
                return category
        
        # Special case for vegetarian
        meat_ingredients = ['chicken', 'beef', 'pork', 'fish', 'salmon', 'lamb', 'turkey']
        if not any(any(meat in ing for meat in meat_ingredients) for ing in ingredients):
            return 'Vegetarian'
        
        return 'Main Course'  # Default category

    def create_edit_button(self, icon_name):
        button = QPushButton()
        button.setFlat(True)
        button.setFixedSize(32, 32)
        
        # Create an SVG icon with the current accent color
        svg_data = {
            'edit': '''
                <svg viewBox="0 0 24 24" width="16" height="16">
                    <path fill="#7ed957" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                </svg>
            ''',
            'category': '''
                <svg viewBox="0 0 24 24" width="16" height="16">
                    <path fill="#7ed957" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-11h2v3h3v2h-3v3h-2v-3H8v-2h3V9z"/>
                </svg>
            '''
        }
        
        # Convert SVG to QIcon
        svg_bytes = svg_data[icon_name].encode('utf-8')
        pixmap = QPixmap()
        pixmap.loadFromData(svg_bytes)
        button.setIcon(QIcon(pixmap))
        button.setToolTip("Edit Title" if icon_name == "edit" else "Edit Category")
        return button

    def add_recipe_to_list(self, recipe):
        self.recipes.append(recipe)
        idx = len(self.recipes) - 1
        
        # Auto-detect category
        detected_category = self.detect_category(recipe)
        self.recipe_edits[idx] = {
            'title': recipe['title'],
            'category': detected_category
        }
        
        # Create row widget with fixed height
        row = QWidget()
        row.setFixedHeight(50)
        row.setStyleSheet("QWidget:hover { background-color: #2d313a; }")
        
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(8)
        
        # Title label
        title_label = QLabel(recipe['title'])
        title_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #f3f6fa;")
        title_label.setMinimumWidth(200)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(title_label)
        
        # Category label
        cat_label = QLabel(detected_category)
        cat_label.setStyleSheet("font-size: 14px; color: #7ed957; font-weight: 500;")
        cat_label.setMinimumWidth(120)
        cat_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(cat_label)
        
        # Edit buttons with icons
        edit_title_btn = self.create_edit_button("edit")
        edit_title_btn.clicked.connect(lambda: self.edit_recipe_title(row))
        row_layout.addWidget(edit_title_btn)
        
        edit_cat_btn = self.create_edit_button("category")
        edit_cat_btn.clicked.connect(lambda: self.edit_recipe_category(row))
        row_layout.addWidget(edit_cat_btn)
        
        # Store references
        row.title_label = title_label
        row.cat_label = cat_label
        row.idx = idx
        
        # Add to layout
        self.recipe_list_layout.addWidget(row)
        self.recipe_rows.append(row)
        
        # Update UI
        self.recipe_list_widget.updateGeometry()
        QApplication.processEvents()

    def edit_recipe_title(self, row):
        old_title = self.recipe_edits[row.idx]['title']
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Edit Recipe Title")
        dialog.setLabelText("Enter new title:")
        dialog.setTextValue(old_title)
        dialog.resize(400, dialog.height())  # Make dialog wider
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_title = dialog.textValue()
            if new_title:
                self.recipe_edits[row.idx]['title'] = new_title
                row.title_label.setText(new_title)

    def edit_recipe_category(self, row):
        old_cat = self.recipe_edits[row.idx]['category']
        categories = [
            'Breakfast', 'Appetizer', 'Soup', 'Salad', 'Main Course',
            'Side Dish', 'Dessert', 'Bread', 'Beverage', 'Vegetarian'
        ]
        new_cat, ok = QInputDialog.getItem(
            self, "Edit Category",
            "Choose category:",
            categories,
            categories.index(old_cat) if old_cat in categories else 0,
            editable=True
        )
        if ok and new_cat:
            self.recipe_edits[row.idx]['category'] = new_cat
            row.cat_label.setText(new_cat)

    def extraction_finished(self, recipes):
        self.extract_btn.setEnabled(True)
        if recipes:
            self.generate_btn.setEnabled(True)
            self.status_label.setText(f"Extracted {len(recipes)} recipes successfully")
            self.save_links_to_md()
        else:
            self.status_label.setText("No recipes could be extracted")
        QApplication.processEvents()

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

        # Get edited recipes with categories
        edited_recipes = []
        for idx, recipe in enumerate(self.recipes):
            recipe_copy = recipe.copy()
            edit = self.recipe_edits.get(idx, {})
            recipe_copy['title'] = edit.get('title', recipe['title'])
            recipe_copy['category'] = edit.get('category', 'Uncategorized')
            edited_recipes.append(recipe_copy)

        # Sort recipes by category
        edited_recipes.sort(key=lambda x: (x['category'], x['title']))

        # Group recipes by category
        categorized_recipes = {}
        for recipe in edited_recipes:
            cat = recipe['category']
            if cat not in categorized_recipes:
                categorized_recipes[cat] = []
            categorized_recipes[cat].append(recipe)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save EPUB", "recipe_collection.epub", "EPUB files (*.epub)"
        )

        if not file_path:
            return

        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Generating EPUB...")

        # Pass categorized recipes
        book_title = self.bookname_input.text().strip() or "Recipe Book"
        self.generator = EpubGenerator(categorized_recipes, file_path, book_title)
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

    def select_recipe_row(self, row):
        for r in self.recipe_rows:
            r.setStyleSheet("")
        row.setStyleSheet("background-color: #222; border-radius: 8px;")
        self.selected_row = row

    def edit_selected_recipe(self):
        row = getattr(self, 'selected_row', None)
        if not row:
            QMessageBox.information(self, "No Selection", "Please select a recipe to edit.")
            return
        idx = row.idx
        old = self.recipe_edits.get(idx, {'title': self.recipes[idx]['title'], 'category': ''})
        title, ok1 = QInputDialog.getText(self, "Edit Recipe Title", "Title:", QLineEdit.EchoMode.Normal, old['title'])
        if not ok1:
            return
        category, ok2 = QInputDialog.getText(self, "Edit Category", "Category:", QLineEdit.EchoMode.Normal, old['category'])
        if not ok2:
            return
        self.recipe_edits[idx] = {'title': title, 'category': category}
        row.title_label.setText(title)
        row.cat_label.setText(category)

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for better cross-platform appearance
    
    window = RecipeConverter()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
