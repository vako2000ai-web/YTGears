"""Original synthesized sound beds. No downloaded or third-party music assets."""
from pathlib import Path
import math
import random
import struct
import wave


def create_audio(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    rate = 22050
    random_ = random.Random(70)
    def save(name, seconds, sample):
        path = directory / f"{name}.wav"
        if not path.exists():
            frames = bytearray()
            for i in range(round(rate * seconds)):
                t = i / rate
                value = max(-.98, min(.98, sample(t)))
                frames.extend(struct.pack("<h", int(value * 32767)))
            with wave.open(str(path), "wb") as file:
                file.setnchannels(1); file.setsampwidth(2); file.setframerate(rate); file.writeframes(frames)
        return path
    paths = {}
    paths["mechanism"] = save("mechanism", 2, lambda t: .12 * math.sin(math.tau * 82 * t)
        + .035 * math.sin(math.tau * 164 * t) + .12 * random_.uniform(-1, 1) * math.exp(-((t * 8) % 1) * 36))
    paths["impact"] = save("impact", 2.8, lambda t: .7 * random_.uniform(-1, 1) * math.exp(-t * 8)
        + .25 * math.sin(math.tau * 95 * t) * math.exp(-t * 16)
        + .18 * math.sin(math.tau * 1730 * t) * math.exp(-t * 2.7)
        + .3 * random_.uniform(-1, 1) * math.exp(-t * 2.1) * (.3 + .7 * abs(math.sin(t * 41))))
    paths["music"] = save("ambient", 8, lambda t: sum(.065 * math.sin(math.tau * f * t + .15 * math.sin(math.tau * .125 * t))
        for f in (110, 165, 220, 261.625)) * (.7 + .3 * math.sin(math.pi * t / 8)**2))
    return paths
