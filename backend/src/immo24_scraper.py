import base64
import json
import os
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except Exception:
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False

# Supported real estate websites
SUPPORTED_SITES = {
    "immoscout24": ["immobilienscout24.de", "immoscout24.de", "immo24"],
    "immowelt": ["immowelt.de"],
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _clean_price(value) -> Optional[float]:
    """Convert a price string/number into a float."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"([0-9][0-9\.\s,]+)", str(value))
    if not match:
        return None

    candidate = match.group(1)
    candidate = candidate.replace("\xa0", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(candidate)
    except ValueError:
        return None


def _format_address(address_block: Dict) -> Optional[str]:
    """Build a readable address from a schema.org address block."""
    if not isinstance(address_block, dict):
        return None

    parts = [
        address_block.get("streetAddress"),
        address_block.get("postalCode"),
        address_block.get("addressLocality"),
        address_block.get("addressRegion"),
        address_block.get("addressCountry"),
    ]
    cleaned = [p.strip() for p in parts if p and isinstance(p, str) and p.strip()]
    return ", ".join(cleaned) if cleaned else None


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _detect_site(url: str) -> Optional[str]:
    """Detect which real estate site the URL belongs to."""
    lower_url = (url or "").lower()
    for site_key, patterns in SUPPORTED_SITES.items():
        if any(pattern in lower_url for pattern in patterns):
            return site_key
    return None


def _extract_listing_info_with_gemini(html_text: str, page_title: str = "") -> Dict:
    """Use Gemini AI to extract listing information from HTML text.
    
    This is more reliable than CSS selectors since it can understand context.
    """
    if not GENAI_AVAILABLE or not genai:
        return {}
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {}
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("model", "gemini-2.0-flash-exp"))
        
        # Extract just the text content (not full HTML) to reduce tokens
        soup = BeautifulSoup(html_text, "html.parser")
        
        # Remove script and style tags
        for tag in soup(["script", "style", "meta", "link", "noscript"]):
            tag.decompose()
        
        # Get text content
        text_content = soup.get_text(separator="\n", strip=True)
        
        # Limit text to avoid token limits (keep first ~8000 chars which should have the key info)
        text_content = text_content[:8000]
        
        prompt = f"""Extract property listing information from this German real estate page.
Page title: {page_title}

Page content:
{text_content}

Return ONLY a valid JSON object with these fields (use null if not found):
{{
    "price": <number or null - the rental/purchase price as a number, e.g. 1650.00>,
    "currency": <string - "EUR" or the currency symbol found>,
    "address": <string or null - full address including street, postal code, city>,
    "size_sqm": <number or null - size in square meters>,
    "rooms": <number or null - number of rooms>,
    "property_type": <string or null - e.g. "Wohnung", "Haus", "Apartment">,
    "is_rental": <boolean - true if rental, false if for sale>
}}

Return ONLY the JSON, no other text."""

        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean up response - remove markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        
        result = json.loads(response_text)
        # Ensure we return a dict, not a list
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            return {}
        return result
    except Exception as e:
        print(f"Gemini extraction failed: {e}")
        return {}


def _extract_from_json_ld(soup: BeautifulSoup) -> Dict:
    """Pull price, address, and images from JSON-LD blobs if present."""
    price = None
    currency = None
    address = None
    images: List[str] = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.text)
        except Exception:
            continue

        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            offers = entry.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price_spec = offers.get("priceSpecification", {})
                if isinstance(price_spec, list):
                    price_spec = price_spec[0] if price_spec else {}
                if not isinstance(price_spec, dict):
                    price_spec = {}
                price = price or _clean_price(
                    offers.get("price") or price_spec.get("price")
                )
                currency = currency or offers.get("priceCurrency")

            if not address:
                addr_candidate = entry.get("address")
                if isinstance(addr_candidate, list):
                    addr_candidate = addr_candidate[0] if addr_candidate else None
                if not addr_candidate:
                    location = entry.get("location")
                    if isinstance(location, list):
                        location = location[0] if location else None
                    if isinstance(location, dict):
                        addr_candidate = location.get("address")
                        if isinstance(addr_candidate, list):
                            addr_candidate = addr_candidate[0] if addr_candidate else None
                address = _format_address(addr_candidate)

            image_field = entry.get("image") or entry.get("photos")
            if isinstance(image_field, str):
                images.append(image_field)
            elif isinstance(image_field, list):
                images.extend([img for img in image_field if isinstance(img, str)])

    return {"price": price, "currency": currency, "address": address, "images": images}


def _fallback_price_and_address(html: str) -> Dict:
    """Use regex fallbacks to get price/address if JSON-LD misses it."""
    price = None
    address = None

    price_match = re.search(r'"(?:price|buyingPrice)"\s*:\s*"?([0-9\.\s,]+)"?', html)
    if price_match:
        price = _clean_price(price_match.group(1))

    # Basic address pattern: street, postal code, city
    address_match = re.search(
        r'"streetAddress"\s*:\s*"([^"]+)"[^}]+?"postalCode"\s*:\s*"([^"]+)"[^}]+?"addressLocality"\s*:\s*"([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if address_match:
        street, postal, city = address_match.groups()
        address = ", ".join([part for part in [street, postal, city] if part])

    return {"price": price, "address": address}


def _parse_listing_html(html: str, page_url: str) -> Dict:
    soup = BeautifulSoup(html, "html.parser")
    json_ld_data = _extract_from_json_ld(soup)
    fallback_data = _fallback_price_and_address(html)

    price = json_ld_data.get("price") or fallback_data.get("price")
    address = json_ld_data.get("address") or fallback_data.get("address")
    currency = json_ld_data.get("currency") or "EUR"

    image_urls = json_ld_data.get("images", []) + _extract_image_urls(soup, html, page_url)
    image_urls = _dedupe_preserve_order(image_urls)

    return {
        "soup": soup,
        "price": price,
        "address": address,
        "currency": currency,
        "images": image_urls,
    }


def _extract_image_urls(soup: BeautifulSoup, html_text: str, page_url: str) -> List[str]:
    urls: List[str] = []

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        urls.append(urljoin(page_url, og_image["content"]))

    for img in soup.find_all("img"):
        for attr in ("data-src", "data-original", "src"):
            src = img.get(attr)
            if not src:
                continue
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                urls.append(urljoin(page_url, src.split("?")[0]))
                break

    # Regex fallback to catch URLs embedded inside JSON or scripts
    if html_text:
        # Normal and unescaped slashes
        candidates = []
        for text_variant in (html_text, html_text.replace("\\/", "/")):
            regex = re.compile(r'https?://[\w\-./%]+\.(?:jpe?g|png|webp)(?:\?[^"\'\s]*)?', re.IGNORECASE)
            candidates.extend(regex.findall(text_variant))
        urls.extend(candidates)

    return _dedupe_preserve_order(urls)


def _download_images(image_urls: List[str], max_images: int) -> List[Dict]:
    photos = []
    if not image_urls:
        return photos
    for idx, image_url in enumerate(image_urls[:max_images]):
        try:
            response = requests.get(image_url, headers=DEFAULT_HEADERS, timeout=20)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
            extension = "jpg"
            if "png" in content_type:
                extension = "png"
            elif "webp" in content_type:
                extension = "webp"

            filename = f"immo24-photo-{idx + 1}.{extension}"
            photos.append(
                {
                    "url": image_url,
                    "filename": filename,
                    "content_type": content_type,
                    "base64": base64.b64encode(response.content).decode("utf-8"),
                }
            )
        except Exception:
            continue

    return photos


def _accept_cookie_consent(page) -> None:
    """Try to accept cookie consent dialogs on the page."""
    # Common cookie consent button selectors for German sites and Immo24
    consent_selectors = [
        # ImmoScout24 specific
        'button[data-testid="uc-accept-all-button"]',
        'button[id="uc-btn-accept-banner"]',
        '#usercentrics-root >> button:has-text("Alle akzeptieren")',
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Akzeptieren")',
        'button:has-text("Alle Cookies akzeptieren")',
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        # Generic consent buttons
        '[class*="consent"] button[class*="accept"]',
        '[class*="cookie"] button[class*="accept"]',
        '[id*="consent"] button',
        '[id*="cookie"] button[class*="accept"]',
        'button[class*="consent-accept"]',
        'button[class*="cookie-accept"]',
        # Shadow DOM for Usercentrics (common on German sites)
        '#usercentrics-root',
    ]
    
    for selector in consent_selectors:
        try:
            # Handle shadow DOM for Usercentrics
            if selector == '#usercentrics-root':
                page.evaluate("""() => {
                    const ucRoot = document.querySelector('#usercentrics-root');
                    if (ucRoot && ucRoot.shadowRoot) {
                        const acceptBtn = ucRoot.shadowRoot.querySelector('button[data-testid="uc-accept-all-button"]');
                        if (acceptBtn) acceptBtn.click();
                    }
                }""")
                continue
            
            element = page.locator(selector).first
            if element.is_visible(timeout=500):
                element.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _create_stealth_context(p, headless: bool = True):
    """Create a browser context with anti-detection measures."""
    browser = p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--disable-gpu",
            "--window-size=1920,1080",
        ],
    )
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="de-DE",
        timezone_id="Europe/Berlin",
        ignore_https_errors=True,
        viewport={"width": 1920, "height": 1080},
        java_script_enabled=True,
        has_touch=False,
        is_mobile=False,
        device_scale_factor=1,
    )
    
    # Add stealth scripts to every page
    context.add_init_script("""
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // Override navigator.plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        // Override navigator.languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['de-DE', 'de', 'en-US', 'en']
        });
        
        // Override chrome runtime
        window.chrome = {
            runtime: {}
        };
        
        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)
    
    return browser, context


