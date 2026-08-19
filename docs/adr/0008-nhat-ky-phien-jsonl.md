# ADR 0008 — Nhật ký phiên: một file jsonl mỗi phiên trình duyệt, `logs/` là thư mục mới

- **Ngày:** 2026-08-19
- **Trạng thái:** Accepted
- **Liên quan:** `ui/streamlit_app.py`, `AGENTS.md`, `.gitignore`,
  `docs/adr/0005-streamlit-demo-tren-railway.md`

## Bối cảnh

Tab "Lịch sử phiên" đã hiện bảng/biểu đồ cho mọi request đã gửi trong phiên
trình duyệt, nhưng chỉ sống trong `st.session_state` — không có cách nào
mang dữ liệu đó ra khỏi trình duyệt để xem lại hay đính kèm báo cáo. Yêu cầu
mới: sau khi chạy, ghi thành một file jsonl trong một thư mục cố định, tên
phân biệt theo thời gian chạy; giao diện phải hiện được nội dung jsonl đó và
cho tải file về.

## Quyết định 1 — Một file mới, không tái dùng `DEMO_LOG_PATH`

`ui/streamlit_app.py` đã có một audit log (`DEMO_LOG_PATH`,
`/tmp/streamlit-probe/requests.jsonl`) — nhưng đó là log **dùng chung cho cả
tiến trình** (một `ProbeClient`/`AuditLog` qua `@st.cache_resource`, đọc ở
`get_client()`), ghi mọi thứ mọi phiên vào một file, đúng vai trò audit trail
kỹ thuật (redact tại sink, phục vụ `tests/test_redaction.py`-style).

Nhật ký phiên là một khái niệm khác: **một file cho một phiên trình duyệt**,
đọc được bởi người xem demo, không phải bởi máy kiểm tra redaction. Nên thay
vì sửa `AuditLog`, `ui/streamlit_app.py` tự ghi thêm một bản tóm tắt
(`_append_session_log`) ngay tại hai chỗ đã có sẵn
`st.session_state["history"].append(...)` — `render_agent_tab` và
`page_manual::_send_manual_request` — không đụng vào `client.py`/`audit.py`,
không đụng bất biến redact-tại-sink đã có.

`result.body_excerpt` đã được `ProbeClient.request` scrub theo API key trước
khi tới đây (`client.py`: "Safe to print: it never holds a credential"), nên
file phiên không cần tự redact thêm gì.

## Quyết định 2 — Thư mục mới `logs/`, không phải `data/`

`data/` theo `AGENTS.md` là output của CLI/test một-người-dùng, và
`ui/streamlit_app.py` từ ADR 0005 đã cố tình **không** ghi vào đó — một demo
công khai ghi vào thư mục dành cho một người chạy sẽ làm nó hết disposable
(nhiều phiên cùng lúc, không ai "sở hữu" thư mục đó). Thay vì phá quy ước
này, tuần này thêm hẳn một thư mục mới, `logs/`, với đúng vai trò: output máy
sinh, đa người dùng, vẫn disposable — xoá đi không mất thông tin gì ngoài
lịch sử demo. `AGENTS.md` và `.gitignore` đã cập nhật (`logs/` gitignore
giống `data/`, gitignore vì đây là output không phải mã nguồn — không phải vì
nhạy cảm).

Tên file: `session_{YYYYMMDD_HHMMSS}_{uuid8}.jsonl`, thời điểm là lúc request
**đầu tiên** của phiên được gửi (không phải lúc mở trang) — một phiên chỉ mở
tab xem allowlist rồi đóng không tạo ra file rỗng nào trong `logs/`.

## Quyết định 3 — UI chỉ hiện file của chính phiên đang xem, không duyệt file người khác

`render_session_log_section()` (trong tab "Lịch sử phiên") đọc đúng
`st.session_state["session_log_path"]` — không liệt kê hay cho tải file của
phiên khác, dù `logs/` là một thư mục dùng chung. Đây là một quyết định thu
hẹp phạm vi có chủ đích: một demo public liệt kê toàn bộ log của mọi người
xem trước đó là một câu hỏi về privacy/multi-tenant chưa được đặt ra và chưa
cần trả lời cho yêu cầu hiện tại ("cho tôi xem log tôi vừa chạy"). Nội dung
mỗi file không nhạy cảm (không PII thật, payload đều tổng hợp từ
`SAFE_PAYLOADS`, không có API key) nên rủi ro nếu mở rộng sau này là thấp,
nhưng việc mở rộng đó là một quyết định UX/sản phẩm riêng, không lẫn vào đây.

Hiển thị: `st.code(content, language="json")` cho đúng nguyên văn file jsonl
(không dựng lại thành bảng), cộng `st.download_button` để tải nguyên file.

## Cái giá phải trả

- **Ghi hai nơi cho cùng một request** (`DEMO_LOG_PATH` dùng chung +
  `logs/session_*.jsonl` theo phiên) — chấp nhận, vì hai file trả lời hai câu
  hỏi khác nhau (kỹ thuật/redaction vs. đọc lại một phiên demo), và tách biệt
  này giữ nguyên bất biến redact-tại-sink của `AuditLog` thay vì mở rộng nó
  cho một mục đích khác.
- **`logs/` không giới hạn dung lượng/tuổi file.** Chấp nhận cho phạm vi demo
  hiện tại — dọn dẹp (nếu cần) là việc vận hành thủ công, giống `data/`.

## Hệ quả

- Thêm một trường vào bản ghi phiên (ví dụ `round_no`) thì sửa
  `_append_session_log`, không đụng `AuditLog`/`ProbeResult`.
- Muốn cho phép duyệt log của phiên khác sau này là một quyết định mới, cần
  cân nhắc riêng câu hỏi privacy/multi-tenant nêu ở Quyết định 3.
