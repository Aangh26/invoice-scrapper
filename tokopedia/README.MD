# Tokopedia Invoice Scraper

A Python script to automatically extract invoice data from Tokopedia e-commerce platform.

## Features

- Navigates to transaction history
- Downloads invoice PDFs
- Extracts key information from invoices
- Exports data to CSV/Excel format

## Installation

1. Clone the repository
```bash
git clone https://github.com/IEatCodeDaily/invoice-scrapper.git
```
2. Run the installer script (.ps1 or .sh)
```
./install.ps1
```

## Requirements

- Python 3.6+
- Playwright


## Usage

Navigate to `https://www.tokopedia.com/order-list`. Copy paste all of the invoice ID you want to download to `invoice_ids.txt`. Refer to `invoice_ids.example.txt` for examples.

The scrapper require your SID_TOKOPEDIA cookie for authorization. there're 3 ways to do this,
1. Use the --login parameter to open a login menu for tokopedia. It will save the SID directly from the session cookie.
```bash
python tokopedia_scrapper.py --login
```

2. Insert the token as a parameter

```bash
python tokopedia_scrapper.py --token <YOUR_TOKEN_HERE>
```

3. Put the token inside `token.txt` then run the script
```bash
python tokopedia_scrapper.py --token <YOUR_TOKEN_HERE>
```

The script will store your Invoice PDFs into `invoice_pdf` folder

### Options

- `--token <YOUR_TOKEN_HERE>`: specify your SID_TOKOPEDIA token
- `--login`: run the login flow to get the token automatically

## Disclaimer

This tool is for personal use only. Please respect Tokopedia's Terms of Service.

## License

MIT