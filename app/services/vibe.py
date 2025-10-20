from typing import Dict
from loguru import logger


async def analyze_vibe_safe(text: str):
    try:
        from transformers import pipeline
        clf = pipeline("sentiment-analysis")
        res = clf(text)
        # Map to simple emotions
        emotions: Dict[str, float] = {}
        for out in res:
            label = out.get('label', 'NEUTRAL').lower()
            score = float(out.get('score', 0.0))
            if 'pos' in label:
                emotions['positive'] = max(emotions.get('positive', 0.0), score)
            elif 'neg' in label:
                emotions['negative'] = max(emotions.get('negative', 0.0), score)
            else:
                emotions['neutral'] = max(emotions.get('neutral', 0.0), score)
        summary = max(emotions, key=emotions.get) if emotions else 'neutral'
        from app.models.schemas import VibeAnalysisResponse
        return VibeAnalysisResponse(emotions=emotions, summary=summary)
    except Exception as e:
        logger.warning("Vibe analysis unavailable: {}", e)
        from app.models.schemas import VibeAnalysisResponse
        return VibeAnalysisResponse(emotions={"neutral": 1.0}, summary="neutral")
