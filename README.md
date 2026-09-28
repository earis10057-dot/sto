# 네이버 블로그 자동화 (blogauto)

생활정보 블로거를 위한 **리서치 → 초안 → 점검 → 이미지** 자동화 도구입니다.
발행은 사람이 직접 합니다. 자동 발행, 자동 댓글, 자동 서로이웃은 네이버 약관 위반이라 넣지 않았습니다.

| 단계 | 명령 | 결과물 |
|---|---|---|
| 검색량·트렌드 수집 | `python -m blogauto keywords` | `data/keywords.xlsx` (검색량 / 트렌드 / 급상승 시트) |
| 오늘의 주제 후보 | `python -m blogauto topics` | `output/topics/날짜.md` |
| 새 공고 모니터링 | `python -m blogauto monitor` | 텔레그램·디스코드·슬랙 알림 + `output/monitor/날짜.md` |
| 위 3개를 한 번에 | `python -m blogauto daily` | 예약 실행용 |
| 글 초안 + 점검 + 이미지 | `python -m blogauto write "주제" -k 키워드` | `output/posts/날짜_키워드/` |

## 1. 설치

```bash
python -m venv .venv
# 윈도우: .venv\Scripts\activate   /  맥·리눅스: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # 윈도우: copy .env.example .env
```

`.env` 에 다음 키를 채웁니다.

| 키 | 발급처 | 쓰는 곳 |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | 초안 작성, 주제 추천, 맞춤법 |
| `NAVER_CLIENT_ID` / `SECRET` | developers.naver.com → 애플리케이션 등록 (데이터랩(검색어트렌드), 검색 API 추가) | 트렌드, 블로그 검색 |
| `NAVER_AD_API_KEY` / `SECRET_KEY` / `CUSTOMER_ID` | searchad.naver.com → 도구 → API 사용 관리 | 월간 검색량, 연관 키워드 |
| `TELEGRAM_*` 또는 `WEBHOOK_URL` (선택) | 텔레그램 BotFather / 디스코드·슬랙 웹훅 | 공고 알림 |

모든 동작 설정은 `config/settings.yaml` 에 있습니다. 시드 키워드, 감시할 사이트, 소제목 기호, 이미지 테마 등을 여기서 바꿉니다.

## 2. 소재 발굴과 키워드 리서치

### 검색량·트렌드를 매일 수집해 스프레드시트에 쌓기
```bash
python -m blogauto keywords                       # settings.yaml 의 seed_keywords 사용
python -m blogauto keywords --seeds "기초연금,에너지바우처"
```
- **검색량** 시트: 시드별 연관 키워드의 월간 PC·모바일 검색량과 경쟁 정도. 날짜별로 누적되고, 같은 날 다시 돌려도 중복되지 않습니다.
- **트렌드** 시트: 데이터랩 일간 검색 비율 (키워드별 0~100)
- **급상승** 시트: 최근 7일 평균과 그 전 7일 평균을 비교해 많이 오른 순서

### 홈판·인기글 패턴으로 "오늘 쓸 주제" 뽑기
1. 네이버 홈판에서 눈에 띄는 제목을 `data/homefeed.txt` 에 한 줄씩 붙여넣습니다.
2. 아래 명령을 실행합니다.
```bash
python -m blogauto topics             # 패턴 통계 + AI 주제 후보 10개
python -m blogauto topics --no-llm    # AI 없이 통계만 (무료)
```
홈판 제목, 시드 키워드의 블로그 상위 글 제목, 검색량·급상승 데이터를 함께 분석합니다.
숫자·연도·물음표·괄호를 쓴 비율, 자주 나온 단어와 꼬리말(총정리, 신청방법 등) 같은 통계를 낸 뒤,
주제·메인 키워드·지금 써야 하는 이유·차별화 관점·제목 예시를 제안합니다. 후보마다 바로 실행할 수 있는 `write` 명령도 붙어 있습니다.

### 정부지원금·정책·금리 공고 모니터링
```bash
python -m blogauto monitor             # 처음 실행 때는 현재 글 목록만 기록
python -m blogauto monitor --dry-run   # 기록·알림 없이 확인만
```
`settings.yaml` 의 `monitor.sources` 에 RSS 주소나 게시판 목록 페이지(+CSS 선택자)를 넣으면 됩니다.
제목에 `include_keywords`(지원금, 대출, 금리 등) 중 하나가 있어야 알리고, `exclude_keywords` 가 있으면 알리지 않습니다.

## 3. 글 초안 작성

