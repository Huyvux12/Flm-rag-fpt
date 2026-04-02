import asyncio
from playwright.async_api import async_playwright, Playwright, expect
import json
import urllib.parse
import re
import os

# Thư mục lưu profile trình duyệt - chỉ cần đăng nhập 1 lần
BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")


async def crawl_flm(playwright: Playwright, major_code="AI"):
    """
    Crawls FLM FPT Edu to get curriculum and syllabus information.
    Sử dụng persistent context để bypass "This browser or app may not be secure".
    """
    # Sử dụng persistent context + stealth args để Google không phát hiện automation
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=BROWSER_PROFILE_DIR,
        headless=False,
        channel="chrome",  # Dùng Chrome đã cài trên máy thay vì Chromium bundled
        args=[
            "--disable-blink-features=AutomationControlled",  # Ẩn flag automation
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-extensions",
            "--start-maximized",
        ],
        ignore_default_args=["--enable-automation"],  # Bỏ flag enable-automation
        viewport=None,  # Sử dụng kích thước cửa sổ thực
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # Ẩn webdriver property để giảm fingerprint
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        // Ghi đè navigator.plugins để giả lập trình duyệt thật
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        // Ghi đè navigator.languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['vi-VN', 'vi', 'en-US', 'en'],
        });
    """)

    print("Đang điều hướng đến flm.fpt.edu.vn...")
    await page.goto("https://flm.fpt.edu.vn", timeout=60000)

    # Kiểm tra xem đã đăng nhập chưa (session từ lần trước)
    await page.wait_for_timeout(3000)  # Đợi redirect nếu có
    current_url = page.url
    
    if "flm.fpt.edu.vn" in current_url and "accounts.google.com" not in current_url:
        # Kiểm tra thêm xem có nút đăng nhập không
        login_needed = await page.locator("text=Sign in").count() > 0 or "login" in current_url.lower()
        if not login_needed:
            print("✅ Đã đăng nhập sẵn từ session trước! Tiếp tục crawl...")
        else:
            print("⚠️ Cần đăng nhập. Vui lòng đăng nhập thủ công trong cửa sổ Chrome...")
            print("Sau khi đăng nhập thành công, nhấn Enter trong console này để tiếp tục...")
            input()
            print("Đã xác nhận đăng nhập. Tiếp tục...")
    else:
        print("⚠️ Đang ở trang đăng nhập Google. Vui lòng đăng nhập thủ công...")
        print("Sau khi đăng nhập thành công và quay về FLM, nhấn Enter trong console này để tiếp tục...")
        input()
        print("Đã xác nhận đăng nhập. Tiếp tục...")

    # Đợi trang load hoàn tất sau redirect đăng nhập (LoginWithFEID → Home)
    print("Đợi trang load hoàn tất sau đăng nhập...")
    await page.wait_for_load_state("networkidle", timeout=60000)
    await page.wait_for_timeout(3000)  # Buffer thêm cho redirect chain
    
    # Nếu chưa ở trang Home, điều hướng về
    if "/Home" not in page.url:
        print(f"Đang ở {page.url}, điều hướng về trang Home...")
        await page.goto("https://flm.fpt.edu.vn/Home", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=60000)
        await page.wait_for_timeout(2000)
    
    print(f"URL hiện tại: {page.url}")

    print("Bấm vào 'View Curriculum'...")
    # Thử nhiều selector khác nhau cho nút View Curriculum
    view_curriculum_button = page.locator(
        'a[href*="ListCurriculum"], a:has-text("View Curriculum"), a.a-button[href*="ListCurriculum"]'
    ).first
    
    try:
        await view_curriculum_button.wait_for(state="visible", timeout=15000)
        await view_curriculum_button.click()
    except Exception as e:
        print(f"Không tìm thấy nút 'View Curriculum' bằng selector. Thử điều hướng trực tiếp...")
        await page.goto("https://flm.fpt.edu.vn/role/student/ListCurriculum.aspx", timeout=60000)
    
    await page.wait_for_load_state("networkidle", timeout=60000)
    print("Đã vào trang Curriculum.")

    print(f"Nhập mã ngành '{major_code}' và tìm kiếm...")
    await page.locator("#txtKeyword").fill(major_code)
    await page.locator("#btnSearch").click()
    await page.wait_for_load_state("networkidle", timeout=60000)
    print("Đã tìm kiếm curriculum.")

    print("Bấm vào curriculum đầu tiên...")
    first_curriculum_link = page.locator(
        '//table[contains(@class, "table")]/tbody/tr[1]/td[3]/a[contains(@href, "CurriculumDetails.aspx")]')
    if await first_curriculum_link.count() == 0:
        first_curriculum_link = page.locator(
            '//table//tr[td][1]//a[contains(@href, "CurriculumDetails.aspx")]')

    try:
        await first_curriculum_link.click()
        await page.wait_for_load_state("networkidle", timeout=60000)
        print("Đã mở chi tiết curriculum.")
    except Exception as e:
        print(f"Không thể click vào link curriculum đầu tiên. Lỗi: {e}")
        print("Vui lòng kiểm tra selector cho link curriculum hoặc trang không có kết quả.")
        await context.close()
        return

    curriculum_subjects = []
    curriculum_page_url = page.url
    curriculum_title = f"Curriculum for {major_code}"  # Default title

    try:
        curriculum_title_element = page.locator(
            f"//h3[contains(text(), 'Bachelor Program') or contains(text(), '{major_code}') or contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{major_code.upper()}')]").first
        if await curriculum_title_element.count() == 0:
            curriculum_title_element = page.locator(
                "div.container-fluid h3").first

        if await curriculum_title_element.count() > 0:
            potential_title = (await curriculum_title_element.inner_text()).strip()
            # Check if it's a generic header
            if "FPT University Learning Materials" in potential_title and len(potential_title) > len("FPT University Learning Materials") + 5:
                # Try to find a more specific one
                specific_titles = page.locator(
                    f"//h3[not(contains(text(), 'FPT University Learning Materials')) and (contains(text(), 'Bachelor Program') or contains(text(), '{major_code}'))]")
                if await specific_titles.count() > 0:
                    curriculum_title = (await specific_titles.first.inner_text()).strip()
                else:  # If no better title, use the one found but try to clean it
                    curriculum_title = potential_title.replace(
                        "FPT University Learning Materials", "").strip().lstrip('-').strip()

            else:
                curriculum_title = potential_title

            print(f"Tên chương trình: {curriculum_title}")
        else:
            print(
                f"Không tìm thấy tiêu đề chương trình cụ thể. Sử dụng tiêu đề mặc định.")
            # curriculum_title is already defaulted
            page_title_text = await page.title()
            if page_title_text and "curriculum" in page_title_text.lower():
                curriculum_title_from_tag = page_title_text.split(
                    "|")[0].strip() if "|" in page_title_text else page_title_text.strip()
                if curriculum_title_from_tag != "FPT University Learning Materials":  # Avoid generic page title
                    curriculum_title = curriculum_title_from_tag
                print(f"Lấy tiêu đề từ thẻ <title>: {curriculum_title}")
    except Exception as e:
        print(f"Lỗi khi tìm tiêu đề chương trình: {e}")
        # curriculum_title remains defaulted

    major_info_data = {
        "major_code_input": major_code,
        "curriculum_title_on_page": curriculum_title,
        "curriculum_url": curriculum_page_url,
        "syllabuses": []
    }

    print("Bắt đầu lấy danh sách môn học từ khung chương trình...")
    potential_subject_tables = page.locator(
        "//table[contains(@class, 'table-bordered') or contains(@class, 'table-striped')]")
    num_tables = await potential_subject_tables.count()
    print(f"Tìm thấy {num_tables} bảng tiềm năng chứa môn học.")

    main_subject_rows_data = []

    for i in range(num_tables):
        table = potential_subject_tables.nth(i)
        header_row = table.locator("tr").first
        header_cells_text_loc = header_row.locator("th, td")
        header_texts = []
        for j in range(await header_cells_text_loc.count()):
            header_texts.append((await header_cells_text_loc.nth(j).inner_text()).strip().lower())

        is_subject_table = (
            any("code" in h or "mã" in h for h in header_texts) and
            any("semester" in h or "kỳ" in h or "sem" in h for h in header_texts) and
            any("subject name" in h or "tên" in h or "title" in h or "học phần" in h for h in header_texts)
        )

        if is_subject_table:
            print(
                f"Bảng {i} được xác định là bảng môn học. Header: {header_texts}")

            idx_code, idx_name, idx_semester, idx_credit = -1, -1, -1, -1
            for idx, h_text in enumerate(header_texts):
                if ("code" in h_text or "mã" in h_text) and idx_code == -1:
                    idx_code = idx
                elif ("subject name" in h_text or "tên" in h_text or "title" in h_text or "học phần" in h_text) and idx_name == -1:
                    idx_name = idx
                elif ("semester" in h_text or "kỳ" in h_text or "sem" in h_text) and idx_semester == -1:
                    idx_semester = idx
                elif ("credit" in h_text or "tc" in h_text or "tín chỉ" in h_text) and idx_credit == -1:
                    idx_credit = idx

            if not (idx_code != -1 and idx_name != -1 and idx_semester != -1):
                print(
                    f"Bảng {i} có vẻ là bảng môn học nhưng không tìm đủ các cột Code, Name, Semester trong header. Bỏ qua.")
                continue

            rows_in_table = table.locator("tbody tr, tr:not(:first-child)")
            for k in range(await rows_in_table.count()):
                row_locator = rows_in_table.nth(k)
                cells = row_locator.locator("td")
                num_cells_in_row = await cells.count()

                if num_cells_in_row > max(idx_code, idx_name, idx_semester, idx_credit if idx_credit != -1 else 0):
                    try:
                        subject_code = (await cells.nth(idx_code).inner_text()).strip()

                        subject_name_el = cells.nth(
                            idx_name).locator("a").first
                        if await subject_name_el.count() > 0:
                            subject_name = (await subject_name_el.inner_text()).strip()
                        else:
                            subject_name = (await cells.nth(idx_name).inner_text()).strip()

                        semester_text = (await cells.nth(idx_semester).inner_text()).strip()

                        credit_text = ""
                        if idx_credit != -1 and idx_credit < num_cells_in_row:
                            credit_text = (await cells.nth(idx_credit).inner_text()).strip()

                        if subject_code and subject_name:
                            main_subject_rows_data.append({
                                "code": subject_code,
                                "name": subject_name,
                                "semester_text": semester_text,
                                "credit_text": credit_text
                            })
                    except Exception as e:
                        print(
                            f"Lỗi khi trích xuất dữ liệu từ một hàng trong bảng {i}, hàng {k}: {e}")
        # else:
        #     print(f"Bảng {i} không phải bảng môn học (header không khớp: {header_texts})")

    print(
        f"Tìm thấy {len(main_subject_rows_data)} hàng môn học tiềm năng trong khung chương trình chính từ các bảng.")

    for subject_data in main_subject_rows_data:
        subject_code = subject_data["code"]
        subject_name = subject_data["name"]
        semester_text = subject_data["semester_text"]

        semester = None
        is_semester_valid = False
        if semester_text.isdigit() and semester_text != "":
            semester = int(semester_text)
            is_semester_valid = True

        if subject_code and "PHE_COM" not in subject_code.upper() and \
           "VOV" not in subject_code.upper() and \
           "PDP" not in subject_code.upper() and \
           not subject_code.upper().startswith("SSG") and \
           not subject_code.upper().startswith("GDQP"):
            if is_semester_valid and semester == 0:
                print(
                    f"Bỏ qua môn {subject_code} - {subject_name} vì thuộc kỳ 0.")
                continue

            is_placeholder_combo_code = "COM" in subject_code.upper() and any(char.isdigit()
                                                                              for char in subject_code.split("COM")[-1])

            if is_placeholder_combo_code and "PHE_COM" not in subject_code.upper():
                print(
                    f"Môn {subject_code} ({subject_name}) được xác định là placeholder cho combo, sẽ được xử lý ở phần combo.")
            else:
                curriculum_subjects.append({
                    "code": subject_code,
                    "name": subject_name,
                    "semester": semester if is_semester_valid else semester_text,
                    "type": "core"
                })
                print(
                    f"Đã thêm môn: {subject_code} - {subject_name} (Kỳ: {semester_text})")
        else:
            if subject_code:
                print(
                    f"Bỏ qua môn: {subject_code} - {subject_name} (do là PHE_COM, VOV, PDP, SSG, GDQP hoặc rỗng)")

    print(
        f"Đã lấy {len(curriculum_subjects)} môn từ khung chương trình chính (sau khi lọc).")

    print("Kiểm tra và xử lý các môn Combo...")
    try:
        view_combo_button = page.locator('a[href*="/Compo/ViewComBo"]')
        if await view_combo_button.count() > 0:
            print("Tìm thấy nút 'View Combo'. Đang bấm...")
            await view_combo_button.first.click()
            await page.wait_for_load_state("networkidle", timeout=60000)
            print("Đã vào trang danh sách Combo.")

            combo_page_url = page.url
            combo_links_locator = page.locator(
                '//table//tbody//tr//td//a[contains(@href, "/Compo/Detail/")]')
            combo_count = await combo_links_locator.count()
            print(f"Tìm thấy {combo_count} combo.")

            combo_details_to_scrape = []
            for i in range(combo_count):
                combo_link_element = combo_links_locator.nth(i)
                combo_name_full = (await combo_link_element.inner_text()).strip()
                combo_href = await combo_link_element.get_attribute("href")
                combo_short_name = combo_name_full.split(":")[0].strip()

                if "PHE_COM" in combo_name_full.upper():
                    print(f"Bỏ qua combo '{combo_name_full}' do là PHE_COM.")
                    continue
                print(
                    f"Đang chuẩn bị lấy chi tiết cho combo: {combo_name_full}")
                combo_details_to_scrape.append(
                    {"name": combo_name_full, "short_name": combo_short_name, "href": combo_href})

            for combo_info in combo_details_to_scrape:
                print(
                    f"Đang điều hướng đến chi tiết combo: {combo_info['name']}")
                absolute_combo_url = urllib.parse.urljoin(
                    page.url, combo_info['href'])
                await page.goto(absolute_combo_url, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=60000)

                combo_subject_rows = page.locator(
                    '//table[.//th[contains(text(),"Subject Code")]]/tbody/tr[td]')
                combo_subject_count = await combo_subject_rows.count()
                print(
                    f"Tìm thấy {combo_subject_count} môn trong combo '{combo_info['name']}'.")

                for j in range(combo_subject_count):
                    row = combo_subject_rows.nth(j)
                    cells = row.locator("td")
                    if await cells.count() >= 4:
                        try:
                            combo_subject_code = (await cells.nth(1).inner_text()).strip()
                            combo_subject_name = (await cells.nth(2).inner_text()).strip()
                            combo_semester_text = (await cells.nth(3).inner_text()).strip()
                            semester = None
                            if combo_semester_text.isdigit():
                                semester = int(combo_semester_text)
                            if combo_subject_code:
                                curriculum_subjects.append({
                                    "code": combo_subject_code,
                                    "name": combo_subject_name,
                                    "semester": semester if semester is not None else combo_semester_text,
                                    "type": "combo",
                                    "combo_name": combo_info['name'],
                                    "combo_short_name": combo_info['short_name']
                                })
                                print(
                                    f"  Đã thêm môn combo: {combo_subject_code} - {combo_subject_name} (Kỳ: {combo_semester_text}) từ combo '{combo_info['name']}'")
                        except Exception as e:
                            print(
                                f"Lỗi khi xử lý một hàng môn học trong combo '{combo_info['name']}': {e}")
                print(
                    f"Đã lấy xong môn cho combo '{combo_info['name']}'. Quay lại trang danh sách combo.")
                await page.goto(combo_page_url, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=60000)
            print("Đã xử lý xong tất cả các combo hợp lệ.")
            print(f"Quay lại trang khung chương trình: {curriculum_page_url}")
            await page.goto(curriculum_page_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)
        else:
            print("Không tìm thấy nút 'View Combo'. Bỏ qua phần xử lý combo.")
    except Exception as e:
        print(f"Lỗi trong quá trình xử lý combo: {e}")
        if curriculum_page_url and page.url != curriculum_page_url:
            await page.goto(curriculum_page_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)

    print(
        f"Tổng số môn học đã thu thập (bao gồm cả combo): {len(curriculum_subjects)}")
    unique_subjects_dict = {}
    for s in curriculum_subjects:
        if s['code'] in unique_subjects_dict:
            if s['type'] == 'combo' and unique_subjects_dict[s['code']]['type'] != 'combo':
                unique_subjects_dict[s['code']] = s
            elif s['type'] == 'combo' and unique_subjects_dict[s['code']]['type'] == 'combo':
                existing_combo_name = unique_subjects_dict[s['code']].get(
                    'combo_name', '')
                new_combo_name = s.get('combo_name', '')
                if new_combo_name and new_combo_name not in existing_combo_name:
                    unique_subjects_dict[s['code']
                                         ]['combo_name'] = f"{existing_combo_name}; {new_combo_name}"
                existing_short_name = unique_subjects_dict[s['code']].get(
                    'combo_short_name', '')
                new_short_name = s.get('combo_short_name', '')
                if new_short_name and new_short_name not in existing_short_name:
                    unique_subjects_dict[s['code']
                                         ]['combo_short_name'] = f"{existing_short_name}; {new_short_name}"
        else:
            unique_subjects_dict[s['code']] = s

    all_subjects = list(unique_subjects_dict.values())
    print(f"Tổng số môn học duy nhất: {len(all_subjects)}")
    for subj in all_subjects:
        print(f" - {subj['code']}: {subj['name']} (Kỳ: {subj.get('semester', 'N/A')}, Loại: {subj['type']}, Combo: {subj.get('combo_short_name', 'N/A')})")

    # Điều hướng trực tiếp đến trang Syllabus Management (không cần click button)
    # FLM sử dụng URL dạng /gui/role/student/... (có prefix /gui/)
    print("Điều hướng trực tiếp đến trang Syllabus Management...")
    
    syllabus_urls_to_try = [
        "https://flm.fpt.edu.vn/gui/role/student/SyllabusManagement",
        "https://flm.fpt.edu.vn/gui/role/student/SyllabusManagement.aspx",
        "https://flm.fpt.edu.vn/role/student/SyllabusManagement.aspx",
        "https://flm.fpt.edu.vn/role/student/SyllabusManagement",
    ]
    
    syllabus_page_loaded = False
    for syl_url in syllabus_urls_to_try:
        try:
            print(f"  Thử URL: {syl_url}")
            await page.goto(syl_url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            # Kiểm tra xem trang có phải Syllabus Management không
            if "syllabus" in page.url.lower() or await page.locator("#txtSubCode, #btnSearch, #gvSyllabus").first.count() > 0:
                syllabus_page_loaded = True
                print(f"  ✅ Đã vào trang Syllabus Management. URL: {page.url}")
                break
        except Exception as e:
            print(f"  ❌ URL {syl_url} không hoạt động: {e}")
            continue
    
    if not syllabus_page_loaded:
        print("⚠️ Không thể vào trang Syllabus Management bằng URL trực tiếp.")
        print("Thử quay về Home và tìm nút View Syllabus...")
        await page.goto("https://flm.fpt.edu.vn/Home", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        
        # Screenshot để debug
        print(f"URL hiện tại: {page.url}")
        print("Tìm tất cả các link trên trang...")
        all_links = page.locator("a[href]")
        link_count = await all_links.count()
        for i in range(min(link_count, 30)):
            href = await all_links.nth(i).get_attribute("href")
            text = (await all_links.nth(i).inner_text()).strip()
            if text:
                print(f"  Link: '{text}' -> {href}")
        
        # Tìm bất kỳ link nào liên quan đến Syllabus
        syllabus_link = page.locator('a[href*="yllabus" i]').first
        if await syllabus_link.count() > 0:
            print("Tìm thấy link Syllabus, đang click...")
            await syllabus_link.click()
            await page.wait_for_load_state("networkidle", timeout=60000)
            await page.wait_for_timeout(2000)
        else:
            print("KHÔNG tìm thấy link Syllabus nào trên trang Home. Dừng lại.")
            await context.close()
            return
    
    syllabus_search_page_url = page.url

    all_syllabus_data_final = []

    for subject_info in all_subjects:
        subject_code_to_search = subject_info["code"]
        print(
            f"\\nĐang tìm kiếm syllabus cho môn: {subject_code_to_search} - {subject_info['name']}")

        if page.url != syllabus_search_page_url and not page.url.startswith(syllabus_search_page_url.split("?")[0]):
            print(
                f"Không ở trang tìm kiếm syllabus (URL hiện tại: {page.url}). Điều hướng lại: {syllabus_search_page_url}")
            await page.goto(syllabus_search_page_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)

        try:
            search_input_syllabus = page.locator("#txtSubCode")
            await search_input_syllabus.fill(subject_code_to_search)
            search_button_syllabus = page.locator("#btnSearch")
            await search_button_syllabus.click()
            await page.wait_for_load_state("networkidle", timeout=60000)
            print(f"Đã tìm kiếm syllabus cho {subject_code_to_search}.")
        except Exception as e:
            print(
                f"Lỗi khi nhập hoặc bấm nút tìm kiếm syllabus cho {subject_code_to_search}: {e}")
            continue

        try:
            syllabus_link_xpath = (
                f"//table[@id='gvSyllabus']/tbody/tr"
                f"[td[2][normalize-space(translate(normalize-space(text()), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')) = '{subject_code_to_search.upper()}']]"
                f"[1]/td[4]/a[contains(@href, 'SyllabusDetails.aspx')]"
            )
            syllabus_link_locator = page.locator(syllabus_link_xpath)

            if await syllabus_link_locator.count() > 0:
                print(
                    f"Bấm vào link syllabus của {subject_code_to_search} (XPath chính)...")
                await syllabus_link_locator.first.click()
                await page.wait_for_load_state("networkidle", timeout=60000)
                print(
                    f"Đã mở trang chi tiết syllabus cho {subject_code_to_search}.")

                syllabus_data_extracted = await extract_syllabus_details(page, subject_info)
                if syllabus_data_extracted:
                    major_info_data["syllabuses"].append(
                        syllabus_data_extracted)
                    print(
                        f"Đã crawl xong syllabus cho {subject_code_to_search}.")
                else:
                    print(
                        f"Không thể crawl syllabus cho {subject_code_to_search}.")

                print(
                    f"Đã xử lý xong {subject_code_to_search}. Quay lại trang tìm kiếm: {syllabus_search_page_url}")
                await page.goto(syllabus_search_page_url, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=60000)

            else:
                print(
                    f"Không tìm thấy link syllabus cho {subject_code_to_search} bằng XPath chính. Thử tìm cách khác...")
                all_links_in_table = page.locator(
                    f"//table[@id='gvSyllabus']//a[contains(@href, 'SyllabusDetails.aspx')]")
                found_fallback = False
                for i in range(await all_links_in_table.count()):
                    link = all_links_in_table.nth(i)
                    row_of_link = link.locator("xpath=ancestor::tr[1]")
                    if await row_of_link.count() > 0:
                        cell_with_code = row_of_link.locator(
                            "td").nth(1)
                        if await cell_with_code.count() > 0:
                            code_text_in_cell = (await cell_with_code.inner_text()).strip()
                            if code_text_in_cell.upper() == subject_code_to_search.upper():
                                print(
                                    f"Bấm vào link syllabus của {subject_code_to_search} (Fallback)...")
                                await link.click()
                                await page.wait_for_load_state("networkidle", timeout=60000)
                                print(
                                    f"Đã mở trang chi tiết syllabus cho {subject_code_to_search}.")

                                syllabus_data_extracted = await extract_syllabus_details(page, subject_info)
                                if syllabus_data_extracted:
                                    major_info_data["syllabuses"].append(
                                        syllabus_data_extracted)
                                print(
                                    f"Đã crawl xong syllabus cho {subject_code_to_search}.")
                                print(
                                    f"Đã xử lý xong {subject_code_to_search} (fallback). Quay lại trang tìm kiếm: {syllabus_search_page_url}")
                                await page.goto(syllabus_search_page_url, timeout=60000)
                                await page.wait_for_load_state("networkidle", timeout=60000)
                                found_fallback = True
                                break
                if not found_fallback:
                    print(
                        f"Không tìm thấy link syllabus cho {subject_code_to_search} sau khi tìm kiếm (kể cả fallback). Bỏ qua.")

        except Exception as e:
            print(
                f"Lỗi khi xử lý syllabus cho môn {subject_code_to_search}: {e}")
            print(
                f"Đang ở URL: {page.url}. Sẽ thử quay lại trang tìm kiếm syllabus.")
            try:
                if page.url != syllabus_search_page_url:
                    await page.goto(syllabus_search_page_url, timeout=60000)
                    await page.wait_for_load_state("networkidle", timeout=60000)
            except Exception as nav_err:
                print(
                    f"Không thể quay lại trang tìm kiếm syllabus. Thử về Home rồi vào lại Syllabus Management. Lỗi: {nav_err}")
                try:
                    await page.locator("a#btn-home").click()
                    await page.wait_for_load_state("networkidle", timeout=60000)
                    await page.goto(syllabus_search_page_url, timeout=60000)
                    await page.wait_for_load_state("networkidle", timeout=60000)
                    syllabus_search_page_url = page.url
                    print("Đã quay về trang Syllabus Management qua Home.")
                except Exception as final_nav_err:
                    print(
                        f"Không thể điều hướng về Syllabus Management ngay cả qua Home. Bỏ qua môn {subject_code_to_search}. Lỗi: {final_nav_err}")
            continue

    print("\\n--- HOÀN TẤT QUÁ TRÌNH CRAWL ---")
    if major_info_data["syllabuses"]:
        output_filename = f"flm_data_{major_code}.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(major_info_data, f, ensure_ascii=False, indent=2)
        print(f"Đã lưu dữ liệu vào file: {output_filename}")
    else:
        print("Không có dữ liệu syllabus nào được thu thập cho ngành này.")

    await context.close()


async def extract_text_by_label(page, label_text, parent_locator=None, next_sibling_tag='dd', single_value=True, try_direct_id_format=None):
    """
    Hàm helper để lấy text từ element theo label của nó hoặc ID cụ thể.
    Ưu tiên tìm theo ID nếu `try_direct_id_format` được cung cấp.
    Sau đó, ưu tiên cấu trúc <dt><label>Text</label></dt><dd>Value</dd> hoặc <dt>Text</dt><dd>Value</dd>
    Hoặc cấu trúc <tr><td>Label</td><td>Value</td></tr>
    """
    base_element = page.locator(parent_locator) if parent_locator else page
    normalized_label_text = label_text.strip().rstrip(':')

    # Try direct ID format first if specified (e.g., "lbl{LabelTextNoSpaces}")
    if try_direct_id_format:
        # Example: "Credit(s)" -> "lblNoCredit", "Syllabus ID" -> "lblSyllabusID"
        id_to_try = try_direct_id_format.replace("{LabelTextNoSpaces}", normalized_label_text.replace(
            " ", "").replace("(", "").replace(")", "").replace("'", ""))
        # Specific common known mappings
        if normalized_label_text.lower() == "credit(s)":
            id_to_try = "lblNoCredit"
        elif normalized_label_text.lower() == "prerequisite(s)":
            id_to_try = "lblPreRequisite"
        elif normalized_label_text.lower() == "student task(s)":
            id_to_try = "lblStudentTask"
        elif normalized_label_text.lower() == "tool(s)":
            id_to_try = "lblTools"
        elif normalized_label_text.lower() == "decision no. mm/dd/yyyy":
            id_to_try = "lblDecisionNo"  # Handle label variation
        elif normalized_label_text.lower() == "decision no.":
            id_to_try = "lblDecisionNo"
        elif normalized_label_text.lower() == "isapproved":
            id_to_try = "lblIsApproved"
        elif normalized_label_text.lower() == "minavgmarktopass":
            id_to_try = "lblMinAvgMarkToPass"
        elif normalized_label_text.lower() == "isactive":
            id_to_try = "lblIsActive"
        elif normalized_label_text.lower() == "approveddate":
            id_to_try = "lblApprovedDate"

        direct_id_locator = base_element.locator(f"#{id_to_try}")
        if await direct_id_locator.count() > 0:
            text_content = (await direct_id_locator.first.all_inner_texts())
            joined_text = "\\n".join(text_content).strip()
            if joined_text:
                return joined_text if single_value else [joined_text]

    # Try dt/dd structure (like in DWP301c.html)
    dt_xpath = f"//dt[label[normalize-space(.)='{normalized_label_text}'] or normalize-space(.)='{normalized_label_text}']"
    dt_elements = base_element.locator(dt_xpath)
    count = await dt_elements.count()
    if count > 0:
        values = []
        for i in range(count):
            dt_element = dt_elements.nth(i)
            # Check for dd, div, or p as the following sibling
            value_element = dt_element.locator(
                f"xpath=./following-sibling::{next_sibling_tag}[1] | ./following-sibling::div[1] | ./following-sibling::p[1]")
            if await value_element.count() > 0:
                all_text = await value_element.first.all_inner_texts()
                text_content = "\\n".join(all_text).strip()
                if text_content:
                    values.append(text_content)
            else:  # Sometimes value is part of dt itself after a colon or similar
                dt_text_content = (await dt_element.inner_text()).replace(normalized_label_text, "").strip().lstrip(':').strip()
                if dt_text_content:
                    values.append(dt_text_content)
        if values:
            return values[0] if single_value else values

    # Try tr/td structure (like in CSI106.html's #table-detail)
    # Matches: <td>Label:</td><td>Value</td> OR <td>Label</td><td>Value</td>
    # And ensures the label text is primarily in the first td
    tr_xpath = f"//tr[ (td[1][contains(normalize-space(.),'{normalized_label_text}')] or th[1][contains(normalize-space(.),'{normalized_label_text}')]) and (td[2] or th[2]) ]"
    tr_elements = base_element.locator(tr_xpath)
    tr_count = await tr_elements.count()

    if tr_count > 0:
        values = []
        for i in range(tr_count):
            first_cell = tr_elements.nth(i).locator("td, th").first
            first_cell_text = (await first_cell.inner_text()).strip()
            # Check if the first cell is indeed the label we are looking for (more precise match)
            if normalized_label_text.lower() in first_cell_text.lower().rstrip(':').lower():
                value_cell = tr_elements.nth(i).locator(
                    "td:nth-child(2), th:nth-child(2)")
                if await value_cell.count() > 0:
                    text_content_list = await value_cell.first.all_inner_texts()
                    joined_text = "\\n".join(text_content_list).strip()

                    # If value_cell has a span with an ID, prefer that text
                    span_in_value_cell = value_cell.first.locator("span[id]")
                    if await span_in_value_cell.count() > 0:
                        span_text_list = await span_in_value_cell.first.all_inner_texts()
                        span_joined_text = "\\n".join(span_text_list).strip()
                        if span_joined_text:  # Prioritize span text if available
                            joined_text = span_joined_text

                    if joined_text:
                        values.append(joined_text)
        if values:
            return values[0] if single_value else values

    # Fallback: if label is something like "<h3>Label</h3><div>Value</div>"
    header_label_xpath = f"//h1[normalize-space(.)='{normalized_label_text}'] | //h2[normalize-space(.)='{normalized_label_text}'] | //h3[normalize-space(.)='{normalized_label_text}'] | //h4[normalize-space(.)='{normalized_label_text}'] | //b[normalize-space(.)='{normalized_label_text}'] | //strong[normalize-space(.)='{normalized_label_text}']"
    header_elements = base_element.locator(header_label_xpath)
    header_count = await header_elements.count()
    if header_count > 0:
        values = []
        for i in range(header_count):
            header_element = header_elements.nth(i)
            # Look for the next div, p, or ul/ol as the value container
            value_container = header_element.locator(
                "xpath=./following-sibling::div[1] | ./following-sibling::p[1] | ./following-sibling::ul[1] | ./following-sibling::ol[1]")
            if await value_container.count() > 0:
                all_text = await value_container.first.all_inner_texts()
                text_content = "\\n".join(all_text).strip()
                if text_content:
                    values.append(text_content)
        if values:
            return values[0] if single_value else values

    return "" if single_value else []


async def extract_syllabus_details(page, subject_info):
    subject_code = subject_info["code"]
    print(f"Bắt đầu trích xuất chi tiết syllabus cho {subject_code}...")
    data = {"metadata": {}, "materials": [], "learning_outcomes": [], "schedule": [
    ], "assessments": [], "has_download_materials_button": False}

    # --- URLs and IDs ---
    data["metadata"]["syllabus_url"] = page.url
    data["metadata"]["syllabus_id_from_url"] = page.url.split(
        "sylID=")[-1] if "sylID=" in page.url else ""
    data["metadata"]["course_id"] = subject_code
    data["metadata"]["course_name_from_curriculum"] = subject_info.get(
        "name", "")
    data["metadata"]["semester_from_curriculum"] = subject_info.get(
        "semester", "")
    data["metadata"]["combo_name_from_curriculum"] = subject_info.get(
        "combo_name", "")
    data["metadata"]["combo_short_name_from_curriculum"] = subject_info.get(
        "combo_short_name", "")

    # --- Determine main content area for metadata ---
    # DWP301c uses #tabs-1, CSI106 uses #table-detail which is a direct child of #content > div
    # For CSI106, the direct_id_format will be attempted first.
    # For DWP301c, it will fall back to dt/dd search within #tabs-1.
    metadata_container_selector_tabs = "#tabs-1"  # For DWP301c style
    # For CSI106 style
    metadata_container_selector_table = "div#content > div > table#table-detail.table-detail"

    # Attempt to find the main h1 title first
    h1_title_loc = page.locator("div#content h1.mb-4").first
    h1_title_text = ""
    if await h1_title_loc.count() > 0:
        h1_title_text = (await h1_title_loc.inner_text()).strip()

    # --- Title and English Title ---
    try:
        # Try CSI106 style first (specific spans)
        title_val = ""
        eng_title_val = ""

        lbl_syllabus_name = page.locator("#lblSyllabusName")
        if await lbl_syllabus_name.count() > 0:
            title_val = (await lbl_syllabus_name.first.inner_text()).strip()

        lbl_syllabus_name_eng = page.locator("#lblSyllabusNameEnglish")
        if await lbl_syllabus_name_eng.count() > 0:
            eng_title_val = (await lbl_syllabus_name_eng.first.inner_text()).strip()

        if title_val:
            data["metadata"]["title"] = title_val
            data["metadata"]["english_title"] = eng_title_val if eng_title_val else title_val.split(
                "_")[0].strip()  # Fallback if no specific english title
        else:  # Try DWP301c style
            title_el = page.locator(
                f"{metadata_container_selector_tabs} div.title-page > h3").first
            if await title_el.count() > 0:
                title_text = (await title_el.inner_text()).strip()
                data["metadata"]["title"] = title_text
                if "_" in title_text:  # DWP301c often has English_Vietnamese
                    parts = title_text.split("_", 1)
                    data["metadata"]["english_title"] = parts[0].strip()
                else:
                    data["metadata"]["english_title"] = title_text
            # Fallback to general h1 if specific selectors fail
            elif h1_title_text and "syllabus details" not in h1_title_text.lower():
                data["metadata"]["title"] = h1_title_text
                # Assume same if not specified
                data["metadata"]["english_title"] = h1_title_text
            else:  # Ultimate fallback
                data["metadata"]["title"] = subject_info.get(
                    "name", f"Syllabus for {subject_code}")
                data["metadata"]["english_title"] = subject_info.get(
                    "name", f"Syllabus for {subject_code}")

        print(f"  Title: {data['metadata']['title']}")
        print(f"  English Title: {data['metadata']['english_title']}")

    except Exception as e:
        print(f"Lỗi khi lấy title: {e}")
        if h1_title_text and "syllabus details" not in h1_title_text.lower():
            data["metadata"]["title"] = h1_title_text
            data["metadata"]["english_title"] = h1_title_text
        else:
            data["metadata"]["title"] = subject_info.get(
                "name", f"Syllabus for {subject_code}")
            data["metadata"]["english_title"] = subject_info.get(
                "name", f"Syllabus for {subject_code}")

    # --- Other Metadata ---
    # The direct_id_format "lbl{LabelTextNoSpaces}" is for CSI106.html like structures using #lbl... spans
    # For DWP301c, it will use the dt/dd search within the #tabs-1 parent_locator.
    # For CSI106, it will try direct ID, then tr/td search within the #table-detail parent_locator.

    # Default to CSI106 style for direct ID attempt
    current_metadata_container = metadata_container_selector_table
    if await page.locator(metadata_container_selector_tabs).count() > 0 and await page.locator(metadata_container_selector_tabs).is_visible():
        # Switch if DWP301c style is prominent
        current_metadata_container = metadata_container_selector_tabs

    # If neither primary container is found, use page as base for extract_text_by_label
    if not await page.locator(current_metadata_container).count():
        print(
            f"  Không tìm thấy container metadata chính ({metadata_container_selector_tabs} hoặc {metadata_container_selector_table}). Sẽ tìm trên toàn trang.")
        current_metadata_container = None

    data["metadata"]["syllabus_id"] = await extract_text_by_label(page, "Syllabus ID", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or data["metadata"]["syllabus_id_from_url"]
    data["metadata"]["syllabus_code"] = await extract_text_by_label(page, "Syllabus Code", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or data["metadata"]["syllabus_id"]

    # Subject Code (usually taken from subject_info, but can verify)
    subject_code_from_page = await extract_text_by_label(page, "Subject Code", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    if subject_code_from_page and subject_code_from_page.upper() != subject_code.upper():
        print(
            f"  Cảnh báo: Mã môn học trên trang ({subject_code_from_page}) khác với mã đang tìm ({subject_code}).")
        # Decide if you want to use subject_code_from_page or keep the original one
    data["metadata"]["subject_code_on_page"] = subject_code_from_page

    data["metadata"]["credits"] = await extract_text_by_label(page, "Credit(s)", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "NoCredit", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")  # Alias for CSI106
    # Default
    data["metadata"]["degree_level"] = await extract_text_by_label(page, "Degree Level", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or "Bachelor"
    data["metadata"]["time_allocation"] = await extract_text_by_label(page, "Time allocation", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["prerequisites"] = await extract_text_by_label(page, "Pre-Requisite", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "Prerequisite(s)", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")

    desc_val = await extract_text_by_label(page, "Description", current_metadata_container, next_sibling_tag='div', try_direct_id_format="lbl{LabelTextNoSpaces}")
    if not desc_val:
        desc_val = await extract_text_by_label(page, "Description", current_metadata_container, next_sibling_tag='dd', try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["description"] = desc_val

    data["metadata"]["student_tasks"] = await extract_text_by_label(page, "Student task(s)", current_metadata_container, next_sibling_tag='div', try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "StudentTasks", current_metadata_container, next_sibling_tag='div', try_direct_id_format="lbl{LabelTextNoSpaces}")

    data["metadata"]["tools"] = await extract_text_by_label(page, "Tool(s)", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["scoring_scale"] = await extract_text_by_label(page, "Scoring Scale", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or "10"
    data["metadata"]["min_avg_mark_to_pass"] = await extract_text_by_label(page, "MinAvgMarkToPass", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "Min average mark to pass", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or "5"

    approved_text = await extract_text_by_label(page, "IsApproved", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["is_approved"] = "True" if approved_text.lower(
    ) == "approved" or approved_text.lower() == "true" else "False"

    status_text = await extract_text_by_label(page, "IsActive", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "Status", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["is_active"] = "True" if status_text.lower(
    ) == "active" or status_text.lower() == "true" else "False"

    # Infer active if approved and no status
    if not status_text and data["metadata"]["is_approved"] == "True":
        data["metadata"]["is_active"] = "True"

    decision_no_text = await extract_text_by_label(page, "Decision No. MM/dd/yyyy", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "DecisionNo MM/dd/yyyy", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "Decision No.", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["decision_no"] = decision_no_text.strip(
    ) if decision_no_text else ""

    approved_date_from_decision = ""
    if data["metadata"]["decision_no"]:
        # Regex to find date like dd/mm/yyyy or mm/dd/yyyy possibly after "dated" or just in the string
        match = re.search(
            r'(?:dated\s+)?(\d{1,2}/\d{1,2}/\d{4})', data["metadata"]["decision_no"], re.IGNORECASE)
        if match:
            approved_date_from_decision = match.group(1)

    effective_date_text = await extract_text_by_label(page, "ApprovedDate", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}") or \
        await extract_text_by_label(page, "Effective Date", current_metadata_container, try_direct_id_format="lbl{LabelTextNoSpaces}")
    data["metadata"]["approved_date"] = effective_date_text.strip(
    ) if effective_date_text else approved_date_from_decision

    # Note (Grading Breakdown / Completion Criteria)
    # For DWP301c.html:
    grading_breakdown_header = page.locator(
        f"{metadata_container_selector_tabs} h4:has-text('Grading Breakdown')")
    if await grading_breakdown_header.count() > 0:
        note_elements = grading_breakdown_header.locator(
            "xpath=./following-sibling::*")
        note_texts = []
        for i in range(await note_elements.count()):
            tag_name = await note_elements.nth(i).evaluate("el => el.tagName.toLowerCase()")
            if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                if i > 0:  # Stop if we hit another header
                    break
            note_texts.append(await note_elements.nth(i).inner_text())
        data["metadata"]["note"] = "\\n".join(note_texts).strip()
    else:  # For CSI106.html or if "Grading Breakdown" header not found
        note_val = await extract_text_by_label(page, "Note", current_metadata_container, next_sibling_tag='div', try_direct_id_format="lbl{LabelTextNoSpaces}")
        data["metadata"]["note"] = note_val

    print(f"  Metadata extracted.")

    print("  Extracting materials...")
    # No tab clicking needed. Directly look for the table.
    material_rows_locator = page.locator(
        # Includes header if no tbody
        "table#gvMaterial tbody tr, table#gvMaterial tr:not(:first-child)")
    # If tbody is empty or not present, try without tbody
    if await page.locator("table#gvMaterial tbody tr").count() == 0:
        material_rows_locator = page.locator("table#gvMaterial tr")

    material_count = await material_rows_locator.count()
    header_skipped = False
    if material_count > 0:
        # Check if the first row is a header row based on th tags
        first_row_is_header_loc = material_rows_locator.first.locator("th")
        if await first_row_is_header_loc.count() > 0:
            header_skipped = True
            print(f"    Skipping header row in gvMaterial.")

    print(
        f"    Found {material_count} potential material rows (including header if present).")

    actual_material_rows_to_process = material_count - \
        1 if header_skipped else material_count
    start_index = 1 if header_skipped else 0

    for i in range(start_index, material_count):
        row = material_rows_locator.nth(i)
        cells = row.locator("td")
        if await cells.count() >= 10:  # Expect at least 10 columns for materials
            try:
                mat = {
                    # Index 0 for CSI106, 1 for DWP301c (if # is first)
                    "description": (await cells.nth(0).inner_text()).strip(),
                    "author": (await cells.nth(1).inner_text()).strip(),
                    "publisher": (await cells.nth(2).inner_text()).strip(),
                    "published_date": (await cells.nth(3).inner_text()).strip(),
                    "edition": (await cells.nth(4).inner_text()).strip(),
                    "isbn": (await cells.nth(5).inner_text()).strip(),
                    "is_main_material": await cells.nth(6).locator("input[type='checkbox']").is_checked(),
                    "is_hard_copy": await cells.nth(7).locator("input[type='checkbox']").is_checked(),
                    "is_online": await cells.nth(8).locator("input[type='checkbox']").is_checked(),
                    "note": (await cells.nth(9).inner_text()).strip()
                }
                # Adjust indices if the first column is a number/selector column for DWP301c
                # DWP301c first td can be a number
                if await cells.first.locator("input[type='checkbox']").count() == 0 and (await cells.first.inner_text()).strip().isdigit():
                    mat = {
                        "description": (await cells.nth(1).inner_text()).strip(),
                        "author": (await cells.nth(2).inner_text()).strip(),
                        "publisher": (await cells.nth(3).inner_text()).strip(),
                        "published_date": (await cells.nth(4).inner_text()).strip(),
                        "edition": (await cells.nth(5).inner_text()).strip(),
                        "isbn": (await cells.nth(6).inner_text()).strip(),
                        "is_main_material": await cells.nth(7).locator("input[type='checkbox']").is_checked(),
                        "is_hard_copy": await cells.nth(8).locator("input[type='checkbox']").is_checked(),
                        "is_online": await cells.nth(9).locator("input[type='checkbox']").is_checked(),
                        "note": (await cells.nth(10).inner_text()).strip() if await cells.count() > 10 else ""
                    }

                if "coursera.org/learn/" in mat["description"] and not mat["publisher"]:
                    mat["publisher"] = "Coursera"
                    mat["is_online"] = True
                data["materials"].append(mat)
            except Exception as e:
                print(f"    Error processing a material row: {e}")
        elif await cells.count() > 0:  # Log if row has cells but not enough
            print(f"    Skipping material row {i-start_index+1} due to insufficient columns: {await cells.count()} found.")

    print(f"    Extracted {len(data['materials'])} materials.")

    print("  Extracting learning outcomes...")
    # No tab clicking. Directly look for the table.
    clo_rows_locator = page.locator(
        "table#gvLO tbody tr, table#gvLO tr:not(:first-child)")
    if await page.locator("table#gvLO tbody tr").count() == 0:
        clo_rows_locator = page.locator("table#gvLO tr")

    clo_count = await clo_rows_locator.count()
    header_skipped_clo = False
    if clo_count > 0:
        first_row_is_header_loc_clo = clo_rows_locator.first.locator("th")
        if await first_row_is_header_loc_clo.count() > 0:
            header_skipped_clo = True
            print(f"    Skipping header row in gvLO.")

    print(
        f"    Found {clo_count} potential CLO rows (including header if present).")
    start_index_clo = 1 if header_skipped_clo else 0

    for i in range(start_index_clo, clo_count):
        row = clo_rows_locator.nth(i)
        cells = row.locator("td")
        # DWP301c: CLO Name (text or input), CLO Details, LO Details
        # CSI106: No (text), CLO Name, CLO Details
        if await cells.count() >= 2:  # Minimum for ID and Details
            try:
                clo_id_text = (await cells.nth(0).inner_text()).strip()
                details_text = ""

                if await cells.count() >= 3:  # Likely CSI106 structure or DWP301c with 3 cols
                    # Check if first col is numeric (CSI106 'No.' or DWP301c 'No.')
                    # If first col is number, second is ID, third is Details
                    if clo_id_text.isdigit() or (await cells.nth(0).locator("input").count() > 0 and (await cells.nth(0).locator("input").first.get_attribute("value") or "").isdigit()):
                        # Actual CLO ID like "CLO1"
                        clo_id_text = (await cells.nth(1).inner_text()).strip()
                        details_text = (await cells.nth(2).inner_text()).strip()
                    # Assume first col is ID, second is Details (DWP301c old structure)
                    else:
                        details_text = (await cells.nth(1).inner_text()).strip()
                else:  # Only 2 columns, first is ID, second is Details
                    details_text = (await cells.nth(1).inner_text()).strip()

                if clo_id_text and details_text:
                    data["learning_outcomes"].append(
                        {"id": clo_id_text, "details": details_text})
            except Exception as e:
                print(f"    Error processing a CLO row: {e}")
        elif await cells.count() > 0:
            print(f"    Skipping CLO row {i-start_index_clo+1} due to insufficient columns: {await cells.count()} found.")

    print(f"    Extracted {len(data['learning_outcomes'])} learning outcomes.")

    print("  Extracting schedule...")
    # No tab clicking. Directly look for the table.
    schedule_rows_locator = page.locator(
        "table#gvSchedule tbody tr, table#gvSchedule tr:not(:first-child)")
    if await page.locator("table#gvSchedule tbody tr").count() == 0:
        schedule_rows_locator = page.locator("table#gvSchedule tr")

    schedule_count = await schedule_rows_locator.count()
    header_skipped_schedule = False
    if schedule_count > 0:
        first_row_is_header_loc_schedule = schedule_rows_locator.first.locator(
            "th")
        if await first_row_is_header_loc_schedule.count() > 0:
            header_skipped_schedule = True
            print(f"    Skipping header row in gvSchedule.")

    print(
        f"    Found {schedule_count} schedule rows (including header if present).")
    start_index_schedule = 1 if header_skipped_schedule else 0

    for i in range(start_index_schedule, schedule_count):
        row = schedule_rows_locator.nth(i)
        cells = row.locator("td")
        # Expect Session, Topic, Learning Activities (Teaching Type), CLOs, ITU, Student Materials, S-Download, Student Tasks
        # DWP301c: 8 columns (0-7)
        # CSI106: 9 columns (0-8) - col 0 is "No."
        expected_min_cols = 7  # Session to Student Tasks at least

        idx_session, idx_topic, idx_teaching_type, idx_clo, idx_itu, idx_materials, idx_download, idx_tasks = - \
            1, -1, -1, -1, -1, -1, -1, -1

        num_cells_actual = await cells.count()

        if num_cells_actual >= expected_min_cols:
            # Dynamic column mapping based on CSI106 (has 'No.' column) vs DWP301c
            first_cell_text_sched = (await cells.nth(0).inner_text()).strip()
            is_csi_style_sched = first_cell_text_sched.isdigit(
            ) and num_cells_actual >= 8  # CSI106 has 'No.' as first col

            if is_csi_style_sched:
                idx_session = 1
                idx_topic = 2
                idx_teaching_type = 3
                idx_clo = 4
                idx_itu = 5
                # Skipping "Activities" for now from CSI106 as it's not in DWP301c
                idx_materials = 6  # Student Materials
                idx_download = 7  # S-Download Link
                idx_tasks = 8     # Student Task
            else:  # DWP301c style
                idx_session = 0
                idx_topic = 1
                idx_teaching_type = 2
                idx_clo = 3
                idx_itu = 4
                idx_materials = 5  # Student Materials
                idx_download = 6  # S-Download Link
                idx_tasks = 7     # Student Tasks

            try:
                session_item = {
                    "session": (await cells.nth(idx_session).inner_text()).strip(),
                    "topic": (await cells.nth(idx_topic).inner_text()).strip(),
                    "teaching_type": (await cells.nth(idx_teaching_type).inner_text()).strip(),
                    "learning_outcomes": [(lo.strip()) for lo in (await cells.nth(idx_clo).inner_text()).split(',') if lo.strip()],
                    "itu": (await cells.nth(idx_itu).inner_text()).strip(),
                    "materials": (await cells.nth(idx_materials).inner_text()).strip(),
                    "tasks": (await cells.nth(idx_tasks).inner_text()).strip() if idx_tasks < num_cells_actual else ""
                }

                if idx_download < num_cells_actual:
                    download_cell = cells.nth(idx_download)
                    download_link_el = download_cell.locator("a")
                    if await download_link_el.count() > 0:
                        href_val = await download_link_el.first.get_attribute("href")
                        if href_val and href_val.strip() != "#":  # Ensure it's a real link
                            session_item["download_link"] = href_val
                        else:  # If href is '#' or empty, take the text content if any
                            link_text = (await download_link_el.first.inner_text()).strip()
                            session_item["download_link"] = link_text if link_text else ""
                    else:  # No anchor, just text
                        session_item["download_link"] = (await download_cell.inner_text()).strip()
                else:
                    session_item["download_link"] = ""

                session_item["urls"] = ""  # Placeholder
                data["schedule"].append(session_item)
            except Exception as e:
                print(f"    Error processing a schedule row: {e}")
        elif await cells.count() > 0:
            print(f"    Skipping schedule row {i-start_index_schedule+1} due to insufficient columns: {await cells.count()} found.")
    print(f"    Extracted {len(data['schedule'])} schedule items.")

    for item in data["schedule"]:
        if "download_link" in item and item["download_link"]:
            link_text = item["download_link"]
            if link_text and not link_text.startswith("http") and not link_text.startswith("javascript:") and ("/" in link_text or "." in link_text):
                try:
                    # Check if it's already an absolute URL from a previous run or a valid relative path
                    if not urllib.parse.urlparse(link_text).scheme and not urllib.parse.urlparse(link_text).netloc:
                        item["download_link"] = urllib.parse.urljoin(
                            page.url, link_text.strip())
                except Exception:
                    pass  # Keep original if parsing fails

    print("  Extracting assessments...")
    # No tab clicking. Directly look for the table.
    assessment_rows_locator = page.locator(
        "table#gvAssessment tbody tr, table#gvAssessment tr:not(:first-child)")
    if await page.locator("table#gvAssessment tbody tr").count() == 0:
        assessment_rows_locator = page.locator("table#gvAssessment tr")

    assessment_count = await assessment_rows_locator.count()
    header_skipped_assessment = False
    if assessment_count > 0:
        first_row_is_header_loc_assessment = assessment_rows_locator.first.locator(
            "th")
        if await first_row_is_header_loc_assessment.count() > 0:
            header_skipped_assessment = True
            print(f"    Skipping header row in gvAssessment.")

    print(
        f"    Found {assessment_count} assessment rows (including header if present).")
    start_index_assessment = 1 if header_skipped_assessment else 0

    for i in range(start_index_assessment, assessment_count):
        row = assessment_rows_locator.nth(i)
        cells = row.locator("td")
        # DWP301c: Category, Type, Part, Weight(%), CLOs mapped, Duration, Question Type, No. Questions, Knowledge and Skill, Grading guide, Note (11 cols)
        # CSI106: Assessment Method, Type, Part, Weight, CLOs, Time, Format, Question type, Knowledge and Skills, Details/Notes (10 cols)
        # Need to map these carefully
        num_cells_assessment = await cells.count()
        if num_cells_assessment >= 10:  # Common minimum
            try:
                asm = {}
                # Try to determine structure by header or unique values if possible, for now, hardcode based on observed patterns
                is_dwp_style_assessment = num_cells_assessment >= 11  # DWP often has 11

                if is_dwp_style_assessment:
                    asm = {
                        "category": (await cells.nth(0).inner_text()).strip(),
                        "type": (await cells.nth(1).inner_text()).strip(),
                        "part": (await cells.nth(2).inner_text()).strip(),
                        "weight": (await cells.nth(3).inner_text()).strip().rstrip('%'),
                        "clos": [(clo.strip()) for clo in (await cells.nth(4).inner_text()).split(',') if clo.strip()],
                        "duration": (await cells.nth(5).inner_text()).strip(),
                        "question_type": (await cells.nth(6).inner_text()).strip(),
                        "no_question": (await cells.nth(7).inner_text()).strip(),
                        "knowledge_and_skill": (await cells.nth(8).inner_text()).strip(),
                        "grading_guide": (await cells.nth(9).inner_text()).strip(),
                        "note": (await cells.nth(10).inner_text()).strip()
                    }
                else:  # Assume CSI106 style (10 columns typically)
                    asm = {
                        # Assessment Method
                        "category": (await cells.nth(0).inner_text()).strip(),
                        "type": (await cells.nth(1).inner_text()).strip(),
                        "part": (await cells.nth(2).inner_text()).strip(),
                        "weight": (await cells.nth(3).inner_text()).strip().rstrip('%'),
                        "clos": [(clo.strip()) for clo in (await cells.nth(4).inner_text()).split(',') if clo.strip()],
                        # Time
                        "duration": (await cells.nth(5).inner_text()).strip(),
                        # Format
                        "question_type": (await cells.nth(6).inner_text()).strip(),
                        # Assumed if present, else empty
                        "no_question": (await cells.nth(7).inner_text()).strip(),
                        "knowledge_and_skill": (await cells.nth(8).inner_text()).strip(),
                        # Details/Notes
                        "note": (await cells.nth(9).inner_text()).strip(),
                        "grading_guide": ""  # Not explicitly in CSI106 example, defaults to empty
                    }

                # Default, will try to extract from note later
                asm["completion_criteria"] = ""
                if "final exam" in asm.get("category", "").lower() and data["metadata"].get("note"):
                    note_lower = data["metadata"]["note"].lower()
                    if "completion criteria:" in note_lower:
                        asm["completion_criteria"] = data["metadata"]["note"].split(
                            "Completion Criteria:")[-1].split("\\n")[0].strip()
                    # DWP301c style
                    elif "final te score >=" in data["metadata"]["note"].lower():
                        for line in data["metadata"]["note"].split("\\n"):
                            if "final te score >=" in line.lower():
                                asm["completion_criteria"] = line.strip()
                                break
                    elif ">=" in data["metadata"]["note"] and ("final exam" in note_lower or "final practical" in note_lower or "final theory" in note_lower):
                        for line in data["metadata"]["note"].split("\\n"):
                            # Avoid overly long lines
                            if ">=" in line and len(line) < 150:
                                asm["completion_criteria"] = line.strip()
                                break
                data["assessments"].append(asm)
            except Exception as e:
                print(f"    Error processing an assessment row: {e}")
        elif await cells.count() > 0:
            print(f"    Skipping assessment row {i-start_index_assessment+1} due to insufficient columns: {await cells.count()} found.")
    print(f"    Extracted {len(data['assessments'])} assessments.")

    download_all_button = page.locator(
        "a[id*='btnDownloadAll'], button[id*='btnDownloadAll'], input[type='button'][id*='DownloadAll'], a:has-text('Download All Materials')")
    if await download_all_button.count() > 0:
        first_dl_button = download_all_button.first
        if await first_dl_button.is_visible() and await first_dl_button.is_enabled():
            data["has_download_materials_button"] = True
    else:
        data["has_download_materials_button"] = False
    print(
        f"  Has 'Download All Materials' button: {data['has_download_materials_button']}")

    # --- Course Type Guess ---
    is_coursera_only = False
    is_coursera_hybrid = False
    if subject_code.lower().endswith('c'):
        is_coursera_only = True
    elif subject_code.lower().endswith('m'):
        is_coursera_hybrid = True
    student_tasks_lower = data["metadata"].get("student_tasks", "").lower()
    if "coursera" in student_tasks_lower and ("certification" in student_tasks_lower or "certificate" in student_tasks_lower):
        if not is_coursera_hybrid:
            is_coursera_only = True
    coursera_links_in_materials = 0
    for mat in data["materials"]:
        if "coursera.org" in mat.get("description", "") or "coursera" == mat.get("publisher", "").lower():
            coursera_links_in_materials += 1
    if coursera_links_in_materials > 0:
        if coursera_links_in_materials == len(data["materials"]) and len(data["materials"]) > 0:
            if not is_coursera_hybrid:
                is_coursera_only = True
        elif not is_coursera_only:
            is_coursera_hybrid = True
    data["metadata"]["course_type_guess"] = "coursera_only" if is_coursera_only else \
        "coursera_hybrid" if is_coursera_hybrid else \
        "traditional"
    print(
        f"  Guessed course type for {subject_code}: {data['metadata']['course_type_guess']}")
    print(f"Hoàn tất trích xuất syllabus cho {subject_code}.")
    return data


async def main():
    async with async_playwright() as playwright:
        await crawl_flm(playwright, major_code="BCH_BC")

if __name__ == "__main__":
    asyncio.run(main())