import os
import re
import json
import smtplib
import requests
from bs4 import BeautifulSoup
import gspread
from email.mime.text import MIMEText

# Configuration: set your search URLs and other parameters
OLX_URLS = [
"https://www.olx.pl/nieruchomosci/mieszkania/wynajem/krakow/?search%5Bfilter_float_m%3Afrom%5D=60&search%5Bfilter_float_price%3Ato%5D=4000"
]
OTODOM_URLS = [
    "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/malopolskie/krakow/krakow/krakow?limit=36&priceMax=4000&areaMin=60&by=LATEST&direction=DESC&page=1"
]
#TODO: add env variables for URLs
# os.environ["OLX_URLS"] = "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/krakow/?search%5Bfilter_float_m%3Afrom%5D=60&search%5Bfilter_float_price%3Ato%5D=4000"
# os.environ["OTODOM_URLS"] = "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/malopolskie/krakow/krakow/krakow?limit=36&priceMax=4000&areaMin=60&by=LATEST&direction=DESC&page=1"
os.environ["SHEET_ID"] = "10lQL1ut3XgoUzv3qEE22BwHvf-rbXaZDR8nFvaixk24"
os.environ["SHEET_NAME"] = "candidate_generation"
# check codespace/gspread/service_account.json

# Function to scrape OLX listings
def scrape_olx():
    headers = {"User-Agent": "Mozilla/5.0"}
    offers = []
    for base_url in OLX_URLS:
        page = 1
        while True:
            # Append page param properly (use "&" if base_url already has "?" in it)
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}page={page}"
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
                "https://www.olx.pl"
                link = link_tag["href"] if link_tag else ""
                if not link.startswith("http"):
                    link = "https://www.olx.pl" + link
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
                send_to_candidate_filtering = False
                offers.append([uuid, title, price, area, link, date_added, send_to_candidate_filtering])
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
            if len(offers) >= 200:
                break
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
                send_to_candidate_filtering = False
                offers.append([uuid, title, price, area, link, date_added, send_to_candidate_filtering])
            page += 1
            # el = soup.select_one('a.css-qbxu1w[data-page="6"]')
            # find the <li> that has the “active” class
            print(f"Scraped Otodom page {page} with {len(anchors)} listings")
    return offers

# Function to write new offers to Google Sheets
def write_to_sheets(new_offers):
    if not new_offers:
        return
    gc = gspread.service_account(filename="service_account.json")
    sh = gc.open_by_key(os.getenv("SHEET_ID"))
    worksheet = sh.worksheet(os.getenv("SHEET_NAME")) if os.getenv("SHEET_NAME") else sh.sheet1
    worksheet.append_rows(new_offers, value_input_option="RAW")

# Function to send notification email via Gmail
def send_email(new_offers):
    if not new_offers or not os.getenv("GMAIL_USER") or not os.getenv("GMAIL_PASSWORD"):
        print("No new offers to send or Gmail credentials not set.")
        return
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_PASSWORD")
    subject = f"Nowe oferty nieruchomości: {len(new_offers)} nowe ogłoszenia"
    lines = []
    for uuid, title, price, area, link, date, _ in new_offers:
        line = f"- {uuid} | {title} | {price} | {area}"
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
    import smtplib, ssl
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            print("Connecting to Gmail SMTP server...")
            print("Logging in to Gmail...")
            server.starttls(context=ssl.create_default_context())
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

def remove_html_suffix(s: str) -> str:
    if s.endswith('.html'):
        return s[:-5]  # usuwa ostatnie 5 znaków: ".html"
    return s

# Main function to orchestrate the scraping and notification
def main():
    olx_offers = scrape_olx()
    print("OLX Offers:")
    print(f"Found {len(olx_offers)} offers on OLX")
    otodom_offers = scrape_otodom()
    print("Otodom Offers:")
    print(f"Found {len(otodom_offers)} offers on Otodom")
    # Combine and deduplicate offers by link
    all_offers = []
    seen_links = set()
    for i, offer in enumerate(olx_offers + otodom_offers):
        link = offer[4]
        print(f"Processing offer {i}: {offer[1]} | Link: {link}")
        if link and link not in seen_links:
            seen_links.add(link)
            all_offers.append(offer)
    print(f"Total unique offers found: {len(seen_links)}")

    # Check which offers are new by comparing with Google Sheet
    new_offers = []
    if all_offers:
        gc = gspread.service_account(filename="service_account.json")
        sh = gc.open_by_key(os.getenv("SHEET_ID"))
        worksheet = sh.worksheet(os.getenv("SHEET_NAME")) if os.getenv("SHEET_NAME") else sh.sheet1
        try:
            existing_links = worksheet.col_values(5)  # assuming Link is 4th column (A=1, B=2, C=3, D=4)
            print(f"Found {len(existing_links)} existing links in Google Sheets")
            print(f"Existing links: {existing_links[:10]}...")  # Print first 10 for brevity
        except Exception:
            existing_links = []
        existing_links = {lnk.strip() for lnk in existing_links if lnk and lnk.strip().startswith("http")}
        for offer in all_offers:
            if offer[4] not in existing_links and "hpr" not in offer[4]:  # filter out hpr links
                link_without_html = remove_html_suffix(offer[4])
                offer[4] = link_without_html
                new_offers.append(offer)
        print(f"Found {len(new_offers)} new offers not in Google Sheets")
    # Write new offers to sheet and send email notification
    if new_offers:
        write_to_sheets(new_offers)
        send_email(new_offers)

if __name__ == "__main__":
    main()
