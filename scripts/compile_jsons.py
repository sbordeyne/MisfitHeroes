from pathlib import Path
import json
from typing import TypedDict
import os


class ResultSource(TypedDict):
    source: str
    layout: str
    faction: str
    effect_category: str
    name: str
    effect_text: str
    cost: int
    victory_points: int | str
    regions: dict[str, dict[str, float]]
    artwork_path: str


class ResultEffect(TypedDict):
    category: str
    text: str


class ResultOutput(TypedDict):
    name: str
    cost: int
    effect: ResultEffect
    faction: str
    artwork_url: str
    points: int

ROOT_DIR = Path(__file__).parent.parent
output_file = ROOT_DIR / "data" / "cards.json"
output_file.parent.mkdir(parents=True, exist_ok=True)  # Ensure the output directory exists
current_data = json.loads(output_file.read_text(encoding="utf-8")) if output_file.exists() else {"backgrounds": [], "foregrounds": []}

def format_data(data: ResultSource) -> ResultOutput:
    name = data["name"]
    cost = data["cost"]
    victory_points = data["victory_points"]
    effect = {"text": data["effect_text"]}
    effect["category"] = data["effect_category"] or ""
    faction = data["faction"]
    layout = "backgrounds" if data["layout"] == "background" else "foregrounds"
    slug = data["artwork_path"].split("/")[-2]  # Extract the slug from the artwork_path
    artwork_url = f"https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/cards/{layout}/{slug}.png"
    points = int(victory_points) if isinstance(victory_points, int) else -1
    return {
        "name": name,
        "cost": cost,
        "effect": effect,
        "faction": faction,
        "artwork_url": artwork_url,
        "points": points,
        "layout": layout
    }


total: list[ResultOutput] = []



for json_file in ROOT_DIR.glob("assets/processed/**/results.json"):
    data: ResultSource = json.loads(json_file.read_text(encoding="utf-8"))

    # Write the new dictionary to a JSON file in the output directory
    formatted = format_data(data)
    total.append(formatted)

for item in total:
    current_data[item["layout"]].append(item)

output_file.write_text(json.dumps(current_data, indent=2, ensure_ascii=False), encoding="utf-8")
