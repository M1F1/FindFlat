import os
import re
import json
import smtplib
import requests
from bs4 import BeautifulSoup
# import gspread
from email.mime.text import MIMEText

# Configuration: set your search URLs and other parameters
OLX_URLS = [
    "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/krakow/?search%5Bfilter_float_price:to%5D=4000&search%5Bfilter_float_m:from%5D=60"
]
OTODOM_URLS = [
    "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/malopolskie/krakow/krakow/krakow?limit=36&priceMax=4000&areaMin=60&by=LATEST&direction=DESC&page=1"
]

# Google Sheets and Gmail credentials via environment variables:
# SHEET_ID (Google Sheet ID), SHEET_NAME (optional sheet name),
# GSPREAD_CREDENTIALS (JSON service account credentials),
# GMAIL_USER (your Gmail address), GMAIL_PASSWORD (App Password).

# Function to scrape OLX listings
def scrape_olx():
    headers = {"User-Agent": "Mozilla/5.0"}
    offers = []
    for base_url in OLX_URLS:
        page = 1
        while True:
            # Append page param properly (use "&" if base_url already has "?" in it)
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}={page}"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
            except Exception as e:
                print(f"Request error for OLX page {page}: {e}")
                break
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select('div[data-cy="l-card"]')
            if not cards:
                break  # no listings on this page, end pagination
            for card in cards:
                # Extract title and link
                title_tag = card.find("h6")
                title = title_tag.get_text(strip=True) if title_tag else ""
                link_tag = card.select_one('a:not(:has(img))')
                link = "https://www.olx.pl" + link_tag["href"] if link_tag else ""
                # /d/oferta/4-pokoje-i-balkon-i-klimatyzacja-i-88m2-i-chrobrego-CID3-ID15NLb7.html
                # extract title from link using regex only last part after last slash and CID3
                import re
                # write a function to extract ID from link
                def extract_id_from_link(link):
                    m = re.search(r'ID[0-9A-Za-z]+(?=\.html)', link)
                    return m.group(0) if m else ""
                uuid = extract_id_from_link(link)


                # Extract price
                price_tag = card.find("p", {"data-testid": "ad-price"})
                price = price_tag.get_text(strip=True) if price_tag else ""
                # Extract date added (from location-date field, part after the hyphen)
                loc_date_tag = card.find("p", {"data-testid": "location-date"})
                date_added = ""
                if loc_date_tag:
                    loc_date_text = loc_date_tag.get_text(strip=True)
                    parts = loc_date_text.split("-")
                    if len(parts) > 1:
                        date_added = parts[-1].strip()
                # Extract area (metraż)
                area = ""
                for elem in card.find_all(string=re.compile(r"m²")):
                    text = elem.strip()
                    if text.endswith("m²") and "zł" not in text:
                        area = text  # e.g. "56 m²" for rentals
                        break
                    if text.endswith("m²") and "zł" in text:
                        area = text.split("-")[0].strip()  # e.g. "35 m²" from "35 m² - 10857 zł/m²"
                        break
                offers.append([uuid, title, price, area, link, date_added])
            page += 1
            print(f"Scraped OLX page {page} with {len(cards)} listings")
    return offers

