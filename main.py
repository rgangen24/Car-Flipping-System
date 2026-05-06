import os
import json
import re
import base64
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

app = FastAPI()

# Configuration
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

class AuctionURL(BaseModel):
    url: str

class AnalysisRequest(BaseModel):
    image_data: Optional[List[str]] = None  # Base64 strings
    model_name: Optional[str] = "Unknown Vehicle"
    year: Optional[int] = 2018
    starts_status: Optional[str] = "Unknown"

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/health")
async def health_check():
    return {"status": "APEX AI Engine Online", "v": "1.4.2", "has_key": API_KEY is not None}

@app.post("/api/fetch-auction-data")
async def fetch_auction_data(data: AuctionURL):
    try:
        async with httpx.AsyncClient(follow_redirects=True) as h_client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = await h_client.get(data.url, timeout=15.0, headers=headers)
            if response.status_code != 200:
                return {"success": False, "error": f"Status {response.status_code}"}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find(id='vehTitle').text.strip() if soup.find(id='vehTitle') else "Unknown"
            year_val = 2018
            year_tag = soup.find(id='vehYear')
            if year_tag:
                try: year_val = int(year_tag.text.strip())
                except: pass
            
            starts = "YES" if 'check' in str(soup.find(id='vehStarts')).lower() else "NO"
            
            # EXTRACT ALL IMAGES
            image_urls = []
            base_url = ""
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'cloudfront.net' in src and '/Photos/' in src:
                    base_url = src.split('/Photos/')[0] + '/Photos/'
                    break
            
            if base_url:
                image_urls.extend([f"{base_url}360/Front.jpg", f"{base_url}360/Rear.jpg", f"{base_url}360/Dash.jpg", f"{base_url}360/Engine_All.jpg"])
                for i in range(1, 10): image_urls.append(f"{base_url}360/Additional_{i}.jpg")
            
            return {
                "success": True,
                "model": title,
                "year": year_val,
                "starts": starts,
                "image_urls": image_urls
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/analyze-vehicle")
async def analyze_vehicle(request_data: AnalysisRequest = Body(...)):
    if not API_KEY or not client:
        return {"success": False, "error": "API Key Missing"}

    parts = []
    if request_data.image_data:
        for b64 in request_data.image_data[:6]: # Optimized to 6 images for Vercel speed
            try:
                if "," in b64: b64 = b64.split(",")[1]
                parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))
            except: continue

    # Prompt now includes a UNIVERSAL VALUATION requirement
    prompt = f"""
    You are a Senior Salvage Assessor in South Africa. 
    Analyze this {request_data.year} {request_data.model_name}. 
    Listing Status: Starts: {request_data.starts_status}.
    
    TASK:
    1. ARV: Even if photos are missing, what is the CLEAN MARKET RETAIL for this car in ZAR?
    2. DAMAGES: Identify: (bumper-rep, frontend-rep, paint-rep, airbags-rep).
    3. DETAILED REPORT: Explain what you see or what is likely wrong.
    
    Return raw JSON ONLY:
    {{"damages": ["..."], "market_retail": 125000, "insight": "...", "detailed_report": "..."}}
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt, *parts] if parts else [prompt],
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        return {"success": True, **json.loads(response.text)}
    except Exception as e:
        return {"success": False, "error": f"AI Engine Timeout: {str(e)}"}
