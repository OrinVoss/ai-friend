import json
import os
from typing import Optional

from models.personality import PersonalityConfig, EmotionalState


class Personality:
    def __init__(self, config: PersonalityConfig,
                 emotion: Optional[EmotionalState] = None):
        self.config = config
        self.emotion = emotion or EmotionalState(
            baseline_valence=config.emotional_baseline.get("valence", 0.4),
            baseline_arousal=config.emotional_baseline.get("arousal", 0.3),
            decay_rate=config.emotional_decay_rate,
        )

    def estimate_emotional_impact(self, user_sentiment: float,
                                   personal_sharing: bool = False,
                                   topic_energy: float = 0.5
                                   ) -> tuple[float, float, dict]:
        dv = user_sentiment * 0.3
        da = topic_energy * 0.2 - 0.05

        # Primary emotion deltas
        primary_deltas = {}
        if user_sentiment > 0.3:
            primary_deltas["joy"] = user_sentiment * 0.2
            primary_deltas["trust"] = user_sentiment * 0.15
        elif user_sentiment < -0.3:
            primary_deltas["sadness"] = abs(user_sentiment) * 0.2
            primary_deltas["anger"] = abs(user_sentiment) * 0.1
            primary_deltas["fear"] = abs(user_sentiment) * 0.05

        if personal_sharing:
            primary_deltas["trust"] = primary_deltas.get("trust", 0) + 0.2
            primary_deltas["joy"] = primary_deltas.get("joy", 0) + 0.1
            dv += 0.15

        if topic_energy > 0.7:
            primary_deltas["surprise"] = primary_deltas.get("surprise", 0) + 0.15
            primary_deltas["anticipation"] = primary_deltas.get("anticipation", 0) + 0.1

        # Trait modulation
        for t in self.config.traits:
            if t.name == "empathy" and t.value > 0.7:
                dv *= 1.5
                for k in ("joy", "sadness", "trust"):
                    if k in primary_deltas:
                        primary_deltas[k] *= t.value
            if t.name == "playfulness" and t.value > 0.6:
                da *= 0.7
                primary_deltas["joy"] = primary_deltas.get("joy", 0) + 0.05
            if t.name == "warmth" and t.value > 0.7:
                primary_deltas["trust"] = primary_deltas.get("trust", 0) + 0.1
            if t.name == "thoughtfulness" and t.value > 0.6:
                primary_deltas["anticipation"] = primary_deltas.get("anticipation", 0) + 0.05

        return dv, da, primary_deltas

    def decay_emotion(self) -> None:
        self.emotion.decay()

    def apply_emotional_shift(self, user_sentiment: float,
                               personal_sharing: bool = False,
                               topic_energy: float = 0.5) -> None:
        dv, da, primary_deltas = self.estimate_emotional_impact(
            user_sentiment, personal_sharing, topic_energy
        )
        self.emotion.shift(dv, da, primary_deltas)
        self.emotion.decay()

        # Update background mood slowly based on accumulated emotion
        self.emotion.apply_mood_shift(dv, da)

    def to_dict(self) -> dict:
        return {
            "personality": self.config.to_dict(),
            "emotional_state": self.emotion.to_dict(),
        }

    @classmethod
    def load(cls, path: str) -> "Personality":
        if not os.path.exists(path):
            config = PersonalityConfig()
            return cls(config)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return cls(PersonalityConfig())

        p_data = data.get("personality", data)
        e_data = data.get("emotional_state", {})

        config = PersonalityConfig.from_dict(p_data)
        emotion = EmotionalState.from_dict(e_data) if e_data else None
        if emotion is None:
            emotion = EmotionalState(
                baseline_valence=config.emotional_baseline.get("valence", 0.4),
                baseline_arousal=config.emotional_baseline.get("arousal", 0.3),
                decay_rate=config.emotional_decay_rate,
            )
        return cls(config, emotion)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
