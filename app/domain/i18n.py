# app/domain/i18n.py

SUPPORTED_LANGS = ["en", "hi", "gu", "ta", "te"]

MESSAGES = {
    # Language selection prompt
    "LANG_PROMPT": {
        "en": "Choose language:\n1. English\n2. हिन्दी\n3. ગુજરાતી\n4. தமிழ்\n5. తెలుగు\n\nYou can send 0 anytime to go back to the main menu.",
        "hi": "भाषा चुनें:\n1. English\n2. हिन्दी\n3. ગુજરાતી\n4. தமிழ்\n5. తెలుగు\n\nआप कभी भी 0 भेजकर मुख्य मेनू पर जा सकते हैं।",
        "gu": "ભાષા પસંદ કરો:\n1. English\n2. हिन्दी\n3. ગુજરાતી\n4. தமிழ்\n5. తెలుగు\n\nતમે કોઈપણ સમયે 0 મોકલીને મુખ્ય મેનુ પર જઈ શકો છો.",
        "ta": "மொழியைத் தேர்ந்தெடுக்கவும்:\n1. English\n2. हिन्दी\n3. ગુજરાતી\n4. தமிழ்\n5. తెలుగు\n\nஎப்போது வேண்டுமானாலும் 0 அனுப்பி முதன்மை பட்டிக்கு செல்லலாம்.",
        "te": "భాషను ఎంచుకోండి:\n1. English\n2. हिन्दी\n3. ગુજરાતી\n4. தமிழ்\n5. తెలుగు\n\nఎప్పుడైనా 0 పంపి మెయిన్ మెనూకి వెళ్ళవచ్చు.",
    },
    # Main Menu
    "MAIN_MENU": {
        "en": "Main Menu:\n1. GST Filing\n2. ITR Filing\n3. Upload Invoice\n4. Help\n5. Change language\n0. Show this main menu again",
        "hi": "मुख्य मेनू:\n1. GST फाइलिंग\n2. ITR फाइलिंग\n3. इनवॉइस अपलोड\n4. सहायता\n5. भाषा बदलें\n0. मुख्य मेनू फिर से दिखाएँ",
        "gu": "મુખ્ય મેનુ:\n1. GST ફાઇલિંગ\n2. ITR ફાઇલિંગ\n3. ઇનવૉઇસ અપલોડ\n4. મદદ\n5. ભાષા બદલો\n0. મુખ્ય મેનુ ફરી બતાવો",
        "ta": "முதன்மை பட்டி:\n1. GST பதிவு\n2. ITR பதிவு\n3. ரசீது பதிவேற்றம்\n4. உதவி\n5. மொழியை மாற்றவும்\n0. முதன்மை பட்டியை மீண்டும் காட்டு",
        "te": "మెయిన్ మెనూ:\n1. GST ఫైలింగ్\n2. ITR ఫైలింగ్\n3. ఇన్వాయిస్ అప్‌లోడ్\n4. సహాయం\n5. భాష మార్చండి\n0. మెయిన్ మెనూని మళ్లీ చూపించు",
    },
    # GST sub-menu
    "GST_MENU": {
        "en": "GST Menu:\n1. GSTR-3B Summary\n2. GSTR-1 (B2B/B2C) Preview\n3. Back to Main Menu\n0. Back to Main Menu",
        "hi": "GST मेनू:\n1. GSTR-3B सारांश\n2. GSTR-1 (B2B/B2C) पूर्वावलोकन\n3. मुख्य मेनू पर वापस\n0. मुख्य मेनू पर वापस",
        "gu": "GST મેનુ:\n1. GSTR-3B સારાંશ\n2. GSTR-1 (B2B/B2C) પૂર્વદર્શન\n3. મુખ્ય મેનુ પર પાછા જાઓ\n0. મુખ્ય મેનુ પર પાછા જાઓ",
        "ta": "GST பட்டி:\n1. GSTR-3B சுருக்கம்\n2. GSTR-1 (B2B/B2C) முன்னோட்டம்\n3. முதன்மை பட்டிக்கு திரும்ப\n0. முதன்மை பட்டிக்கு திரும்ப",
        "te": "GST మెనూ:\n1. GSTR-3B సారాంశం\n2. GSTR-1 (B2B/B2C) ప్రివ్యూ\n3. మెయిన్ మెనుకి వెనక్కి\n0. మెయిన్ మెనుకి వెనక్కి",
    },
    # Ask period for 3B
    "ASK_GST_PERIOD_3B": {
        "en": "Send GST period for GSTR-3B as YYYY-MM (e.g., 2025-11).\nSend 0 to go back to the main menu.",
        "hi": "GSTR-3B के लिए अवधि YYYY-MM के रूप में भेजें (जैसे 2025-11)।\nमुख्य मेनू पर वापस जाने के लिए 0 भेजें।",
        "gu": "GSTR-3B માટે સમયગાળો YYYY-MM તરીકે મોકલો (જેમ કે 2025-11).\nમુખ્ય મેનુ પર પાછા જવા માટે 0 મોકલો.",
        "ta": "GSTR-3B க்கான காலத்தை YYYY-MM வடிவில் அனுப்பவும் (எ.கா. 2025-11).\nமுதன்மை பட்டிக்கு திரும்ப 0 அனுப்பவும்.",
        "te": "GSTR-3B కోసం కాలాన్ని YYYY-MM రూపంలో పంపండి (ఉదా: 2025-11).\nమెయిన్ మెనుకి వెనక్కి వెళ్లడానికి 0 పంపండి.",
    },
    # Ask period for 1
    "ASK_GST_PERIOD_1": {
        "en": "Send GST period for GSTR-1 as YYYY-MM (e.g., 2025-11).\nSend 0 to go back to the main menu.",
        "hi": "GSTR-1 के लिए अवधि YYYY-MM के रूप में भेजें (जैसे 2025-11)।\nमुख्य मेनू पर वापस जाने के लिए 0 भेजें।",
        "gu": "GSTR-1 માટે સમયગાળો YYYY-MM તરીકે મોકલો (જેમ કે 2025-11).\nમુખ્ય મેનુ પર પાછા જવા માટે 0 મોકલો.",
        "ta": "GSTR-1 க்கான காலத்தை YYYY-MM வடிவில் அனுப்பவும் (எ.கா. 2025-11).\nமுதன்மை பட்டிக்கு திரும்ப 0 அனுப்பவும்.",
        "te": "GSTR-1 కోసం కాలాన్ని YYYY-MM రూపంలో పంపండి (ఉదా: 2025-11).\nమెయిన్ మెనుకి వెనక్కి వెళ్లడానికి 0 పంపండి.",
    },
    "INVALID_CHOICE": {
        "en": "Invalid choice. Please send one of the shown options.\nYou can send 0 anytime to go back to the main menu.",
        "hi": "गलत विकल्प। कृपया दिए गए विकल्पों में से एक भेजें।\nआप कभी भी 0 भेजकर मुख्य मेनू पर जा सकते हैं।",
        "gu": "ખોટો વિકલ્પ. કૃપા કરીને બતાવેલા વિકલ્પોમાંથી એક મોકલો.\nતમે કોઈપણ સમયે 0 મોકલીને મુખ્ય મેનુ પર જઈ શકો છો.",
        "ta": "தவறான தேர்வு. காட்டப்பட்ட விருப்பங்களில் ஒன்றை அனுப்பவும்.\nஎப்போது வேண்டுமானாலும் 0 அனுப்பி முதன்மை பட்டிக்கு செல்லலாம்.",
        "te": "తప్పు ఎంపిక. చూపిన ఎంపికలలో ఒకదాన్ని పంపండి.\nఎప్పుడైనా 0 పంపి మెయిన్ మెనుకి వెళ్ళవచ్చు.",
    },
}


def t(key: str, lang: str) -> str:
    """Simple translation helper: get message by key + language."""
    lang = lang if lang in SUPPORTED_LANGS else "en"
    return MESSAGES.get(key, {}).get(lang, MESSAGES.get(key, {}).get("en", key))
