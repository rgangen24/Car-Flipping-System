# APEX Auction Intelligence System - v1.0.1
import os
import tempfile
import json
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

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
        
        # Use Gemini 2.0 Flash for fast vision tasks
        model = genai.GenerativeModel('gemini-2.0-flash')
        
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
        return {"success": False, "error": str(e)}
    finally:
        os.remove(temp_path)
