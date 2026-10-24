"""Alert wording, in the five languages the citizen app offers.

English, Hindi and Assamese were written for the original prototype. Bengali
and Nepali, and every report-driven message (advisory / confirmed / all
clear), are MACHINE TRANSLATIONS awaiting review by a native speaker before
any real deployment — see NEEDS_NATIVE_REVIEW.

The severity band, zone, score, confidence and the ranked contributing factors
are always present — an alert that says only "danger" is not actionable, and an
alert without its confidence would overstate what the system knows.
"""
from __future__ import annotations

from .base import AlertPayload

NEEDS_NATIVE_REVIEW = {"bn", "ne", "as:report", "hi:report", "bn:report", "ne:report"}

SEVERITY_WORDS = {
    "en": {"LOW": "LOW", "MODERATE": "MODERATE", "HIGH": "HIGH", "CRITICAL": "CRITICAL"},
    "hi": {"LOW": "न्यून", "MODERATE": "मध्यम", "HIGH": "उच्च", "CRITICAL": "अति गंभीर"},
    "as": {"LOW": "কম", "MODERATE": "মধ্যম", "HIGH": "উচ্চ", "CRITICAL": "অতি গুৰুতৰ"},
    "bn": {"LOW": "কম", "MODERATE": "মাঝারি", "HIGH": "উচ্চ", "CRITICAL": "অতি গুরুতর"},
    "ne": {"LOW": "न्यून", "MODERATE": "मध्यम", "HIGH": "उच्च", "CRITICAL": "अति गम्भीर"},
}

TIER_WORDS = {
    "en": {"ADVISORY": "ADVISORY", "WARNING": "WARNING"},
    "hi": {"ADVISORY": "सलाह", "WARNING": "चेतावनी"},
    "as": {"ADVISORY": "পৰামৰ্শ", "WARNING": "সতৰ্কবাণী"},
    "bn": {"ADVISORY": "পরামর্শ", "WARNING": "সতর্কবার্তা"},
    "ne": {"ADVISORY": "सल्लाह", "WARNING": "चेतावनी"},
}

# Report-driven messages. The ADVISORY wording is deliberately cautious: it
# says the reports are unverified and tells people what to do meanwhile.
REPORT_TEXT = {
    "advisory": {
        "en": "Unverified public reports of a landslide near {place}. Stay alert, avoid the slope/road, await official confirmation.",
        "hi": "{place} के पास भूस्खलन की असत्यापित जन-सूचनाएँ। सतर्क रहें, ढलान/सड़क से दूर रहें, आधिकारिक पुष्टि की प्रतीक्षा करें।",
        "as": "{place}ৰ ওচৰত ভূমিস্খলনৰ অসত্যাপিত ৰাজহুৱা খবৰ। সজাগ থাকক, ঢাল/পথৰ পৰা আঁতৰি থাকক, চৰকাৰী নিশ্চিতকৰণৰ বাবে অপেক্ষা কৰক।",
        "bn": "{place}-এর কাছে ভূমিধসের অযাচাইকৃত জনসাধারণের খবর। সতর্ক থাকুন, ঢাল/রাস্তা এড়িয়ে চলুন, সরকারি নিশ্চিতকরণের অপেক্ষা করুন।",
        "ne": "{place} नजिक पहिरोको अपुष्ट सार्वजनिक सूचना। सतर्क रहनुहोस्, भिरालो/सडकबाट टाढा रहनुहोस्, आधिकारिक पुष्टिको प्रतीक्षा गर्नुहोस्।",
    },
    "confirmed": {
        "en": "WARNING: landslide near {place} confirmed by the district authority. Move away from the slope/road now and follow official instructions.",
        "hi": "चेतावनी: {place} के पास भूस्खलन की ज़िला प्रशासन ने पुष्टि की है। तुरंत ढलान/सड़क से दूर हटें और आधिकारिक निर्देशों का पालन करें।",
        "as": "সতৰ্কবাণী: {place}ৰ ওচৰত ভূমিস্খলন জিলা প্ৰশাসনে নিশ্চিত কৰিছে। এতিয়াই ঢাল/পথৰ পৰা আঁতৰি যাওক আৰু চৰকাৰী নিৰ্দেশ মানি চলক।",
        "bn": "সতর্কবার্তা: {place}-এর কাছে ভূমিধস জেলা প্রশাসন নিশ্চিত করেছে। এখনই ঢাল/রাস্তা থেকে সরে যান এবং সরকারি নির্দেশ মেনে চলুন।",
        "ne": "चेतावनी: {place} नजिक पहिरो जिल्ला प्रशासनले पुष्टि गरेको छ। तुरुन्तै भिरालो/सडकबाट टाढा जानुहोस् र आधिकारिक निर्देशन पालना गर्नुहोस्।",
    },
    "all_clear": {
        "en": "All clear: the reported landslide near {place} was checked by the district authority and found to be a false report. No action needed.",
        "hi": "सब सुरक्षित: {place} के पास बताए गए भूस्खलन की ज़िला प्रशासन ने जाँच की, सूचना गलत पाई गई। कोई कार्रवाई आवश्यक नहीं।",
        "as": "সকলো সুৰক্ষিত: {place}ৰ ওচৰত জনোৱা ভূমিস্খলন জিলা প্ৰশাসনে পৰীক্ষা কৰিছে, খবৰটো ভুল আছিল। একো কৰিবলগীয়া নাই।",
        "bn": "সব ঠিক আছে: {place}-এর কাছে জানানো ভূমিধস জেলা প্রশাসন পরীক্ষা করেছে, খবরটি ভুল ছিল। কোনো পদক্ষেপের প্রয়োজন নেই।",
        "ne": "सबै ठीक छ: {place} नजिक सूचित पहिरो जिल्ला प्रशासनले जाँच गर्‍यो, सूचना गलत थियो। कुनै कारबाही आवश्यक छैन।",
    },
}