def _fetch_with_playwright(target_url: str, headless: bool = True) -> Optional[Dict]:
    """Render the page in headless Chromium to bypass WAF and return HTML + discovered images.
    
    Automatically handles cookie consent dialogs and waits for dynamic content to load.
    """
    if not PLAYWRIGHT_AVAILABLE or not sync_playwright:
        return None

    cleaned_url = target_url.split("#", 1)[0]

    try:
        with sync_playwright() as p:
            browser, context = _create_stealth_context(p, headless)
            
            page = context.new_page()
            
            # Navigate to the page
            page.goto(cleaned_url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait a bit for initial load
            page.wait_for_timeout(2000)
            
            # Try to accept cookie consent
            _accept_cookie_consent(page)
            
            # Wait for the page to settle after potential consent click
            page.wait_for_timeout(1500)
            
            # Try to wait for network to be idle
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # Continue even if networkidle times out
            
            # Scroll down to trigger lazy loading
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            
            html = page.content()
            image_urls = page.evaluate(
                """() => Array.from(document.querySelectorAll('img'))
                    .map(img => img.currentSrc || img.src)
                    .filter(Boolean)"""
            )
            
            # Also try to get images from picture elements and srcset
            additional_images = page.evaluate(
                """() => {
                    const urls = [];
                    // From picture source elements
                    document.querySelectorAll('picture source').forEach(src => {
                        const srcset = src.getAttribute('srcset');
                        if (srcset) {
                            srcset.split(',').forEach(s => {
                                const url = s.trim().split(' ')[0];
                                if (url) urls.push(url);
                            });
                        }
                    });
                    // From img srcset
                    document.querySelectorAll('img[srcset]').forEach(img => {
                        const srcset = img.getAttribute('srcset');
                        if (srcset) {
                            srcset.split(',').forEach(s => {
                                const url = s.trim().split(' ')[0];
                                if (url) urls.push(url);
                            });
                        }
                    });
                    // From background images
                    document.querySelectorAll('[style*="background-image"]').forEach(el => {
                        const style = el.getAttribute('style');
                        const match = style.match(/url\\(['"]*([^'"\\)]+)['"]*\\)/);
                        if (match) urls.push(match[1]);
                    });
                    return urls;
                }"""
            )
            
            all_images = list(set((image_urls or []) + (additional_images or [])))
            
            context.close()
            browser.close()
            return {
                "html": html,
                "used_url": cleaned_url,
                "images": all_images,
                "method": "playwright",
            }
    except Exception as e:
        print(f"Playwright fetch failed: {e}")
        return None


def _is_search_page(url: str) -> bool:
    """Check if the URL is a search results page rather than a single listing."""
    lower_url = url.lower()
    # Search pages typically have /Suche/ in the path or query params like ?searchQuery
    search_indicators = ["/suche/", "searchquery", "wohnung-mieten", "wohnung-kaufen", 
                         "haus-mieten", "haus-kaufen", "gewerbe-", "/search"]
    return any(indicator in lower_url for indicator in search_indicators) and "/expose/" not in lower_url


def _extract_search_results_with_playwright(url: str, max_listings: int = 10) -> Dict:
    """Extract listing information from a search results page using Playwright."""
    if not PLAYWRIGHT_AVAILABLE or not sync_playwright:
        return {"listings": [], "images": []}
    
    try:
        with sync_playwright() as p:
            browser, context = _create_stealth_context(p, headless=True)
            
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            
            # Accept cookie consent
            _accept_cookie_consent(page)
            page.wait_for_timeout(2000)
            
            # Check if we hit a CAPTCHA page
            page_title = page.title()
            if "robot" in page_title.lower() or "captcha" in page_title.lower():
                print(f"Bot detection page encountered: {page_title}")
                # Try waiting longer and refreshing
                page.wait_for_timeout(5000)
                page.reload()
                page.wait_for_timeout(3000)
                _accept_cookie_consent(page)
                page.wait_for_timeout(2000)
            
            # Scroll to load lazy images
            for _ in range(3):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            
            # Extract listing data from search results
            listings_data = page.evaluate("""() => {
                const listings = [];
                const images = [];
                
                // ImmoScout24 search result selectors
                const resultItems = document.querySelectorAll('[data-testid="result-list-entry"], .result-list-entry, article[data-item], .result-list__listing');
                
                resultItems.forEach((item, index) => {
                    if (index >= """ + str(max_listings) + """) return;
                    
                    const listing = {};
                    
                    // Get link to listing
                    const link = item.querySelector('a[href*="/expose/"]');
                    if (link) {
                        listing.url = link.href;
                        listing.id = link.href.match(/expose\\/([0-9]+)/)?.[1];
                    }
                    
                    // Get price
                    const priceEl = item.querySelector('[data-testid="price"], .result-list-entry__criteria-item--price, .font-highlight, [class*="price"]');
                    if (priceEl) {
                        listing.price_text = priceEl.textContent.trim();
                    }
                    
                    // Get address
                    const addressEl = item.querySelector('[data-testid="address"], .result-list-entry__address, [class*="address"]');
                    if (addressEl) {
                        listing.address = addressEl.textContent.trim();
                    }
                    
                    // Get title
                    const titleEl = item.querySelector('[data-testid="title"], .result-list-entry__brand-title, h2, [class*="title"]');
                    if (titleEl) {
                        listing.title = titleEl.textContent.trim();
                    }
                    
                    // Get images from this listing card
                    const imgs = item.querySelectorAll('img');
                    imgs.forEach(img => {
                        const src = img.currentSrc || img.src || img.getAttribute('data-src');
                        if (src && !src.includes('data:image') && !src.includes('placeholder')) {
                            images.push(src);
                            if (!listing.image) listing.image = src;
                        }
                    });
                    
                    // Also check picture elements
                    const pictures = item.querySelectorAll('picture source');
                    pictures.forEach(source => {
                        const srcset = source.srcset;
                        if (srcset) {
                            const firstUrl = srcset.split(',')[0].trim().split(' ')[0];
                            if (firstUrl && !firstUrl.includes('data:image')) {
                                images.push(firstUrl);
                                if (!listing.image) listing.image = firstUrl;
                            }
                        }
                    });
                    
                    if (listing.url || listing.image) {
                        listings.push(listing);
                    }
                });
                
                // Also get any other images on the page
                document.querySelectorAll('img').forEach(img => {
                    const src = img.currentSrc || img.src;
                    if (src && src.includes('immobilienscout24') && 
                        !src.includes('data:image') && !src.includes('placeholder') &&
                        !src.includes('logo') && !src.includes('icon') &&
                        (src.includes('.jpg') || src.includes('.jpeg') || src.includes('.png') || src.includes('.webp'))) {
                        images.push(src);
                    }
                });
                
                return { listings, images: [...new Set(images)] };
            }""")
            
            html = page.content()
            page_title = page.title()
            
            # Check if we hit bot detection
            bot_detected = "robot" in page_title.lower() or "captcha" in page_title.lower()
            
            context.close()
            browser.close()
            
            # Handle case where listings_data might not be a dict
            if not isinstance(listings_data, dict):
                listings_data = {"listings": [], "images": []}
            return {
                "listings": listings_data.get("listings", []),
                "images": listings_data.get("images", []),
                "html": html,
                "bot_detected": bot_detected,
            }
    except Exception as e:
        print(f"Search page extraction failed: {e}")
        return {"listings": [], "images": [], "bot_detected": True}


# ==================== IMMOWELT.DE SUPPORT ====================

def _is_immowelt_search_page(url: str) -> bool:
    """Check if the Immowelt URL is a search results page."""
    lower_url = url.lower()
    # Single listings have /expose/ in the URL
    if "/expose/" in lower_url:
        return False
    # Search pages have patterns like /suche/, -mieten, -kaufen, or /liste/
    search_indicators = ["/suche/", "/liste/", "wohnungen-mieten", "wohnungen-kaufen",
                         "haeuser-mieten", "haeuser-kaufen", "wohnung-mieten", 
                         "haus-mieten", "haus-kaufen", "immobilien"]
    return any(indicator in lower_url for indicator in search_indicators)


def _extract_immowelt_listing_data(soup: BeautifulSoup, html_text: str, page_url: str, page_title: str = "") -> Dict:
    """Extract listing data from an Immowelt single listing page.
    
    Uses Gemini AI as primary extraction method, with CSS selector fallback.
    """
    result = {
        "price": None,
        "currency": "EUR",
        "address": None,
        "size_sqm": None,
        "rooms": None,
        "property_type": None,
        "images": [],
    }
    
    # Try Gemini AI extraction first (most reliable)
    gemini_data = _extract_listing_info_with_gemini(html_text, page_title)
    if gemini_data:
        if gemini_data.get("price"):
            result["price"] = gemini_data["price"]
        if gemini_data.get("currency"):
            result["currency"] = gemini_data["currency"]
        if gemini_data.get("address"):
            result["address"] = gemini_data["address"]
        if gemini_data.get("size_sqm"):
            result["size_sqm"] = gemini_data["size_sqm"]
        if gemini_data.get("rooms"):
            result["rooms"] = gemini_data["rooms"]
        if gemini_data.get("property_type"):
            result["property_type"] = gemini_data["property_type"]
    
    # Fallback: Try JSON-LD (standard format)
    if not result["price"] or not result["address"]:
        json_ld_data = _extract_from_json_ld(soup)
        if not result["price"] and json_ld_data.get("price"):
            result["price"] = json_ld_data["price"]
        if json_ld_data.get("currency"):
            result["currency"] = json_ld_data["currency"]
        if not result["address"] and json_ld_data.get("address"):
            result["address"] = json_ld_data["address"]
        if json_ld_data.get("images"):
            result["images"].extend(json_ld_data["images"])
    
    # Fallback: Try specific Immowelt selectors for price
    if not result["price"]:
        price_selectors = [
            'div[data-testid="price"]',
            'span[class*="price"]',
            'div[class*="price"]',
            'strong[class*="price"]',
            '[class*="keyinfo"] [class*="value"]',
        ]
        for selector in price_selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    price_text = element.get_text(strip=True)
                    price_val = _clean_price(price_text)
                    if price_val:
                        result["price"] = price_val
                        break
            except Exception:
                continue
        
        # Regex fallback for price in HTML
        if not result["price"]:
            price_match = re.search(r'([0-9][0-9\.\s]*(?:,\d{2})?)\s*€', html_text)
            if price_match:
                result["price"] = _clean_price(price_match.group(1))
    
    # Fallback: Try to get address from selectors
    if not result["address"]:
        address_selectors = [
            'div[data-testid="address"]',
            'span[class*="address"]',
            'div[class*="address"]',
            '[class*="location"]',
            'p[class*="location"]',
        ]
        for selector in address_selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    addr_text = element.get_text(strip=True)
                    if addr_text and len(addr_text) > 5:
                        result["address"] = addr_text
                        break
            except Exception:
                continue
    
    # Extract images (always do this regardless of Gemini)
    img_patterns = [
        r'"(https://[^"]*immowelt[^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"(https://[^"]*mms\.immowelt[^"]*)"',
        r'"(https://[^"]*cdn[^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
    ]
    for pattern in img_patterns:
        for match in re.findall(pattern, html_text, re.IGNORECASE):
            if match and "placeholder" not in match.lower() and "logo" not in match.lower():
                result["images"].append(match)
    
    # Also get from img tags
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and ("immowelt" in src or "mms." in src or "cdn" in src) and "logo" not in src.lower():
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(page_url, src)
            result["images"].append(src)
        
        # Check srcset
        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(","):
                url_part = part.strip().split(" ")[0]
                if url_part and "logo" not in url_part.lower():
                    if url_part.startswith("//"):
                        url_part = "https:" + url_part
                    elif url_part.startswith("/"):
                        url_part = urljoin(page_url, url_part)
                    result["images"].append(url_part)
    
    result["images"] = _dedupe_preserve_order(result["images"])
    return result


def _extract_immowelt_search_results(soup: BeautifulSoup, html_text: str, page_url: str) -> Dict:
    """Extract listings from an Immowelt search results page."""
    listings = []
    images = []
    
    # Find listing cards - Immowelt uses various class patterns
    listing_selectors = [
        'div[data-testid="serp-card"]',
        'div[class*="listitem"]',
        'div[class*="estate"]',
        'div[class*="result"]',
        'article[class*="immobilie"]',
        'a[href*="/expose/"]',
    ]
    
    found_items = []
    for selector in listing_selectors:
        items = soup.select(selector)
        if items:
            found_items.extend(items)
            break
    
    for item in found_items[:15]:  # Limit to first 15
        listing = {}
        
        # Find link
        link = item.find("a", href=True) if item.name != "a" else item
        if link and "/expose/" in link.get("href", ""):
            href = link["href"]
            if href.startswith("/"):
                href = urljoin(page_url, href)
            listing["url"] = href
        
        # Find title/name
        title_elem = item.find(["h2", "h3", "span"], class_=lambda c: c and ("title" in c.lower() or "headline" in c.lower() if c else False))
        if title_elem:
            listing["title"] = title_elem.get_text(strip=True)
        
        # Find price
        price_elem = item.find(class_=lambda c: c and "price" in c.lower() if c else False)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            listing["price"] = _clean_price(price_text)
        
        # Find address
        addr_elem = item.find(class_=lambda c: c and ("location" in c.lower() or "address" in c.lower()) if c else False)
        if addr_elem:
            listing["address"] = addr_elem.get_text(strip=True)
        
        # Find image
        img = item.find("img")
        if img:
            src = img.get("src") or img.get("data-src")
            if src and "placeholder" not in src.lower() and "logo" not in src.lower():
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(page_url, src)
                listing["image"] = src
                images.append(src)
        
        if listing.get("url") or listing.get("image"):
            listings.append(listing)
    
    # Also get general images from the page
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and "logo" not in src.lower() and "icon" not in src.lower() and "placeholder" not in src.lower():
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(page_url, src)
                images.append(src)
    
    return {
        "listings": listings,
        "images": _dedupe_preserve_order(images),
    }


def _fetch_immowelt_with_playwright(url: str, is_search: bool = False) -> Dict:
    """Fetch Immowelt page using Playwright for JavaScript-rendered content.
    
    Immowelt requires a proper browser session, so we use non-headless mode
    to get the full page content.
    """
    if not PLAYWRIGHT_AVAILABLE or not sync_playwright:
        return {"html": "", "images": [], "bot_detected": False}
    
    def _try_fetch(headless: bool) -> Dict:
        with sync_playwright() as p:
            browser, context = _create_stealth_context(p, headless=headless)
            page = context.new_page()
            
            try:
                response = page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_timeout(3000)  # Wait for JS to render
                
                # Handle cookie consent
                _accept_cookie_consent(page)
                page.wait_for_timeout(1500)
                
                # Scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                
                html = page.content()
                page_title = page.title()
                
                # Get images via JavaScript
                image_urls = page.evaluate("""() => {
                    const urls = [];
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.currentSrc || img.src || img.dataset.src;
                        if (src && src.startsWith('http') && !src.includes('logo') && !src.includes('icon')) {
                            urls.push(src);
                        }
                    });
                    document.querySelectorAll('picture source').forEach(src => {
                        const srcset = src.srcset;
                        if (srcset) {
                            srcset.split(',').forEach(s => {
                                const url = s.trim().split(' ')[0];
                                if (url && url.startsWith('http')) urls.push(url);
                            });
                        }
                    });
                    return [...new Set(urls)];
                }""")
                
                # Ensure image_urls is a list
                if not isinstance(image_urls, list):
                    image_urls = []
                
                # Check for bot detection
                bot_detected = "robot" in page_title.lower() or "captcha" in page_title.lower() or "blocked" in page_title.lower()
                
                return {
                    "html": html,
                    "images": image_urls,
                    "bot_detected": bot_detected,
                    "title": page_title,
                }
            finally:
                context.close()
                browser.close()
    
    try:
        # Try headless first
        result = _try_fetch(headless=True)
        
        # If HTML is too short or no images, try with visible browser
        if len(result.get("html", "")) < 10000 and not result.get("images"):
            print("Headless mode got minimal content, trying with visible browser...")
            result = _try_fetch(headless=False)
        
        return result
    except Exception as e:
        print(f"Immowelt Playwright fetch failed: {e}")
        return {"html": "", "images": [], "bot_detected": False}


def _fetch_immowelt_listing(url: str, max_images: int = 5) -> Dict:
    """Fetch data from an Immowelt listing or search page."""
    is_search = _is_immowelt_search_page(url)
    
    result = {
        "url": url,
        "source": "immowelt.de",
        "price": None,
        "currency": "EUR",
        "address": None,
        "size_sqm": None,
        "rooms": None,
        "property_type": None,
        "photos": [],
        "listings": [] if is_search else None,
    }
    
    # Always try Playwright first for Immowelt (needed for JS-rendered content)
    playwright_data = _fetch_immowelt_with_playwright(url, is_search)
    
    # Ensure playwright_data is a dict
    if not isinstance(playwright_data, dict):
        playwright_data = {"html": "", "images": [], "title": ""}
    
    html_text = playwright_data.get("html", "") or ""
    page_title = playwright_data.get("title", "") or ""
    
    # Fallback to simple requests if Playwright failed
    if not html_text or len(html_text) < 5000:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            if resp.status_code == 200 and len(resp.text) > len(html_text):
                html_text = resp.text
        except Exception as e:
            print(f"Immowelt requests fetch failed: {e}")
    
    if not html_text:
        result["error"] = "Failed to fetch page content"
        return result
    
    soup = BeautifulSoup(html_text, "html.parser")
    
    # Initialize image_urls before the if/else
    image_urls = []
    
    if is_search:
        # Extract search results
        search_data = _extract_immowelt_search_results(soup, html_text, url)
        if not isinstance(search_data, dict):
            search_data = {"listings": [], "images": []}
        result["listings"] = search_data.get("listings", []) or []
        image_urls = search_data.get("images") or []
        
        # Also include Playwright-found images
        pw_images = playwright_data.get("images") if isinstance(playwright_data.get("images"), list) else []
        image_urls.extend(pw_images)
        
        # Get price and address from first listing
        if result["listings"] and isinstance(result["listings"], list) and len(result["listings"]) > 0:
            first = result["listings"][0]
            if isinstance(first, dict):
                result["price"] = first.get("price")
                result["address"] = first.get("address")
    else:
        # Extract single listing data (uses Gemini AI)
        listing_data = _extract_immowelt_listing_data(soup, html_text, url, page_title)
        if not isinstance(listing_data, dict):
            listing_data = {}
        result["price"] = listing_data.get("price")
        result["address"] = listing_data.get("address")
        result["size_sqm"] = listing_data.get("size_sqm")
        result["rooms"] = listing_data.get("rooms")
        result["property_type"] = listing_data.get("property_type")
        image_urls = listing_data.get("images") or []
        
        # Include Playwright images
        pw_images = playwright_data.get("images") if isinstance(playwright_data.get("images"), list) else []
        image_urls.extend(pw_images)
    
    # Dedupe and download images
    image_urls = _dedupe_preserve_order(image_urls) if image_urls else []
    result["photos"] = _download_images(image_urls, max_images=max_images)
    
    return result


# ==================== MAIN ENTRY POINT ====================

def fetch_immo24_listing(url: str, max_images: int = 5) -> Dict:
    """
    Fetch price, address, and photos from a German property listing.
    
    Supports:
    - ImmoScout24 (immobilienscout24.de) - NOTE: Has strong bot protection, may fail
    - Immowelt (immowelt.de) - Recommended, more reliable
    
    Args:
        url: Property listing URL from a supported site.
        max_images: Maximum number of images to download.

    Returns a dictionary with keys: price, currency, address, photos (base64 list), url, source.
    For search pages, also includes 'listings' with individual listing info.
    
    Note: ImmoScout24 has strong bot protection. If scraping fails, the response will
    include a 'bot_detected' flag and helpful guidance.
    """
    if not url:
        raise ValueError("Please provide a valid property listing URL.")
    
    # Detect which site this URL is from
    site = _detect_site(url)
    
    if site == "immowelt":
        return _fetch_immowelt_listing(url, max_images)
    
    elif site == "immoscout24":
        # ImmoScout24 handling (may be blocked by bot detection)
        lower_url = url.lower()
        
        # Check if this is a search results page
        if _is_search_page(url):
            result = _fetch_search_page(url, max_images)
        else:
            result = _fetch_single_listing(url, max_images)
        
        # Check if we got blocked by bot detection
        if not result.get("photos") and not result.get("listings"):
            result["bot_detected"] = True
            result["warning"] = (
                "ImmoScout24 has blocked automated access due to bot detection. "
                "Alternative options:\n"
                "1. Try using immowelt.de instead (more reliable): https://www.immowelt.de\n"
                "2. Upload property images directly using the /detect endpoint\n"
                "3. Manually enter the property details"
            )
        
        return result
    
    else:
        # Unsupported site
        supported = ", ".join([f"{k} ({', '.join(v)})" for k, v in SUPPORTED_SITES.items()])
        raise ValueError(
            f"Unsupported property website. Please use one of the following:\n"
            f"Supported sites: {supported}\n\n"
            f"Recommended: immowelt.de (more reliable, no bot blocking)"
        )


def _fetch_search_page(url: str, max_images: int = 5) -> Dict:
    """Fetch data from a search results page."""
    search_data = _extract_search_results_with_playwright(url, max_listings=10)
    
    # Ensure search_data is a dict
    if not isinstance(search_data, dict):
        search_data = {"listings": [], "images": [], "bot_detected": True}
    
    listings = search_data.get("listings", []) or []
    all_image_urls = search_data.get("images", []) or []
    bot_detected = search_data.get("bot_detected", False)
    
    # Download images from search results
    photos = _download_images(all_image_urls, max_images=max_images)
    
    # Extract price and address from first listing if available
    price = None
    address = None
    if listings and isinstance(listings, list) and len(listings) > 0:
        first = listings[0]
        if isinstance(first, dict):
            if first.get("price_text"):
                price = _clean_price(first["price_text"])
            address = first.get("address")
    
    result = {
        "source": "immo24_search",
        "url": url,
        "price": price,
        "currency": "EUR",
        "address": address,
        "photos": photos,
        "image_count": len(photos),
        "listings": listings,
        "listings_count": len(listings),
        "fetched_from": url,
        "playwright_used": True,
        "is_search_page": True,
    }
    
    # Add helpful message if bot was detected or no listings found
    if bot_detected or (not listings and not photos):
        result["warning"] = (
            "ImmoScout24 has blocked automated access. Please use a direct listing URL "
            "(e.g., https://www.immobilienscout24.de/expose/123456789) instead of a search page."
        )
        result["bot_detected"] = True
    
    return result


def _fetch_single_listing(url: str, max_images: int = 5) -> Dict:
    """Fetch data from a single listing page."""
    
    def _fetch_html(target_url: str) -> Dict[str, str]:
        """Attempt to fetch HTML directly; fall back to a text mirror if blocked."""
        cleaned_url = target_url.split("#", 1)[0]
        mirror_base = "https://r.jina.ai/http://"
        mirror_url = mirror_base + cleaned_url.replace("https://", "").replace("http://", "")

        headers = dict(DEFAULT_HEADERS)

        try:
            response = requests.get(
                cleaned_url,
                headers=headers,
                timeout=(15, 60),  # connect, read
                allow_redirects=True,
            )
            # Even if unauthorized, try to use the body if present
            if response.status_code == 200 and response.text:
                return {"html": response.text, "used_url": cleaned_url}
            if response.text:
                return {"html": response.text, "used_url": cleaned_url}
            response.raise_for_status()
        except requests.HTTPError as http_err:
            status = http_err.response.status_code if http_err.response is not None else None
            if status not in {401, 403, 451}:
                raise
        except Exception:
            # Fall through to mirror
            pass

        # Mirror fallback (text-only), shorter timeout to avoid hangs
        mirror_resp = requests.get(mirror_url, headers=headers, timeout=(10, 25))
        mirror_resp.raise_for_status()
        return {"html": mirror_resp.text, "used_url": mirror_url}

    used_playwright = False
    fetched = None
    parsed = None
    photos = []

    # Try Playwright first (handles cookies automatically)
    if PLAYWRIGHT_AVAILABLE:
        rendered = _fetch_with_playwright(url)
        if rendered and rendered.get("html"):
            fetched = rendered
            parsed = _parse_listing_html(rendered["html"], rendered["used_url"])
            photos = _download_images(parsed["images"], max_images=max_images or 5)
            if photos or parsed.get("price") or parsed.get("address"):
                used_playwright = True

    # Fall back to requests-based approach if Playwright didn't work
    if not used_playwright or not photos:
        try:
            requests_fetched = _fetch_html(url)
            requests_parsed = _parse_listing_html(requests_fetched["html"], url)
            requests_photos = _download_images(requests_parsed["images"], max_images=max_images or 5)
            
            # Use requests results if they're better
            if requests_photos and len(requests_photos) > len(photos):
                fetched = requests_fetched
                parsed = requests_parsed
                photos = requests_photos
                used_playwright = False
            elif not photos and (requests_parsed.get("price") or requests_parsed.get("address")):
                # Use requests data if we got useful info
                if not parsed or (not parsed.get("price") and not parsed.get("address")):
                    fetched = requests_fetched
                    parsed = requests_parsed
                    used_playwright = False
        except Exception:
            pass  # Stick with Playwright results if requests fails

    # Last resort: try Playwright again if we haven't yet and still have no results
    if not photos and not used_playwright and PLAYWRIGHT_AVAILABLE:
        rendered = _fetch_with_playwright(url)
        if rendered and rendered.get("html"):
            fetched = rendered
            parsed = _parse_listing_html(rendered["html"], rendered["used_url"])
            photos = _download_images(parsed["images"], max_images=max_images or 5)
            used_playwright = True

    # If we still have nothing, set defaults
    if not fetched:
        fetched = {"used_url": url}
    if not parsed or not isinstance(parsed, dict):
        parsed = {"price": None, "currency": "EUR", "address": None, "images": []}

    return {
        "source": "immo24",
        "url": url,
        "price": parsed.get("price") if isinstance(parsed, dict) else None,
        "currency": (parsed.get("currency") if isinstance(parsed, dict) else None) or "EUR",
        "address": parsed.get("address") if isinstance(parsed, dict) else None,
        "photos": photos if isinstance(photos, list) else [],
        "image_count": len(photos) if isinstance(photos, list) else 0,
        "fetched_from": fetched.get("used_url", url) if isinstance(fetched, dict) else url,
        "playwright_used": used_playwright,
        "is_search_page": False,
    }
