import os
import json
import re
import tempfile
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, Body
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
    model_name: Optional[str] = "Unknown Vehicle"
    starts_status: Optional[str] = "Unknown"

@app.get("/")
async def read_root():
    return {"status": "APEX AI Engine Online", "v": "1.3.1", "has_key": API_KEY is not None}

@app.post("/api/fetch-auction-data")
async def fetch_auction_data(data: AuctionURL):
    try:
        async with httpx.AsyncClient() as h_client:
            response = await h_client.get(data.url, timeout=10.0)
            if response.status_code != 200:
                return {"success": False, "error": f"Auction House unreachable (Status {response.status_code})"}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # PRECISION EXTRACTION
            title = "Unknown Car"
            title_tag = soup.find(id='vehTitle')
            if title_tag:
                title = title_tag.text.strip()
            
            year = 2018
            year_tag = soup.find(id='vehYear')
            if year_tag:
                try:
                    year = int(year_tag.text.strip())
                except:
                    year_match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
                    year = int(year_match.group(0)) if year_match else 2018
            else:
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
            
            keys_tag = soup.find(id='vehKeys')
            if keys_tag: specs['keys'] = "YES" if 'check' in str(keys_tag).lower() or 'yes' in keys_tag.text.lower() else "NO"
            
            code_tag = soup.find(id='vehCode')
            if code_tag: specs['code'] = code_tag.text.strip()

            # Image Extraction
            image_urls = []
            img_selectors = ['.slick-slide:not(.slick-cloned) img', 'li img.current-image', '.vehicle-image img']
            for sel in img_selectors:
                for img in soup.select(sel):
                    src = img.get('src') or img.get('data-src') or img.get('srcset')
                    if src and ('cloudfront' in src or 'auctionnation' in src):
                        if src.startswith('//'): src = 'https:' + src
                        if src not in image_urls: image_urls.append(src)
            
            if not image_urls:
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src and ('vehicles' in src or 'lot' in src):
                        if src not in image_urls: image_urls.append(src)

            return {
                "success": True,
                "model": model_name,
                "year": year,
                "odometer": specs.get('odometer', 'Unknown'),
                "starts": specs.get('starts', 'Unknown'),
                "keys": specs.get('keys', 'Unknown'),
                "code": specs.get('code', 'Unknown'),
                "image_urls": image_urls[:10]
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/analyze-vehicle")
async def analyze_vehicle(
    file: Optional[UploadFile] = File(None),
    request_data: Optional[AnalysisRequest] = Body(None)
):
    if not API_KEY or not client:
        return {
            "success": False, 
            "error": "CRITICAL: GEMINI_API_KEY is missing from server environment. Go to Vercel Settings > Environment Variables and add it."
        }

    temp_paths = []
    try:
        if file:
            suffix = os.path.splitext(file.filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                temp.write(await file.read())
                temp_paths.append(temp.name)
        elif request_data and request_data.image_urls:
            async with httpx.AsyncClient() as h_client:
                for url in request_data.image_urls[:5]:
                    try:
                        img_resp = await h_client.get(url, timeout=5.0)
                        if img_resp.status_code == 200:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp:
                                temp.write(img_resp.content)
                                temp_paths.append(temp.name)
                    except:
                        continue

        if not temp_paths:
            return {"success": False, "error": "AI could not reach auction photos. Check your internet connection."}

        model_v = request_data.model_name if request_data else "Unknown"
        starts_v = request_data.starts_status if request_data else "Unknown"
        
        prompt = f"""
        You are a Senior Salvage Assessor in Cape Town. Analyze these photos for a {model_v}.
        Listing Status: Starts: {starts_v}.
        
        1. DAMAGES: Identify (bumper-rep, frontend-rep, paint-rep, airbags-rep).
        2. VALUE: Estimate the CLEAN RETAIL price in ZAR (South African Rands).
        3. INSIGHT: Note specific damage like 'Front bumper hanging', 'Airbag out', or 'Grille missing'.
        
        Return raw JSON ONLY:
        {{"damages": ["..."], "market_retail": 120000, "insight": "..."}}
        """

        images = []
        for p in temp_paths:
            with open(p, "rb") as f:
                images.append(types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt, *images],
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
    finally:
        for p in temp_paths:
            if os.path.exists(p): os.remove(p)
