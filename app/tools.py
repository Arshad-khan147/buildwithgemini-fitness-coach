# Copyright 2026 Google LLC
# Firestore tools for fitness-coach agent.

from google.adk.tools import ToolContext
from google.cloud import firestore

# HARDCODED GCP PROJECT ID & BUCKET NAME (as required for Agent Platform compatibility)
FIRESTORE_PROJECT = "qwiklabs-gcp-02-6a284814c841"
MEDIA_BUCKET_NAME = "fitness-coach-media-qwiklabs-gcp-02-6a284814c841"


def get_firestore_client() -> firestore.Client:
    """Initialize Firestore client with hardcoded project ID string."""
    return firestore.Client(project=FIRESTORE_PROJECT, database="(default)")


def search_workout_routines(category: str = "", difficulty: str = "") -> list[dict]:
    """Search available workout routines from the Firestore catalog.

    Args:
        category: Optional category filter e.g. "Strength", "Cardio", "Flexibility".
        difficulty: Optional difficulty filter e.g. "Beginner", "Intermediate", "Advanced", "All Levels".

    Returns:
        List of matching workout routine objects.
    """
    db = get_firestore_client()
    collection_ref = db.collection("workout_plans")
    docs = collection_ref.stream()

    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id

        # Apply category filter
        if category and category.lower() not in data.get("category", "").lower():
            continue
        # Apply difficulty filter
        if difficulty and difficulty.lower() not in data.get("difficulty", "").lower():
            continue

        results.append(data)

    return results


def get_workout_routine(workout_id: str) -> dict:
    """Get detailed information about a specific workout routine by its ID.

    Args:
        workout_id: The ID of the workout routine (e.g. "workout_1", "workout_2").

    Returns:
        Workout routine details or error dict if not found.
    """
    db = get_firestore_client()
    doc_ref = db.collection("workout_plans").document(workout_id)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    else:
        return {"error": f"Workout routine '{workout_id}' not found."}


def log_workout_session(
    workout_name: str, duration_minutes: int, calories_burned: int = 0, notes: str = ""
) -> dict:
    """Log a completed workout session to the user's workout log history in Firestore.

    Args:
        workout_name: Name of the workout performed (e.g. "Full Body Strength Routine").
        duration_minutes: Duration of the workout in minutes.
        calories_burned: Estimated calories burned.
        notes: Optional notes or comments on how the workout felt.

    Returns:
        Confirmation object with saved workout log details.
    """
    db = get_firestore_client()
    logs_ref = db.collection("workout_logs")

    log_entry = {
        "workout_name": workout_name,
        "duration_minutes": duration_minutes,
        "calories_burned": calories_burned,
        "notes": notes,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }

    doc_ref = logs_ref.add(log_entry)[1]
    return {
        "status": "success",
        "log_id": doc_ref.id,
        "message": f"Successfully logged workout '{workout_name}' ({duration_minutes} mins).",
    }


def calculate_target_heart_rate(age: int, resting_heart_rate: int = 60) -> dict:
    """Calculates personalized target heart rate training zones based on age and resting heart rate.

    Args:
        age: The user's age in years.
        resting_heart_rate: Resting heart rate in beats per minute (default is 60 bpm).

    Returns:
        Dict containing max heart rate and target ranges for Fat Burn, Aerobic, and Peak zones.
    """
    max_hr = 220 - age
    hrr = max_hr - resting_heart_rate

    fat_burn_low = round(resting_heart_rate + hrr * 0.50)
    fat_burn_high = round(resting_heart_rate + hrr * 0.70)

    aerobic_low = round(resting_heart_rate + hrr * 0.70)
    aerobic_high = round(resting_heart_rate + hrr * 0.85)

    peak_low = round(resting_heart_rate + hrr * 0.85)
    peak_high = round(resting_heart_rate + hrr * 0.95)

    return {
        "age": age,
        "max_heart_rate_bpm": max_hr,
        "resting_heart_rate_bpm": resting_heart_rate,
        "zones": {
            "Fat Burn (50-70%)": f"{fat_burn_low} - {fat_burn_high} bpm",
            "Aerobic / Fitness (70-85%)": f"{aerobic_low} - {aerobic_high} bpm",
            "Peak / Anaerobic (85-95%)": f"{peak_low} - {peak_high} bpm",
        },
    }


