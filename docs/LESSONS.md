# 실수 기록 (LESSONS)

이 저장소에서 실제로 생긴 문제를 모두 적는다. 새 문제가 생기면 같은 형식으로 **해당 절 맨 아래에 추가**하고, 재발 방지 테스트나 규칙을 반드시 함께 남긴다. 요약 규칙은 [CLAUDE.md](../CLAUDE.md)에 있다. 짝 도구 [music-folder-organizer](https://github.com/microhan1/music-folder-organizer)에도 같은 형식의 `docs/LESSONS.md`가 있다.

형식: 증상 → 원인 → 해결 → 재발 방지. 2026-10-01 이전 항목은 커밋 기록에서 옮겨 적었다(괄호 안은 커밋).

---

## A. 제품 코드 버그

### A1. 자동 선택이 이미 있는 태그를 덮어씀 (`57d8ba0`)
- 증상: 태그가 다 있는 베스트 앨범 rip에 일괄 처리를 돌리면 앨범·연도·표지가 원곡의 원래 앨범 것으로 바뀜
- 원인: 자동 선택(일괄, CLI `--auto`)이 직접 고른 것과 똑같이 모든 칸을 덮어씀
- 해결: 자동 선택은 빈 칸만 채움. 사용자가 직접 「선택 적용」하거나 `--overwrite`일 때만 바꿈
- 재발 방지: `test_apply_candidate_fill_gaps_vs_overwrite`. 규칙: **사람이 확인하지 않는 일괄 동작은 있는 값을 지우지 않는다**

### A2. 한 글자 일본어 제목이 "무의미한 이름"으로 잡혀 자동 선택이 막힘 (`57d8ba0`)
- 증상: `唱`, `虹` 등 17곡이 자동 선택에서 빠짐
- 원인: 짧은 제목을 무의미한 파일명(`track01` 류)과 같이 취급
- 해결: 숫자·track 류만 무의미한 이름으로 봄
- 재발 방지: `test_generic_names`. 규칙: 길이로 판단하지 말고 패턴으로 판단한다(CJK 제목은 짧다)

### A3. 파일명의 버전 표기를 가수-제목 구분으로 잘라 엉뚱한 곡이 1위 (`326268f`)
- 증상: `Time Pavement - Karaoke.flac` → 가수 Time Pavement, 제목 Karaoke (52점 오답)
- 해결: 뒤에 붙은 말이 Karaoke·off vocal·TV size 등 버전 표기면 제목의 일부로 봄. karaoke·off vocal·instrumental은 같은 말로 비교
- 재발 방지: `test_version_suffix_is_part_of_the_title`, `test_karaoke_and_off_vocal_compare_equal`, `test_base_title_drops_version_suffix_only`

### A4. 소리로 찾기와 텍스트 검색의 앨범명이 다름 (`b64478f`)
- 원인: AcoustID 발매 목록은 순서가 의미 없고 번역판 pseudo-release가 섞임
- 해결: 상위 3개 후보는 MusicBrainz 녹음 조회로 가장 이른 정식 발매 정보를 다시 읽음
- 재발 방지: `test_mb_parsing_prefers_official_album`. 규칙: 외부 API 목록의 "첫 번째"를 정답으로 믿지 않는다

### A5. 표지가 없는 후보가 많음 (`52f340c`)
- 원인: Cover Art Archive에는 발매·발매 그룹 모두 표지가 없는 경우가 많음(HTTP 500 포함)
- 해결: 발매 그룹 표지 → iTunes 앨범 검색(이름 유사도 0.6 이상) 순으로 폴백
- 재발 방지: `test_itunes_album_artwork_picks_matching_album`, `test_mb_parsing_keeps_release_group_id`

### A6. 창 모드 exe에서 소리로 찾기가 실패할 수 있음 (`1abc728`)
- 원인: 콘솔 없는 exe는 자식 프로세스(fpcalc)에 물려줄 표준 입력 핸들이 없음
- 해결: `stdin=DEVNULL` 명시, "fpcalc 없음"과 "실행 실패"를 구분, 원인을 exe 옆 `music-tag-filler.log`에 기록
- 재발 방지: 자동 테스트 없음 → 규칙: **외부 프로그램을 부르는 기능은 콘솔 없는 exe로 직접 확인한다**

### A7. 검색이 파일당 4.7~7.6초 (`a68f1a5`)
- 원인: 응답 시간이 아니라 요청 간격 대기. 한국어 기본값 KR 스토어는 음원이 없어 빈 결과 뒤 3.1초 대기 후 US 폴백
- 해결: 빈 스토어 건너뛰기, iTunes는 "60초 창에 20회" 제한, iTunes·MusicBrainz 동시 호출, 썸네일 병렬 → 파일당 0.3~2.1초
- 재발 방지: `test_window_allows_burst_then_paces`, `test_empty_storefront_is_skipped` 등 `tests/test_net.py`. 규칙: 느리면 먼저 **어디서 기다리는지 잰다**

### A8. 300곡을 넣으면 메모리 +240MB (`d85f015`)
- 원인: 목록의 모든 파일이 표지 원본 바이트를 들고 있음
- 해결: 태그만 유지하고 표지는 보일 때·저장할 때 다시 읽음, 내려받은 표지는 세션 임시 폴더에 → +2MB
- 재발 방지: 화면 하단 메모리 사용량 표시. 규칙: 파일마다 붙는 큰 데이터는 메모리에 쌓지 않는다

### A9. 파일 목록이 클릭·입력 때마다 튐 (`8204a32`)
- 원인: 갱신 때 모든 줄을 지우고 다시 넣음 → 스크롤·선택이 흔들림
- 해결: 바뀐 줄만 제자리에서 고치고 스크롤 위치 복원
- 재발 방지: 자동 테스트 없음 → 규칙: Treeview는 전체 다시 그리기보다 제자리 갱신. 40곡 끝까지 내린 상태에서 클릭·입력으로 확인

### A10. 후보 표 썸네일이 대부분 비어 있음 (`ad5b6fe`)
- 원인: 표를 다시 채울 때마다 진행 중이던 썸네일 요청을 전부 버림 → 23줄 중 2줄만 표시
- 해결: URL마다 한 번만 받아 캐시하는 영구 풀
- 재발 방지: 자동 테스트 없음 → 규칙: 비동기 작업을 화면 갱신과 같이 취소하지 않는다

### A11. 로딩 표시가 검색 후에도 남음 (`fab4d7e`)
- 원인: 마무리 블록에서 플래그만 끄고 위젯은 그대로 → `place_forget`이 불리지 않음
- 해결: 플래그 대신 실제 위젯 상태(`winfo_ismapped`)로 확인
- 재발 방지: 규칙: 화면 상태는 내 변수가 아니라 **위젯에게 묻는다**

### A12. 서버에 보내는 앱 버전이 0.1.0에 머묾 (v0.1.7에서 고침, `ae548ea`)
- 증상: v0.1.1~v0.1.6 동안 MusicBrainz·iTunes·AcoustID에 `music-tag-filler/0.1.0`으로 요청
- 원인: `net.py`의 `APP_VERSION`을 릴리스 때 올리는 절차가 없었음. MusicBrainz는 정확한 앱 이름·버전을 요구
- 해결: 0.1.7로 맞추고 코드에 "릴리스마다 올린다" 주석
- 재발 방지: [CLAUDE.md](../CLAUDE.md)의 릴리스 점검 1번

## B. 실제 데이터에서 알게 된 것

- B1. 실제 J-POP 553곡(mp3 529·flac 24)으로 시험해야 A1·A2가 드러났다. 합성 음원 테스트만으로는 보이지 않음 (`57d8ba0`)
- B2. 표지가 4장 박힌 파일이 있음 → 가장 큰 앞표지를 보여 줌 (`57d8ba0`)
- B3. iTunes KR 스토어에는 음원 판매가 없음 → 결과 0건이면 US로 폴백, 반복되면 건너뜀 (`a68f1a5`)
- B4. AcoustID가 Instrumental로 판정해 오답이 되는 경우가 있음(6곡 중 1곡) → 소리로 찾기는 후보를 보여 주고 사람이 고르게 둠

## C. 짝 도구(음악 폴더 정리)와의 약속

- C1. **백업 파일 이름은 `<파일명>.tagbak.json`, 음악 파일 바로 옆.** 음악 폴더 정리가 파일을 옮길 때 이 이름 규칙으로 백업을 함께 옮기고 새 파일명에 맞춰 이름을 바꾼다. 이름 규칙을 바꾸면 폴더 정리 뒤 되돌리기가 깨진다
- C2. **되돌리기는 경로·파일명에 의존하지 않는다.** 백업의 `"file"` 값은 기록용이며 복원에 쓰지 않는다. 폴더 정리가 파일 이름을 바꾸기 때문이다
- C3. **식별자 태그 형식**(README "아티스트 식별 정보" 표)은 폴더 정리가 읽는다. 바꾸면 폴더 정리의 `test_ids_written_by_music_tag_filler_merge_artists`와 `test_music_tag_filler_backup_still_restores_after_moving`이 깨진다. 이 두 테스트는 이 저장소의 `tags.py`를 직접 불러 쓴다(`Tags`, `Ids`, `write_file`, `make_backup`, `restore_backup`)
- C4. README에 짝 도구와의 연동을 적을 때는 그쪽 코드와 테스트로 확인한 것만 적는다. iTunes 아티스트 ID는 폴더 정리 v0.1.2부터 읽으므로 README에 버전을 밝혀 둠 (2026-10-01)

## D. 작업 방식·배포

- D1. AcoustID 앱 키를 소스에 넣지 않는다. `acoustid_key.txt`(gitignore)를 빌드 때만 묶는다 (`b6f8cdc`). 키 값은 로그·대화에 출력하지 않는다
- D2. `dist\settings.json`에는 사용자 설정(AcoustID 키 포함 가능)이 있다 → 빌드·정리 때 지우지 말고 백업, 내용을 출력하지 않는다
- D3. 빌드 로그에는 묶인 데이터 파일 이름이 나오지 않는다 → `python -m PyInstaller.utils.cliutils.archive_viewer --list dist/music-tag-filler.exe`로 `acoustid_key.txt`·`third_party\fpcalc.exe`·아이콘이 들었는지 확인 (2026-10-01)
- D4. 공개 저장소이므로 커밋 전에 스테이징된 파일에서 개인 경로(`C:\Users\...`)를 검색한다
- D5. Windows 환경 함정(경로 형식, cp949, 백슬래시가 든 수정은 Edit 도구로)은 짝 도구의 `docs/LESSONS.md` D절과 같다
