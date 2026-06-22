import sys
import os

source_path = r"C:\Users\HP\.gemini\antigravity-ide\brain\3a4704bc-0671-491b-9ba2-48196b885866\.system_generated\steps\643\content.md"
dest_path = r"c:\SCDT\webgis-backend\new_cairo.osm"

try:
    with open(source_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    xml_start = content.find("<?xml")
    if xml_start != -1:
        xml_content = content[xml_start:]
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        print("Successfully extracted XML to new_cairo.osm")
    else:
        print("XML not found in the source file.")
except Exception as e:
    print(f"Error: {e}")
