# app/infrastructure/external/translation_bhashini.py
"""
Bhashini (MeitY) Neural Machine Translation integration.

Uses the ULCA pipeline for Indic language translation.

Requires environment variables:
    BHASHINI_USER_ID                   — your Bhashini user ID
    BHASHINI_ULCA_API_KEY              — ULCA API key
    BHASHINI_TRANSLATION_PIPELINE_ID   — pipeline ID for NMT task
    BHASHINI_PIPELINE_BASE_URL         — base URL (default: https://meity-auth.ulcacontrib.org/ulca/apis)

If not configured, returns original text (graceful fallback).
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("translation_bhashini")

# Language code mapping (our codes → Bhashini/ULCA codes)
_LANG_MAP = {
    "en": "en",
    "hi": "hi",
    "gu": "gu",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
}


async def translate_with_bhashini(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> str:
    """Translate text using Bhashini ULCA NMT pipeline.

    Parameters
    ----------
    text : str
        Text to translate.
    source_lang : str
        Source language code (e.g. "hi", "ta"). Use "auto" for auto-detect.
    target_lang : str
        Target language code (default "en").

    Returns
    -------
    str
        Translated text. Returns original text if Bhashini is not configured
        or if translation fails.
    """
    user_id = settings.BHASHINI_USER_ID
    api_key = settings.BHASHINI_ULCA_API_KEY
    pipeline_id = settings.BHASHINI_TRANSLATION_PIPELINE_ID
    base_url = settings.BHASHINI_PIPELINE_BASE_URL

    if not user_id or not api_key or not pipeline_id:
        # Not configured — return original text silently
        return text

    src = _LANG_MAP.get(source_lang, source_lang)
    tgt = _LANG_MAP.get(target_lang, target_lang)

    # Step 1: Get pipeline config (compute endpoint + service ID)
    config_url = f"{base_url}/v0/model/getModelsPipeline"
    config_payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": src,
                        "targetLanguage": tgt,
                    }
                },
            }
        ],
        "pipelineRequestConfig": {
            "pipelineId": pipeline_id,
        },
    }
    config_headers = {
        "Content-Type": "application/json",
        "userID": user_id,
        "ulcaApiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Get pipeline compute config
            config_resp = await client.post(
                config_url, json=config_payload, headers=config_headers
            )
            config_resp.raise_for_status()
            config_data = config_resp.json()

            # Extract compute endpoint and service ID
            pipeline_config = config_data.get("pipelineResponseConfig", [{}])
            if not pipeline_config:
                logger.warning("Empty pipeline config from Bhashini")
                return text

            inference_url = config_data.get("pipelineInferenceAPIEndPoint", {}).get(
                "callbackUrl", ""
            )
            inference_key = config_data.get("pipelineInferenceAPIEndPoint", {}).get(
                "inferenceApiKey", {}
            ).get("value", "")

            if not inference_url:
                logger.warning("No inference URL from Bhashini pipeline config")
                return text

            service_id = pipeline_config[0].get("config", [{}])[0].get("serviceId", "")

            # Step 2: Call the inference endpoint
            inference_payload = {
                "pipelineTasks": [
                    {
                        "taskType": "translation",
                        "config": {
                            "language": {
                                "sourceLanguage": src,
                                "targetLanguage": tgt,
                            },
                            "serviceId": service_id,
                        },
                    }
                ],
                "inputData": {
                    "input": [{"source": text}],
                },
            }
            inference_headers = {
                "Content-Type": "application/json",
                "Authorization": inference_key,
            }

            infer_resp = await client.post(
                inference_url, json=inference_payload, headers=inference_headers
            )
            infer_resp.raise_for_status()
            infer_data = infer_resp.json()

            # Extract translated text
            outputs = infer_data.get("pipelineResponse", [{}])
            if outputs:
                output_list = outputs[0].get("output", [{}])
                if output_list:
                    translated = output_list[0].get("target", "")
                    if translated:
                        return translated

            logger.warning("Bhashini returned no translation: %s", infer_data)
            return text

    except httpx.HTTPStatusError as e:
        logger.warning("Bhashini HTTP error %d: %s", e.response.status_code, e)
        return text
    except Exception:
        logger.exception("Bhashini translation failed")
        return text