DEMO_PREFIX = {"en": "[DEMO]", "hi": "[डेमो]", "as": "[ডেমো]", "bn": "[ডেমো]", "ne": "[डेमो]"}

_SUBJECT = {
    "en": "{severity} landslide risk — {zone}, {district}",
    "hi": "{severity} भूस्खलन जोखिम — {zone}, {district}",
    "as": "{severity} ভূমিস্খলনৰ বিপদ — {zone}, {district}",
    "bn": "{severity} ভূমিধসের ঝুঁকি — {zone}, {district}",
    "ne": "{severity} पहिरो जोखिम — {zone}, {district}",
}

_HEADLINE = {
    "en": "Landslide risk in {zone} has reached {severity}.",
    "hi": "{zone} में भूस्खलन का जोखिम {severity} स्तर पर पहुँच गया है।",
    "as": "{zone}ত ভূমিস্খলনৰ বিপদ {severity} স্তৰত উপনীত হৈছে।",
    "bn": "{zone}-এ ভূমিধসের ঝুঁকি {severity} স্তরে পৌঁছেছে।",
    "ne": "{zone} मा पहिरोको जोखिम {severity} स्तरमा पुगेको छ।",
}

_LABELS = {
    "en": {
        "score": "Risk score", "confidence": "Confidence", "factors": "Why this was raised",
        "roads": "Roads exposed", "villages": "Settlements exposed", "issued": "Issued",
        "advice": "Advisory", "open": "Open in dashboard",
        "advice_text": ("Restrict non-essential movement on the listed routes, position response "
                        "teams, and dispatch a field officer to verify slope condition."),
        "disclaimer": ("Decision support only — not a guaranteed prediction. Risk is an estimate "
                       "with the confidence shown above. ALL DATA IN THIS PROTOTYPE IS SIMULATED."),
    },
    "hi": {
        "score": "जोखिम स्कोर", "confidence": "विश्वास स्तर", "factors": "कारण",
        "roads": "प्रभावित सड़कें", "villages": "प्रभावित बस्तियाँ", "issued": "जारी",
        "advice": "सलाह", "open": "डैशबोर्ड खोलें",
        "advice_text": ("सूचीबद्ध मार्गों पर अनावश्यक आवागमन सीमित करें, बचाव दल तैनात करें, और "
                        "ढलान की स्थिति जाँचने हेतु क्षेत्रीय अधिकारी भेजें।"),
        "disclaimer": ("यह केवल निर्णय-सहायक अनुमान है, गारंटीशुदा भविष्यवाणी नहीं। इस प्रोटोटाइप "
                       "का समस्त डेटा सिम्युलेटेड है।"),
    },
    "as": {
        "score": "বিপদ স্ক'ৰ", "confidence": "নিশ্চয়তা", "factors": "কাৰণ",
        "roads": "প্ৰভাৱিত পথ", "villages": "প্ৰভাৱিত জনবসতি", "issued": "জাৰি",
        "advice": "পৰামৰ্শ", "open": "ডেশ্ববৰ্ড খোলক",
        "advice_text": ("তালিকাভুক্ত পথত অপ্ৰয়োজনীয় যাতায়াত সীমিত কৰক, উদ্ধাৰকাৰী দল প্ৰস্তুত ৰাখক, "
                        "আৰু ঢালৰ অৱস্থা পৰীক্ষা কৰিবলৈ ক্ষেত্ৰ বিষয়া পঠিয়াওক।"),
        "disclaimer": ("এয়া কেৱল সিদ্ধান্ত-সহায়ক অনুমান, নিশ্চিত ভৱিষ্যদ্বাণী নহয়। এই প্ৰ'ট'টাইপৰ "
                       "সকলো তথ্য অনুকৰণ কৰা।"),
    },
}


