#!/usr/bin/env python3
"""Build the "Save to Afterscroll" iOS shortcut: Share → Save to Afterscroll from
Instagram (or any app) posts the link to the server's /v1/save, and the bot
picks it up within a minute. The app's own share button does the same; this
is the fallback for share sheets that hide app extensions.

    python3 tools/make_shortcut.py      # writes "ios/build/Save to Afterscroll.shortcut" (signed)

The server address and APP_TOKEN are read from .env and baked into the file,
so the output goes to ios/build/ (gitignored) and must never be committed or
shared: anyone holding the file can queue links on the server.

Signed with macOS's own `shortcuts sign`, so the phone can import it.
"""

import json
import pathlib
import plistlib
import subprocess
import sys
import uuid

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "tools"))
from recategorize import load_env  # noqa: E402

OBJ = "￼"  # Shortcuts' placeholder character for an inline variable


def _out(uid: str, name: str) -> dict:
    return {"OutputUUID": uid, "Type": "ActionOutput", "OutputName": name}


def _token(attachment: dict) -> dict:
    return {"Value": attachment, "WFSerializationType": "WFTextTokenAttachment"}


def _text(s: str, attachments: dict | None = None) -> dict:
    return {"Value": {"string": s, "attachmentsByRange": attachments or {}},
            "WFSerializationType": "WFTextTokenString"}


def _dict(pairs: dict) -> dict:
    return {"Value": {"WFDictionaryFieldValueItems": [
        {"WFItemType": 0, "WFKey": _text(k), "WFValue": _text(v)} for k, v in pairs.items()]},
        "WFSerializationType": "WFDictionaryFieldValue"}


def build(api_base: str, token: str) -> dict:
    links, first, body, sent = (str(uuid.uuid4()).upper() for _ in range(4))
    # The request body, with the shared link spliced in where OBJ sits. The
    # server pulls the first http(s) link out of whatever text arrives.
    template = json.dumps({"url": OBJ}, ensure_ascii=False)
    # attachmentsByRange counts UTF-16 code units, like NSString.
    pos = len(template[:template.index(OBJ)].encode("utf-16-le")) // 2
    actions = [
        {"WFWorkflowActionIdentifier": "is.workflow.actions.detect.link",
         "WFWorkflowActionParameters": {"UUID": links,
                                        "WFInput": _token({"Type": "ExtensionInput"})}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.getitemfromlist",
         "WFWorkflowActionParameters": {"UUID": first, "WFItemSpecifier": "First Item",
                                        "WFInput": _token(_out(links, "URLs"))}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
         "WFWorkflowActionParameters": {"UUID": body, "WFTextActionText": _text(
             template, {f"{{{pos}, 1}}": _out(first, "Item from List")})}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
         "WFWorkflowActionParameters": {
             "UUID": sent,
             "WFURL": api_base.rstrip("/") + "/v1/save",
             "WFHTTPMethod": "POST",
             "ShowHeaders": True,
             "WFHTTPHeaders": _dict({"Authorization": f"Bearer {token}",
                                     "Content-Type": "application/json"}),
             "WFHTTPBodyType": "File",
             "WFRequestVariable": _token(_out(body, "Text")),
         }},
        # Show what the server actually answered ({"queued": ...} or an error),
        # not a hard-coded "Saved" — the old one said Saved while every request
        # to Notion was failing.
        {"WFWorkflowActionIdentifier": "is.workflow.actions.notification",
         "WFWorkflowActionParameters": {
             "WFNotificationActionTitle": "Afterscroll",
             "WFNotificationActionBody": _text(f"{OBJ}", {"{0, 1}": _out(sent, "Contents of URL")}),
             "WFNotificationActionSound": False}},
    ]
    return {
        "WFWorkflowClientVersion": "2607.0.2",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4292093695,   # yellow
                           "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem"],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowImportQuestions": [],
        "WFWorkflowActions": actions,
    }


def main() -> int:
    load_env()
    import os
    token, base = os.environ["APP_TOKEN"], os.environ["APP_API_BASE"]
    out_dir = PROJ / "ios" / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, signed = out_dir / "Save-to-Afterscroll-unsigned.shortcut", out_dir / "Save to Afterscroll.shortcut"
    raw.write_bytes(plistlib.dumps(build(base, token), fmt=plistlib.FMT_BINARY))
    # `shortcuts sign` fails now and then on a cold start; a second try works.
    for attempt in (1, 2):
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(raw),
                            "--output", str(signed)], capture_output=True, text=True)
        if r.returncode == 0:
            break
        if attempt == 2:
            raise SystemExit(f"shortcuts sign failed: {r.stderr.strip()}")
    raw.unlink()
    print(f"wrote {signed} ({signed.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
