# ADR 0009 — Agent giám sát cũng chấm request thủ công, cộng một mẫu không an toàn

- **Ngày:** 2026-08-19
- **Trạng thái:** Accepted
- **Liên quan:** `src/safe_probe/plan.py`, `ui/streamlit_app.py`,
  `tests/test_judge_agent.py`, `tests/test_approval_gate.py`,
  `docs/adr/0007-agent-giam-sat-rui-ro.md`

## Bối cảnh

ADR 0007 giới hạn agent giám sát vào đúng tab "Agent AI": "Trang 'Gửi request
thủ công' ... không đổi -- chỉ tab 'Agent AI' mới có hai agent." Yêu cầu mới
đảo lại quyết định đó: agent giám sát cũng đánh giá và đưa nhận xét cho từng
request thủ công, và nếu nó chấm không an toàn thì người phải Approve. Thêm
một mẫu request cố tình không an toàn, tô đỏ để dễ thấy trên UI.

## Quyết định 1 — Hàm judge mới, không tái dùng `judge_proposal`

`judge_proposal` (ADR 0007) tra `route_id`/`payload_id` trong hai danh sách
đóng -- request thủ công không có danh sách nào để tra: method/path/query/
body do người gõ tay, hoàn toàn tự do. Nên thêm `judge_manual_request` riêng
trong `plan.py`, dùng chung `Verdict`/`_validate_verdict`/`should_auto_send`
nhưng có `MANUAL_JUDGE_SYSTEM_PROMPT` khác: thay vì hỏi "đề xuất này có khớp
hai danh sách không", nó hỏi thẳng "nội dung này có dạng một cuộc tấn công
thật không" (SQLi, command/path injection, SSRF, CRLF, bypass đăng nhập...).

**Đây là một bảo đảm yếu hơn `judge_proposal`'s.** Guardrail thật của
`judge_proposal` nằm ở chỗ *không có gì để nó mô tả sai* -- input luôn đã
được `_validate()` gạn trước. `judge_manual_request` không có tầng đó; nó
dựa vào việc model đọc hiểu đúng hình dạng tấn công trong văn bản tự do, tức
là đúng loại "biện pháp yếu" ADR 0002 đã cảnh báo. Chấp nhận, vì đây vẫn
**không phải cổng an toàn thật** -- xem Quyết định 2.

## Quyết định 2 — Vẫn chỉ điều khiển cái click, gateway vẫn là cổng thật

Bất biến của ADR 0007 giữ nguyên: verdict không đổi được `method`/`path`/
`body` của request, và `_send_manual_request`/`client.request()` là chỗ duy
nhất một request thủ công thật sự rời tool -- gọi giống hệt nhau dù lối vào
là người bấm Approve hay judge chấm `low`. Judge chấm sai (kể cả bị lừa) tệ
nhất cũng chỉ tự gửi sớm một request mà chính người đó đã tự gõ và sắp bấm
gửi -- không có gì "thoát" ra ngoài cái người đã định gửi. Gateway
(`policy.yml`) không biết và không quan tâm judge nói gì; nó vẫn là biên giới
an ninh thật duy nhất, đúng luận điểm xuyên suốt từ ADR 0002.

**Không thay luật cũ, chỉ CỘNG thêm lý do phải duyệt:**

```
cần duyệt = (POST hoặc mang body)        -- luật cũ, ADR 0006, không đổi
          OR (judge chấm needs_review)   -- mới
```

Tức là: một request trước đây đã cần duyệt (mọi POST/có body) thì vẫn cần
duyệt y hệt, dù judge nói gì. Judge chỉ có thể *thêm* trường hợp cần duyệt
(vd. một GET không mang body nhưng path/query trông như tấn công), không bao
giờ *bớt đi* một trường hợp luật cũ đã bắt buộc. `request_needs_approval()`
(luật cũ) không đổi một dòng nào.

## Quyết định 3 — Một mẫu SQLi thật, tô đỏ, nhắm vào Juice Shop

