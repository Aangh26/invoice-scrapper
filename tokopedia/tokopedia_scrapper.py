import os
import asyncio
from playwright.async_api import async_playwright, Playwright
from playwright_stealth import Stealth
from datetime import datetime
import glob
import argparse
import json
import re # Import regex for cleaning total belanja value
import random # Import random for human-like delays

# --- Configuration ---
# Base URL for Tokopedia invoices
BASE_URL = "https://www.tokopedia.com/invoice?id="
BASE_URL_WITH_SOURCE = "https://www.tokopedia.com/invoice?id={}&source=bom"
LOGIN_URL = "https://www.tokopedia.com/login" # Tokopedia login URL
LOGIN_CHECK_URL = "https://www.tokopedia.com/order-list"

# Input file containing invoice IDs, one per line
INVOICE_IDS_FILE = "invoice_ids.txt"

# Output directory to save PDF files
OUTPUT_DIR = "invoices_pdf"
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshots") # Retained for consistency, no screenshots saved in headless mode

# Path to save/load browser session state (cookies, local storage, etc.)
STATE_FILE_PATH = "login_state.json"

# Month mapping for Indonesian dates to numerical format
MONTH_MAP = {
    'Januari': '01', 'Februari': '02', 'Maret': '03', 'April': '04',
    'Mei': '05', 'Juni': '06', 'Juli': '07', 'Agustus': '08',
    'September': '09', 'Oktober': '10', 'November': '11', 'Desember': '12'
}

# --- Script Logic ---

