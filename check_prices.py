#!/usr/bin/env python3
"""
check_prices.py

Controlla i prezzi Amazon dei componenti elencati in components.json,
salva uno storico in price_history.json e manda una notifica push via
ntfy.sh quando il prezzo di un componente cambia.

Pensato per girare periodicamente da GitHub Actions (o da un cron
qualsiasi su un PC/Raspberry Pi).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

COMPONENTS_FILE = "components.json"
HISTORY_FILE = "price_history.json"
PLACEHOLDER = "INSERISCI_LINK_AMAZON_QUI"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_URL = "https://ntfy.sh"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
}

PRICE_SELECTORS = [
    "#corePriceDisplay_desktop_feature_div span.a-offscreen",
    "#corePrice_feature_div span.a-offscreen",
    "#corePrice_desktop span.a-offscreen",
    ".priceToPay span.a-offscreen"
]

PRICE_REGEX = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€")


def parse_price(text: str):
    if not text:
        return None
    match = PRICE_REGEX.search(text)
    raw = match.group(1) if match else text.strip()
    raw = raw.replace("€", "").strip()
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def fetch_price(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "lxml")

    for selector in PRICE_SELECTORS:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            price = parse_price(el.get_text(strip=True))
            if price is not None:
                return price

    price = parse_price(soup.get_text(" "))
    if price is not None:
        return price

    raise RuntimeError("Prezzo non trovato nella pagina (selettori cambiati?)")


def send_ntfy(title: str, message: str, url: str = None):
    if not NTFY_TOPIC:
        print("  (NTFY_TOPIC non impostato: notifica saltata)")
        return
    HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
    "cookie": "i18n-prefs=EUR; lc-acgit=it_IT; sp-cdn=L5Z9:IT",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    }
    if url:
        headers["Actions"] = f"view, Apri su Amazon, {url}, clear=true"
    try:
        requests.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  Errore invio notifica ntfy: {exc}")


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    data = load_json(COMPONENTS_FILE, {"components": []})
    components = data["components"]
    history = load_json(HISTORY_FILE, [])

    snapshot_prices = {}
    changes = []

    for comp in components:
        cid = comp["id"]
        name = comp["name"]
        url = comp.get("url", "")
        old_price = comp.get("current_price")

        if not url or url == PLACEHOLDER:
            print(f"[{cid}] link non ancora configurato, salto.")
            snapshot_prices[cid] = old_price
            continue

        print(f"[{cid}] controllo {name}...")
        try:
            new_price = fetch_price(url)
        except Exception as exc:
            print(f"  Errore: {exc}")
            snapshot_prices[cid] = old_price
            continue

        snapshot_prices[cid] = new_price

        if old_price is None:
            print(f"  Prezzo iniziale: {new_price} €")
        elif new_price != old_price:
            delta = round(new_price - old_price, 2)
            print(f"  Cambiato: {old_price} € -> {new_price} € ({delta:+.2f} €)")
            changes.append(
                {
                    "id": cid,
                    "name": name,
                    "url": url,
                    "old_price": old_price,
                    "new_price": new_price,
                    "delta": delta,
                }
            )
        else:
            print(f"  Invariato: {new_price} €")

        comp["current_price"] = new_price
        time.sleep(3)

    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prices": snapshot_prices,
        }
    )

    save_json(COMPONENTS_FILE, data)
    save_json(HISTORY_FILE, history)

    if changes:
        for c in changes:
            arrow = "🔺" if c["delta"] > 0 else "🔻"
            msg = (
                f"{arrow} {c['old_price']:.2f} € → {c['new_price']:.2f} € "
                f"({c['delta']:+.2f} €)"
            )
            send_ntfy(f"Prezzo cambiato: {c['name']}", msg, url=c["url"])
        print(f"\n{len(changes)} cambio/i di prezzo notificato/i.")
    else:
        print("\nNessun cambio di prezzo in questo controllo.")


if __name__ == "__main__":
    sys.exit(main())
