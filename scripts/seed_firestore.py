# Copyright 2026 Google LLC
# Seed script for Firestore workout_plans collection.

import sys
from google.cloud import firestore

# HARDCODED GCP PROJECT ID (as required for Agent Platform compatibility)
FIRESTORE_PROJECT = "qwiklabs-gcp-02-6a284814c841"

SEED_WORKOUTS = [
    {
        "id": "workout_1",
        "name": "Full Body Strength Routine",
        "category": "Strength",
        "difficulty": "Intermediate",
        "duration_minutes": 45,
        "target_muscle_groups": ["Chest", "Back", "Legs", "Core"],
        "exercises": ["Barbell Squats 4x10", "Dumbbell Bench Press 4x10", "Bent-Over Rows 4x12", "Plank 3x60s"],
        "calories_burned_est": 350,
    },
    {
        "id": "workout_2",
        "name": "HIIT Cardio Burn",
        "category": "Cardio",
        "difficulty": "Beginner",
        "duration_minutes": 30,
        "target_muscle_groups": ["Full Body", "Cardio"],
        "exercises": ["Jumping Jacks 45s", "Mountain Climbers 45s", "Burpees 30s", "High Knees 45s"],
        "calories_burned_est": 300,
    },
    {
        "id": "workout_3",
        "name": "Mobility & Recovery Flow",
        "category": "Flexibility",
        "difficulty": "All Levels",
        "duration_minutes": 25,
        "target_muscle_groups": ["Hamstrings", "Hips", "Shoulders", "Spine"],
        "exercises": ["Cat-Cow Stretch 2m", "Downward Dog 90s", "Pigeon Pose 2m per side", "Child's Pose 3m"],
        "calories_burned_est": 100,
    },
    {
        "id": "workout_4",
        "name": "Upper Body Hypertrophy",
        "category": "Strength",
        "difficulty": "Advanced",
        "duration_minutes": 50,
        "target_muscle_groups": ["Biceps", "Triceps", "Shoulders", "Chest"],
        "exercises": ["Overhead Shoulder Press 4x8", "Incline Dumbbell Press 4x10", "Bicep Curls 3x12", "Tricep Dips 3x15"],
        "calories_burned_est": 400,
    },
]


def main():
    print(f"Connecting to Firestore for project: {FIRESTORE_PROJECT}...")
    db = firestore.Client(project=FIRESTORE_PROJECT, database="(default)")
    collection_ref = db.collection("workout_plans")

    for item in SEED_WORKOUTS:
        doc_id = item["id"]
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(item)
        print(f"  ✓ Seeded document: {doc_id} -> '{item['name']}'")

    print(f"Successfully seeded {len(SEED_WORKOUTS)} items into 'workout_plans' collection.")


if __name__ == "__main__":
    main()
