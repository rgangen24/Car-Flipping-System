import os
import json
import re
import base64
import tempfile
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
    image_urls: Optional[List[str]] = None
    image_data: Optional[List[str]] = None  # Base64 strings
    model_name: Optional[str] = "Unknown Vehicle"
    starts_status: Optional[str] = "Unknown"

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/health")
async def health_check():
    return {"status": "APEX AI Engine Online", "v": "1.3.3", "has_key": API_KEY is not None}

@app.post("/api/fetch-auction-data")
async def fetch_auction_data(data: AuctionURL):
    try:
        async with httpx.AsyncClient(follow_redirects=True) as h_client:
            # Set headers to look like a real browser
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = await h_client.get(data.url, timeout=10.0, headers=headers)
            if response.status_code != 200:
                return {"success": False, "error": f"Auction House unreachable (Status {response.status_code})"}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # PRECISION EXTRACTION
            title = "Unknown Car"
            title_tag = soup.find(id='vehTitle')
            if title_tag: title = title_tag.text.strip()
            
            year = 2018
            year_tag = soup.find(id='vehYear')
            if year_tag:
                try:
                    year = int(year_tag.text.strip())
                except:
                    year_match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
                    year = int(year_match.group(0)) if year_match else 2018

            model_name = title.replace(str(year), "").strip() if title else "Unknown Car"
            if not model_name or model_name.lower() == 'vehicles':
                model_name = title

            specs = {}
            odo_tag = soup.find(id='vehOdo')
            if odo_tag: specs['odometer'] = odo_tag.text.strip()
            
            starts_tag = soup.find(id='vehStarts')
            if starts_tag: specs['starts'] = "YES" if 'check' in str(starts_tag).lower() or 'yes' in starts_tag.text.lower() else "NO"
            
            # Advanced Image Extraction (Targeting 360 and Slider)
            image_urls = []
            # 1. Look for 360 front image
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'Photos/360/Front.jpg' in src:
                    if src.startswith('//'): src = 'https:' + src
                    image_urls.append(src)
            
            # 2. Look for slick slider images
            slick_imgs = soup.select('.slick-slide:not(.slick-cloned) img')
            for img in slick_imgs:
                src = img.get('src') or img.get('data-src')
                if src and 'cloudfront' in src:
                    if src.startswith('//'): src = 'https:' + src
                    if src not in image_urls: image_urls.append(src)

            # Fallback
            if len(image_urls) < 3:
                for img in soup.find_all('img'):
                    src = img.get('src', '')
                    if ('vehicles' in src or 'prod' in src) and 'cloudfront' in src:
                        if src.startswith('//'): src = 'https:' + src
                        if src not in image_urls: image_urls.append(src)

            return {
                "success": True,
                "model": model_name,
                "year": year,
                "odometer": specs.get('odometer', 'Unknown'),
                "starts": specs.get('starts', 'Unknown'),
                "image_urls": image_urls[:12]
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/analyze-vehicle")
async def analyze_vehicle(
    file: Optional[UploadFile] = File(None),
    request_data: Optional[AnalysisRequest] = Body(None)
):
    if not API_KEY or not client:
        return {"success": False, "error": "CRITICAL: GEMINI_API_KEY missing from Vercel settings."}

    parts = []
    try:
        # Handle Base64 Data (Nuclear Option)
        if request_data and request_data.image_data:
            for b64 in request_data.image_data[:5]:
                try:
                    if "," in b64: b64 = b64.split(",")[1]
                    img_bytes = base64.b64decode(b64)
                    parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
                except: continue

        # Handle Uploaded File
        if file:
            img_bytes = await file.read()
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

        # Handle URLs (Fallback)
        if not parts and request_data and request_data.image_urls:
            async with httpx.AsyncClient() as h_client:
                for url in request_data.image_urls[:5]:
                    try:
                        img_resp = await h_client.get(url, timeout=5.0)
                        if img_resp.status_code == 200:
                            parts.append(types.Part.from_bytes(data=img_resp.content, mime_type="image/jpeg"))
                    except: continue

        if not parts:
            return {"success": False, "error": "AI could not reach auction photos. Trying manual analysis..."}

        model_v = request_data.model_name if request_data else "Unknown"
        starts_v = request_data.starts_status if request_data else "Unknown"
        
        prompt = f"""
        You are a Senior Salvage Assessor in Cape Town. Analyze these photos for a {model_v}.
        Listing Status: Starts: {starts_v}.
        
        1. DAMAGES: Identify (bumper-rep, frontend-rep, paint-rep, airbags-rep).
        2. VALUE: Estimate the CLEAN RETAIL price (ARV) in South African Rands. Be realistic.
        3. INSIGHT: Note specific damage like 'Front bumper hanging', 'Airbag deployed', or 'Grille missing'.
        
        Return raw JSON ONLY:
        {{"damages": ["..."], "market_retail": 120000, "insight": "..."}}
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt, *parts],
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        
        data = json.loads(response.text)
        m_retail_raw = str(data.get("market_retail", "0"))
        m_retail_clean = "".join(filter(str.isdigit, m_retail_raw))
        m_retail = int(m_retail_clean) if m_retail_clean else 0

        return {
            "success": True, 
            "damages": data.get("damages", []), 
            "market_retail": m_retail,
            "insight": data.get("insight", "Analysis complete.")
        }

    except Exception as e:
        return {"success": False, "error": f"AI Engine Error: {str(e)}"}