# Function to scrape Otodom listings
def scrape_otodom():
    headers = {"User-Agent": "Mozilla/5.0"}
    offers = []
    for base_url in OTODOM_URLS:
        page = 1
        while True:
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}page={page}"
            print(f"Scraping Otodom page {page}: {url}")
            try:
                resp = requests.get(url, headers=headers, timeout=10)
            except Exception as e:
                print(f"Request error for Otodom page {page}: {e}")
                break
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            anchors = soup.select('a[data-cy="listing-item-link"]')
            # anchors = soup.select('a[data-cy="listing-item-link"]').e7pblr4
            #html body div#__next div.css-1bx5ylf.e1xea6843 main.css-1nw9pmu.ej9hb240 div.css-1n25z8k.e1xea6840 div.css-79elbk.e1xea6841 div.css-feokcq.e1xea6844 div.e1fx09lx0.css-yqh7ml div.css-1i43dhb.e1fx09lx1 div div.css-18budxx.e7pblr0 ul.e7pblr4.css-iiviho
            if not anchors:
                break  # no listings on this page
            for a in anchors:
                link = "https://www.otodom.pl" + a.get("href", "")
                uuid = link[-7:]  
                title = a.get_text(strip=True)
                # Find parent container of the listing (article or list item)
                container = a.find_parent("article")
                if container is None:
                    container = a.find_parent("li")
                price = ""
                area = ""
                date_added = ""  # Otodom cards usually don't show date added
                if container:
                    text_segments = list(container.stripped_strings)
                    # Find price (first text ending with 'zł' that is not price per m²)
                    for t in text_segments:
                        if t.endswith("zł") and "/m²" not in t:
                            price = t[:-2].strip() # remove 'zł' and any trailing spaces
                            break
                    # Find area (text containing 'm²')
                    for t in text_segments:
                        if "m²" in t:
                            match = re.search(r"[\d\.,]+\s*m²", t)
                            if match:
                                area = match.group(0)
                                break
                offers.append([uuid, title, price, area, link, date_added])
            page += 1
            # el = soup.select_one('a.css-qbxu1w[data-page="6"]')
            # find the <li> that has the “active” class
            print(f"Scraped Otodom page {page} with {len(anchors)} listings")
            if len(offers) > 200:
                break
    return offers

# Function to write new offers to Google Sheets
def write_to_sheets(new_offers):
    if not new_offers:
        return
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    gc = gspread.service_account_from_dict(json.loads(creds_json)) if creds_json else gspread.service_account()
    sh = gc.open_by_key(os.getenv("SHEET_ID"))
    worksheet = sh.worksheet(os.getenv("SHEET_NAME")) if os.getenv("SHEET_NAME") else sh.sheet1
    worksheet.append_rows(new_offers, value_input_option="RAW")

# Function to send notification email via Gmail
def send_email(new_offers):
    if not new_offers or not os.getenv("GMAIL_USER") or not os.getenv("GMAIL_PASSWORD"):
        return
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_PASSWORD")
    subject = f"Nowe oferty nieruchomości: {len(new_offers)} nowe ogłoszenia"
    lines = []
    for title, price, area, link, date in new_offers:
        line = f"- {title} | {price} | {area}"
        if date:
            line += f" | {date}"
        line += f" | {link}"
        lines.append(line)
    body = "Wykryto nowe oferty:\n" + "\n".join(lines)
    # Compose and send the email
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = gmail_user
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(gmail_user, gmail_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")

# Main function to orchestrate the scraping and notification
def main():
    # olx_offers = scrape_olx()
    # print("OLX Offers:")
    # print(olx_offers)
    # print(f"Found {len(olx_offers)} offers on OLX")
    otodom_offers = scrape_otodom()
    print("Otodom Offers:")
    print(otodom_offers)
    print(f"Found {len(otodom_offers)} offers on Otodom")
    # # Combine and deduplicate offers by link
    # all_offers = []
    # seen_links = set()k
    # for offer in olx_offers + otodom_offers:
    #     link = offer[3]
    #     if link and link not in seen_links:
    #         seen_links.add(link)
    #         all_offers.append(offer)
    # # Check which offers are new by comparing with Google Sheet
    # new_offers = []
    # if all_offers:
    #     creds_json = os.getenv("GSPREAD_CREDENTIALS")
    #     gc = gspread.service_account_from_dict(json.loads(creds_json)) if creds_json else gspread.service_account()
    #     sh = gc.open_by_key(os.getenv("SHEET_ID"))
    #     worksheet = sh.worksheet(os.getenv("SHEET_NAME")) if os.getenv("SHEET_NAME") else sh.sheet1
    #     try:
    #         existing_links = worksheet.col_values(4)  # assuming Link is 4th column (A=1, B=2, C=3, D=4)
    #     except Exception:
    #         existing_links = []
    #     existing_links = {lnk.strip() for lnk in existing_links if lnk and lnk.strip().startswith("http")}
    #     for offer in all_offers:
    #         if offer[3] not in existing_links:
    #             new_offers.append(offer)
    # # Write new offers to sheet and send email notification
    # if new_offers:
    #     write_to_sheets(new_offers)
    #     send_email(new_offers)

if __name__ == "__main__":
    main()
