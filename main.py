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
            
            return {
                "success": True,
                "model": model_name,
                "year": year
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/analyze-vehicle")
async def analyze_vehicle(file: UploadFile = File(...)):
    print("DEBUG: Handling analyze-vehicle request with Gemini 2.0")
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

    # Save temp file
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(await file.read())
        temp_path = temp.name

    try:
        # Upload to Gemini
        vision_file = genai.upload_file(temp_path)
        
        # Use the correct 2026-era model name found via diagnostics
        try:
            model = genai.GenerativeModel('gemini-flash-latest')
        except:
            model = genai.GenerativeModel('gemini-2.5-flash')
        
        
        prompt = """
        You are APEX, a Cape Town car salvage expert with 20 years of experience in the Wingfield and Aucor auction circuits. 
        Examine this car auction photo carefully.
        
        1. Detect specific damage types from this list:
           - bumper-rep (Bumper damage)
           - frontend-rep (Front-end impact, radiator/grill)
           - paint-rep (Paint scratches, minor panel dents)
           - airbags-rep (Airbags deployed inside)
        
        2. Provide a 'Pro Strategy' insight. Mention things like:
           - If it's a front-end hit, warn about hidden radiator/intercooler costs.
           - If it's a VW/Audi, mention common clip breakages.
           - If it looks like a cheap previous repair, point it out.
        
        Return ONLY a raw JSON object (no markdown, no codeblocks):
        {
            "damages": ["bumper-rep", "paint-rep"], 
            "insight": "Expert observation about the damage severity or hidden risks."
        }
        """
        
        response = model.generate_content([vision_file, prompt])
        genai.delete_file(vision_file.name)
        
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