```bash
python -m blogauto write "2026 근로장려금 반기 신청 방법" -k "근로장려금 반기" \
    --ref 공고원문.txt --spell
```
| 옵션 | 설명 |
|---|---|
| `-k, --keyword` | 메인 키워드 |
| `-r, --ref` | 참고자료 파일 (공고 원문 등, 여러 번 지정 가능). **사실 정보는 여기서만 가져옵니다.** |
| `-n, --notes` | 추가 요청 (예: "신청 방법을 단계별로 자세히") |
| `--spell` / `--apply-spelling` | AI 맞춤법 검사 / 수정안을 초안에 바로 반영 |
| `--theme` | 이미지 테마 `navy` `mint` `coral` `mono` `forest` |
| `--no-images` | 이미지 생성 생략 |

**내 문체로 쓰게 하려면**
- `config/style.md`: 말투, 구조, 지켜야 할 규칙을 적습니다. 이 내용이 그대로 AI에게 전달됩니다.
- `config/samples/`: 예전에 쓴 글(.txt/.md)을 넣으면 가장 최근 3편의 말투와 구성을 따라 씁니다.
- `settings.yaml` → `writer`: 소제목 기호(■), 인용구 사용 여부, 소제목 개수, 목표 글자수

**결과물** (`output/posts/20260928_근로장려금-반기/`)
```
draft.txt          네이버 에디터에 붙여넣을 본문 (제목 후보 5개, [인용구], [이미지: ...] 위치 표시)
draft.md           미리보기용
meta.json          제목 후보, 해시태그, 3줄 요약, 썸네일 문구 3안, 확인할 사실 목록
check_report.md    발행 전 점검 리포트
images/            thumbnail_1~3.png (1080×1080), section_01..png (1080×720), summary.png (1080×1350)
```
참고자료에 없는 금액·날짜는 AI가 지어내지 않고 `[확인 필요]` 로 남깁니다. 발행 전에 꼭 공식 출처로 확인하세요.

### 점검 항목 (`check_report.md`)
- **금칙어·과장광고**: `config/banned_words.yaml` (과장광고, 의료·건강, 금융·대출, 지원금 단정, 저품질 위험 문구). 자유롭게 추가할 수 있습니다.
- **분량·키워드**: 공백 제외 글자수, 메인 키워드 등장 횟수(너무 적거나 많으면 경고), 키워드가 들어간 제목 여부, 너무 긴 문장, 남아 있는 `[확인 필요]`
- **맞춤법·띄어쓰기** (`--spell`): 구어체 말투는 유지하고 확실한 오류만 지적합니다.

초안을 직접 고친 뒤 다시 점검하거나 이미지만 다시 만들 수도 있습니다.
```bash
python -m blogauto check  output/posts/20260928_근로장려금-반기 --spell
python -m blogauto images output/posts/20260928_근로장려금-반기 --theme mint
```
썸네일 문구는 `meta.json` 의 `thumbnail_texts` 를 고치면 됩니다. `*별표*` 로 감싼 단어는 강조색으로 표시되고, `\n` 은 줄바꿈입니다.

## 4. 이미지 폰트
윈도우 맑은 고딕, 맥 애플 SD 산돌고딕, 리눅스 나눔·Noto 폰트를 자동으로 찾습니다.
프리텐다드나 G마켓 산스 같은 폰트를 쓰려면 `fonts/` 폴더에 .ttf 파일을 넣으세요. 파일 이름에 Bold 가 들어간 폰트는 제목에 쓰입니다.

## 5. 매일 자동 실행
- **윈도우 작업 스케줄러**: 동작 → 프로그램 `경로\.venv\Scripts\python.exe`, 인수 `-m blogauto daily`, 시작 위치 = 프로젝트 폴더
- **맥·리눅스 cron** (매일 오전 7시):
  ```
  0 7 * * * cd /path/to/sto && .venv/bin/python -m blogauto daily >> output/daily.log 2>&1
  ```
- 공고 모니터링만 더 자주 돌리려면 `-m blogauto monitor` 를 1~3시간 간격으로 따로 등록하세요.

## 6. 비용 참고
- 네이버 API: 무료 (데이터랩 하루 1,000회, 검색 하루 25,000회 한도)
- Claude API: 글 1편에 초안 1회, `--spell` 사용 시 1회 추가, 주제 추천은 하루 1회 호출합니다. 모델은 `.env` 의 `BLOGAUTO_MODEL` 로 바꿀 수 있습니다.

## 테스트
```bash
python -m pytest -q
```
네이버와 Claude 호출은 모킹되어 있어 API 키 없이 돌아갑니다.
