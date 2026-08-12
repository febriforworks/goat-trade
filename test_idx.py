import cloudscraper
import json

http = cloudscraper.CloudScraper()
url = "https://idx.co.id/primary/TradingSummary/GetStockSummary?length=10&start=0"

print(f"Fetching {url}")
try:
    response = http.get(url)
    print(f"Status Code: {response.status_code}")
    print(f"Response Text (first 500 chars): {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
