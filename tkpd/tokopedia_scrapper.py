import os
import asyncio
from playwright.async_api import async_playwright, Playwright
from playwright_stealth import Stealth
import glob
import argparse

# --- Configuration ---
# IMPORTANT: Replace 'YOUR_SID_TOKOPEDIA_COOKIE_VALUE' with your actual cookie value.
# You can get this by logging into Tokopedia, opening your browser's developer tools (F12),
# going to the 'Application' or 'Storage' tab, finding 'Cookies' for tokopedia.com,
# and copying the value of '_SID_Tokopedia_'.
SID_TOKOPEDIA_COOKIE = 'uACnGbI8jr2wclnaDKbq07OUDG0ZlIqE_P9ExyV4lIOudg7qiqq1eNN5l220XFaOwLIPdCfj63rpnaIhTARjBzYlfOcYIY0OthKP5fLPvKF-CUo6ub2YLaknwADsMG6o'

# Base URL for Tokopedia invoices
BASE_URL = "https://www.tokopedia.com/invoice?id="

# Input file containing invoice IDs, one per line
INVOICE_IDS_FILE = "invoice_ids.txt"

# Output directory to save PDF files
OUTPUT_DIR = "invoices"
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshots") # New directory for screenshots

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

    # Create screenshot directory, though screenshots are no longer saved in this version
    if not os.path.exists(SCREENSHOT_DIR):
        os.makedirs(SCREENSHOT_DIR)
        # print(f"Created screenshot directory: {SCREENSHOT_DIR} (no screenshots will be saved in headless mode)")
    # else:
        # print(f"Screenshot directory already exists: {SCREENSHOT_DIR} (no screenshots will be saved in headless mode)")


def read_invoice_ids(filename):
    """Reads invoice IDs from a text file."""
    invoice_ids = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                invoice_id = line.strip()
                if invoice_id:  # Ensure the line is not empty
                    invoice_ids.append(invoice_id)
        print(f"Successfully read {len(invoice_ids)} invoice IDs from {filename}.")
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found. Please create it with invoice IDs.")
    return invoice_ids

def format_date_for_filename(date_str):
    """Converts a date string like '26 Juni 2025' to '2025-06-26'."""
    parts = date_str.split(' ')
    if len(parts) != 3:
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_') # Fallback if format is unexpected

    day = parts[0]
    month_id = parts[1]
    year = parts[2]

    month_num = MONTH_MAP.get(month_id)
    if not month_num:
        return date_str.replace(' ', '_').replace('/', '_').replace(':', '_') # Fallback if month not found

    return f"{year}-{month_num}-{day.zfill(2)}"