`MANUAL_PRESETS` có thêm `"🔴 POST /rest/user/login"`, body
`{"email": "admin@juice-sh.op' OR 1=1--", "password": "x"}` -- đúng dạng bypass
đăng nhập bằng SQL injection kinh điển của OWASP Juice Shop (một trong các
challenge có sẵn của ứng dụng cố tình dễ tổn thương này). Route `login` đã có
sẵn trong allowlist (`gateway/policy.yml`, ghi chú "wrong credentials return
401 and write nothing -- safe to fuzz"), nên gửi mẫu này không chạm gì ngoài
allowlist.

Đây **không phải** một payload phá hoại thêm vào `payloads.py` -- bất biến
"không thêm payload phá hoại" trong `AGENTS.md` chỉ áp cho catalogue
`SAFE_PAYLOADS` mà agent 1 được phép tự chọn, dùng cho fuzzing tự động qua
hai danh sách đóng. Trang "Gửi request thủ công" từ đầu đã cho người gõ bất
cứ nội dung gì (đúng nghĩa đen "Tự dựng một request bất kỳ"); mẫu này chỉ là
một ví dụ có sẵn cho đúng nội dung đó, để chứng minh judge thật sự bắt được
dạng tấn công chứ không chỉ đề xuất lành tính -- xem
`tests/test_judge_agent.py::test_manual_judge_flags_the_sqli_shaped_sample_preset`.

**Phát hiện khi chạy thật:** ghi chú "wrong credentials return 401 and write
nothing" ở `gateway/policy.yml::login` đúng cho input sai thông thường, nhưng
sai cho chính mẫu SQLi này -- Juice Shop có sẵn lỗ hổng bypass đăng nhập bằng
SQL injection (một challenge chính thức của OWASP Juice Shop), nên request
mẫu thực sự đăng nhập thành công (`200`, kèm JWT thật trong body). Đây đúng
là bài học minh hoạ tốt: guardrail của gateway/tool không và không thể sửa
một lỗ hổng ở tầng ứng dụng -- xem [Vấn đề 1, ADR 0002](0002-guardrail-hai-lop.md)
áp cho một lớp lỗi khác.

Nhưng việc này lộ ra một lỗ hổng thật trong `audit.py::SECRET_SHAPED`
(có từ trước tuần này): pattern chỉ tính một dấu ngăn cách giữa từ khoá và
giá trị, nên `"token":"eyJ..."` (JSON key có ngoặc kép đóng NGAY TRƯỚC dấu
hai chấm) không khớp -- token JWT thật đã lọt nguyên vẹn vào `body_excerpt`
hiện trên UI. Đã sửa: thêm `["']?` ngay sau từ khoá (giống `PASSWORD_SHAPED`
đã làm đúng từ đầu), kèm test tái hiện chính xác hình dạng response này
(`tests/test_redaction.py::test_a_json_quoted_token_field_is_caught_too`).
Không phải lỗi riêng của tính năng này, nhưng chính tính năng này (gửi một
request thật, chạm một ứng dụng thật, không phải stub) là thứ duy nhất tìm
ra được nó.

Tô đỏ: nút preset này có `key="preset_unsafe_sample"` cố định (khác pattern
`preset_{path}_{query}` của các mẫu khác, vì `/` trong path không dùng an
toàn được làm CSS class selector), style bằng `.st-key-preset_unsafe_sample`
trong `inject_css`. Nhận định của judge trên thẻ phê duyệt cũng dùng
🔴/`needs_review` (khác 🟡 ở tab Agent AI) -- đỏ đã có nghĩa "cần chú ý" nhất
quán với `OUTCOME_COLORS` của trang, và đúng yêu cầu "dễ nhận thấy".

## Cái giá phải trả

- **Mỗi lần bấm "Gửi request" giờ đợi thêm một lệnh gọi LLM**, kể cả một GET
  đơn giản như preset "GET /health" -- trước đây trang này gửi tức thì. Chấp
  nhận cho phạm vi hiện tại, cùng đánh đổi độ trễ đã ghi ở ADR 0007.
- **Không có `OPENCODE_API_KEY` thì mọi request thủ công đều cần duyệt.**
  `judge_manual_request` fail-safe về `needs_review` khi lớp LLM lỗi (kể cả
  lỗi "thiếu key"), nên một máy chưa cấu hình LLM sẽ thấy trang này đòi
  Approve cho tất cả, kể cả GET không body -- khác hẳn hành vi trước đây.
  Đây là hệ quả trực tiếp của "fail-safe, không fail-open" đã chọn xuyên suốt
  repo (ADR 0004/0006/0007), không phải một lỗi.
- **Bảo đảm của `judge_manual_request` yếu hơn `judge_proposal`'s** (Quyết
  định 1) -- chấp nhận vì nó vẫn chỉ là ý kiến thứ hai, không phải cổng an
  toàn; cổng thật vẫn là gateway.

## Hệ quả

- Thêm một dạng tấn công mới cần nhận diện: sửa `MANUAL_JUDGE_SYSTEM_PROMPT`,
  không đụng `_send_manual_request`/`client.request()`.
- Muốn thêm mẫu "không an toàn" khác: thêm một dòng vào `MANUAL_PRESETS` với
  `danger=True` và một `key` riêng nếu path có `/`.
