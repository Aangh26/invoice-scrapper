import os
import asyncio
from playwright.async_api import async_playwright, Playwright
from playwright_stealth import Stealth
from datetime import datetime
import glob
import argparse
import json

# --- Configuration ---
# Base URL for Tokopedia invoices
BASE_URL = "https://www.tokopedia.com/invoice?id="
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
        # print(f"Created screenshot directory: {SCREENSHOT_DIR} (no screenshots will be saved in headless mode)")


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
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_')

    day = parts[0]
    month_id = parts[1]
    year = parts[2]

    month_num = MONTH_MAP.get(month_id)
    if not month_num:
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_')

    return f"{year}-{month_num}-{day.zfill(2)}"


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


async def create_authenticated_context(p, sid_tokopedia_cookie=None):
    """
    Creates an authenticated browser context either from saved state or using SID cookie.
    Returns (browser, context) tuple or (None, None) if authentication fails.
    """
    browser = None
    context = None

    # Try to load saved state first
    if os.path.exists(STATE_FILE_PATH):
        try:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=STATE_FILE_PATH)
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
            print(f"Error loading session state from {STATE_FILE_PATH}: {e}")
            print("Falling back to _SID_Tokopedia_ cookie (if provided).")
            if browser:
                await browser.close()
            browser = None
            context = None

    # Fall back to using SID cookie
    if not context and sid_tokopedia_cookie:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.add_cookies([
            {
                'name': '_SID_Tokopedia_',
                'value': sid_tokopedia_cookie,
                'domain': '.tokopedia.com',
                'path': '/',
                'expires': -1
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


async def scrape_invoices(context):
    """
    Main scraping function that processes all invoice IDs and downloads PDFs.
    """
    invoice_ids = read_invoice_ids(INVOICE_IDS_FILE)
    if not invoice_ids:
        print("No invoice IDs found. Exiting.")
        return

    for invoice_id in invoice_ids:
        await fetch_and_save_invoice_pdf(context, invoice_id)
        print("-" * 30)


async def fetch_and_save_invoice_pdf(context, invoice_id: str):
    """
    Fetches the invoice page using Playwright and saves it as a PDF.
    Receives an already configured context.
    """
    url = f"{BASE_URL}{invoice_id}"

    # Sanitize invoice_id for filename use (replace '/' with '_')
    sanitized_invoice_id = invoice_id.replace('/', '_')

    # Pre-check for existing PDF based on invoice ID
    potential_filepath_pattern = os.path.join(OUTPUT_DIR, f"invoice_*_{sanitized_invoice_id}.pdf")
    existing_files = glob.glob(potential_filepath_pattern)
    if existing_files:
        print(f"PDF for invoice {invoice_id} already exists (found: {os.path.basename(existing_files[0])}). Skipping download.")
        return

    print(f"Attempting to fetch and save PDF for invoice: {invoice_id}")

    page = None # Initialize page to None for error handling
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2) # Give a little extra time for rendering

        page_title = await page.title()
        if "Login" in page_title or "Error" in page_title:
            print(f"WARNING: Invoice {invoice_id} might not have loaded correctly.")
            print(f"Page title: '{page_title}'. This often means the session state is invalid or expired, or you were redirected to a login/error page.")
            print("Consider running with '--login' to re-authenticate and save a new session state.")
            return

        purchase_date_element = page.locator('div.css-z5llve:has(span:has-text("Tanggal Pembelian")) > p')
        raw_date_text = None
        if await purchase_date_element.count() > 0:
            raw_date_text = (await purchase_date_element.inner_text()).strip().replace('<!-- -->', '').strip()
        else:
            print(f"Could not find 'Tanggal Pembelian' for invoice {invoice_id}. Using 'unknown_date' in filename.")

        formatted_date = "unknown_date"
        if raw_date_text:
            formatted_date = format_date_for_filename(raw_date_text)

        final_pdf_filename = f"invoice_{formatted_date}_{sanitized_invoice_id}.pdf"
        output_pdf_filepath = os.path.join(OUTPUT_DIR, final_pdf_filename)

        await page.pdf(path=output_pdf_filepath, format="A4", print_background=True)
        print(f"Successfully saved PDF for invoice {invoice_id} to {output_pdf_filepath}")

    except Exception as e:
        print(f"CRITICAL ERROR processing invoice {invoice_id}: {type(e).__name__} - {e}")
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
    async with Stealth().use_async(async_playwright()) as p:
        browser = None
        try:
            # Get SID token for fallback
            sid_tokopedia_cookie = await get_sid_token(args)
            
            # Try to create authenticated context
            browser, context = await create_authenticated_context(p, sid_tokopedia_cookie)
            
            if not browser or not context:
                print("Failed to create authenticated context. Exiting.")
                return
            
            # Proceed with scraping
            await scrape_invoices(context)
            
        finally:
            if browser:
                await browser.close()


async def main():
    """Main asynchronous function to orchestrate the PDF downloading process."""
    parser = argparse.ArgumentParser(description="Download Tokopedia invoices as PDFs.")
    parser.add_argument('--token', type=str, help='_SID_Tokopedia_ cookie value (fallback if login state not used).')
    parser.add_argument('--login', action='store_true', help='Perform a manual login and save session state to login_state.json.')
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
