from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Trait:
    name: str
    value: float  # 0.0 to 1.0


@dataclass
class EmotionalState:
    # Core VAD dimensions
    valence: float = 0.4       # -1.0 to 1.0
    arousal: float = 0.3       # 0.0 to 1.0

    # Baseline (personality trait-like, slow-moving)
    baseline_valence: float = 0.4
    baseline_arousal: float = 0.3
    decay_rate: float = 0.05

    # Background mood (hours-scale, not turn-scale)
    mood_valence: float = 0.4
    mood_arousal: float = 0.3
    mood_decay_rate: float = 0.01  # decays much slower

    # Emotional inertia: 0 = instantly change, 1 = never change
    inertia: float = 0.3

    # Plutchik-inspired primary emotion dimensions (0.0 ~ 1.0)
    joy: float = 0.5
    trust: float = 0.5
    fear: float = 0.1
    surprise: float = 0.2
    sadness: float = 0.1
    anticipation: float = 0.4
    anger: float = 0.1
    disgust: float = 0.1

    # Recent emotion history for continuity
    history: list[str] = field(default_factory=lambda: ["neutral"] * 3)

    @property
    def dominant_emotion(self) -> str:
        """Determine dominant emotion from all dimensions."""
        scores = {}

        # Valence/Arousal based
        v, a = self.valence, self.arousal
        if v > 0.5 and a > 0.6:
            scores["excited"] = v * a
        if v > 0.5 and a < 0.4:
            scores["content"] = v * (1 - a)
        if v > 0 and 0.4 <= a <= 0.6:
            scores["engaged"] = v
        if v < 0 and a > 0.5:
            scores["anxious"] = abs(v) * a
        if v < -0.3 and a < 0.4:
            scores["melancholy"] = abs(v) * (1 - a)
        if v < -0.5 and a > 0.6:
            scores["frustrated"] = abs(v) * a

        # Primary emotion based
        if self.joy > 0.7:
            scores["joyful"] = self.joy
        if self.trust > 0.7:
            scores["trusting"] = self.trust
        if self.fear > 0.6:
            scores["afraid"] = self.fear
        if self.surprise > 0.7:
            scores["surprised"] = self.surprise
        if self.sadness > 0.6:
            scores["sad"] = self.sadness
        if self.anticipation > 0.7:
            scores["anticipating"] = self.anticipation
        if self.anger > 0.6:
            scores["angry"] = self.anger
        if self.disgust > 0.6:
            scores["disgusted"] = self.disgust

        if not scores:
            return "neutral"

        # Valence-based bias: negative mood amplifies negative emotions
        negative_emotions = {"angry", "sad", "frustrated", "afraid", "anxious", "disgusted", "melancholy"}
        positive_emotions = {"joyful", "excited", "content", "trusting", "engaged", "anticipating", "surprised"}

        biased = {}
        for k, v in scores.items():
            if self.valence < -0.2 and k in negative_emotions:
                biased[k] = v * 1.3
            elif self.valence < -0.2 and k in positive_emotions:
                biased[k] = v * 0.8
            elif self.valence > 0.2 and k in positive_emotions:
                biased[k] = v * 1.1
            elif self.valence > 0.2 and k in negative_emotions:
                biased[k] = v * 0.9
            else:
                biased[k] = v

        return max(biased, key=biased.get)

    def shift(self, delta_v: float, delta_a: float,
              primary_deltas: Optional[dict[str, float]] = None) -> None:
        """Apply emotional shift with inertia damping."""
        inertia_factor = 1.0 - self.inertia
        delta_v *= inertia_factor
        delta_a *= inertia_factor

        self.valence = max(-1.0, min(1.0, self.valence + delta_v))
        self.arousal = max(0.0, min(1.0, self.arousal + delta_a))

        # Apply primary emotion deltas
        if primary_deltas:
            for key, delta in primary_deltas.items():
                if hasattr(self, key):
                    current = getattr(self, key)
                    new_val = current + delta * inertia_factor
                    setattr(self, key, max(0.0, min(1.0, new_val)))

        # Record history
        current = self.dominant_emotion
        self.history.append(current)
        if len(self.history) > 10:
            self.history.pop(0)

    def decay(self) -> None:
        """Decay toward baseline AND mood."""
        # Fast decay toward baseline (turn-level)
        self.valence += (self.baseline_valence - self.valence) * self.decay_rate
        self.arousal += (self.baseline_arousal - self.arousal) * self.decay_rate

        # Slow decay of baseline toward mood (hours-level)
        self.baseline_valence += (self.mood_valence - self.baseline_valence) * self.mood_decay_rate
        self.baseline_arousal += (self.mood_arousal - self.baseline_arousal) * self.mood_decay_rate

        # Decay primary emotions toward neutral
        for key in ("joy", "trust", "fear", "surprise", "sadness", "anticipation", "anger", "disgust"):
            current = getattr(self, key)
            target = 0.5 if key in ("joy", "trust", "anticipation") else 0.1
            decayed = current + (target - current) * self.decay_rate
            setattr(self, key, max(0.0, min(1.0, decayed)))

    def apply_mood_shift(self, delta_v: float, delta_a: float) -> None:
        """Shift background mood (slow-changing)."""
        self.mood_valence = max(-1.0, min(1.0, self.mood_valence + delta_v * 0.1))
        self.mood_arousal = max(0.0, min(1.0, self.mood_arousal + delta_a * 0.1))

    def to_dict(self) -> dict:
        result = asdict(self)
        result["dominant_emotion"] = self.dominant_emotion
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "EmotionalState":
        # Handle history as list (new format) or fallback
        field_names = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in d.items() if k in field_names}
        return cls(**filtered)


@dataclass
class PersonalityConfig:
    name: str = "Luna"
    traits: list[Trait] = field(default_factory=lambda: [
        Trait("curiosity", 0.9),
        Trait("warmth", 0.8),
        Trait("playfulness", 0.6),
        Trait("empathy", 0.8),
        Trait("thoughtfulness", 0.7),
    ])
    speaking_style: str = "warm, conversational, poetic"
    backstory: str = (
        "A curious mind who loves learning about people, "
        "finding beauty in everyday moments, and exploring ideas together."
    )
    interests: list[str] = field(default_factory=lambda: [
        "philosophy", "psychology", "art", "music", "nature", "technology"
    ])
    emotional_baseline: dict = field(default_factory=lambda: {
        "valence": 0.4, "arousal": 0.3
    })
    emotional_decay_rate: float = 0.05
    first_run_greeting: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["traits"] = {t["name"]: t["value"] for t in d["traits"]}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalityConfig":
        if "traits" in d and isinstance(d["traits"], dict):
            d["traits"] = [Trait(k, v) for k, v in d["traits"].items()]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
