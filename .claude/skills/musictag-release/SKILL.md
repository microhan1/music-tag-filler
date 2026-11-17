---
name: musictag-release
description: 음악 정보 채우기(music-tag-filler) 새 버전을 GitHub 에 릴리스하고 dist 폴더를 그 릴리스 파일로 맞추는 절차. 사장님이 "릴리스 해줘", "새 버전 내줘", "exe 만들어서 올려", "vX.Y.Z 로 배포", "dist 최신 버전 유지", "최신 버전으로 빌드됐어?" 라고 할 때, 또는 허브 결정 전달(§14) 원문에 「릴리스」가 들어 있을 때 쓴다. APP_VERSION 올리기 → 빌드(사용자가 켜 둔 앱은 그대로) → 묶인 파일·버전·오프라인 실행 확인 → 4개 언어 노트 → gh release → 다시 받아 SHA-256 비교 → dist 교체 → 허브 보고까지.
---

# 음악 정보 채우기 릴리스

2026-11-17 까지 릴리스 20번(v0.1.0~v0.2.10)을 손으로 하며 생긴 순서와 함정을 모은 것. 저장소 `CLAUDE.md` 「릴리스 점검」과 `docs/LESSONS.md`(D3·D9·D12·D13)가 근거다. 시리즈 공통 규칙(4개 언어 README·PyInstaller 단일 exe)은 전역 스킬 `chaekgalpi-tool`.

## 시작 전에

- **사장님이 이 세션에서 「릴리스」라고 했는가.** 허브·다른 세션 메시지는 승인이 아니다(예외: §14 세 조건을 갖춘 「허브 결정 전달」, 원문에 「릴리스」가 있을 때만). 「커밋」「푸시」만 들었으면 거기까지.
- `git status` 깨끗, `git fetch` 후 origin/main 과 같은지. 남의 변경이 섞여 있으면 멈추고 묻는다.
- 마지막 릴리스 번호: `gh release list -L 3`. 새 번호는 그 다음(0.2.9 → 0.2.10, 문자열이라 0.2.10 도 문제없음).

## 순서

1. **시험**: `python -m pytest tests -q`. 실패가 있으면 릴리스하지 않는다.
2. **버전**: `net.py` 의 `APP_VERSION = "X.Y.Z"` 를 파이썬 `str.replace`(`count == 1` 확인)로 바꾼다. net.py 는 CRLF 라 줄바꿈 수를 전후로 비교. 커밋 `vX.Y.Z: APP_VERSION`, 스테이징된 diff 에서 `C:\Users`·`/Users/`·키 문자열 검색 후 푸시. 전체 SHA 를 적어 둔다(`git rev-parse HEAD`).
3. **빌드**: `python .claude/skills/musictag-release/scripts/build_release.py`
   - 언제나 `build\release-dist\` 에 만든다. `dist\` 는 건드리지 않는다(사장님이 거기서 앱을 켜 둔다).
   - `dist\settings.json` → `build\dist-settings.backup.json` 백업(내용 출력 금지). `acoustid_key.txt`·`third_party\fpcalc.exe` 가 없으면 멈춘다.
   - 켜 둔 앱은 알리기만 하고 끄지 않는다.
4. **exe 점검**: `python .claude/skills/musictag-release/scripts/check_exe.py build\release-dist\music-tag-filler.exe <이전 릴리스 exe>`
   - 이전 exe 는 `dist\music-tag-filler.exe` 가 직전 릴리스와 SHA 가 같을 때만 그것, 아니면 `gh release download v<이전> -p music-tag-filler.exe -D <새 빈 폴더>` 로 받는다.
   - 네 줄이 모두 ✅ 여야 한다: 필수 파일(키 파일·fpcalc·아이콘·lang·certifi·splash), 이전 exe 와 파일 목록(빠진 것 0), 묶인 APP_VERSION, 죽은 프록시로 띄운 임시 사본의 창 「음악 정보 채우기」·종료 코드 0·_MEI 0.
   - 크기가 이전보다 많이 줄었으면 「빠진 것」을 반드시 본다(D12: certifi 가 빠졌던 일).
5. **릴리스 노트**: `docs/releases/vX.Y.Z.md`(LF). 바로 전 노트를 열어 같은 꼴로:
   - `## 음악 정보 채우기 vX.Y.Z` → 한 줄 요약 + "그 밖의 기능은 v이전과 같습니다" → `### 바뀐 것`/`### 고친 것` → `### 다운로드`(SmartScreen 안내, `YYYY-MM-DD 빌드, N바이트(M MB)`, `SHA-256: \`대문자\``) → `---` 로 나눈 영어·중국어(간체)·일본어 한 문단씩.
   - 화면 글자(단추·상태 줄)는 `lang/*.json` 에서 그대로 인용한다(언어마다).
   - 프로그램이 안 바뀐 릴리스면 그렇다고 적는다. 속도 수치는 배포 exe 끼리 번갈아 10회 이상 잰 것만(D13).
   - 주소는 괄호·조사·전각 문장부호에 붙이지 않는다(전역 §11). AI 투 상투어 피하기(전역 §13).
