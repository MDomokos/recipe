#!/usr/bin/env python3

import sys
import os
import json
import requests
import re
import time
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_me
from recipe_scrapers._exceptions import WebsiteNotImplementedError
from urllib.parse import urljoin
from typing import Dict, List, Any, Optional, Tuple
import logging
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import from recipe_epub_converter_v2
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up logging
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'recipe_extraction_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)

log = logging.getLogger(__name__)

def get_parent_dir():
    """Get the parent directory path"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_urls():
    """Get URLs from command line or recipe_links.md in parent directory"""
    if len(sys.argv) > 1:
        return sys.argv[1:]
    
    try:
        recipe_links_path = os.path.join(get_parent_dir(), 'recipe_links.md')
        with open(recipe_links_path, 'r', encoding='utf-8') as f:
            content = f.read()
            urls = re.findall(r'(?m)^(?:- \[.*?\]\()?(\bhttps?://[^\s\)]+)(?:\))?', content)
            if urls:
                return urls
    except Exception as e:
        log.error(f"Error reading recipe_links.md: {e}")
    
    log.error("No URLs provided. Please pass URLs as arguments or add them to recipe_links.md")
    sys.exit(1)

class RecipeExtractor:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1'
        }
          # Ingredient selectors
        self.ingredient_selectors = [
            # WPRM Plugin
            '.wprm-recipe-ingredient-group .wprm-recipe-ingredient',
            '.wprm-recipe-ingredients-container li',
            '.wprm-recipe-ingredients li',
            '[id*="wprm-recipe-ingredient"]',
            
            # Tasty Recipes Plugin
            '.tasty-recipes-ingredients li',
            '.tasty-recipe-ingredients li',
            '.tasty-recipes-ingredient-item',
            
            # Core WP Recipe Maker
            '.wpurp-recipe-ingredients li',
            '.wpurp-recipe-ingredient',
            
            # Generic recipe plugins
            '[class*="recipe-ingredients"] li',
            '[class*="ingredients-list"] li',
            '[class*="ingredient-item"]',
            
            # Specific recipe sites/plugins
            '.recipe-ingredients__item',  # Whisk Affair
            '.recipe-ingredients__list-item',  # Food Fanatic
            '.ingredients-list__item',  # Common recipe theme
            '[class*="ERS-ingredients"] li',
            '[class*="recipe-ingred_str"]',
            
            # Schema.org standard
            '[itemprop="recipeIngredient"]',
            '[itemprop="ingredients"]',
            
            # Common HTML patterns
            '.ingredients li',
            '.ingredient-list li',
            'ul.ingredients li',
            '[class*="ingredient"] li'
        ]
        
        # Instruction selectors
        self.instruction_selectors = [
            # WPRM Plugin
            '.wprm-recipe-instruction-group .wprm-recipe-instruction',
            '.wprm-recipe-instructions-container li',
            '.wprm-recipe-instructions li',
            '[id*="wprm-recipe-instruction"]',
            
            # Tasty Recipes Plugin
            '.tasty-recipes-instructions li',
            '.tasty-recipe-instructions li',
            '.tasty-recipes-instruction-item',
            
            # Core WP Recipe Maker
            '.wpurp-recipe-instructions li',
            '.wpurp-recipe-instruction',
            
            # Generic recipe plugins
            '[class*="recipe-instructions"] li',
            '[class*="recipe-steps"] li',
            '[class*="recipe-directions"] li',
            
            # Specific recipe sites/plugins
            '.recipe-instructions__step',  # Whisk Affair
            '.recipe-method__step',  # Food Fanatic
            '.method-steps__item',  # Common recipe theme
            '[class*="ERS-instructions"] li',
            '[class*="recipe-method"] li',
            
            # Schema.org standard
            '[itemprop="recipeInstructions"]',
            '.instructions li',
            '.instruction-list li',
            'ol.instructions li',
            '[class*="instruction"] li',
            '[class*="step"] li'
        ]
        ]

    def test_extraction(self, url: str) -> Dict[str, Any]:
        """Extract recipe data from a URL using multiple methods"""
        log.info(f"\n{'='*80}\nTesting recipe extraction from: {url}\n{'='*80}")
        
        results = {
            'url': url,
            'http_response': None,
            'recipe_scrapers': {'success': False},
            'json_ld': {'success': False},
            'html': {'success': False},
            'errors': [],
            'warnings': [],
            'final_recipe': None
        }

        try:
            # Test HTTP request with a longer timeout
            response = requests.get(url, headers=self.headers, timeout=20)
            results['http_response'] = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'content_length': len(response.content),
                'encoding': response.encoding
            }
            
            # Check for rate limiting
            if response.status_code == 429:
                log.error("Rate limited by the website")
                results['errors'].append("Rate limited (HTTP 429)")
                return results
                
            if response.status_code == 403:
                log.error("Access forbidden - possibly due to anti-scraping measures")
                results['errors'].append("Access forbidden (HTTP 403)")
                return results
                
            response.raise_for_status()
            
            # 1. Try recipe-scrapers
            try:
                log.info("Attempting recipe-scrapers...")
                scraper = scrape_me(url)
                recipe_data = {
                    'success': True,
                    'title': scraper.title(),
                    'ingredients': scraper.ingredients(),
                    'instructions': scraper.instructions(),
                    'total_time': str(scraper.total_time()),
                    'yields': str(scraper.yields())
                }
                results['recipe_scrapers'] = recipe_data
                log.info("Successfully extracted with recipe-scrapers")
                
                # If recipe-scrapers worked well, use it as final recipe
                results['final_recipe'] = self.format_recipe_data(recipe_data)
                
            except WebsiteNotImplementedError as e:
                log.warning(f"recipe-scrapers not supported: {e}")
                results['errors'].append(f"recipe-scrapers error: {str(e)}")
            except Exception as e:
                log.error(f"recipe-scrapers failed: {e}")
                results['errors'].append(f"recipe-scrapers error: {str(e)}")

            # Parse with BeautifulSoup for further extraction attempts
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 2. Try JSON-LD extraction if recipe-scrapers failed
            if not results['final_recipe']:
                json_ld_results = self.extract_json_ld(soup)
                results['json_ld'] = json_ld_results
                
                if json_ld_results and json_ld_results.get('success'):
                    results['final_recipe'] = json_ld_results.get('recipe')
                    log.info("Using JSON-LD data for final recipe")
            
            # 3. Try HTML structure extraction if other methods failed
            if not results['final_recipe']:
                html_results = self.extract_from_html(soup, url)
                results['html'] = html_results
                
                if html_results and html_results.get('success'):
                    results['final_recipe'] = html_results.get('recipe')
                    log.info("Using HTML structure data for final recipe")

            # Validate final recipe
            if results['final_recipe']:
                self.validate_recipe(results['final_recipe'])
                log.info("Final recipe validated successfully")
            else:
                log.error("No usable recipe could be extracted")
                results['errors'].append("No usable recipe could be extracted")

        except Exception as e:
            log.error(f"Extraction failed: {e}")
            results['errors'].append(f"Extraction error: {str(e)}")

        return results

    def extract_json_ld(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract recipe data from JSON-LD structured data"""
        log.info("\nAttempting JSON-LD extraction...")
        result = {
            'success': False,
            'recipe': None,
            'errors': [],
            'raw_data': None
        }

        try:
            json_scripts = soup.find_all('script', type='application/ld+json') + \
                         soup.find_all('script', type='application/json')
            
            log.info(f"Found {len(json_scripts)} JSON-LD scripts")
            
            for script in json_scripts:
                try:
                    # Clean the JSON string
                    json_str = re.sub(r'[\x00-\x1F\x7F]', '', script.string or '')
                    if not json_str:
                        continue
                        
                    data = json.loads(json_str)
                    result['raw_data'] = data
                    
                    # Find Recipe schema
                    recipe_data = self.find_recipe_schema(data)
                    
                    if recipe_data:
                        log.info("Found Recipe schema in JSON-LD")
                        parsed_recipe = self.parse_structured_recipe(recipe_data)
                        if self.is_valid_recipe(parsed_recipe):
                            result['success'] = True
                            result['recipe'] = parsed_recipe
                            return result
                
                except json.JSONDecodeError as e:
                    result['errors'].append(f"JSON decode error: {str(e)}")
                except Exception as e:
                    result['errors'].append(f"JSON-LD parsing error: {str(e)}")
            
            log.warning("No valid Recipe schema found in JSON-LD")
            return result
            
        except Exception as e:
            log.error(f"JSON-LD extraction failed: {e}")
            result['errors'].append(f"JSON-LD extraction error: {str(e)}")
            return result

    def find_recipe_schema(self, data: Any) -> Optional[Dict[str, Any]]:
        """Find Recipe schema in JSON-LD data"""
        def is_recipe(obj):
            if isinstance(obj, dict):
                type_value = obj.get('@type')
                return type_value == 'Recipe' or (
                    isinstance(type_value, list) and 'Recipe' in type_value
                )
            return False

        def search_recursive(obj):
            if isinstance(obj, dict):
                if is_recipe(obj):
                    return obj
                if '@graph' in obj:
                    for item in obj['@graph']:
                        if isinstance(item, dict) and is_recipe(item):
                            return item
                for value in obj.values():
                    result = search_recursive(value)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = search_recursive(item)
                    if result:
                        return result
            return None

        return search_recursive(data)

    def extract_from_html(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract recipe data from HTML structure"""
        log.info("\nAttempting HTML structure extraction...")
        result = {
            'success': False,
            'recipe': None,
            'matched_selectors': {
                'ingredients': [],
                'instructions': []
            },
            'errors': []
        }

        try:
            recipe = {
                'url': url,
                'title': self.extract_title(soup),
                'ingredients': [],
                'instructions': []
            }

            # Test each ingredient selector
            for selector in self.ingredient_selectors:
                try:
                    elements = soup.select(selector)
                    if elements:
                        ingredients = [el.get_text().strip() for el in elements if el.get_text().strip()]
                        if ingredients:
                            log.info(f"Found {len(ingredients)} ingredients with selector: {selector}")
                            result['matched_selectors']['ingredients'].append(selector)
                            recipe['ingredients'] = ingredients
                            break
                except Exception as e:
                    result['errors'].append(f"Ingredient selector error ({selector}): {str(e)}")

            # Test each instruction selector
            for selector in self.instruction_selectors:
                try:
                    elements = soup.select(selector)
                    if elements:
                        instructions = [el.get_text().strip() for el in elements if el.get_text().strip()]
                        if instructions:
                            log.info(f"Found {len(instructions)} instructions with selector: {selector}")
                            result['matched_selectors']['instructions'].append(selector)
                            recipe['instructions'] = instructions
                            break
                except Exception as e:
                    result['errors'].append(f"Instruction selector error ({selector}): {str(e)}")

            if recipe['ingredients'] or recipe['instructions']:
                result['success'] = True
                result['recipe'] = recipe
                log.info("HTML structure extraction successful")
            else:
                log.warning("No ingredients or instructions found in HTML structure")

        except Exception as e:
            log.error(f"HTML structure extraction failed: {e}")
            result['errors'].append(f"HTML extraction error: {str(e)}")

        return result

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract recipe title from HTML"""
        title_selectors = [
            'h1.recipe-title',
            'h1.entry-title',
            'h1[class*="recipe"]',
            'h1[class*="title"]',
            '.wprm-recipe-name',  # WPRM specific
            '.recipe-title',
            'h1',
            'title'
        ]
        
        for selector in title_selectors:
            try:
                element = soup.select_one(selector)
                if element and element.get_text().strip():
                    return element.get_text().strip()
            except:
                continue
        
        return "Untitled Recipe"

    def parse_structured_recipe(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse recipe data from structured format (JSON-LD)"""
        recipe = {
            'title': data.get('name', data.get('headline', 'Untitled Recipe')),
            'ingredients': [],
            'instructions': [],
            'total_time': '',
            'yields': ''
        }

        # Extract ingredients
        raw_ingredients = data.get('recipeIngredient', data.get('ingredients', []))
        if isinstance(raw_ingredients, str):
            raw_ingredients = [ing.strip() for ing in raw_ingredients.split('\n')]
        elif isinstance(raw_ingredients, dict):
            raw_ingredients = [str(ing) for ing in raw_ingredients.values()]
        
        recipe['ingredients'] = [ing.strip() for ing in raw_ingredients if ing and ing.strip()]

        # Extract instructions
        raw_instructions = data.get('recipeInstructions', [])
        instructions = []
        
        def extract_instruction_text(inst):
            if isinstance(inst, dict):
                return inst.get('text', inst.get('step', ''))
            return str(inst) if inst else ''

        if isinstance(raw_instructions, str):
            steps = re.split(r'\n+|\d+\.\s*|\d+\)\s*', raw_instructions)
            instructions = [step.strip() for step in steps if step.strip()]
        elif isinstance(raw_instructions, (list, tuple)):
            for inst in raw_instructions:
                text = extract_instruction_text(inst)
                if text.strip():
                    instructions.append(text.strip())

        recipe['instructions'] = instructions
        recipe['total_time'] = str(data.get('totalTime', ''))
        recipe['yields'] = str(data.get('recipeYield', data.get('yield', '')))

        return recipe

    def format_recipe_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert recipe-scrapers output to our standard format"""
        return {
            'title': data.get('title', 'Untitled Recipe'),
            'ingredients': data.get('ingredients', []),
            'instructions': self.convert_instructions_to_list(data.get('instructions', [])),
            'total_time': str(data.get('total_time', '')),
            'yields': str(data.get('yields', ''))
        }

    def convert_instructions_to_list(self, instructions: Any) -> List[str]:
        """Convert instructions to a list of strings"""
        if isinstance(instructions, list):
            return [str(step).strip() for step in instructions if str(step).strip()]
        elif isinstance(instructions, str):
            steps = re.split(r'\n+|\d+\.\s*|\d+\)\s*', instructions)
            return [step.strip() for step in steps if step.strip()]
        return []

    def is_valid_recipe(self, recipe: Dict[str, Any]) -> bool:
        """Check if the recipe has the minimum required data"""
        return (recipe.get('title') and 
                (recipe.get('ingredients') or recipe.get('instructions')))

    def validate_recipe(self, recipe: Dict[str, Any]) -> None:
        """Validate recipe data and log warnings"""
        if not recipe.get('title'):
            log.warning("Recipe is missing a title")
        
        if not recipe.get('ingredients'):
            log.warning("Recipe has no ingredients")
        elif len(recipe['ingredients']) < 2:
            log.warning(f"Recipe has very few ingredients: {len(recipe['ingredients'])}")
            
        if not recipe.get('instructions'):
            log.warning("Recipe has no instructions")
        elif len(recipe['instructions']) < 2:
            log.warning(f"Recipe has very few instructions: {len(recipe['instructions'])}")

def main():
    urls = get_urls()
    
    if not urls:
        log.error("No URLs found to process")
        sys.exit(1)

    extractor = RecipeExtractor()
    results = []
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    for i, url in enumerate(urls, 1):
        url = url.strip()
        if not url:
            continue
            
        log.info(f"\nTesting URL {i}/{len(urls)}: {url}")
        try:
            result = extractor.test_extraction(url)
            results.append(result)
            
            # Print summary
            print(f"\nSummary for {url}:")
            print("-" * 80)
            
            if result['http_response']:
                print(f"HTTP Status: {result['http_response']['status_code']}")
                
                # Check rate limiting headers
                headers = result['http_response'].get('headers', {})
                rate_limit_remaining = headers.get('x-ratelimit-remaining', 
                                                 headers.get('x-rate-limit-remaining'))
                if rate_limit_remaining:
                    print(f"Rate limit remaining: {rate_limit_remaining}")
            
            print("\nExtraction Methods:")
            print("1. recipe-scrapers:", "Success" if result.get('recipe_scrapers', {}).get('success') else "Failed")
            print("2. JSON-LD:", "Success" if result.get('json_ld', {}).get('success') else "Failed")
            print("3. HTML Structure:", "Success" if result.get('html', {}).get('success') else "Failed")
            
            if result.get('final_recipe'):
                print("\nExtracted Recipe:")
                print(f"Title: {result['final_recipe'].get('title', 'Unknown')}")
                print(f"Ingredients: {len(result['final_recipe'].get('ingredients', []))} items")
                print(f"Instructions: {len(result['final_recipe'].get('instructions', []))} steps")
            
            if result.get('errors'):
                print("\nErrors:")
                for error in result['errors']:
                    print(f"- {error}")
            
            print("\n" + "="*80 + "\n")
            
            # Add longer delay between requests to avoid rate limiting
            if i < len(urls):
                delay = 10  # 10 seconds between requests
                log.info(f"Waiting {delay} seconds before next request...")
                time.sleep(delay)
            
        except Exception as e:
            log.error(f"Failed to test {url}: {e}")

    # Save detailed results to JSON in results directory
    output_file = results_dir / f'extraction_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        log.info(f"\nDetailed results saved to {output_file}")
    except Exception as e:
        log.error(f"Failed to save results: {e}")

if __name__ == '__main__':
    main()