def create_output_directory():
    """Creates the output directories if they don't exist."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")
    else:
        print(f"Output directory already exists: {OUTPUT_DIR}")

    if not os.path.exists(SCREENSHOT_DIR):
        os.makedirs(SCREENSHOT_DIR)
        print(f"Created screenshot directory: {SCREENSHOT_DIR}")
    else:
        print(f"Screenshot directory already exists: {SCREENSHOT_DIR}")


def read_invoice_ids(filename):
    """Reads invoice IDs from a text file."""
    invoice_ids = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                invoice_id = line.strip()
                if invoice_id:
                    invoice_ids.append(invoice_id)
        print(f"Successfully read {len(invoice_ids)} invoice IDs from {filename}.")
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found. Please create it with invoice IDs.")
    return invoice_ids

def format_date_for_filename(date_str):
    """Converts a date string like '26 Juni 2025' to '2025-06-26'."""
    parts = date_str.split(' ')
    if len(parts) != 3:
        # Fallback for unexpected formats
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_')

    day = parts[0]
    month_id = parts[1]
    year = parts[2]

    month_num = MONTH_MAP.get(month_id)
    if not month_num:
        # Fallback if month name is not in map
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_')

    return f"{year}-{month_num}-{day.zfill(2)}"

def parse_rupiah_to_int(rupiah_str: str) -> int:
    """
    Converts a Rupiah string (e.g., "TOTAL TAGIHAN\nRp1.087.000") to an integer (e.g., 1087000).
    It now specifically extracts the Rp value first.
    Returns 0 if parsing fails or no Rp value is found.
    """
    if not rupiah_str:
        return 0

    # Step 1: Find the part that looks like "Rp" followed by numbers and dots/commas
    # This regex looks for 'Rp' (case-insensitive), then optionally a space,
    # then one or more digits, followed by zero or more groups of (dot or comma followed by digits).
    match = re.search(r'Rp\s*([\d.,]+)', rupiah_str, re.IGNORECASE)
    
    if match:
        # Step 2: Extract the matched number string (e.g., "1.087.000")
        numeric_part = match.group(1)
        
        # Step 3: Remove all non-digit characters from the numeric part
        cleaned_str = re.sub(r'[^0-9]', '', numeric_part)
        try:
            return int(cleaned_str)
        except ValueError:
            print(f"Warning: Could not convert '{cleaned_str}' to integer from '{rupiah_str}'.")
            return 0
    else:
        print(f"Warning: No 'Rp' value found in string: '{rupiah_str}'.")
        return 0

async def check_login_status(context):
    """
    Checks if the current context has a valid login session by navigating to a known logged-in page.
    Returns True if logged in, False otherwise.
    """
    test_page = None
    try:
        test_page = await context.new_page()
        await test_page.goto(LOGIN_CHECK_URL, wait_until="load")
        current_url = test_page.url
        current_title = await test_page.title()

        # Check if we were redirected back to the login page or if the title indicates login
        if "login" in current_url.lower() or "Login" in current_title:
            print("WARNING: Session appears to be invalid or expired.")
            print(f"Current URL: {current_url}, Current Title: {current_title}")
            return False
        else:
            print(f"Session appears valid. Current URL: {current_url}, Title: {current_title}")
            return True
    except Exception as e:
        print(f"Error checking login status: {e}")
        return False
    finally:
        if test_page:
            await test_page.close()


async def handle_manual_login():
    """
    Handles the manual login process and saves the session state.
    """
    print("\n" + "="*50)
    print("--- MANUAL LOGIN REQUIRED ---")
    print(f"Opening browser to {LOGIN_URL}...")
    
    async with async_playwright() as p_raw:
        browser = None
        try:
            # Launch visible browser for manual login, NO STEALTH HERE
            browser = await p_raw.chromium.launch(headless=False)
            context = await browser.new_context()

            page = await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            print(f"Browser opened. Please log in to Tokopedia in the new window.")
            print("Giving the page a moment to load fully...")
            await asyncio.sleep(5)

            print("After you successfully log in (and potentially navigate to your dashboard/invoice page),")
            print("return to this terminal and press ENTER to save the session state.")
            print("="*50 + "\n")

            # User will manually interact with the browser for login
            input("Press Enter after logging in to Tokopedia and seeing your dashboard/invoice page...")

            await context.storage_state(path=STATE_FILE_PATH)
            print(f"Session state saved to {STATE_FILE_PATH}. You can now run the script without '--login'.")
        finally:
            if browser:
                await browser.close()


async def create_authenticated_context(p, sid_tokopedia_cookie=None, debug=False):
    """
    Creates an authenticated browser context either from saved state or using SID cookie.
    Returns (browser, context) tuple or (None, None) if authentication fails.
    """
    browser = None
    context = None

    # Try to load saved state first
    if os.path.exists(STATE_FILE_PATH):
        try:
            # Use more human-like browser settings with enhanced anti-detection
            browser = await p.chromium.launch(
                headless=not debug,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-field-trial-config',
                    '--disable-back-forward-cache',
                    '--disable-ipc-flooding-protection',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--no-zygote',
                    '--single-process',
                    '--disable-gpu',
                    '--disable-extensions'
                ]
            )
            
            # Enhanced context with more realistic fingerprinting
            context = await browser.new_context(
                storage_state=STATE_FILE_PATH,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1366, 'height': 768},  # More common resolution
                device_scale_factor=1,
                locale='id-ID',
                timezone_id='Asia/Jakarta',
                color_scheme='light',
                reduced_motion='no-preference',
                forced_colors='none',
                extra_http_headers={
                    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1'
                }
            )
            
            # Add JavaScript to mask automation signatures
            await context.add_init_script("""
                // Remove webdriver property
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                
                // Mock languages and plugins
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['id-ID', 'id', 'en-US', 'en'],
                });
                
                // Mock hardware concurrency
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    get: () => 8,
                });
                
                // Mock memory
                Object.defineProperty(navigator, 'deviceMemory', {
                    get: () => 8,
                });
                
                // Mock permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                
                // Override chrome runtime
                Object.defineProperty(window, 'chrome', {
                    get: () => ({
                        runtime: {
                            onConnect: undefined,
                            onMessage: undefined,
                        },
                    }),
                });
                
                // Mock window.outerWidth and window.outerHeight
                Object.defineProperty(window, 'outerWidth', {
                    get: () => 1366,
                });
                Object.defineProperty(window, 'outerHeight', {
                    get: () => 768,
                });
            """)
            
            if debug:
                print(f"DEBUG: Loaded session state from {STATE_FILE_PATH}.")
            else:
                print(f"Loaded session state from {STATE_FILE_PATH}.")

            # Check if the loaded state is still valid
            if await check_login_status(context):
                return browser, context
            else:
                print("Falling back to _SID_Tokopedia_ cookie (if provided).")
                await browser.close()
                browser = None
                context = None
        except Exception as e:
            if debug:
                print(f"DEBUG: Error loading session state from {STATE_FILE_PATH}: {e}")
            else:
                print(f"Error loading session state from {STATE_FILE_PATH}: {e}")
            print("Falling back to _SID_Tokopedia_ cookie (if provided).")
            if browser:
                await browser.close()
            browser = None
            context = None

    # Fall back to using SID cookie
    if not context and sid_tokopedia_cookie:
        # Launch with visible browser for debugging or headless for normal operation
        if debug:
            browser = await p.chromium.launch(headless=False, slow_mo=1000)
            print("DEBUG: Running in visible mode for debugging...")
        else:
            browser = await p.chromium.launch(headless=True)
            
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        await context.add_cookies([
            {
                'name': '_SID_Tokopedia_',
                'value': sid_tokopedia_cookie,
                'domain': '.tokopedia.com',
                'path': '/',
                'expires': -1 # Session cookie
            }
        ])
        print("Using _SID_Tokopedia_ cookie for authentication.")
        
        # Check if the cookie-based authentication is valid
        if not await check_login_status(context):
            print("WARNING: _SID_Tokopedia_ cookie appears to be invalid or expired.")
            await browser.close()
            return None, None
    elif not context:
        print("\n" + "="*50)
        print("!!! URGENT: AUTHENTICATION TOKEN IS NOT SUPPLIED !!!")
        print("Please provide it via --token argument, in a 'token.txt' file, or run with '--login' to save session state.")
        print("Refer to the instructions to get the cookie value from your browser.")
        print("="*50 + "\n")
        return None, None

    return browser, context


async def scrape_invoices(context, debug=False, max_concurrent=3, single_invoice_id=None, fast_mode=False):
    """
    Main scraping function that processes all invoice IDs and downloads PDFs concurrently.
    max_concurrent: maximum number of concurrent downloads (default: 3, max recommended: 5).
    single_invoice_id: if provided, only process this specific invoice ID.
    fast_mode: if True, use shorter delays for production runs.
    """
    if single_invoice_id:
        invoice_ids = [single_invoice_id]
        if debug:
            print(f"Processing single invoice: {single_invoice_id}")
    else:
        invoice_ids = read_invoice_ids(INVOICE_IDS_FILE)
        if debug:
            print(f"Total invoices to process: {len(invoice_ids)}")
    
    if not invoice_ids:
        print("No invoice IDs found. Exiting.")
        return

    # Limit concurrency to reasonable bounds
    max_concurrent = min(max_concurrent, 5)  # Cap at 5 to avoid overwhelming the server
    if len(invoice_ids) == 1:
        max_concurrent = 1  # Single invoice doesn't need concurrency
    
    print(f"Processing {len(invoice_ids)} invoice(s) with {max_concurrent} concurrent worker(s)...")
    if fast_mode:
        print("Using fast mode - reduced delays for production runs")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def sem_fetch(invoice_id):
        async with semaphore:
            await fetch_and_save_invoice_pdf(context, invoice_id, debug=debug, fast_mode=fast_mode)
            print("-" * 30)

    tasks = [asyncio.create_task(sem_fetch(invoice_id)) for invoice_id in invoice_ids]
    await asyncio.gather(*tasks)


async def fetch_and_save_invoice_pdf(context, invoice_id: str, debug=False, fast_mode=False):
    """
    Fetches the invoice page using Playwright, extracts 'TOTAL BELANJA',
    and saves it as a PDF with the total in the filename.
    Receives an already configured context.
    fast_mode: if True, use shorter delays for production runs.
    """
    url = BASE_URL_WITH_SOURCE.format(invoice_id)

    # Sanitize invoice_id for filename use (replace '/' with '_')
    sanitized_invoice_id = invoice_id.replace('/', '_')

    # Pre-check for existing PDF based on invoice ID pattern (now includes total belanja)
    potential_filepath_pattern = os.path.join(OUTPUT_DIR, f"invoice_*_{sanitized_invoice_id}_*.pdf")
    existing_files = glob.glob(potential_filepath_pattern)
    if existing_files:
        print(f"PDF for invoice {invoice_id} already exists (found: {os.path.basename(existing_files[0])}). Skipping download.")
        return

    print(f"Attempting to fetch and save PDF for invoice: {invoice_id}")

    # Set timing parameters based on mode
    if fast_mode:
        initial_delay = random.uniform(1, 2)
        nav_delay = random.uniform(0.5, 1.5)
        scroll_delay = random.uniform(0.3, 0.8)
        content_wait = random.uniform(2, 4)
        final_wait = random.uniform(2, 4)
    else:
        initial_delay = random.uniform(3, 6)
        nav_delay = random.uniform(2, 4)
        scroll_delay = random.uniform(1, 3)
        content_wait = random.uniform(5, 8)
        final_wait = random.uniform(5, 8)

    page = None # Initialize page to None for error handling
    try:
        page = await context.new_page()
        
        # Enable request interception for advanced header manipulation
        await page.route("**/*", lambda route: route.continue_(headers={
            **route.request.headers,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        }))
        
        # Add random delay to appear more human-like
        await asyncio.sleep(initial_delay)
        
        # Inject additional anti-detection scripts
        await page.add_init_script("""
            // Override Date to avoid timezone detection
            const originalDate = Date;
            Date = class extends originalDate {
                getTimezoneOffset() {
                    return -420; // Jakarta timezone
                }
            };
            
            // Mock battery API
            Object.defineProperty(navigator, 'getBattery', {
                get: () => () => Promise.resolve({
                    charging: true,
                    chargingTime: 0,
                    dischargingTime: Infinity,
                    level: 1
                })
            });
            
            // Mock connection
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    downlink: 10,
                    rtt: 50
                })
            });
            
            // Override canvas fingerprinting
            const getContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(type) {
                if (type === '2d') {
                    const context = getContext.call(this, type);
                    const originalFillText = context.fillText;
                    context.fillText = function() {
                        originalFillText.apply(this, arguments);
                    };
                    return context;
                }
                return getContext.call(this, type);
            };
        """)
        
        if debug:
            print(f"DEBUG: Navigating to URL: {url}")
            print("DEBUG: Enhanced anti-detection measures loaded")
        
        # Navigate with more human-like behavior and sophisticated evasion
        try:
            # Multi-step navigation to mimic human browsing
            if debug:
                print("DEBUG: Starting multi-step human-like navigation...")
            
            # Step 1: Visit main page to establish session
            await page.goto("https://www.tokopedia.com", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(nav_delay)
            
            # Step 2: Simulate mouse movement and scroll
            if debug:
                print("DEBUG: Simulating human interaction...")
            await page.mouse.move(random.randint(100, 500), random.randint(100, 400))
            await asyncio.sleep(random.uniform(0.3, 1.0))
            await page.mouse.wheel(0, random.randint(100, 300))
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Step 3: Visit a common page first (like search or category)
            await page.goto("https://www.tokopedia.com/search", wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(random.uniform(0.5, 2.0))
            
            # Step 4: Now navigate to the invoice with enhanced headers
            await page.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Referer': 'https://www.tokopedia.com/search'
            })
            
            if debug:
                print(f"DEBUG: Navigating to invoice URL: {url}")
            
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if debug:
                print(f"DEBUG: Initial navigation response status: {response.status if response else 'No response'}")
                
        except Exception as nav_error:
            if debug:
                print(f"DEBUG: Navigation error: {nav_error}")
                print("DEBUG: Trying direct navigation...")
            response = await page.goto(url, wait_until="load", timeout=45000)
        
        # Wait for network to be quiet with human-like delays
        await page.wait_for_load_state("networkidle", timeout=20000)
        if debug:
            print("DEBUG: Network idle state reached")
        
        # Wait for JavaScript to render content - Enhanced SPA handling
        if debug:
            print("DEBUG: Waiting for SPA content to render with enhanced detection...")
        
        # Simulate human scroll and interaction to trigger JavaScript
        await page.mouse.move(random.randint(200, 600), random.randint(200, 500))
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.mouse.wheel(0, random.randint(50, 200))
        await asyncio.sleep(scroll_delay)
        
        # Wait for the content div to be populated (SPA indicator)
        try:
            await page.wait_for_function(
                "document.querySelector('#content') && document.querySelector('#content').children.length > 0",
                timeout=10000 if fast_mode else 15000
            )
            if debug:
                print("DEBUG: Content div populated")
        except:
            if debug:
                print("DEBUG: Content div not populated within timeout, trying alternative detection...")
            
            # Alternative: wait for any React/Vue components to mount
            try:
                await page.wait_for_function(
                    "document.querySelector('[data-testid], [class*=\"css-\"], [data-react-]')",
                    timeout=6000 if fast_mode else 10000
                )
                if debug:
                    print("DEBUG: React/Vue components detected")
            except:
                if debug:
                    print("DEBUG: No framework components detected, continuing anyway")
        
        # Enhanced interaction to trigger lazy loading (reduced for fast mode)
        if debug:
            print("DEBUG: Triggering lazy loading with scroll simulation...")
        
        # Scroll to different positions to trigger content loading
        scroll_positions = [200, 500, 800] if fast_mode else [200, 500, 800, 1200]
        for scroll_pos in scroll_positions:
            await page.evaluate(f"window.scrollTo(0, {scroll_pos})")
            await asyncio.sleep(random.uniform(0.3, 1.0) if fast_mode else random.uniform(0.5, 1.5))
            await page.mouse.move(random.randint(100, 700), random.randint(100, 600))
            await asyncio.sleep(random.uniform(0.2, 0.8) if fast_mode else random.uniform(0.5, 1))
        
        # Return to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(random.uniform(1, 2) if fast_mode else random.uniform(2, 4))
        
        # Additional wait for dynamic content with randomization
        await asyncio.sleep(content_wait)
        
        # Try to wait for specific invoice elements to appear with multiple strategies
        if debug:
            print("DEBUG: Waiting for invoice-specific content with multiple strategies...")
        
        # Strategy 1: Wait for text content (reduced timeout for fast mode)
        try:
            await page.wait_for_selector(
                'text="TOTAL BELANJA", text="Tanggal Pembelian", text="Invoice", text="Faktur"',
                timeout=5000 if fast_mode else 8000
            )
            if debug:
                print("DEBUG: Invoice text elements detected")
        except:
            if debug:
                print("DEBUG: No invoice text elements detected, trying DOM-based detection...")
            
            # Strategy 2: Wait for common invoice CSS classes
            try:
                await page.wait_for_selector(
                    '[class*="invoice"], [class*="total"], [class*="belanja"], [class*="pembelian"], [class*="tagihan"]',
                    timeout=5000 if fast_mode else 8000
                )
                if debug:
                    print("DEBUG: Invoice CSS elements detected")
            except:
                if debug:
                    print("DEBUG: No invoice CSS elements detected")
        
        # Strategy 3: Force JavaScript execution by clicking around (reduced for fast mode)
        if debug:
            print("DEBUG: Forcing JavaScript execution with click simulation...")
        
        try:
            # Click in different areas to trigger event handlers
            click_count = 2 if fast_mode else 3
            for _ in range(click_count):
                x, y = random.randint(200, 800), random.randint(200, 600)
                await page.mouse.click(x, y, delay=random.randint(30, 100))
                await asyncio.sleep(random.uniform(0.3, 1.0) if fast_mode else random.uniform(0.5, 1.5))
        except:
            pass
        
        # Final extended wait to ensure all dynamic content is loaded
        await asyncio.sleep(final_wait)

        # Check current URL to see if we were redirected
        current_url = page.url
        if debug:
            print(f"DEBUG: Current URL after navigation: {current_url}")
        
        page_title = await page.title()
        if debug:
            print(f"DEBUG: Page title: '{page_title}'")
        
        # Check for common redirect/error patterns
        if "login" in current_url.lower() or "Login" in page_title or "Error" in page_title:
            print(f"WARNING: Invoice {invoice_id} might not have loaded correctly.")
            print(f"Detected redirect to login or error page")
            print("This suggests the session token is invalid or expired.")
            return

        # Check if page has actual content by looking for common invoice elements
        if debug:
            print("DEBUG: Checking page content...")
        
        # Get page HTML for debugging
        if debug:
            page_content = await page.content()
            print(f"DEBUG: Page HTML length: {len(page_content)} characters")
            
            # Check for anti-bot detection
            if "captcha" in page_content.lower() or "robot" in page_content.lower():
                print("DEBUG: WARNING: Possible CAPTCHA or anti-bot detection!")
                print("DEBUG: The site may be blocking automated access.")
            
            # Check if content div is populated
            content_div = await page.locator('#content').inner_html()
            print(f"DEBUG: Content div HTML length: {len(content_div)} characters")
            if len(content_div) > 100:
                print("DEBUG: Content div appears to be populated")
            else:
                print("DEBUG: Content div appears empty or minimal")
        
        body_text = await page.locator('body').inner_text()
        if debug:
            print(f"DEBUG: Body text length: {len(body_text)} characters")
        
        # Look for invoice-specific content with more comprehensive search
        invoice_indicators = [
            "invoice", "Invoice", "INVOICE",
            "faktur", "Faktur", "FAKTUR", 
            "tagihan", "Tagihan", "TAGIHAN",
            "total", "Total", "TOTAL",
            "tokopedia", "Tokopedia", "TOKOPEDIA",
            "belanja", "Belanja", "BELANJA",
            "pembelian", "Pembelian", "PEMBELIAN",
            "tanggal", "Tanggal", "TANGGAL"
        ]
        
        content_found = any(indicator in body_text for indicator in invoice_indicators)
        if debug:
            print(f"DEBUG: Invoice-related content found: {content_found}")
        
        # Also check for invoice elements in the DOM structure
        dom_content_check = False
        try:
            # Check for common invoice DOM elements
            invoice_elements = await page.locator('[class*="invoice"], [class*="total"], [class*="belanja"], [class*="pembelian"]').count()
            if invoice_elements > 0:
                dom_content_check = True
                if debug:
                    print(f"DEBUG: Found {invoice_elements} potential invoice DOM elements")
        except:
            pass
        
        overall_content_found = content_found or dom_content_check
        
        if not overall_content_found:
            print(f"WARNING: No invoice-related content detected for invoice {invoice_id}")
            if debug:
                print(f"DEBUG: First 1000 characters of page text: {body_text[:1000]}")
                page_content = await page.content()
                print(f"DEBUG: First 2000 characters of HTML: {page_content[:2000]}")
            # Don't return yet, continue to save screenshot for debugging
        
        # Check if the page is mostly empty or just has basic structure
        if len(body_text.strip()) < 100:
            print(f"WARNING: Page appears to have very little content ({len(body_text)} chars)")
            if debug:
                print(f"DEBUG: Page content: {body_text}")
            # Don't return, let's save screenshot anyway for debugging

        # --- Extract Purchase Date ---
        purchase_date_element = page.locator('div.css-z5llve:has(span:has-text("Tanggal Pembelian")) > p')
        raw_date_text = None
        if await purchase_date_element.count() > 0:
            raw_date_text = (await purchase_date_element.inner_text()).strip().replace('', '').strip()
            if debug:
                print(f"DEBUG: Found purchase date: {raw_date_text}")
        else:
            if debug:
                print(f"DEBUG: Could not find 'Tanggal Pembelian' for invoice {invoice_id}. Using 'unknown_date' in filename.")

        formatted_date = "unknown_date"
        if raw_date_text:
            formatted_date = format_date_for_filename(raw_date_text)

        # --- Extract "TOTAL BELANJA" ---
        total_belanja_value = 0 # Default value if not found

        # Try multiple strategies to robustly find the TOTAL BELANJA value
        total_belanja_label_locator = page.locator(':text("TOTAL BELANJA")')
        found = False
        if await total_belanja_label_locator.count() > 0:
            if debug:
                print(f"DEBUG: Found {await total_belanja_label_locator.count()} 'TOTAL BELANJA' elements")
            for i in range(await total_belanja_label_locator.count()):
                label = total_belanja_label_locator.nth(i)
                # Try immediate next sibling
                sibling = label.locator('xpath=./following-sibling::*[1]')
                if await sibling.count() > 0:
                    raw_total_belanja_text = await sibling.inner_text()
                    total_belanja_value = parse_rupiah_to_int(raw_total_belanja_text)
                    if debug:
                        print(f"DEBUG: Extracted 'TOTAL BELANJA' (sibling): {raw_total_belanja_text} -> {total_belanja_value}")
                    found = True
                    break
                # Try parent then parent's next sibling
                parent = label.locator('xpath=..')
                parent_sibling = parent.locator('xpath=./following-sibling::*[1]')
                if await parent_sibling.count() > 0:
                    raw_total_belanja_text = await parent_sibling.inner_text()
                    total_belanja_value = parse_rupiah_to_int(raw_total_belanja_text)
                    if debug:
                        print(f"DEBUG: Extracted 'TOTAL BELANJA' (parent sibling): {raw_total_belanja_text} -> {total_belanja_value}")
                    found = True
                    break
                # Try searching for a number in the same parent
                parent_text = await parent.inner_text()
                if 'Rp' in parent_text:
                    total_belanja_value = parse_rupiah_to_int(parent_text)
                    if debug:
                        print(f"DEBUG: Extracted 'TOTAL BELANJA' (parent text): {parent_text} -> {total_belanja_value}")
                    found = True
                    break
        if not found:
            if debug:
                print(f"DEBUG: Could not find the value for 'TOTAL BELANJA' for invoice {invoice_id}. Tried multiple strategies.")

        # --- Construct Filename ---
        total_belanja_str = f"{total_belanja_value}" if total_belanja_value else "0"
        
        final_pdf_filename = f"invoice_{formatted_date}_{sanitized_invoice_id}_{total_belanja_str}.pdf"
        output_pdf_filepath = os.path.join(OUTPUT_DIR, final_pdf_filename)

        # Save a screenshot for debugging if in debug mode or if content issues detected
        if debug or not content_found or len(body_text.strip()) < 100:
            screenshot_filename = f"debug_{formatted_date}_{sanitized_invoice_id}.png"
            screenshot_filepath = os.path.join(SCREENSHOT_DIR, screenshot_filename)
            
            if debug:
                print(f"DEBUG: Saving debug screenshot to: {screenshot_filepath}")
            await page.screenshot(path=screenshot_filepath, full_page=True)
        
        if debug:
            print(f"DEBUG: Generating PDF for invoice {invoice_id}...")
        await page.pdf(path=output_pdf_filepath, format="A4", print_background=True)
        
        # Check if PDF was created and has reasonable size
        if os.path.exists(output_pdf_filepath):
            file_size = os.path.getsize(output_pdf_filepath)
            if debug:
                print(f"DEBUG: PDF created with size: {file_size} bytes")
            if file_size < 1000:  # Less than 1KB is probably blank
                print(f"WARNING: PDF size is very small ({file_size} bytes) - likely blank!")
                if debug:
                    screenshot_filename = f"debug_{formatted_date}_{sanitized_invoice_id}.png"
                    screenshot_filepath = os.path.join(SCREENSHOT_DIR, screenshot_filename)
                    print(f"DEBUG: Check the debug screenshot at: {screenshot_filepath}")
            else:
                print(f"Successfully saved PDF for invoice {invoice_id} to {output_pdf_filepath}")
        else:
            print(f"ERROR: PDF file was not created for invoice {invoice_id}")

    except Exception as e:
        print(f"CRITICAL ERROR processing invoice {invoice_id}: {type(e).__name__} - {e}")
        if debug:
            print(f"DEBUG: Full error details: {e}")
        print("This could still be due to anti-bot measures or an invalid session.")
    finally:
        if page:
            await page.close()


async def get_sid_token(args):
    """
    Retrieves the SID token from command line arguments or token.txt file.
    Returns the token string or None if not found.
    """
    sid_tokopedia_cookie = None
    
    if args.token:
        sid_tokopedia_cookie = args.token
        print("Using _SID_Tokopedia_ cookie from command-line argument.")
    else:
        token_file_path = "token.txt"
        if os.path.exists(token_file_path):
            try:
                with open(token_file_path, 'r') as f:
                    sid_tokopedia_cookie = f.read().strip()
                print(f"Using _SID_Tokopedia_ cookie from {token_file_path}.")
            except Exception as e:
                print(f"Error reading token from {token_file_path}: {e}")
        else:
            print(f"Warning: '{token_file_path}' not found.")
    
    return sid_tokopedia_cookie


async def handle_login_flow():
    """
    Handles the manual login flow using a visible browser.
    Saves the session state for future use.
    """
    await handle_manual_login()


async def handle_normal_scraping(args):
    """
    Handles the normal scraping operation using saved state or SID token.
    """
    async with async_playwright() as p:
        browser = None
        try:
            # Get SID token for fallback
            sid_tokopedia_cookie = await get_sid_token(args)
            
            # Try to create authenticated context
            browser, context = await create_authenticated_context(p, sid_tokopedia_cookie, debug=args.debug)
            
            if not browser or not context:
                print("Failed to create authenticated context. Exiting.")
                return
            
            # Proceed with scraping
            await scrape_invoices(
                context, 
                debug=args.debug, 
                max_concurrent=args.concurrency,
                single_invoice_id=args.single_invoice,
                fast_mode=args.fast
            )
            
        finally:
            if browser:
                await browser.close()


async def main():
    """Main asynchronous function to orchestrate the PDF downloading process."""
    parser = argparse.ArgumentParser(description="Download Tokopedia invoices as PDFs.")
    parser.add_argument('--token', type=str, help='_SID_Tokopedia_ cookie value (fallback if login state not used).')
    parser.add_argument('--login', action='store_true', help='Perform a manual login and save session state to login_state.json.')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with verbose output and visible browser.')
    parser.add_argument('--single-invoice', type=str, help='Process only a single invoice by ID (for testing purposes).')
    parser.add_argument('--concurrency', type=int, default=3, help='Number of concurrent invoice downloads (default: 3, max recommended: 5).')
    parser.add_argument('--fast', action='store_true', help='Use faster timing for production runs (shorter delays).')
    args = parser.parse_args()

    create_output_directory()
    
    if args.login:
        await handle_login_flow()
    else:
        await handle_normal_scraping(args)

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(main())
    else:
        asyncio.run(main())