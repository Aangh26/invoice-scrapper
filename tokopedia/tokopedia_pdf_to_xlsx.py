import os
import re
from datetime import datetime
import pandas as pd
from pypdf import PdfReader
from openpyxl.styles import Alignment, numbers
# --- configurations ---
# Indonesian month mapping
MONTH_MAP = {
    'Januari': '01', 'Februari': '02', 'Maret': '03', 'April': '04',
    'Mei': '05', 'Juni': '06', 'Juli': '07', 'Agustus': '08',
    'September': '09', 'Oktober': '10', 'November': '11', 'Desember': '12'
}

# Folder path
PDF_DIR = "invoices_pdf"
OUTPUT_FILE = f"{PDF_DIR}\\invoice_data.xlsx"

# --- script logic ---

def parse_indonesian_date(date_str):
    """Convert 'dd <Month Name in Indonesian> yyyy' to datetime object."""
    match = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', date_str)
    if match:
        day, month_str, year = match.groups()
        month = MONTH_MAP.get(month_str.capitalize(), '01')
        return datetime.strptime(f"{day}-{month}-{year}", "%d-%m-%Y")
    return None

def extract_invoice_data(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Invoice ID: first line
    invoice_id = lines[0] if lines else ''
    
    # Transaction time
    transaction_time = None
    for line in lines:
        if "Tanggal Pembelian" in line:
            transaction_time = parse_indonesian_date(line)
            break

    # Recap: between "INVOICE" or line ending with "0", and line containing "Berat:"
    start_index = end_index = None
    for i, line in enumerate(lines):
        if "INVOICE" in line or line.endswith("0"):
            start_index = i + 1
            break
    for i in range(start_index or 0, len(lines)):
        if line := lines[i]:
            if "Berat:" in line:
                end_index = i
                break
    recap = "\n".join(lines[start_index:end_index]) if start_index and end_index else ''

    # Price: find line starting with TOTAL BELANJA Rp... but NOT containing 'INVOICE'
    price = ''
    for line in lines:
        if "TOTAL BELANJA" in line and "Rp" in line and "INVOICE" not in line:
            match = re.search(r'Rp[\d.,]+', line)
            if match:
                price = match.group()
                break

    return {
        "invoice_id": invoice_id,
        "transaction_time": transaction_time,
        "recap": recap,
        "price": price
    }

data = []

# Loop through PDFs
for filename in os.listdir(PDF_DIR):
    if filename.lower().endswith(".pdf"):
        pdf_path = os.path.join(PDF_DIR, filename)
        try:
            reader = PdfReader(pdf_path)
            text = ''
            for page in reader.pages:
                text += page.extract_text() or ''
            invoice_info = extract_invoice_data(text)
            data.append(invoice_info)
        except Exception as e:
            print(f"Error reading {filename}: {e}")

# Create DataFrame
df = pd.DataFrame(data)# Add 'transaction_dd-mm' column
df['transaction_dd-mm'] = df['transaction_time'].dt.strftime('%d-%m')
cols = list(df.columns)
if 'transaction_time' in cols and 'transaction_dd-mm' in cols:
    cols.insert(cols.index('transaction_time') + 1, cols.pop(cols.index('transaction_dd-mm')))
    df = df[cols]
# print(df.head())

# Save to Excel
df.to_excel(OUTPUT_FILE, index=False)
print(f"Data saved to {OUTPUT_FILE}")
