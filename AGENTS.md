# AGENTS.md

AI 코딩 에이전트(Claude Code, Codex, Cursor 등)가 이 저장소에서 작업할 때 따를 안내입니다.
사람을 위한 사용법은 `README.md` 에 있습니다.

## 프로젝트 개요

`blogauto` 는 네이버 생활정보 블로거를 위한 파이썬 도구입니다.
**리서치 → 초안 → 점검 → 이미지** 까지 자동화하고, 발행은 사람이 직접 합니다.

- 리서치: 검색광고 API(월간 검색량) + 데이터랩(트렌드) → `data/keywords.xlsx`, 홈판 제목 패턴 분석 → 주제 후보, 정부 사이트 RSS/게시판 감시 → 알림
- 초안: Claude API 로 사용자 문체(`config/style.md`, `config/samples/`)에 맞춘 글 + 제목 5개·해시태그·3줄 요약·썸네일 문구 3안
- 점검: 금칙어·과장광고(`config/banned_words.yaml`), 키워드 반복·분량, 선택적 AI 맞춤법
- 이미지: 글마다 썸네일 1장(1080×1080) + 본문 16:9 4장(1280×720)
- 사용 방식: 버튼 프로그램(`blogauto/gui.py`, tkinter) 또는 명령어(`python -m blogauto ...`)

## 명령어

```bash
pip install -r requirements.txt       # 설치 (Python 3.10 이상)
python -m pytest -q                   # 전체 테스트 (네트워크·API 키 불필요)
python -m blogauto --help             # CLI: keywords | topics | monitor | daily | write | check | images
python -m blogauto.gui                # 버튼 프로그램 (tkinter 필요)
```

변경 후에는 반드시 `python -m pytest -q` 를 통과시킵니다.

## 구조

```
blogauto/
  cli.py            명령어 진입점. _check_and_report / _images 는 GUI 도 재사용
  gui.py            tkinter 화면 (글쓰기 / 리서치 / 설정 탭)
  config.py         settings.yaml + user.yaml 병합 로딩, .env 저장, 경로 해석(resolve)
  llm.py            Claude 호출 공통 함수 generate_json (구조화 출력)
  layout.py         이미지 파일 이름과 본문 속 위치의 유일한 기준
  research/         naver_api(API 클라이언트) keywords topics monitor notify sheet(xlsx)
  writer/           draft(초안 생성·렌더링) checker(금칙어·분량·맞춤법)
  images/           cards(Pillow 카드 그리기) fonts(한글 폰트 탐색)
config/             settings.yaml(기본 설정, 주석 포함) style.md banned_words.yaml samples/
tests/              pytest. conftest.py 의 FakeSession / project / sample_meta 픽스처 사용
start-windows.bat   더블클릭 실행기 (첫 실행 시 .venv 생성·설치)
start-mac.command   맥용 실행기
```

## 지켜야 할 규칙

### 제품 원칙
- **자동 발행·자동 댓글·자동 공감·자동 서로이웃 기능은 만들지 않습니다.** 네이버 약관 위반이고 계정 제재 위험이 있습니다.
- 초안 프롬프트는 참고자료에 없는 금액·날짜·조건을 지어내지 않고 `[확인 필요]` 로 표시하게 되어 있습니다. 이 원칙을 약하게 만들지 마세요.
- 이미지에는 `[확인 필요]` 표시가 들어가면 안 됩니다 (`cards._clean`).

### 코드 규칙
- 사용자에게 보이는 문구(출력, 오류, GUI, README)는 **한국어**, 식별자는 영어로 씁니다. 기존 코드의 말투("~해요", "~합니다")를 따릅니다.
- 설정 경로는 항상 `config.resolve()` 로 프로젝트 루트 기준으로 해석합니다. 테스트가 `config.ROOT` 를 임시 폴더로 바꾸기 때문에, 모듈을 불러올 때 경로를 고정하면 안 됩니다.
- 이미지 파일 이름·위치는 `layout.py` 에서만 정합니다. `writer/draft.py`(본문 속 `[이미지: ...]` 표시)와 `images/cards.py`(파일 생성)가 둘 다 여기를 봅니다.
- GUI 에서 바꾼 설정은 `config/user.yaml` 에 저장합니다 (`save_user_settings`). 주석이 달린 `config/settings.yaml` 을 코드로 다시 쓰지 마세요.
- API 키는 `.env` 에만 둡니다 (`save_env`). 코드, 설정 파일, 테스트, 커밋에 키를 넣지 마세요.
- GUI 의 오래 걸리는 작업은 `App.run_task` 로 백그라운드 스레드에서 실행합니다. 작업 스레드에서 위젯을 직접 만지지 말고 결과 콜백(on_done)에서 처리합니다.
- 알려진 오류(`ConfigError`, `NaverAPIError`, `LLMError`, `FileNotFoundError`, `ValueError`)는 CLI 에서 종료 코드 1 과 한 줄짜리 한국어 메시지로 보여 줍니다.

### Claude API
- `llm.generate_json` 한 곳에서만 호출합니다. 공식 `anthropic` SDK(1.x)를 쓰고, 스트리밍 + `output_config.format`(JSON 스키마) + 적응형 사고(`thinking={"type": "adaptive"}`) 방식입니다.
- 기본 모델은 `claude-opus-5` 이고 환경변수 `BLOGAUTO_MODEL` 로 바꿀 수 있습니다. 거절 시 서버 측 자동 대체(`fallbacks="default"`)를 켜 둡니다.
- 새 JSON 스키마에는 `additionalProperties: false` 와 `required` 를 넣습니다.

### 테스트
- 네이버 API 와 Claude 는 실제로 호출하지 않습니다. `FakeSession` 과 `monkeypatch` 로 `generate_json` 을 바꿔 끼웁니다.
- GUI 테스트는 tkinter 나 화면이 없으면 자동으로 건너뜁니다. 리눅스에서 GUI 를 확인하려면 `xvfb-run -a python -m pytest -q` 를 씁니다.

### 파일 형식
- `start-windows.bat` 는 CRLF 줄바꿈이어야 합니다 (`.gitattributes` 로 강제). `start-mac.command` 는 실행 권한(755)을 유지합니다.
- 실행기 파일 이름은 영어로 둡니다. 일부 윈도우 압축 해제 도구가 한글 파일 이름을 깨뜨립니다.