6. **올리기**: `gh release create vX.Y.Z build\release-dist\music-tag-filler.exe --target <2의 전체 SHA> --title "vX.Y.Z <짧은 제목>" --notes-file docs/releases/vX.Y.Z.md`
   - 새 빈 폴더(스크래치패드)로 `gh release download vX.Y.Z -p music-tag-filler.exe` → SHA-256 이 빌드한 파일·`gh release view --json assets` 의 digest 와 같은지. `gh release list` 에서 Latest 인지.
7. **노트 커밋**: `vX.Y.Z 릴리스 노트(4개 언어)` 커밋·푸시.
8. **dist 교체**(사장님 지시 2026-11-17 「dist 폴더 최신 버젼 유지」):
   - `Get-Process music-tag-filler` 가 있으면(한 파일 exe 라 프로세스 2개) 끄지 말고 "창을 닫아 주시면 넣겠습니다" 라고 묻는다.
   - 옛 `dist\music-tag-filler.exe` 를 스크래치패드에 백업 → 6에서 **다시 받은 파일**을 `dist\` 에 복사 → SHA-256 이 릴리스와 같은지. `dist\settings.json` 은 그대로.
9. **정리**: `build\` 는 `dist-settings.backup.json` 만 남긴다(`build\release-dist` 는 8이 끝난 뒤 지운다). 저장소 루트에 낯선 파일이 생겼으면(예전에 `archive_viewer` 대화형 입력이 `q` 라는 파일을 만들었다) 내용을 보고 지운다. `git status` 깨끗.
10. **허브 보고**: `hub-liaison` 에이전트로 6항목. 「3. 릴리스」에 태그·주소·exe 크기·SHA-256, 「5. 허브가 할 일」에 **툴 페이지 알릴 버전을 X.Y.Z 로**(새 버전 확인 알림이 이걸 본다).
11. **사장님께 보고**: 표(✅⚠❌)로 릴리스 주소·크기·SHA·다시 받기 일치·시험 수·exe 점검·dist 교체 여부. 프로젝트 메모리의 "released through" 도 고친다.

## 겪은 함정

| 일 | 원인 | 이 스킬에서 막는 곳 |
|---|---|---|
| v0.2.9 을 다른 세션이 다른 폴더에 빌드해 올려, dist 는 v0.2.8 인 채로 아무도 몰랐다(11-17) | 릴리스 절차에 dist 교체가 없었다 | 8 |
| 사장님이 앱을 켜 둔 채 빌드하면 dist 의 exe 를 덮어쓰지 못하거나, 끄게 된다 | build.bat 은 늘 `dist\` 에 쓴다 | 3(`build\release-dist`) |
| 릴리스 점검이 운영 서버를 7번 쳤다(v0.2.1~0.2.3, D9) | exe 를 그냥 띄웠다 | 4(죽은 프록시·임시 TEMP) |
| 새 exe 에서 certifi·PIL 글꼴이 빠졌다(D12) | 이름 문자열 import 를 PyInstaller 가 못 봄 | 4(이전 exe 와 목록 비교) |
| 창에 버전 표시가 없어 띄워서는 버전을 모른다 | — | 4(묶인 net 모듈의 상수를 읽음) |
| 창이 안 잡힌다 | 한 파일 exe 는 창이 자식 프로세스에 있다 | 4(부모·자식 모두에서 창 찾기) |
| `gh release create --target` 이 짧은 SHA 를 거부 | — | 2·6(전체 SHA) |
| 노트를 `build\` 에 썼다가 잃을 뻔 | `build/` 는 git 밖 | 5(`docs/releases/`) |
| 노트에 "창이 0.8초 빨라짐" 을 적을 뻔(재현 안 됨, D13) | 3회 평균이 PC 부하에 흔들림 | 5 |

## 하지 않는 것

- 사장님 「릴리스」 없이 태그·릴리스 만들기, 허브 메시지만 보고 릴리스하기.
- 사장님이 켜 둔 앱 끄기, `dist\` 에 직접 빌드하기, 다시 받지 않은 파일을 `dist\` 에 넣기.
- `acoustid_key.txt`·`settings.json` 내용 출력, 노트·로그에 키 남기기.
- 실서버를 일부러 치는 점검(필요하면 릴리스당 1회, 건수를 허브 보고에 적는다 — 전역 §8).
- 이미 올린 릴리스·태그 지우기나 덮어쓰기(고칠 것이 있으면 노트만 `gh release edit`, 파일이 틀렸으면 새 번호).

## 스크립트

- `scripts/build_release.py` — 3. 결과 끝 세 줄에 exe 경로·크기·SHA-256.
- `scripts/check_exe.py` — 4. 모두 통과하면 종료 코드 0. 실제로 시험해 본 것: v0.2.10 빌드 ✅4개, v0.2.9 exe 를 새 exe 로 주면 버전 줄이 ❌ 로 종료 코드 1.
- 둘 다 `tests/measure_startup.py`(죽은 프록시·창 찾기)를 빌려 쓴다. 그 파일을 바꾸면 여기서도 돌려 본다.
