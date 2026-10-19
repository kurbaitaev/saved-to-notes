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
    clip, body, sent = (str(uuid.uuid4()).upper() for _ in range(3))
    # The request body, with the shared link spliced in where OBJ sits. The
    # server pulls the first http(s) link out of whatever text arrives.
    # Two slots: what was shared, and the clipboard as the fallback — Instagram
    # hands shortcuts an empty input, so there "Copy link" then run this.
    template = json.dumps({"url": OBJ, "clip": OBJ}, ensure_ascii=False)
    # attachmentsByRange counts UTF-16 code units, like NSString.
    first = template.index(OBJ)
    pos = len(template[:first].encode("utf-16-le")) // 2
    pos2 = len(template[:template.index(OBJ, first + 1)].encode("utf-16-le")) // 2
    actions = [
        {"WFWorkflowActionIdentifier": "is.workflow.actions.getclipboard",
         "WFWorkflowActionParameters": {"UUID": clip}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
         "WFWorkflowActionParameters": {"UUID": body, "WFTextActionText": _text(
             # The whole share, unfiltered: Instagram's item defeated "Get URLs
             # from Input", so the server finds the link in whatever arrives.
             template, {f"{{{pos}, 1}}": {"Type": "ExtensionInput"},
                        f"{{{pos2}, 1}}": _out(clip, "Clipboard")})}},
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
        # Accept anything: if Instagram hands over the video or an image instead
        # of a link, the request still arrives and the server log shows what it was.
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem",
                                              "WFRichTextContentItem", "WFAVAssetContentItem",
                                              "WFImageContentItem", "WFGenericFileContentItem"],
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
