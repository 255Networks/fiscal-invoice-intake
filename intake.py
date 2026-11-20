"""Prepare three local finance review queues from a batch of fictional requests."""
import argparse
import csv
import difflib
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ["request_id", "issuer", "reference", "customer_id", "currency", "amount_minor", "reason", "suggested_customer"]
FIELDS = {"customers": ["customer_id", "name"],
          "requests": ["request_id", "issuer", "reference", "customer_id", "customer_name", "currency", "amount_minor"],
          "prior": ["issuer", "reference", "customer_id", "currency", "amount_minor"]}


def normalized(value):
    return " ".join(value.casefold().split())


def load_rows(data, table):
    with (data / (table + ".csv")).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS[table]:
            raise ValueError(f"Unexpected header in {table}.csv")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"Malformed row in {table}.csv")
        return [{k: v.strip() for k, v in row.items()} for row in rows]


def key(row):
    return row["issuer"], row["reference"]


def signature(row):
    amount = row["amount_minor"]
    canonical = str(int(amount)) if re.fullmatch(r"[0-9]{1,12}", amount) else amount
    return row["customer_id"], row["currency"], canonical


def classify(customers, requests, prior):
    directory = {r["customer_id"]: r["name"] for r in customers}
    if len(directory) != len(customers) or any(not k or not v for k, v in directory.items()):
        raise ValueError("Customer master must have unique nonempty IDs and names")
    request_ids = [r["request_id"] for r in requests]
    if len(set(request_ids)) != len(request_ids) or not all(request_ids):
        raise ValueError("Request IDs must be unique and nonempty")
    history = {key(r): signature(r) for r in prior}
    if len(history) != len(prior):
        raise ValueError("Prior history contains a repeated invoice key")
    payloads = defaultdict(set)
    for row in requests:
        payloads[key(row)].add(signature(row))
    seen = set()
    groups = {"ready": [], "review": [], "duplicates": []}
    for row in requests:
        k = key(row)
        customer = row["customer_id"]
        proposed = ""
        queue = "review"
        if not all(k):
            reason = "MISSING_BUSINESS_KEY"
        elif len(payloads[k]) > 1 or (k in history and history[k] != signature(row)):
            reason = "CONFLICTING_PAYLOAD"
        elif not re.fullmatch(r"[0-9]{1,12}", row["amount_minor"]) or int(row["amount_minor"]) < 1:
            reason = "INVALID_AMOUNT"
        elif row["currency"] != "BRL":
            reason = "UNSUPPORTED_CURRENCY"
        elif customer not in directory:
            names = {normalized(v) for v in directory.values()}
            matches = difflib.get_close_matches(normalized(row["customer_name"]), sorted(names), n=1, cutoff=0.78)
            if matches:
                ids = sorted(i for i, v in directory.items() if normalized(v) == matches[0])
                proposed = "|".join(ids)
            reason = "UNVERIFIED_CUSTOMER"
        elif normalized(row["customer_name"]) != normalized(directory[customer]):
            reason = "NAME_ID_CONFLICT"
        elif k in history or k in seen:
            queue, reason = "duplicates", "ALREADY_ACCEPTED" if k in history else "REPEATED_IN_BATCH"
        else:
            queue, reason = "ready", "VERIFIED"
            seen.add(k)
        result = {field: row.get(field, "") for field in OUTPUT}
        result.update(reason=reason, suggested_customer=proposed)
        groups[queue].append(result)
    return groups


def write_queues(groups, out):
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Choose an empty output directory")
    for queue, rows in groups.items():
        with (out / (queue + ".csv")).open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                # The CSV is intended for spreadsheet viewing. Keep user text literal.
                writer.writerow({k: ("'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v)
                                 for k, v in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        groups = classify(*(load_rows(args.data, name) for name in ("customers", "requests", "prior")))
        write_queues(groups, args.out)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + "\n")
    print(", ".join(f"{len(rows)} {label}" for label, rows in groups.items()))


if __name__ == "__main__":
    main()
