import asyncio
import os
from playwright.async_api import async_playwright

async def setup_manual_session():
    """Set up a manual login session that can be saved and reused"""
    
    # Remove existing session file if it exists
    if os.path.exists('login_state.json'):
        os.remove('login_state.json')
        print("Removed existing login_state.json")
    
    async with async_playwright() as p:
        # Launch a visible browser for manual login
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='id-ID',
            timezone_id='Asia/Jakarta'
        )
        
        page = await context.new_page()
        
        try:
            print("Opening Tokopedia login page...")
            await page.goto("https://www.tokopedia.com/login", wait_until="domcontentloaded")
            
            print("\n" + "="*60)
            print("MANUAL LOGIN INSTRUCTIONS:")
            print("1. Please log in to Tokopedia in the browser that just opened")
            print("2. After logging in successfully, navigate to any invoice page")
            print("3. For example, go to: https://www.tokopedia.com/invoice?id=579571739830814089")
            print("4. Make sure the invoice content loads properly")
            print("5. Come back here and press Enter when done")
            print("="*60)
            
            # Wait for user to complete manual login
            input("\nPress Enter after you've logged in and verified an invoice page loads...")
            
            # Save the session state
            await context.storage_state(path="login_state.json")
            print("\nSession state saved to login_state.json")
            print("You can now use this saved session for automated scraping!")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

async def test_with_saved_session():
    """Test using the saved session"""
    
    if not os.path.exists('login_state.json'):
        print("No saved session found. Please run setup_manual_session() first.")
        return
    
    invoice_id = "579571739830814089"
    url = f"https://www.tokopedia.com/invoice?id={invoice_id}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=1000)
        
        # Load the saved session
        context = await browser.new_context(storage_state="login_state.json")
        page = await context.new_page()
        
        try:
            print(f"Testing with saved session - navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            
            current_url = page.url
            page_title = await page.title()
            
            print(f"Current URL: {current_url}")
            print(f"Page title: '{page_title}'")
            
            body_text = await page.locator('body').inner_text()
            print(f"Body text length: {len(body_text)} characters")
            
            if len(body_text) > 0:
                print(f"First 1000 characters:\n{body_text[:1000]}")
                
                # Look for invoice content
                invoice_found = any(word in body_text.lower() for word in ['invoice', 'tagihan', 'total', 'belanja'])
                print(f"\nInvoice content detected: {invoice_found}")
            
            await page.screenshot(path="session_test_invoice.png", full_page=True)
            print("Screenshot saved as session_test_invoice.png")
            
            input("Press Enter to continue...")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(test_with_saved_session())
    else:
        asyncio.run(setup_manual_session())