def search_public_exercise_db(query: str = "") -> list[dict]:
    """Search the wger open-source public exercise database for exercises matching a query.

    Args:
        query: Optional search term to filter exercises by name, category, or targeted muscles.

    Returns:
        List of exercise details including name, category, muscles, equipment, and description.
    """
    import json
    import re
    import urllib.request

    url = "https://wger.de/api/v2/exerciseinfo/?limit=50"
    req = urllib.request.Request(url, headers={"User-Agent": "FitnessCoachAgent/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return [{"error": f"Failed to fetch public exercise database: {str(e)}"}]

    results = []
    q = query.lower().strip()

    for item in data.get("results", []):
        translations = item.get("translations", [])
        eng_trans = next((t for t in translations if t.get("language") == 2), None)
        if not eng_trans and translations:
            eng_trans = translations[0]

        name = (
            eng_trans.get("name", "")
            if eng_trans
            else (item.get("name") or "Unknown Exercise")
        )
        desc_raw = eng_trans.get("description", "") if eng_trans else ""
        description = re.sub("<[^<]+?>", "", desc_raw).strip()

        category = (
            item.get("category", {}).get("name", "")
            if isinstance(item.get("category"), dict)
            else ""
        )
        muscles = [
            m.get("name_en") or m.get("name", "")
            for m in item.get("muscles", [])
            if isinstance(m, dict)
        ]
        equipment = [
            eq.get("name", "")
            for eq in item.get("equipment", [])
            if isinstance(eq, dict)
        ]

        if q and not (
            q in name.lower()
            or q in category.lower()
            or q in description.lower()
            or any(q in m.lower() for m in muscles)
        ):
            continue

        results.append({
            "id": item.get("id"),
            "name": name,
            "category": category,
            "muscles": muscles,
            "equipment": equipment,
            "description": description[:200],
        })

    return results


def geocode_address(address: str) -> dict:
    """Converts a street address or city name into geographic coordinates (latitude and longitude).

    Args:
        address: The location or address string (e.g. "San Francisco, CA" or "1600 Amphitheatre Pkwy").

    Returns:
        Dict containing formatted address and location coordinates (latitude, longitude).
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY is not configured in environment."}

    encoded_address = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FitnessCoachAgent/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") == "OK" and data.get("results"):
            res = data["results"][0]
            loc = res["geometry"]["location"]
            return {
                "address": res.get("formatted_address"),
                "location": {
                    "latitude": loc["lat"],
                    "longitude": loc["lng"],
                },
            }
        else:
            return {"error": f"Geocoding failed for '{address}': {data.get('status')}"}
    except Exception as e:
        return {"error": f"Geocoding request failed: {str(e)}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "gym",
    radius_meters: float = 2000.0,
) -> list[dict]:
    """Finds nearby places (e.g. gyms, parks, sports complexes) of a given type around coordinates.

    Args:
        latitude: Latitude coordinate of the center point.
        longitude: Longitude coordinate of the center point.
        place_type: Type of place to search for (e.g. "gym", "park", "sports_complex").
        radius_meters: Search radius in meters (default is 2000.0 meters).

    Returns:
        List of matching nearby places with name, formatted address, location, and types.
    """
    import json
    import os
    import urllib.request

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return [{"error": "GOOGLE_MAPS_API_KEY is not configured in environment."}]

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.types",
    }
    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 10,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": float(radius_meters),
            }
        },
    }

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data_bytes, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            response_data = json.loads(resp.read().decode())

        places = []
        for p in response_data.get("places", []):
            display_name = p.get("displayName", {}).get("text", "")
            loc = p.get("location", {})
            places.append({
                "name": display_name,
                "address": p.get("formattedAddress", ""),
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                },
                "types": p.get("types", []),
            })

        return places
    except Exception as e:
        return [{"error": f"Nearby Places search failed: {str(e)}"}]


async def generate_exercise_diagram(
    prompt: str, tool_context: ToolContext
) -> dict:
    """Generates an exercise diagram or posture illustration using AI, saves it as a session artifact,
    and uploads it to Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the exercise or posture diagram to generate (e.g. "Anatomical diagram of proper squat form").

    Returns:
        Dict containing status, filename, public_url, and prompt.
    """
    import time
    from google import genai
    from google.cloud import storage
    from google.genai import types

    client = genai.Client(
        vertexai=True, project=FIRESTORE_PROJECT, location="global"
    )

    try:
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )

        if not resp.candidates or not resp.candidates[0].content.parts:
            return {"error": "No image content returned from model."}

        part = resp.candidates[0].content.parts[0]
        if not part.inline_data:
            return {"error": "Model response did not contain inline image bytes."}

        image_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "image/jpeg"

        ext = "jpg" if "jpeg" in mime_type else ("png" if "png" in mime_type else "bin")
        filename = f"exercise_diagram_{int(time.time())}.{ext}"

        # 1. Save artifact in session context (shows up in Playground Artifacts panel)
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to Cloud Storage bucket & construct public URL
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(MEDIA_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)
        public_url = f"https://storage.googleapis.com/{MEDIA_BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "filename": filename,
            "public_url": public_url,
            "prompt": prompt,
        }
    except Exception as e:
        return {"error": f"Failed to generate and upload exercise diagram: {str(e)}"}


async def generate_exercise_video(
    prompt: str, tool_context: ToolContext
) -> dict:
    """Generates a short exercise demonstration video using Google's Omni model (gemini-omni-flash-preview),
    saves it as a session artifact, and uploads it to Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the exercise or workout movement to generate (e.g. "Demonstrate a proper jumping jack").

    Returns:
        Dict containing status, filename, public_url, and prompt.
    """
    import base64
    import time
    from google import genai
    from google.cloud import storage
    from google.genai import types

    client = genai.Client(
        vertexai=True, project=FIRESTORE_PROJECT, location="global"
    )

    try:
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_obj = getattr(interaction, "output_video", None)
        if not video_obj or not getattr(video_obj, "data", None):
            return {"error": "No video content returned from model."}

        raw_data = video_obj.data
        if isinstance(raw_data, bytes):
            video_bytes = raw_data
        elif isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        else:
            return {"error": "Unexpected data type for video bytes."}

        mime_type = getattr(video_obj, "mime_type", None) or "video/mp4"
        ext = "mp4" if "mp4" in mime_type else "bin"
        filename = f"exercise_video_{int(time.time())}.{ext}"

        # 1. Save artifact in session context (shows up in Playground Artifacts panel)
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to Cloud Storage bucket & construct public URL
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(MEDIA_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)
        public_url = f"https://storage.googleapis.com/{MEDIA_BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "filename": filename,
            "public_url": public_url,
            "prompt": prompt,
        }
    except Exception as e:
        return {"error": f"Failed to generate and upload exercise video: {str(e)}"}





