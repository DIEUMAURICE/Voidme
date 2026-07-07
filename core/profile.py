import json
import os
from datetime import datetime

class UserProfile:
    def __init__(self, profile_path):
        self.path = profile_path
        if not os.path.exists(profile_path):
            self.data = {
                "name": "User",
                "preferences": {},
                "habits": [],
                "facts": [],
                "last_conversations": [],
                "mood": "neutral",
                "first_seen": datetime.now().isoformat(),
                "interaction_count": 0
            }
            self.save()
        else:
            with open(profile_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)

    def get(self, key=None):
        if key is None:
            return self.data
        return self.data.get(key)

    def update(self, key, value):
        self.data[key] = value
        self.save()

    def add_fact(self, fact):
        if "facts" not in self.data:
            self.data["facts"] = []
        self.data["facts"].append(fact)
        self.save()

    def add_conversation(self, summary):
        if "last_conversations" not in self.data:
            self.data["last_conversations"] = []
        self.data["last_conversations"].append({
            "timestamp": datetime.now().isoformat(),
            "summary": summary
        })
        if len(self.data["last_conversations"]) > 20:
            self.data["last_conversations"] = self.data["last_conversations"][-20:]
        self.data["interaction_count"] += 1
        self.save()

    def set_mood(self, mood):
        self.data["mood"] = mood
        self.save()

    def save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)