async def fetch_and_save_invoice_pdf(playwright_instance: Playwright, invoice_id: str, cookie_value: str):
    """
    Fetches the invoice page using Playwright and saves it as a PDF.
    """
    url = f"{BASE_URL}{invoice_id}"

    # Sanitize invoice_id for filename use (replace '/' with '_')
    sanitized_invoice_id = invoice_id.replace('/', '_')

    # --- NEW: Pre-check for existing PDF based on invoice ID ---
    # This check happens BEFORE launching the browser to save time and resources.
    # It looks for any PDF file that contains the sanitized invoice ID in its name.
    potential_filepath_pattern = os.path.join(OUTPUT_DIR, f"invoice_*_{sanitized_invoice_id}.pdf")
    existing_files = glob.glob(potential_filepath_pattern)
    if existing_files:
        print(f"PDF for invoice {invoice_id} already exists (found: {os.path.basename(existing_files[0])}). Skipping download.")
        return
    # --- END NEW ---

    print(f"Attempting to fetch and save PDF for invoice: {invoice_id}")

    browser = None # Initialize browser to None for error handling
    try:
        # Launch Chromium in headless mode
        browser = await playwright_instance.chromium.launch(headless=True)
        context = await browser.new_context()


        # Set the authentication cookie
        await context.add_cookies([
            {
                'name': '_SID_Tokopedia_',
                'value': cookie_value,
                'domain': '.tokopedia.com', # Ensure correct domain
                'path': '/',
                'expires': -1 # Session cookie, or set a future expiration if known
            }
        ])

        page = await context.new_page()

        # Navigate to the invoice URL and wait for the network to be idle
        await page.goto(url, wait_until="networkidle")

        # Add a small delay to ensure rendering is complete, if needed
        # This can sometimes help with dynamic content that loads after networkidle
        await asyncio.sleep(2)

        # Check if the page title indicates an error or redirection (e.g., login page)
        page_title = await page.title()
        if "Login" in page_title or "Error" in page_title:
            print(f"WARNING: Invoice {invoice_id} might not have loaded correctly.")
            print(f"Page title: '{page_title}'. This often means the cookie is invalid or expired, or you were redirected to a login/error page.")
            print("Please ensure your _SID_Tokopedia_ cookie is valid and has sufficient permissions.")
            # Do not attempt to save PDF if it's a login/error page
            return

        # Extract Purchase Date for filename
        purchase_date_element = page.locator('div.css-z5llve:has(span:has-text("Tanggal Pembelian")) > p')
        raw_date_text = None
        if await purchase_date_element.count() > 0:
            raw_date_text = (await purchase_date_element.inner_text()).strip().replace('<!-- -->', '').strip()
        else:
            print(f"Could not find 'Tanggal Pembelian' for invoice {invoice_id}. Using 'unknown_date' in filename.")

        formatted_date = "unknown_date"
        if raw_date_text:
            formatted_date = format_date_for_filename(raw_date_text)

        # Construct final filename with date and sanitized invoice ID
        final_pdf_filename = f"invoice_{formatted_date}_{sanitized_invoice_id}.pdf"
        output_pdf_filepath = os.path.join(OUTPUT_DIR, final_pdf_filename)

        # Save the page as PDF
        await page.pdf(path=output_pdf_filepath, format="A4", print_background=True)
        print(f"Successfully saved PDF for invoice {invoice_id} to {output_pdf_filepath}")

    except Exception as e:
        print(f"CRITICAL ERROR processing invoice {invoice_id}: {type(e).__name__} - {e}")
        print("This could still be due to anti-bot measures or an invalid cookie.")
    finally:
        if browser:
            await browser.close() # Ensure browser is closed even if errors occur

async def main():
    """Main asynchronous function to orchestrate the PDF downloading process."""
    parser = argparse.ArgumentParser(description="Download Tokopedia invoices as PDFs.")
    parser.add_argument('--token', type=str, help='_SID_Tokopedia_ cookie value.')
    args = parser.parse_args()

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

    if not sid_tokopedia_cookie:
        print("\n" + "="*50)
        print("!!! URGENT: _SID_Tokopedia_ COOKIE IS NOT SUPPLIED !!!")
        print("Please provide it via --token argument or in a 'token.txt' file.")
        print("Refer to the instructions to get the cookie value from your browser.")
        print("="*50 + "\n")
        return

    create_output_directory()
    invoice_ids = read_invoice_ids(INVOICE_IDS_FILE)

    if not invoice_ids:
        print("No invoice IDs found. Exiting.")
        return

    async with Stealth().use_async(async_playwright()) as p:
        for invoice_id in invoice_ids:
            await fetch_and_save_invoice_pdf(p, invoice_id, SID_TOKOPEDIA_COOKIE)
            print("-" * 30) # Separator for readability

if __name__ == "__main__":
    # Check if an asyncio event loop is already running
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # If a loop is running (e.g., in Jupyter), await the main function
        # This assumes you are running this in an async-compatible environment
        # like a Jupyter Notebook cell.
        loop.create_task(main())
    else:
        # If no loop is running, run the main function normally
        asyncio.run(main())
