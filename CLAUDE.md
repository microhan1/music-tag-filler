# music-tag-filler 작업 규칙

실제로 있었던 문제와 원인: [docs/LESSONS.md](docs/LESSONS.md).
**문제가 생기면 고친 뒤 반드시 docs/LESSONS.md에 증상·원인·해결·재발 방지를 추가한다.**

## 사용자 파일 안전

- 이 도구는 음악 파일에 태그를 **쓴다**. 사용자의 실제 음악 파일로 시험할 때는 복사본에서 하고, 저장 → 되돌리기가 바이트 단위로 같은지 SHA-1로 확인한다.
- 사람이 확인하지 않는 일괄 동작(자동 선택, `--auto`)은 있는 태그 값을 지우거나 덮어쓰지 않는다.

## 짝 도구(음악 폴더 정리)와의 약속 — 바꾸기 전에 확인

- 백업은 `<파일명>.tagbak.json`, 음악 파일 바로 옆. 되돌리기는 경로·파일명에 의존하지 않는다.
- 식별자 태그 형식(README "아티스트 식별 정보" 표)과 `tags.py`의 `Tags`·`Ids`·`write_file`·`make_backup`·`restore_backup`은 `D:\my\music-folder-organizer`의 통합 테스트가 직접 쓴다. 바꿨으면 그쪽 `python -m pytest tests -q`도 돌린다.
- README에 연동을 적을 때는 그쪽 코드·테스트로 확인한 것만 적는다.

## 검증

1. `python -m pytest tests -q`
2. GUI를 바꿨으면 스크린샷을 찍어 이미지를 직접 열어 확인한다(테스트 통과 ≠ 화면 정상).
3. 외부 프로그램(fpcalc)을 부르는 기능은 콘솔 없는 exe로 확인한다.
4. 느리면 먼저 어디서 기다리는지 잰다(요청 간격 제한이 대부분).

## 릴리스 점검

1. `net.py`의 `APP_VERSION`을 새 버전으로 (User-Agent에 들어감, MusicBrainz 규칙)
2. 깨끗한 작업 트리에서 커밋·푸시. 스테이징된 파일에서 개인 경로(`C:\Users\...`) 검색
3. 빌드 전 `Get-Process music-tag-filler`로 사용자가 앱을 켜 뒀는지 확인. 켜져 있으면 끄지 말고 다른 `--distpath`로. `dist\settings.json`은 백업하고 내용은 출력하지 않는다
4. PowerShell에서 `build.bat`을 절대 경로로 실행. `acoustid_key.txt`가 있어야 키가 묶인다(키 값은 출력 금지)
5. `python -m PyInstaller.utils.cliutils.archive_viewer --list dist/music-tag-filler.exe`로 `acoustid_key.txt`·`third_party\fpcalc.exe`·아이콘 확인
6. exe를 띄워 창 제목 확인(띄운 프로세스만 닫기) → 태그 → `gh release create` → 올린 파일을 다시 받아 SHA-256 비교
7. 프로그램이 안 바뀐 릴리스면 노트에 그렇다고 적는다
