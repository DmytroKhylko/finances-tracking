import argparse
import csv
import os
import xml.etree.ElementTree as ET
from datetime import datetime

FIELDS = [
    "date",
    "time",
    "product",
    "price",
    "quantity",
    "barcode",
    "store",
    "description",
    "check_number",
    "fiscal_number",
    "add_field",
    "currency",
]


def parse_ts(ts):
    dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")


def write_file(filename, rows, delimiter):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def process_xml(xml_path, output_dir):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    dat = root.find("DAT")
    if dat is None:
        raise ValueError(f"Missing <DAT> in {xml_path}")

    c = dat.find("C")
    if c is None:
        raise ValueError(f"Missing <C> inside DAT in {xml_path}")

    e = c.find("E")
    if e is None:
        raise ValueError(f"Missing <E> inside C in {xml_path}")

    ts = e.attrib["TS"]
    check_number = os.path.splitext(os.path.basename(xml_path))[0]
    fiscal_number = e.attrib.get("FN") or dat.attrib.get("FN", "")

    date, time = parse_ts(ts)

    rows = []

    for p in c.findall("P"):
        name = p.attrib.get("NM", "")

        if "PRC" in p.attrib:
            price_int = int(p.attrib["PRC"])  # in kopecks
        else:
            price_int = int(p.attrib["SM"])  # in kopecks

        # Quantity as integer grams
        qty_raw = p.attrib.get("Q")
        quantity_int = int(qty_raw) if qty_raw else 1000  # 1000 g = 1 unit

        barcode = p.attrib.get("CD", "")

        row = {
            "date": date,
            "time": time,
            "product": name,
            "price": price_int,
            "quantity": quantity_int,
            "barcode": barcode,
            "store": "",
            "description": "",
            "check_number": check_number,
            "fiscal_number": fiscal_number,
            "add_field": "",
            "currency": "",
        }

        rows.append(row)

    base = os.path.splitext(os.path.basename(xml_path))[0]

    csv_path = os.path.join(output_dir, f"{base}.csv")
    tsv_path = os.path.join(output_dir, f"{base}.tsv")

    write_file(csv_path, rows, delimiter=",")
    write_file(tsv_path, rows, delimiter="\t")

    print(f"Processed: {xml_path} → {csv_path}, {tsv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse fiscal XML checks and output CSV/TSV."
    )
    parser.add_argument("--check", required=True, help="Directory with XML check files")
    args = parser.parse_args()

    input_dir = args.check
    output_dir = "check-output"

    os.makedirs(output_dir, exist_ok=True)

    files = [f for f in os.listdir(input_dir) if f.lower().endswith(".xml")]

    if not files:
        print("No XML files found in:", input_dir)
        return

    for file in files:
        process_xml(os.path.join(input_dir, file), output_dir)


if __name__ == "__main__":
    main()
