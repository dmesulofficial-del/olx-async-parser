import os
import certifi
import asyncio
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.async_api import async_playwright

# Виправлення проблем з SSL
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['SSL_CERT_FILE'] = certifi.where()

async def fetch_details(browser, ad_data, semaphore, index):
    async with semaphore:
        await asyncio.sleep(random.uniform(2, 4))
        page = await browser.new_page()
        try:
            print(f"[{index}] Обробка: {ad_data['link'][:50]}...")
            await page.goto(ad_data['link'], wait_until="domcontentloaded", timeout=45000)
            
            # Чекаємо появи контейнера з параметрами
            params_selector = '[data-testid="ad-parameters-container"]'
            try:
                await page.wait_for_selector(params_selector, timeout=5000)
            except:
                pass # Якщо не знайшли, спробуємо зібрати те, що є

            # Отримуємо всі параграфи з характеристиками
            param_elements = await page.locator(f'{params_selector} p').all()
            
            # Створюємо словник для швидкого пошуку
            details_map = {}
            for el in param_elements:
                text = await el.inner_text()
                if ":" in text:
                    key, value = text.split(":", 1)
                    details_map[key.strip().lower()] = value.strip()

            # Витягуємо потрібні нам дані зі словника
            floor = details_map.get("поверх", "Не вказано")
            total_floors = details_map.get("поверховість", "Не вказано")
            area = details_map.get("загальна площа", "Не вказано")

            print(f"   -> Знайдено: {floor} пов., {area}")
            return [index, ad_data['price'], floor, total_floors, ad_data['city'], area, ad_data['link']]
            
        except Exception as e:
            print(f"⚠️ Помилка на {index}: {e}")
            return [index, ad_data['price'], "Помилка", "Помилка", ad_data['city'], "Помилка", ad_data['link']]
        finally:
            await page.close()

def save_to_sheets(rows):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("olx-info").sheet1 
        
        sheet.clear()
        headers = ["№", "Ціна", "Поверх", "Поверховість", "Населений пункт", "Площа", "Посилання"]
        sheet.append_row(headers)
        
        if rows:
            sheet.append_rows(rows)
        print(f"✅ Успішно експортовано {len(rows)} рядків у Google Sheets!")
    except Exception as e:
        print(f"❌ Помилка Google Sheets: {e}")

async def main():
    async with async_playwright() as p:
        # headless=False дозволяє бачити, що робить робот. Якщо все ок - змініть на True
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Запуск сканування головної сторінки...")
        await page.goto("https://www.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/kiev/", wait_until="networkidle")
        
        listings = await page.locator('div[data-testid="l-card"]').all()
        print(f"Знайдено оголошень: {len(listings)}")

        initial_data = []
        for unit in listings:
            try:
                price = await unit.locator('[data-testid="ad-price"]').inner_text(timeout=2000)
                location = await unit.locator('[data-testid="location-date"]').inner_text(timeout=2000)
                city = location.split(',')[0].split(' - ')[0].strip()
                link = await unit.locator('a').first.get_attribute('href')
                if link and link.startswith('/'):
                    link = f"https://www.olx.ua{link}"
                initial_data.append({'price': price.strip(), 'city': city, 'link': link})
            except:
                continue
        
        # Використовуємо 1 потік (Semaphore), щоб OLX не видавав помилки таймауту
        semaphore = asyncio.Semaphore(1)
        tasks = []
        print("Починаємо глибокий збір даних (це займе кілька хвилин)...")
        
        for i, ad in enumerate(initial_data, 1):
            tasks.append(fetch_details(browser, ad, semaphore, i))
        
        final_rows = await asyncio.gather(*tasks)
        
        if final_rows:
            save_to_sheets(final_rows)

        await browser.close()
        print("Роботу завершено!")

if __name__ == "__main__":
    asyncio.run(main())