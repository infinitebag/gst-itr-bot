SUPPORTED_LANGS = ["en", "hi", "gu", "ta", "te"]

MESSAGES = {
    "LANG_PROMPT": {
        "en": "Choose language:\n1. English\n2. Hindi\n3. Gujarati\n4. Tamil\n5. Telugu",
        "hi": "भाषा चुनें:\n1. English\n2. Hindi\n3. Gujarati\n4. Tamil\n5. Telugu",
        "gu": "ભાષા પસંદ કરો:\n1. English\n2. Hindi\n3. Gujarati\n4. Tamil\n5. Telugu",
        "ta": "மொழியைத் தேர்ந்தெடு:\n1. English\n2. Hindi\n3. Gujarati\n4. Tamil\n5. Telugu",
        "te": "భాషను ఎంచుకోండి:\n1. English\n2. Hindi\n3. Gujarati\n4. Tamil\n5. Telugu",
    },

    "MAIN_MENU": {
        "en": "Menu:\n1. GST Filing\n2. ITR Filing\n3. Upload Invoice\n4. Help",
        "hi": "मेनू:\n1. GST फाइलिंग\n2. ITR फाइलिंग\n3. इनवॉइस अपलोड\n4. सहायता",
        "gu": "મેનુ:\n1. GST ફાઇલિંગ\n2. ITR ફાઇલિંગ\n3. ઇનવૉઇસ અપલોડ\n4. મદદ",
        "ta": "பட்டி:\n1. GST பதிவு\n2. ITR பதிவு\n3. ரசீது பதிவேற்று\n4. உதவி",
        "te": "మెనూ:\n1. GST ఫైలింగ్\n2. ITR ఫైలింగ్\n3. ఇన్వాయిస్ అప్‌లోడ్\n4. సహాయం",
    },

    "ASK_GST_PERIOD": {
        "en": "Send GST period as YYYY-MM (e.g., 2025-11)",
        "hi": "कृपया YYYY-MM (जैसे 2025-11) भेजें",
        "gu": "કૃપા કરીને YYYY-MM (જેમ 2025-11) મોકલો",
        "ta": "YYYY-MM (எ.கா. 2025-11) என அனுப்பவும்",
        "te": "దయచేసి YYYY-MM (ఉదా: 2025-11) పంపండి",
    }
}

def t(key: str, lang: str):
    lang = lang if lang in SUPPORTED_LANGS else "en"
    return MESSAGES[key][lang]