# Bengali and Nepali alerts reuse the English labels around the translated
# headline until the labels have been reviewed by native speakers.
_LABELS["bn"] = _LABELS["en"]
_LABELS["ne"] = _LABELS["en"]


def lang_of(payload: AlertPayload) -> str:
    return payload.language if payload.language in _LABELS else "en"


def report_line(kind: str, place: str, language: str = "en") -> str:
    """The one-sentence public message for a report-driven alert."""
    table = REPORT_TEXT[kind]
    return table.get(language, table["en"]).format(place=place or "your area")


def subject(payload: AlertPayload) -> str:
    lang = lang_of(payload)
    tier = TIER_WORDS[lang].get(payload.tier, payload.tier)
    if payload.kind == "moderator":
        return payload.title
    if payload.kind == "advisory":
        return f"{tier} — unverified landslide reports near {payload.place or payload.zone_name}"
    if payload.kind == "confirmed":
        return f"{tier} — landslide confirmed near {payload.place or payload.zone_name}"
    if payload.kind == "all_clear":
        return f"ALL CLEAR — false report near {payload.place or payload.zone_name}"
    return f"{tier} · " + _SUBJECT[lang].format(
        severity=SEVERITY_WORDS[lang].get(payload.severity, payload.severity),
        zone=payload.zone_name,
        district=payload.district,
    )


def headline(payload: AlertPayload) -> str:
    lang = lang_of(payload)
    if payload.kind == "moderator":
        return payload.title
    if payload.kind in REPORT_TEXT:
        return report_line(payload.kind, payload.place or payload.zone_name, payload.language)
    return _HEADLINE[lang].format(
        zone=payload.zone_name,
        severity=SEVERITY_WORDS[lang].get(payload.severity, payload.severity),
    )


def plain_text(payload: AlertPayload) -> str:
    lang = lang_of(payload)
    L = _LABELS[lang]
    lines = [
        "BHOOSHAKTI AI — LANDSLIDE EARLY WARNING",
        "[DEMO DATA — SIMULATED]",
        f"TIER: {payload.tier}"
        + ("  (machine-issued, awaiting human confirmation)" if payload.tier == "ADVISORY" else ""),
        "",
        headline(payload),
        "",
        f"{L['score']}: {payload.risk_score:.0f}/100    "
        f"{L['confidence']}: {payload.confidence * 100:.0f}%",
        f"Zone: {payload.zone_code} — {payload.zone_name}, {payload.district}, {payload.state}",
        f"{L['issued']}: {payload.issued_at.strftime('%d %b %Y, %H:%M UTC')}",
        "",
        f"{L['factors']}:",
    ]
    for i, line in enumerate(payload.factor_lines, 1):
        lines.append(f"  {i}. {line}")
    if payload.affected_roads:
        lines += ["", f"{L['roads']}: " + "; ".join(payload.affected_roads)]
    if payload.affected_villages:
        lines += [f"{L['villages']}: " + "; ".join(payload.affected_villages)]
    lines += [
        "",
        f"{L['advice']}: {L['advice_text']}",
        "",
        f"{L['open']}: {payload.deep_link}",
        "",
        "-" * 62,
        L["disclaimer"],
    ]
    return "\n".join(lines)


