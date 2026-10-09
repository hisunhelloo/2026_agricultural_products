"""
공공데이터포털 오픈API: 한국농수산식품유통공사_일별 도,소매 가격정보 조회
https://www.data.go.kr/data/15156057/openapi.do

사용법:
    1) data.go.kr에서 위 데이터셋에 활용신청 -> 승인(자동승인) -> 마이페이지에서 서비스키(인증키) 발급 확인
    2) 프로젝트 루트의 .env 파일에서 PERDAY_PRICE_SERVICE_KEY=발급받은키 로 채워넣기
    3) python scripts/fetch_perday_price.py

API 명세 요약 (data/apispec/ 참고):
    - Method: GET, URL: https://apis.data.go.kr/B552845/perDay/price
    - 필수 파라미터: cond[exmn_ymd::GTE]/LTE(조사일자 범위), cond[ctgry_cd::EQ](부류코드),
      cond[item_cd::EQ](품목코드). 이 중 하나라도 빠지면 에러 없이 totalCount=0으로 응답되어
      "왜 안 되는지" 알기 어려우니 주의 (실제로 겪은 문제).
    - cond[mrkt_cd::EQ] : 시장코드 (선택, 가락도매 = 0110211)
    - numOfRows (최대 1000), pageNo로 페이지네이션
    - 응답 필드: exmn_ymd(조사일자), item_nm/vrty_nm/grd_nm(품목/품종/등급명), mrkt_nm(시장명),
      exmn_dd_prc(조사일가격), exmn_dd_cnvs_prc(조사일kg환산가격) 등

확인된 사실:
    - 2010년, 2015년, 2020년 데이터 모두 조회 성공 (가락도매, 배추 기준) -> 2015~2025 범위 확보 가능
"""

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")


def load_dotenv(path=None):
    """외부 패키지 없이 .env 파일을 읽어 os.environ에 채워넣는다 (이미 설정된 환경변수는 덮어쓰지 않음)."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()

SERVICE_KEY = os.environ.get("PERDAY_PRICE_SERVICE_KEY", "")
BASE_URL = "https://apis.data.go.kr/B552845/perDay/price"
GARAK_WHOLESALE_MRKT_CD = "0110211"  # 가락도매
VEGETABLE_CTGRY_CD = "200"  # 부류코드: 채소류 (필수)

# 품목코드 (부류코드 200 채소류 산하)
ITEM_CODES = {
    "배추": "211",
    "무": "231",
    "건고추": "241",
    "깐마늘(국산)": "258",
    "깐마늘(수입)": "259",
    "양파": "245",
    "파": "246",  # 대파 (6번째 후보 품목)
}


def fetch_page(start_ymd, end_ymd, item_cd, page_no, num_of_rows=1000,
               mrkt_cd=GARAK_WHOLESALE_MRKT_CD, ctgry_cd=VEGETABLE_CTGRY_CD):
    params = {
        "serviceKey": SERVICE_KEY,
        "returnType": "JSON",
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "cond[exmn_ymd::GTE]": start_ymd,
        "cond[exmn_ymd::LTE]": end_ymd,
        "cond[ctgry_cd::EQ]": ctgry_cd,
        "cond[item_cd::EQ]": item_cd,
    }
    if mrkt_cd:
        params["cond[mrkt_cd::EQ]"] = mrkt_cd

    url = BASE_URL + "?" + urllib.parse.urlencode(params, safe="[]:")
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def collect_item(item_name, item_cd, start_ymd, end_ymd, mrkt_cd=GARAK_WHOLESALE_MRKT_CD):
    page_no = 1
    total_count = None
    rows = []

    while True:
        data = fetch_page(start_ymd, end_ymd, item_cd, page_no, mrkt_cd=mrkt_cd)
        header = data["response"]["header"]
        body = data["response"]["body"]

        if header.get("resultCode") != "0":
            print(f"  [{item_name}] API 에러: {header}")
            break

        if total_count is None:
            total_count = body.get("totalCount", 0)
            print(f"  [{item_name}] totalCount = {total_count}")
            if total_count == 0:
                break

        items = body.get("items") or {}
        items = items.get("item", []) if isinstance(items, dict) else items
        if not items:
            break

        rows.extend(items)

        if page_no * 1000 >= total_count:
            break
        page_no += 1
        time.sleep(0.15)

    return rows


def collect_all(start_ymd, end_ymd, out_path, mrkt_cd=GARAK_WHOLESALE_MRKT_CD):
    all_rows = []
    for item_name, item_cd in ITEM_CODES.items():
        rows = collect_item(item_name, item_cd, start_ymd, end_ymd, mrkt_cd=mrkt_cd)
        print(f"  [{item_name}] {len(rows)} rows 수집")
        all_rows.extend(rows)
        time.sleep(0.2)

    if not all_rows:
        print("수집된 행이 없습니다.")
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fieldnames = sorted({k for row in all_rows for k in row.keys()})
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"저장 완료: {out_path} (총 {len(all_rows)} rows)\n")


if __name__ == "__main__":
    if not SERVICE_KEY:
        print("SERVICE_KEY가 설정되지 않았습니다. 프로젝트 루트 .env 파일의 PERDAY_PRICE_SERVICE_KEY= 뒤에 발급받은 키를 넣으세요.")
        sys.exit(1)

    for year in range(2015, 2026):
        out_path = os.path.join(OUT_DIR, "kamis_opendata", f"garak_perday_price_{year}.csv")
        if os.path.exists(out_path):
            print(f"{year}: 이미 존재함, 건너뜀")
            continue
        print(f"=== {year}년 수집 시작 ===")
        collect_all(f"{year}0101", f"{year}1231", out_path)
