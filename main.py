# APEX Auction Intelligence System - v1.0.1
import os
import tempfile
import json
from fastapi import FastAPI, UploadFile, File, Body
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
import re
from typing import List, Optional

# Optional Generative AI integration
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini if key is present
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if HAS_GENAI and API_KEY:
    genai.configure(api_key=API_KEY)

@app.get("/")
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

class AuctionURL(BaseModel):
    url: str

@app.post("/api/fetch-auction-data")
async def fetch_auction_data(data: AuctionURL):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(data.url, timeout=10.0)
            if response.status_code != 200:
                return {"success": False, "error": "Could not reach website"}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Auction Nation usually puts the car title in <h1> or specific meta tags
            title = ""
            h1 = soup.find('h1')
            if h1:
                title = h1.text.strip()
            else:
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.text.strip()

            # Clean title and extract year
            # Example: "2018 VW POLO VIVO 1.4 TRENDLINE"
            year_match = re.search(r'\b(20\d{2}|19\d{2})\b', title)
            year = int(year_match.group(0)) if year_match else 2018
            
            # Remove year from model name
            model_name = title.replace(str(year), "").strip() if year_match else title

            # Extract Odometer, Start Status, Keys from listing-details
            specs = {}
            listing_details = soup.select_one('.listing-details, .vehicle-details')
            if listing_details:
                # Find all items that might contain labels and values
                items = listing_details.find_all(['b', 'div', 'li', 'span'])
                for item in items:
                    text = item.text.strip().lower()
                    # Check for icons (text-success means Yes)
                    has_check = item.find('i', class_='text-success') is not None
                    
                    if 'odometer' in text or 'mileage' in text:
                        # Extract the next text node or sibling
                        val = item.next_sibling if item.next_sibling else ""
                        specs['odometer'] = str(val).strip().replace(":", "") or text.split(':')[-1].strip()
                    if 'starts' in text:
                        specs['starts'] = "YES" if has_check else "NO"
                    if 'keys' in text:
                        specs['keys'] = "YES" if has_check else "NO"
                    if 'code' in text:
                        val = item.next_sibling if item.next_sibling else ""
                        specs['code'] = str(val).strip().replace(":", "") or text.split(':')[-1].strip()

            # Extract Images (Deep Scan)
            image_urls = []
            img_selectors = [
                '.slick-slide:not(.slick-cloned) img',
                'li img.current-image',
                '.vehicle-image img',
                '.gallery-item img'
            ]
            for sel in img_selectors:
                for img in soup.select(sel):
                    src = img.get('src') or img.get('data-src') or img.get('srcset')
                    if src and ('cloudfront' in src or 'auctionnation' in src):
                        if src.startswith('//'): src = 'https:' + src
                        if src not in image_urls: image_urls.append(src)
            
            # Fallback: any image in the main content area
            if not image_urls:
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src and ('vehicles' in src or 'lot' in src or 'prod' in src):
                        if src not in image_urls: image_urls.append(src)

            # Limit to top 10 for AI analysis
            analysis_images = image_urls[:10]
            
            return {
                "success": True,
                "model": model_name,
                "year": year,
                "odometer": specs.get('odometer', 'Unknown'),
                "starts": specs.get('starts', 'Unknown'),
                "has_keys": specs.get('keys', 'Unknown'),
                "code": specs.get('code', 'Unknown'),
                "image_urls": analysis_images
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

class AnalysisRequest(BaseModel):
    image_urls: Optional[List[str]] = None

@app.post("/api/analyze-vehicle")
async def analyze_vehicle(
    file: Optional[UploadFile] = File(None),
    request_data: Optional[AnalysisRequest] = Body(None)
):
    print("DEBUG: Handling analyze-vehicle request")
    # Fallback to simulation if no API key is provided
    if not API_KEY or not HAS_GENAI:
        import random
        import asyncio
        await asyncio.sleep(2)
        damages = ["bumper-rep", "frontend-rep", "paint-rep", "airbags-rep"]
        selected = random.sample(damages, random.randint(1, 3))
        return {
            "success": True, 
            "damages": selected, 
            "insight": "[SIMULATION MODE] Set GEMINI_API_KEY in your environment for real AI analysis."
        }

    # Save temp files
    temp_paths = []
    
    if file:
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(await file.read())
            temp_paths.append(temp.name)
    elif request_data and request_data.image_urls:
        async with httpx.AsyncClient() as client:
            for url in request_data.image_urls[:5]: # Analyze top 5 images for speed/quota
                try:
                    img_resp = await client.get(url, timeout=5.0)
                    if img_resp.status_code == 200:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp:
                            temp.write(img_resp.content)
                            temp_paths.append(temp.name)
                except:
                    continue

    if not temp_paths:
        return {"success": False, "error": "No images provided for analysis"}

    try:
        # Upload to Gemini
        vision_files = [genai.upload_file(p) for p in temp_paths]
        
        # Use the correct 2026-era model name found via diagnostics
        try:
            model = genai.GenerativeModel('gemini-flash-latest')
        except:
            model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = """
        You are APEX, a Cape Town car salvage expert. Examine these car auction photos (Interior and Exterior).
        
        1. Detect damage types: bumper-rep, frontend-rep, paint-rep, airbags-rep.
        2. Provide a 'Pro Strategy' insight. 
           - Look for warning lights on the dashboard.
           - Check for severe structural bends in the engine bay.
           - Note if the interior looks abused or well-kept.
        
        Return raw JSON:
        {"damages": ["..."], "insight": "..."}
        """
        
        response = model.generate_content([*vision_files, prompt])
        for f in vision_files: genai.delete_file(f.name)
        
        try:
            # Clean possible markdown block
            raw_text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_text)
            return {"success": True, "damages": data.get("damages", []), "insight": data.get("insight", "")}
        except Exception as e:
            return {"success": False, "error": f"Failed to parse AI output: {response.text}"}
            
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            try:
                models = [m.name for m in genai.list_models()]
                error_msg += f" | Available models: {', '.join(models)}"
            except:
                pass
        return {"success": False, "error": error_msg}
    finally:
        os.remove(temp_path)