def sms_text(payload: AlertPayload) -> str:
    """<=320 chars: severity, zone, score, confidence, top factor, link."""
    lang = lang_of(payload)
    if payload.kind == "moderator":
        return f"BHOOSHAKTI [DEMO] {payload.title}. {payload.deep_link}"[:320]
    if payload.kind in REPORT_TEXT:
        tier = TIER_WORDS[lang].get(payload.tier, payload.tier)
        label = "ALL CLEAR" if payload.kind == "all_clear" else tier
        line = report_line(payload.kind, payload.place or payload.zone_name, payload.language)
        return f"BHOOSHAKTI {DEMO_PREFIX.get(lang, '[DEMO]')} {label}: {line}"[:320]
    sev = SEVERITY_WORDS[lang].get(payload.severity, payload.severity)
    top = payload.factor_lines[0] if payload.factor_lines else ""
    tier = TIER_WORDS[lang].get(payload.tier, payload.tier)
    body = (f"BHOOSHAKTI AI [DEMO] {tier} {sev} landslide risk: {payload.zone_name}, "
            f"{payload.district}. Score {payload.risk_score:.0f}/100, "
            f"confidence {payload.confidence * 100:.0f}%. {top}. {payload.deep_link}")
    return body[:320]


def voice_text(payload: AlertPayload) -> str:
    """What a text-to-speech call reads aloud: short, no numbers to parse."""
    if payload.kind in REPORT_TEXT:
        return report_line(payload.kind, payload.place or payload.zone_name, payload.language)
    lang = lang_of(payload)
    return f"{TIER_WORDS[lang].get(payload.tier, payload.tier)}. {headline(payload)}"


def safety_line(severity: str | None, place: str, language: str = "en") -> str:
    """Reply to SAFE <pincode> and the IVR risk call-back."""
    lines = {
        "en": {None: "No risk estimate is available for {place} right now.",
               "LOW": "Landslide risk near {place} is LOW. No action needed.",
               "MODERATE": "Landslide risk near {place} is MODERATE. Be watchful near steep slopes.",
               "HIGH": "Landslide risk near {place} is HIGH. Avoid steep slopes and hill roads.",
               "CRITICAL": "Landslide risk near {place} is CRITICAL. Move away from slopes and follow official instructions."},
        "hi": {None: "{place} के लिए अभी कोई जोखिम अनुमान उपलब्ध नहीं है।",
               "LOW": "{place} के पास भूस्खलन जोखिम न्यून है। कोई कार्रवाई आवश्यक नहीं।",
               "MODERATE": "{place} के पास भूस्खलन जोखिम मध्यम है। खड़ी ढलानों के पास सावधान रहें।",
               "HIGH": "{place} के पास भूस्खलन जोखिम उच्च है। खड़ी ढलानों और पहाड़ी सड़कों से बचें।",
               "CRITICAL": "{place} के पास भूस्खलन जोखिम अति गंभीर है। ढलानों से दूर जाएँ और आधिकारिक निर्देशों का पालन करें।"},
    }
    table = lines.get(language, lines["en"])
    return table.get(severity, lines["en"].get(severity, lines["en"][None])).format(place=place)


SEVERITY_COLOURS = {
    # bg, fg — traffic-light ramp shared with web/src/styles/theme.css
    "LOW": ("#22C55E", "#052E16"), "MODERATE": ("#FACC15", "#422006"),
    "HIGH": ("#F97316", "#431407"), "CRITICAL": ("#DC2626", "#FFFFFF"),
}


