#!/usr/bin/env python3
"""Build the "Afterscroll" iOS shortcut: Share → Afterscroll from Instagram (or
any app) drops the link into the Notion inbox, where the bot picks it up within
a minute (notion.inbox_take).

    python3 tools/make_shortcut.py      # writes ios/build/Afterscroll.shortcut (signed)

The Notion token and database id are read from .env and baked into the file,
so the output goes to ios/build/ (gitignored) and must never be committed or
shared: anyone holding the file can write to the database.

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


def build(token: str, db: str) -> dict:
    links, first, body = (str(uuid.uuid4()).upper() for _ in range(3))
    # The request body, with the shared link spliced in where OBJ sits.
    template = json.dumps({
        "parent": {"database_id": db},
        "properties": {
            "Name": {"title": [{"text": {"content": "⏳ Saving…"}}]},
            "Source": {"url": OBJ},
            "Queued": {"checkbox": True},
        }}, ensure_ascii=False)
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
             "WFURL": "https://api.notion.com/v1/pages",
             "WFHTTPMethod": "POST",
             "ShowHeaders": True,
             "WFHTTPHeaders": _dict({"Authorization": f"Bearer {token}",
                                     "Notion-Version": "2022-06-28",
                                     "Content-Type": "application/json"}),
             "WFHTTPBodyType": "File",
             "WFRequestVariable": _token(_out(body, "Text")),
         }},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.notification",
         "WFWorkflowActionParameters": {
             "WFNotificationActionTitle": "Afterscroll",
             "WFNotificationActionBody": "Saved. It'll be sorted in about a minute.",
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
    token, db = os.environ["NOTION_TOKEN"], os.environ["NOTION_DATABASE_ID"]
    out_dir = PROJ / "ios" / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, signed = out_dir / "Afterscroll-unsigned.shortcut", out_dir / "Afterscroll.shortcut"
    raw.write_bytes(plistlib.dumps(build(token, db), fmt=plistlib.FMT_BINARY))
    subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(raw),
                    "--output", str(signed)], check=True, capture_output=True, text=True)
    raw.unlink()
    print(f"wrote {signed} ({signed.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
