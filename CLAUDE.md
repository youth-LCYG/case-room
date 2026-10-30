# Case Room (사건 수사실)

A bilingual (Korean/English) yes-or-no deduction game for a church youth group (grades 6–12), served by GitHub Pages at https://youth-lcyg.github.io/case-room/.

- All cases live in `cases.json`. To add or change a case, edit only that file, following `CASES.md` (content rules, Bible-case rules, picture rules).
- Run `python3 tools/validate.py` before committing; it must print OK.
- Commit to `main`. The "Make pictures" workflow then creates any missing pictures in `images/` through the Cloudflare relay (repository secrets `RELAY_URL`, `RELAY_PASS`).
- `index.html` and `make-pictures.html` read `cases.json` at runtime; don't paste cases into them.
- The game's owner is a youth pastor who writes in Korean. Talk with him in Korean.
