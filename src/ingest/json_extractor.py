"""Extract product data from embedded JSON in HTML pages."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)


def extract_next_data(html: str) -> Optional[Dict[str, Any]]:
    """
    Extract __NEXT_DATA__ script tag content.
    
    Common in Next.js applications.
    """
    try:
        tree = HTMLParser(html)
        scripts = tree.css("script#__NEXT_DATA__")
        if scripts:
            script_content = scripts[0].text()
            return json.loads(script_content)
    except (json.JSONDecodeError, AttributeError, IndexError) as e:
        logger.debug(f"Failed to extract __NEXT_DATA__: {e}")
    return None


def extract_initial_state(html: str) -> Optional[Dict[str, Any]]:
    """
    Extract __INITIAL_STATE__ or __PRELOADED_STATE__ script tag content.
    
    Common in React applications.
    """
    try:
        tree = HTMLParser(html)
        # Try __INITIAL_STATE__
        scripts = tree.css("script")
        for script in scripts:
            text = script.text()
            if text and "__INITIAL_STATE__" in text:
                # Extract the variable assignment
                match = re.search(r"__INITIAL_STATE__\s*=\s*({.+?});", text, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            if text and "__PRELOADED_STATE__" in text:
                match = re.search(r"__PRELOADED_STATE__\s*=\s*({.+?});", text, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
    except (json.JSONDecodeError, AttributeError, re.error) as e:
        logger.debug(f"Failed to extract __INITIAL_STATE__: {e}")
    return None


def extract_json_ld(html: str) -> List[Dict[str, Any]]:
    """
    Extract JSON-LD structured data from script tags.
    
    Returns list of JSON-LD objects found in the page.
    """
    results = []
    try:
        tree = HTMLParser(html)
        scripts = tree.css('script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.text())
                results.append(data)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        logger.debug(f"Failed to extract JSON-LD: {e}")
    return results


def extract_products_from_next_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract product data from __NEXT_DATA__ structure.
    
    This is store-specific and may need customization per site.
    """
    products = []
    
    def search_dict(obj: Any, path: str = "") -> None:
        """Recursively search for product-like structures."""
        if isinstance(obj, dict):
            # Look for common product indicators
            if "title" in obj or "name" in obj:
                if "price" in obj or "currentPrice" in obj or "priceValue" in obj:
                    products.append(obj)
            # Recurse into nested structures
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    search_dict(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    search_dict(item, path)
    
    try:
        # Common paths in Next.js apps
        if "props" in data:
            search_dict(data["props"])
        if "pageProps" in data:
            search_dict(data["pageProps"])
        if "query" in data:
            search_dict(data["query"])
        
        # Also search root level
        search_dict(data)
    except Exception as e:
        logger.debug(f"Failed to extract products from __NEXT_DATA__: {e}")
    
    return products


def extract_products_from_json_ld(json_ld_objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract product data from JSON-LD structured data.
    
    Looks for Product schema.org types.
    """
    products = []
    
    for obj in json_ld_objects:
        try:
            # Check if it's a Product or ItemList containing Products
            obj_type = obj.get("@type", "")
            if isinstance(obj_type, list):
                obj_type = obj_type[0] if obj_type else ""
            
            if obj_type == "Product":
                products.append(obj)
            elif obj_type == "ItemList":
                # Extract products from itemListElement
                items = obj.get("itemListElement", [])
                for item in items:
                    if isinstance(item, dict):
                        item_obj = item.get("item", {})
                        if item_obj.get("@type") == "Product":
                            products.append(item_obj)
        except Exception as e:
            logger.debug(f"Failed to extract products from JSON-LD: {e}")
    
    return products


def extract_embedded_json(html: str) -> Dict[str, Any]:
    """
    Extract all embedded JSON data from HTML.
    
    Returns a dict with keys: next_data, initial_state, json_ld
    """
    result = {
        "next_data": None,
        "initial_state": None,
        "json_ld": [],
    }
    
    result["next_data"] = extract_next_data(html)
    result["initial_state"] = extract_initial_state(html)
    result["json_ld"] = extract_json_ld(html)
    
    return result


def extract_products_from_json(html: str) -> List[Dict[str, Any]]:
    """
    Extract product data from all embedded JSON sources.
    
    Returns a list of product dictionaries found in embedded JSON.
    """
    products = []
    
    # Extract __NEXT_DATA__
    next_data = extract_next_data(html)
    if next_data:
        products.extend(extract_products_from_next_data(next_data))
    
    # Extract JSON-LD
    json_ld_objects = extract_json_ld(html)
    if json_ld_objects:
        products.extend(extract_products_from_json_ld(json_ld_objects))
    
    return products
