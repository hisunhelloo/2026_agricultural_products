"""
기상청 API허브(apihub.kma.go.kr): 지상관측 종관기상관측(ASOS) 일자료
https://apihub.kma.go.kr (활용신청 완료: kma_sfcdd.php, 지상관측>종관기상관측(ASOS)>지상 관측자료 조회)

사용법:
    1) 프로젝트 루트 .env 의 WEATHER_API_KEY= 에 apihub.kma.go.kr authKey가 들어있어야 함
    2) python scripts/fetch_weather_asos.py

API 사용법 요약:
    - URL: https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd.php
    - 파라미터: tm=YYYYMMDD(단일 날짜, 기간조회 아님 - 하루씩 호출해야 함), stn=0(전체 지점) 또는 지점번호, authKey
    - 응답은 JSON이 아니라 # 로 시작하는 헤더 주석 + comma-separated 데이터 라인 + #7777END
    - 하루당 stn=0으로 호출하면 전국 ~95개 관측소 데이터를 한 번에 받을 수 있음 (지점별로 따로 부를 필요 없음)
    - 품목별 주산지 관측소를 아직 특정하지 않았으므로, 일단 전체 지점을 받아서 나중에 필터링한다.
"""

import csv
import datetime
import os
import subprocess
import time
import urllib.parse

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw", "kma_asos")

COLUMNS = [
    "TM", "STN", "WS_AVG", "WR_DAY", "WD_MAX", "WS_MAX", "WS_MAX_TM", "WD_INS", "WS_INS", "WS_INS_TM",
    "TA_AVG", "TA_MAX", "TA_MAX_TM", "TA_MIN", "TA_MIN_TM", "TD_AVG", "TS_AVG", "TG_MIN", "HM_AVG", "HM_MIN",
    "HM_MIN_TM", "PV_AVG", "EV_S", "EV_L", "FG_DUR", "PA_AVG", "PS_AVG", "PS_MAX", "PS_MAX_TM", "PS_MIN",
    "PS_MIN_TM", "CA_TOT", "SS_DAY", "SS_DUR", "SS_CMB", "SI_DAY", "SI_60M_MAX", "SI_60M_MAX_TM", "RN_DAY",
    "RN_D99", "RN_DUR", "RN_60M_MAX", "RN_60M_MAX_TM", "RN_10M_MAX", "RN_10M_MAX_TM", "RN_POW_MAX",
    "RN_POW_MAX_TM", "SD_NEW", "SD_NEW_TM", "SD_MAX", "SD_MAX_TM", "TE_05", "TE_10", "TE_15", "TE_30", "TE_50",
]


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
BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd.php"


def fetch_day(ymd, stn=0, timeout=10):
    params = {"tm": ymd, "stn": stn, "help": 0, "authKey": API_KEY}
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    # urllib/Windows에서 DNS 조회 등이 timeout 파라미터를 무시하고 완전히 행(hang)하는 경우가 있어
    # curl 서브프로세스(+ subprocess.run의 OS 레벨 timeout)로 강제 종료가 가능하게 한다.
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout), url],
        capture_output=True, timeout=timeout + 3,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode}: {result.stderr[:200]!r}")
    text = result.stdout.decode("utf-8", errors="replace")

    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [v for v in line.split(",") if v != ""] if line.endswith(",") else line.split(",")
        # 끝에 trailing comma가 있어 마지막 빈 문자열이 생기는 경우 제거
        if len(fields) == len(COLUMNS) + 1 and fields[-1] == "":
            fields = fields[:-1]
        if len(fields) != len(COLUMNS):
            continue
        rows.append(dict(zip(COLUMNS, fields)))
    return rows, text


def collect_year(year, out_path):
    """연도 단위로 수집하되, 하루마다 바로 파일에 append하고 진행 마커를 남겨
    중간에 죽어도(타임아웃, 행 등) 처음부터 다시 받지 않고 이어서 할 수 있게 한다."""
    start = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    if end > datetime.date.today():
        end = datetime.date.today()

    partial_path = out_path + ".partial"
    progress_path = out_path + ".progress"

    d = start
    total_rows = 0
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            last_done = f.read().strip()
        if last_done:
            d = datetime.datetime.strptime(last_done, "%Y%m%d").date() + datetime.timedelta(days=1)
            with open(partial_path, encoding="utf-8-sig") as f:
                total_rows = max(0, sum(1 for _ in f) - 1)
            print(f"  이어서 수집: {d.strftime('%Y%m%d')}부터 (기존 {total_rows} rows)", flush=True)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    file_exists = os.path.exists(partial_path)
    with open(partial_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not file_exists:
            writer.writeheader()

        while d <= end:
            ymd = d.strftime("%Y%m%d")
            rows = None
            for attempt in range(3):
                try:
                    rows, raw = fetch_day(ymd)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  {ymd}: 3회 실패 ({e}), 건너뜀", flush=True)
                    time.sleep(0.5)

            if rows:
                writer.writerows(rows)
                total_rows += len(rows)
            elif rows == []:
                print(f"  {ymd}: 0 rows", flush=True)
            f.flush()

            # OneDrive 동기화가 파일을 잠깐 잠그는 경우가 있어 PermissionError를 재시도로 흡수한다.
            for pf_attempt in range(5):
                try:
                    with open(progress_path, "w", encoding="utf-8") as pf:
                        pf.write(ymd)
                    break
                except PermissionError:
                    time.sleep(1)

            if d.day == 1:
                print(f"  ...{ymd} 처리 중 (누적 {total_rows} rows)", flush=True)
            d += datetime.timedelta(days=1)
            time.sleep(0.3)

    if total_rows == 0:
        print(f"{year}: 수집된 행 없음")
        return

    os.replace(partial_path, out_path)
    if os.path.exists(progress_path):
        os.remove(progress_path)
    print(f"{year}: 저장 완료 {out_path} ({total_rows} rows)", flush=True)


if __name__ == "__main__":
    import sys

    if not API_KEY:
        print("WEATHER_API_KEY가 설정되지 않았습니다.")
        raise SystemExit(1)

    # 인자 없이 실행하면 아직 없는 연도 중 가장 이른 한 해만 처리하고 종료한다.
    # (한 프로세스가 너무 오래 실행되면 백그라운드 전환 후 행(hang)하는 현상이 있어,
    #  연도별로 짧게 끊어서 여러 번 호출하는 방식으로 우회한다.)
    if len(sys.argv) > 1:
        years = [int(sys.argv[1])]
    else:
        years = None
        for year in range(2015, 2026):
            out_path = os.path.join(OUT_DIR, f"asos_daily_{year}.csv")
            if not os.path.exists(out_path):
                years = [year]
                break
        if years is None:
            print("모든 연도가 이미 완료되어 있습니다.")
            raise SystemExit(0)

    for year in years:
        out_path = os.path.join(OUT_DIR, f"asos_daily_{year}.csv")
        if os.path.exists(out_path):
            print(f"{year}: 이미 존재함, 건너뜀")
            continue
        print(f"=== {year}년 수집 시작 ===")
        collect_year(year, out_path)
