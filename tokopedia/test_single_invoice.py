import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test_single_invoice():
    """Test a single invoice to debug the issue"""
    
    # Read token
    with open('token.txt', 'r') as f:
        token = f.read().strip()
    
    invoice_id = "579571739830814089"  # First invoice from your list
    url = f"https://www.tokopedia.com/invoice?id={invoice_id}"
    
    print(f"Testing invoice: {invoice_id}")
    print(f"URL: {url}")
    print(f"Token: {token[:20]}...{token[-10:]}")  # Show partial token for verification
    
    async with Stealth().use_async(async_playwright()) as p:
        # Try with more realistic browser settings
        browser = await p.chromium.launch(
            headless=False, 
            slow_mo=2000,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=VizDisplayCompositor',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=site-per-process'
            ]
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='id-ID',
            timezone_id='Asia/Jakarta'
        )
        
        # Set additional headers to look more like a real browser
        await context.set_extra_http_headers({
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # Add the cookie
        await context.add_cookies([
            {
                'name': '_SID_Tokopedia_',
                'value': token,
                'domain': '.tokopedia.com',
                'path': '/',
                'expires': -1
            }
        ])
        
        page = await context.new_page()
        
        try:
            # First, visit the main Tokopedia page to establish session
            print("First visiting main Tokopedia page to establish session...")
            await page.goto("https://www.tokopedia.com", wait_until="domcontentloaded")
            await asyncio.sleep(3)
            
            print("Now navigating to invoice page...")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print(f"Response status: {response.status if response else 'No response'}")
            
            # Wait longer for the page to load
            print("Waiting for page to fully load...")
            await asyncio.sleep(10)
            
            # Try to wait for the page content to load
            try:
                await page.wait_for_selector('body', timeout=10000)
                print("Body element found")
                
                # Wait for any JavaScript to execute
                await page.wait_for_load_state("networkidle", timeout=15000)
                print("Network idle state reached")
                
                # Additional wait
                await asyncio.sleep(5)
            except Exception as wait_error:
                print(f"Wait error: {wait_error}")
            
            current_url = page.url
            page_title = await page.title()
            
            print(f"Current URL: {current_url}")
            print(f"Page title: '{page_title}'")
            
            # Check for common elements that might indicate loading issues
            print("\nChecking page elements...")
            
            # Check if there's any content at all
            all_text = await page.locator('*').all_inner_texts()
            total_text = ' '.join(all_text)
            print(f"Total text length from all elements: {len(total_text)}")
            
            # Get page content for analysis
            body_text = await page.locator('body').inner_text()
            print(f"Body text length: {len(body_text)} characters")
            
            if len(body_text) > 0:
                print(f"First 1000 characters:\n{body_text[:1000]}")
            else:
                # Try to get any visible text from the page
                html_content = await page.content()
                print(f"HTML content length: {len(html_content)}")
                print(f"First 2000 characters of HTML:\n{html_content[:2000]}")
            
            # Look for specific anti-bot indicators
            print("\nChecking for anti-bot indicators...")
            captcha_text = await page.locator('text=/captcha/i').count()
            robot_text = await page.locator('text=/robot/i').count()
            blocked_text = await page.locator('text=/blocked/i').count()
            
            print(f"CAPTCHA indicators: {captcha_text}")
            print(f"Robot detection: {robot_text}")
            print(f"Blocked indicators: {blocked_text}")
            
            # Check for specific elements
            print("\nChecking for common elements...")
            
            # Check for login indicators
            login_elements = await page.locator('text=Login').count()
            print(f"Login elements found: {login_elements}")
            
            # Check for invoice elements
            invoice_elements = await page.locator('text=Invoice').count()
            print(f"Invoice elements found: {invoice_elements}")
            
            # Check for Indonesian text
            tagihan_elements = await page.locator('text=Tagihan').count()
            print(f"Tagihan elements found: {tagihan_elements}")
            
            # Take a screenshot for manual inspection
            await page.screenshot(path="debug_test_invoice.png", full_page=True)
            print("Screenshot saved as debug_test_invoice.png")
            
            # Wait for user to inspect
            input("Press Enter to continue (check the browser and screenshot)...")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_single_invoice())
