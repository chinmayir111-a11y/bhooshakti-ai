"""Alert wording, in the three languages the citizen app offers.

The severity band, zone, score, confidence and the ranked contributing factors
are always present — an alert that says only "danger" is not actionable, and an
alert without its confidence would overstate what the system knows.
"""
from __future__ import annotations

from .base import AlertPayload

SEVERITY_WORDS = {
    "en": {"LOW": "LOW", "MODERATE": "MODERATE", "HIGH": "HIGH", "CRITICAL": "CRITICAL"},
    "hi": {"LOW": "न्यून", "MODERATE": "मध्यम", "HIGH": "उच्च", "CRITICAL": "अति गंभीर"},
    "as": {"LOW": "কম", "MODERATE": "মধ্যম", "HIGH": "উচ্চ", "CRITICAL": "অতি গুৰুতৰ"},
}

_SUBJECT = {
    "en": "{severity} landslide risk — {zone}, {district}",
    "hi": "{severity} भूस्खलन जोखिम — {zone}, {district}",
    "as": "{severity} ভূমিস্খলনৰ বিপদ — {zone}, {district}",
}

_HEADLINE = {
    "en": "Landslide risk in {zone} has reached {severity}.",
    "hi": "{zone} में भूस्खलन का जोखिम {severity} स्तर पर पहुँच गया है।",
    "as": "{zone}ত ভূমিস্খলনৰ বিপদ {severity} স্তৰত উপনীত হৈছে।",
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


def lang_of(payload: AlertPayload) -> str:
    return payload.language if payload.language in _LABELS else "en"


def subject(payload: AlertPayload) -> str:
    lang = lang_of(payload)
    return _SUBJECT[lang].format(
        severity=SEVERITY_WORDS[lang].get(payload.severity, payload.severity),
        zone=payload.zone_name,
        district=payload.district,
    )


def headline(payload: AlertPayload) -> str:
    lang = lang_of(payload)
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
    sev = SEVERITY_WORDS[lang].get(payload.severity, payload.severity)
    top = payload.factor_lines[0] if payload.factor_lines else ""
    body = (f"BHOOSHAKTI AI [DEMO] {sev} landslide risk: {payload.zone_name}, "
            f"{payload.district}. Score {payload.risk_score:.0f}/100, "
            f"confidence {payload.confidence * 100:.0f}%. {top}. {payload.deep_link}")
    return body[:320]


def html_body(payload: AlertPayload) -> str:
    """Navy-on-white to match the dashboard. Table layout for mail clients."""
    lang = lang_of(payload)
    L = _LABELS[lang]
    sev = SEVERITY_WORDS[lang].get(payload.severity, payload.severity)

    sev_bg = {"LOW": "#D6DFEA", "MODERATE": "#A8BCD1",
              "HIGH": "#5C7EA4", "CRITICAL": "#1F3864"}.get(payload.severity, "#1F3864")
    sev_fg = "#1F3864" if payload.severity in ("LOW", "MODERATE") else "#FFFFFF"

    factors = "".join(
        f'<tr><td style="padding:6px 0;color:#1F3864;font-weight:600;width:22px;'
        f'vertical-align:top;">{i}.</td>'
        f'<td style="padding:6px 0;color:#22303F;">{line}</td></tr>'
        for i, line in enumerate(payload.factor_lines, 1)
    ) or '<tr><td colspan="2" style="color:#5C7EA4;">—</td></tr>'

    def block(label: str, items: list[str]) -> str:
        if not items:
            return ""
        return (f'<p style="margin:14px 0 0;color:#5C7EA4;font-size:12px;'
                f'letter-spacing:.06em;text-transform:uppercase;">{label}</p>'
                f'<p style="margin:4px 0 0;color:#22303F;">{"; ".join(items)}</p>')

    return f"""\
<div style="background:#EDF1F6;padding:28px 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:620px;margin:0 auto;background:#FFFFFF;border:1px solid #D6DFEA;">
    <div style="background:#1F3864;padding:20px 26px;">
      <div style="color:#FFFFFF;font-size:19px;font-weight:700;letter-spacing:.10em;">BHOOSHAKTI AI</div>
      <div style="color:#A8BCD1;font-size:12px;margin-top:3px;">AI landslide early warning &amp; risk monitoring — North-East India</div>
    </div>

    <div style="padding:8px 26px 0;">
      <span style="display:inline-block;margin-top:16px;background:#EDF1F6;border:1px solid #A8BCD1;color:#1F3864;font-size:10px;letter-spacing:.12em;padding:3px 8px;">DEMO DATA — SIMULATED</span>
    </div>

    <div style="padding:16px 26px 26px;">
      <span style="display:inline-block;background:{sev_bg};color:{sev_fg};font-size:12px;font-weight:700;letter-spacing:.10em;padding:6px 12px;">{sev}</span>

      <h1 style="margin:16px 0 6px;font-size:20px;line-height:1.35;color:#1F3864;font-weight:650;">{headline(payload)}</h1>
      <p style="margin:0;color:#5C7EA4;font-size:13px;">{payload.zone_code} — {payload.zone_name}, {payload.district}, {payload.state}</p>

      <table style="width:100%;border-collapse:collapse;margin:20px 0 4px;">
        <tr>
          <td style="width:50%;background:#EDF1F6;border:1px solid #D6DFEA;padding:14px 16px;">
            <div style="color:#5C7EA4;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['score']}</div>
            <div style="color:#1F3864;font-size:26px;font-weight:700;margin-top:2px;">{payload.risk_score:.0f}<span style="font-size:14px;color:#5C7EA4;">/100</span></div>
          </td>
          <td style="width:50%;background:#EDF1F6;border:1px solid #D6DFEA;border-left:0;padding:14px 16px;">
            <div style="color:#5C7EA4;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['confidence']}</div>
            <div style="color:#1F3864;font-size:26px;font-weight:700;margin-top:2px;">{payload.confidence * 100:.0f}<span style="font-size:14px;color:#5C7EA4;">%</span></div>
          </td>
        </tr>
      </table>

      <p style="margin:20px 0 2px;color:#5C7EA4;font-size:12px;letter-spacing:.06em;text-transform:uppercase;">{L['factors']}</p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">{factors}</table>

      {block(L['roads'], payload.affected_roads)}
      {block(L['villages'], payload.affected_villages)}

      <div style="margin-top:22px;background:#EDF1F6;border-left:3px solid #1F3864;padding:12px 16px;">
        <div style="color:#5C7EA4;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">{L['advice']}</div>
        <div style="color:#22303F;font-size:14px;margin-top:4px;">{L['advice_text']}</div>
      </div>

      <a href="{payload.deep_link}" style="display:inline-block;margin-top:22px;background:#1F3864;color:#FFFFFF;text-decoration:none;font-size:14px;font-weight:600;padding:12px 22px;">{L['open']} →</a>

      <p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #D6DFEA;color:#5C7EA4;font-size:11px;line-height:1.6;">
        {L['issued']}: {payload.issued_at.strftime('%d %b %Y, %H:%M UTC')}<br>
        {L['disclaimer']}
      </p>
    </div>
  </div>
</div>"""
