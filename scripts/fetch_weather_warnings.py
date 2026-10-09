"""
기상청 API허브(apihub.kma.go.kr): 기상특보 > 특보자료 (wrn_met_data.php)
2015~2025년 전체 특보(태풍/건조(가뭄)/폭염/호우 등) 발효 이력 수집.

사용법: python scripts/fetch_weather_warnings.py
(연도별 1회 호출로 끝나서 ASOS처럼 하루 단위로 끊을 필요 없음)

응답 컬럼: TM_FC(발표시각), TM_EF(발효시각), TM_IN(입력시각), STN(지점),
           REG_ID(특보구역코드), WRN(특보종류: T=태풍,D=건조,H=폭염,R=호우,C=한파,
           W=강풍,S=대설,V=풍랑,O=해일,N=지진해일,Y=황사), LVL(단계), CMD(발표/해제 등),
           GRD(등급), CNT(발표횟수), RPT(보고서번호)
"""

import csv
import os
import subprocess
import time

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw", "kma_warnings")
COLUMNS = ["TM_FC", "TM_EF", "TM_IN", "STN", "REG_ID", "WRN", "LVL", "CMD", "GRD", "CNT", "RPT"]
BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/wrn_met_data.php"


def load_dotenv(path=None):
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
API_KEY = os.environ.get("WEATHER_API_KEY", "")


def fetch_year(year, timeout=20):
    params = {
        "reg": "0", "wrn": "A",
        "tmfc1": f"{year}01010000", "tmfc2": f"{year + 1}01010000",
        "disp": "0", "help": "0", "authKey": API_KEY,
    }
    url = BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    result = subprocess.run(["curl", "-sL", "--max-time", str(timeout), url],
                             capture_output=True, timeout=timeout + 3)
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode}: {result.stderr[:200]!r}")
    text = result.stdout.decode("utf-8", errors="replace")

    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [v.strip() for v in line.split(",")]
        if fields and fields[-1] == "=":
            fields = fields[:-1]
        if len(fields) != len(COLUMNS):
            continue
        rows.append(dict(zip(COLUMNS, fields)))
    return rows


if __name__ == "__main__":
    if not API_KEY:
        print("WEATHER_API_KEY가 설정되지 않았습니다.")
        raise SystemExit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    for year in range(2015, 2026):
        out_path = os.path.join(OUT_DIR, f"warnings_{year}.csv")
        if os.path.exists(out_path):
            print(f"{year}: 이미 존재함, 건너뜀")
            continue
        for attempt in range(3):
            try:
                rows = fetch_year(year)
                break
            except Exception as e:
                print(f"{year}: 시도 {attempt + 1} 실패 ({e})")
                time.sleep(1)
        else:
            print(f"{year}: 3회 실패, 건너뜀")
            continue

        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{year}: 저장 완료 ({len(rows)} rows)")
        time.sleep(0.3)