def html_body(payload: AlertPayload) -> str:
    """Teal-on-white to match the dashboard. Table layout for mail clients."""
    lang = lang_of(payload)
    L = _LABELS[lang]
    sev = SEVERITY_WORDS[lang].get(payload.severity, payload.severity)
    sev_bg, sev_fg = SEVERITY_COLOURS.get(payload.severity, ("#DC2626", "#FFFFFF"))
    tier = TIER_WORDS[lang].get(payload.tier, payload.tier)
    tier_note = ("Machine-issued — awaiting human confirmation"
                 if payload.tier == "ADVISORY" else "Confirmed / model CRITICAL")

    factors = "".join(
        f'<tr><td style="padding:6px 0;color:#0F766E;font-weight:600;width:22px;'
        f'vertical-align:top;">{i}.</td>'
        f'<td style="padding:6px 0;color:#22303F;">{line}</td></tr>'
        for i, line in enumerate(payload.factor_lines, 1)
    ) or '<tr><td colspan="2" style="color:#57534E;">—</td></tr>'

    def block(label: str, items: list[str]) -> str:
        if not items:
            return ""
        return (f'<p style="margin:14px 0 0;color:#57534E;font-size:12px;'
                f'letter-spacing:.06em;text-transform:uppercase;">{label}</p>'
                f'<p style="margin:4px 0 0;color:#22303F;">{"; ".join(items)}</p>')

    return f"""\
<div style="background:#F8FAF7;padding:28px 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:620px;margin:0 auto;background:#FFFFFF;border:1px solid #E7E5E4;">
    <div style="background:#0F766E;padding:20px 26px;">
      <div style="color:#FFFFFF;font-size:19px;font-weight:700;letter-spacing:.10em;">BHOOSHAKTI AI</div>
      <div style="color:#CCE7E3;font-size:12px;margin-top:3px;">AI landslide early warning &amp; risk monitoring — North-East India</div>
    </div>

    <div style="padding:8px 26px 0;">
      <span style="display:inline-block;margin-top:16px;background:#F8FAF7;border:1px solid #CCE7E3;color:#0F766E;font-size:10px;letter-spacing:.12em;padding:3px 8px;">DEMO DATA — SIMULATED</span>
    </div>

    <div style="padding:16px 26px 26px;">
      <span style="display:inline-block;background:#0F766E;color:#FFFFFF;font-size:12px;font-weight:700;letter-spacing:.10em;padding:6px 12px;border-radius:6px;">{tier}</span>
      <span style="display:inline-block;background:{sev_bg};color:{sev_fg};font-size:12px;font-weight:700;letter-spacing:.10em;padding:6px 12px;border-radius:6px;">{sev}</span>
      <span style="display:inline-block;color:#57534E;font-size:11px;margin-left:6px;">{tier_note}</span>

      <h1 style="margin:16px 0 6px;font-size:20px;line-height:1.35;color:#0F766E;font-weight:650;">{headline(payload)}</h1>
      <p style="margin:0;color:#57534E;font-size:13px;">{payload.zone_code} — {payload.zone_name}, {payload.district}, {payload.state}</p>

      <table style="width:100%;border-collapse:collapse;margin:20px 0 4px;">
        <tr>
          <td style="width:50%;background:#F8FAF7;border:1px solid #E7E5E4;padding:14px 16px;">
            <div style="color:#57534E;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['score']}</div>
            <div style="color:#0F766E;font-size:26px;font-weight:700;margin-top:2px;">{payload.risk_score:.0f}<span style="font-size:14px;color:#57534E;">/100</span></div>
          </td>
          <td style="width:50%;background:#F8FAF7;border:1px solid #E7E5E4;border-left:0;padding:14px 16px;">
            <div style="color:#57534E;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['confidence']}</div>
            <div style="color:#0F766E;font-size:26px;font-weight:700;margin-top:2px;">{payload.confidence * 100:.0f}<span style="font-size:14px;color:#57534E;">%</span></div>
          </td>
        </tr>
      </table>

      <p style="margin:20px 0 2px;color:#57534E;font-size:12px;letter-spacing:.06em;text-transform:uppercase;">{L['factors']}</p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">{factors}</table>

      {block(L['roads'], payload.affected_roads)}
      {block(L['villages'], payload.affected_villages)}

      <div style="margin-top:22px;background:#F8FAF7;border-left:3px solid #0F766E;padding:12px 16px;">
        <div style="color:#57534E;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['advice']}</div>
        <div style="color:#22303F;font-size:14px;margin-top:4px;">{L['advice_text']}</div>
      </div>

      <a href="{payload.deep_link}" style="display:inline-block;margin-top:22px;background:#0F766E;color:#FFFFFF;text-decoration:none;font-size:14px;font-weight:600;padding:12px 22px;">{L['open']} →</a>

      <p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #E7E5E4;color:#57534E;font-size:11px;line-height:1.6;">
        {L['issued']}: {payload.issued_at.strftime('%d %b %Y, %H:%M UTC')}<br>
        {L['disclaimer']}
      </p>
    </div>
  </div>
</div>"""
