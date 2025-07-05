# Install required packages and Playwright for Python
# This script installs the necessary Python packages and Playwright for web scraping.
Write-Host "Installing required packages for Python..." -ForegroundColor Green
# Check if pip is installed
if (-not (Get-Command pip -ErrorAction SilentlyContinue)) {
    Write-Host "pip is not installed. Please install Python and pip first." -ForegroundColor Red
    exit 1
}
# Install required packages from requirements.txt
Write-Host "Running: pip install -r requirements.txt" -ForegroundColor Cyan
pip install -r requirements.txt

# Simple Playwright Installation Script for Python
Write-Host "Installing Playwright for Python..." -ForegroundColor Green

# Install Playwright package using pip
Write-Host "Running: pip install playwright" -ForegroundColor Cyan
pip install playwright

# Install browser binaries
Write-Host "Running: playwright install" -ForegroundColor Cyan
playwright install

Write-Host "Playwright has been successfully installed!" -ForegroundColor Green
