
#!/usr/bin/env python3
from __future__ import annotations
import csv
import os
import argparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any

OUTPUT_DIR = "check-output"

FIELDS = [
    "date",
    "time",
    "product",
    "price",        # integer kopecks
    "quantity",     # integer * 1000
    "barcode",
    "store",
    "description",
    "check_number",
    "fiscal_number",
    "add_field",
    "currency",
]

# ------------------ Data models ------------------ #

@dataclass
class ParsedItem:
    product: str
    price_int: int      # kopecks
    quantity_int: int   # qty * 1000
    barcode: str = ""


@dataclass
class ParsedCheck:
    date: str
    time: str
    check_number: str
    fiscal_number: str
    store: str = ""
    description: str = ""
    currency: str = "UAH"
    items: List[ParsedItem] = None

def safe_find(parent, tag):
    if parent is None:
        return None
    return parent.find(tag)

def safe_text(parent, tag, default=""):
    if parent is None:
        return default
    node = parent.find(tag)
    if node is None or node.text is None:
        return default
    return node.text.strip()


# ------------------ Base parser ------------------ #

class BaseParser:
    def __init__(self, xml_path: str, root: ET.Element):
        self.xml_path = xml_path
        self.root = root

    def parse(self) -> ParsedCheck:
        raise NotImplementedError


# ------------------ Fiscal parser ------------------ #

class FiscalParser(BaseParser):

    def parse(self) -> ParsedCheck:
        dat = self.root.find("DAT")
        c = dat.find("C")
        e = c.find("E")

        # --- Time ---
        ts = e.attrib["TS"]
        dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
        date = dt.strftime("%Y-%m-%d")
        time = dt.strftime("%H:%M:%S")

        # --- Fiscal number ---
        fiscal = e.attrib.get("FN") or dat.attrib.get("FN", "")

        # --- Check number ---
        if "FN" in e.attrib:
            check_number = e.attrib.get("NO", "") or os.path.splitext(os.path.basename(self.xml_path))[0]
        else:
            check_number = os.path.splitext(os.path.basename(self.xml_path))[0]

        # --- Items ---
        items: List[ParsedItem] = []

        for p in c.findall("P"):
            name = p.attrib.get("NM", "").strip()

            # PRICE: prefer PRC (unit price), else SM (total)
            if "PRC" in p.attrib:
                price_int = int(p.attrib["PRC"])      # already in kopecks
            else:
                price_int = int(p.attrib["SM"])       # fallback (rare)

            # QUANTITY:
            # Q is grams; if missing → 1 unit → 1000
            if "Q" in p.attrib and p.attrib["Q"].isdigit():
                quantity_int = int(p.attrib["Q"])
            else:
                quantity_int = 1000

            barcode = p.attrib.get("CD", "") or p.attrib.get("C", "")

            items.append(ParsedItem(
                product=name,
                price_int=price_int,
                quantity_int=quantity_int,
                barcode=barcode
            ))

        return ParsedCheck(
            date=date,
            time=time,
            check_number=check_number,
            fiscal_number=fiscal,
            store="",
            description="",
            items=items,
        )


# ------------------ GMS parser (<CHECK>) ------------------ #

class GMSParser(BaseParser):

    def parse(self) -> ParsedCheck:
        head = safe_find(self.root, "CHECKHEAD")
        body = safe_find(self.root, "CHECKBODY")

        # --- Date/time ---

        date_raw = safe_text(head, "ORDERDATE")
        time_raw = safe_text(head, "ORDERTIME")

        # Format date: DDMMYYYY → YYYY-MM-DD
        if len(date_raw) == 8:
            date = f"{date_raw[4:8]}-{date_raw[2:4]}-{date_raw[0:2]}"
        else:
            date = ""

        # Format time: HHMMSS → HH:MM:SS
        if len(time_raw) == 6:
            time = f"{time_raw[0:2]}:{time_raw[2:4]}:{time_raw[4:6]}"
        else:
            time = ""

        # --- Check number ---
        check_number = (
            safe_text(head, "ORDERNUM")
            or os.path.splitext(os.path.basename(self.xml_path))[0]
        )

        # --- Fiscal number ---
        fiscal_number = (
            safe_text(head, "CASHREGISTERNUM")
            or safe_text(head, "TIN")
            or safe_text(head, "UID")
        )

        # --- Store & description ---
        store = safe_text(head, "ORGNM")
        description = safe_text(head, "POINTADDR")

        # --- Items ---
        items: List[ParsedItem] = []

        if body is not None:
            for row in body.findall("ROW"):
                name = safe_text(row, "NAME")

                price_text = safe_text(row, "PRICE", "0").replace(",", ".")
                amount_text = safe_text(row, "AMOUNT", "1").replace(",", ".")

                # PRICE → kopecks integer
                price_int = int(Decimal(price_text) * 100)

                # QUANTITY → integer * 1000
                quantity_int = int(Decimal(amount_text) * 1000)

                barcode = safe_text(row, "BARCODE")

                items.append(ParsedItem(
                    product=name,
                    price_int=price_int,
                    quantity_int=quantity_int,
                    barcode=barcode,
                ))

        return ParsedCheck(
            date=date,
            time=time,
            check_number=check_number,
            fiscal_number=fiscal_number,
            store=store,
            description=description,
            items=items,
        )


# ------------------ Processor ------------------ #

class CheckProcessor:
    def __init__(self, input_dir: str):
        self.input_dir = input_dir
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def detect_format(self, root: ET.Element) -> str:
        if root.tag == "CHECK":
            return "gms"
        if root.find("DAT") is not None:
            return "fiscal"
        raise ValueError("Unknown XML format")

    def process_file(self, xml_path: str):
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            print(f"[ERROR] {xml_path}: {e}")
            return

        try:
            fmt = self.detect_format(root)
        except Exception as e:
            print(f"[SKIP] {xml_path}: {e}")
            return

        if fmt == "fiscal":
            parser = FiscalParser(xml_path, root)
        else:
            parser = GMSParser(xml_path, root)

        try:
            parsed = parser.parse()
        except Exception as e:
            print(f"[ERROR] Failed parsing {xml_path}: {e}")
            return

        rows: List[Dict[str, Any]] = []

        for item in parsed.items:
            rows.append({
                "date": parsed.date,
                "time": parsed.time,
                "product": item.product,
                "price": item.price_int,          # integer
                "quantity": item.quantity_int,    # integer
                "barcode": item.barcode,
                "store": parsed.store,
                "description": parsed.description,
                "check_number": parsed.check_number,
                "fiscal_number": parsed.fiscal_number,
                "add_field": "",
                "currency": parsed.currency,
            })

        base = os.path.splitext(os.path.basename(xml_path))[0]
        self._write(os.path.join(OUTPUT_DIR, f"{base}.csv"), rows, ",")
        self._write(os.path.join(OUTPUT_DIR, f"{base}.tsv"), rows, "\t")
        print(f"[OK] {xml_path}")

    def _write(self, path: str, rows, delimiter):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rows)

    def run(self):
        for fname in sorted(os.listdir(self.input_dir)):
            if fname.lower().endswith(".xml"):
                self.process_file(os.path.join(self.input_dir, fname))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", required=True)
    args = parser.parse_args()

    proc = CheckProcessor(args.check)
    proc.run()


if __name__ == "__main__":
    main()
